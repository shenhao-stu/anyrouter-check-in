#!/usr/bin/env python3
"""
AnyRouter.top 自动签到脚本
"""

import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from utils.config import AccountConfig, AppConfig, load_accounts_config
from utils.notify import notify

load_dotenv()

BALANCE_HASH_FILE = 'balance_hash.txt'


def load_balance_hash():
	"""加载余额hash"""
	try:
		if os.path.exists(BALANCE_HASH_FILE):
			with open(BALANCE_HASH_FILE, 'r', encoding='utf-8') as f:
				return f.read().strip()
	except Exception:  # nosec B110
		pass
	return None


def save_balance_hash(balance_hash):
	"""保存余额hash"""
	try:
		with open(BALANCE_HASH_FILE, 'w', encoding='utf-8') as f:
			f.write(balance_hash)
	except Exception as e:
		print(f'Warning: Failed to save balance hash: {e}')


def generate_balance_hash(balances):
	"""生成余额数据的hash"""
	# 将包含 quota 和 used 的结构转换为简单的 quota 值用于 hash 计算
	simple_balances = {k: v['quota'] for k, v in balances.items()} if balances else {}
	balance_json = json.dumps(simple_balances, sort_keys=True, separators=(',', ':'))
	return hashlib.sha256(balance_json.encode('utf-8')).hexdigest()[:16]


def parse_cookies(cookies_data):
	"""解析 cookies 数据"""
	if isinstance(cookies_data, dict):
		return cookies_data

	if isinstance(cookies_data, str):
		cookies_dict = {}
		for cookie in cookies_data.split(';'):
			if '=' in cookie:
				key, value = cookie.strip().split('=', 1)
				cookies_dict[key] = value
		return cookies_dict
	return {}


async def get_waf_cookies_with_playwright(account_name: str, login_url: str, required_cookies: list[str]):
	"""使用 Playwright 获取 WAF cookies（隐私模式）"""
	print(f'[PROCESSING] {account_name}: Starting browser to get WAF cookies...')

	async with async_playwright() as p:
		import tempfile

		with tempfile.TemporaryDirectory() as temp_dir:
			context = await p.chromium.launch_persistent_context(
				user_data_dir=temp_dir,
				headless=False,
				user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
				viewport={'width': 1920, 'height': 1080},
				args=[
					'--disable-blink-features=AutomationControlled',
					'--disable-dev-shm-usage',
					'--disable-web-security',
					'--disable-features=VizDisplayCompositor',
					'--no-sandbox',
				],
			)

			page = await context.new_page()

			try:
				print(f'[PROCESSING] {account_name}: Access login page to get initial cookies...')

				await page.goto(login_url, wait_until='networkidle')

				try:
					await page.wait_for_function('document.readyState === "complete"', timeout=5000)
				except Exception:
					await page.wait_for_timeout(3000)

				cookies = await page.context.cookies()

				waf_cookies = {}
				for cookie in cookies:
					cookie_name = cookie.get('name')
					cookie_value = cookie.get('value')
					if cookie_name in required_cookies and cookie_value is not None:
						waf_cookies[cookie_name] = cookie_value

				print(f'[INFO] {account_name}: Got {len(waf_cookies)} WAF cookies')

				missing_cookies = [c for c in required_cookies if c not in waf_cookies]

				if missing_cookies:
					print(f'[FAILED] {account_name}: Missing WAF cookies: {missing_cookies}')
					await context.close()
					return None

				print(f'[SUCCESS] {account_name}: Successfully got all WAF cookies')

				await context.close()

				return waf_cookies

			except Exception as e:
				print(f'[FAILED] {account_name}: Error occurred while getting WAF cookies: {e}')
				await context.close()
				return None


def _is_cloudflare_response(response) -> bool:
	"""检测响应是否来自 Cloudflare WAF"""
	server = response.headers.get('server', '').lower()
	return 'cloudflare' in server or 'cf-ray' in response.headers


def get_user_info(client, headers, user_info_url: str):
	"""获取用户信息"""
	try:
		response = client.get(user_info_url, headers=headers, timeout=30)

		if response.status_code == 200:
			data = response.json()
			if data.get('success'):
				user_data = data.get('data', {})
				quota = round(user_data.get('quota', 0) / 500000, 2)
				used_quota = round(user_data.get('used_quota', 0) / 500000, 2)
				return {
					'success': True,
					'quota': quota,
					'used_quota': used_quota,
					'display': f'💰 Current balance: ${quota}, Used: ${used_quota}',
				}
		# 检测 Cloudflare 拦截（TLS 指纹不匹配导致 httpx 被 403）
		if response.status_code == 403 and _is_cloudflare_response(response):
			return {
				'success': False,
				'error': f'Failed to get user info: HTTP {response.status_code}',
				'cloudflare': True,
			}
		return {'success': False, 'error': f'Failed to get user info: HTTP {response.status_code}'}
	except Exception as e:
		return {'success': False, 'error': f'Failed to get user info: {str(e)[:50]}...'}


async def prepare_cookies(account_name: str, provider_config, user_cookies: dict) -> dict | None:
	"""准备请求所需的 cookies（可能包含 WAF cookies）"""
	waf_cookies = {}

	if provider_config.needs_waf_cookies():
		login_url = f'{provider_config.domain}{provider_config.login_path}'
		waf_cookies = await get_waf_cookies_with_playwright(account_name, login_url, provider_config.waf_cookie_names)
		if not waf_cookies:
			print(f'[FAILED] {account_name}: Unable to get WAF cookies')
			return None
	else:
		print(f'[INFO] {account_name}: Bypass WAF not required, using user cookies directly')

	return {**waf_cookies, **user_cookies}


NEW_API_CHECKIN_PATH = '/api/user/checkin'


def _parse_check_in_response(account_name: str, response) -> bool:
	"""解析签到响应，返回是否成功"""
	if response.status_code == 200:
		try:
			result = response.json()
			if result.get('ret') == 1 or result.get('code') == 0 or result.get('success'):
				print(f'[SUCCESS] {account_name}: Check-in successful!')
				return True
			else:
				error_msg = result.get('msg', result.get('message', 'Unknown error'))
				already_checked_keywords = ['已经签到', '已签到', '重复签到', 'already checked', 'already signed']
				if any(keyword in error_msg.lower() for keyword in already_checked_keywords):
					print(f'[SUCCESS] {account_name}: Already checked in today')
					return True
				print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
				return False
		except json.JSONDecodeError:
			if 'success' in response.text.lower():
				print(f'[SUCCESS] {account_name}: Check-in successful!')
				return True
			else:
				print(f'[FAILED] {account_name}: Check-in failed - Invalid response format')
				return False
	return False


def _do_check_in_request(client, account_name: str, provider_config, checkin_headers: dict):
	"""发送签到请求（含 404 fallback），返回 response 对象"""
	sign_in_url = f'{provider_config.domain}{provider_config.sign_in_path}'
	response = client.post(sign_in_url, headers=checkin_headers, timeout=30)

	print(f'[RESPONSE] {account_name}: Response status code {response.status_code}')

	# new-api 平台使用 /api/user/checkin，而非 /api/user/sign_in
	# 收到 404 且当前路径不是 new-api 路径时，自动 fallback
	if response.status_code == 404 and provider_config.sign_in_path != NEW_API_CHECKIN_PATH:
		fallback_url = f'{provider_config.domain}{NEW_API_CHECKIN_PATH}'
		print(f'[INFO] {account_name}: sign_in returned 404, trying new-api checkin endpoint: {NEW_API_CHECKIN_PATH}')
		response = client.post(fallback_url, headers=checkin_headers, timeout=30)
		print(f'[RESPONSE] {account_name}: Fallback response status code {response.status_code}')

	return response


MAX_RETRIES = 2
RETRY_DELAY = 5


def execute_check_in(client, account_name: str, provider_config, headers: dict):
	"""执行签到请求，自动适配 one-api(/api/user/sign_in) 和 new-api(/api/user/checkin)，含重试"""
	print(f'[NETWORK] {account_name}: Executing check-in')

	checkin_headers = headers.copy()
	checkin_headers.update({'Content-Type': 'application/json', 'X-Requested-With': 'XMLHttpRequest'})

	last_error = None
	for attempt in range(1, MAX_RETRIES + 1):
		try:
			response = _do_check_in_request(client, account_name, provider_config, checkin_headers)

			if response.status_code == 200:
				return _parse_check_in_response(account_name, response)

			# 5xx 服务端错误可重试
			if response.status_code >= 500 and attempt < MAX_RETRIES:
				print(
					f'[RETRY] {account_name}: HTTP {response.status_code}, retrying in {RETRY_DELAY}s ({attempt}/{MAX_RETRIES})'
				)
				time.sleep(RETRY_DELAY)
				continue

			print(f'[FAILED] {account_name}: Check-in failed - HTTP {response.status_code}')
			return False

		except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, OSError) as e:
			last_error = e
			if attempt < MAX_RETRIES:
				print(
					f'[RETRY] {account_name}: {type(e).__name__}, retrying in {RETRY_DELAY}s ({attempt}/{MAX_RETRIES})'
				)
				time.sleep(RETRY_DELAY)
				continue
			raise

	print(f'[FAILED] {account_name}: Check-in failed after {MAX_RETRIES} attempts - {last_error}')
	return False


def format_compact_notification(account_details: dict, success_count: int, total_count: int) -> str:
	"""格式化紧凑的签到通知（按状态分组，每账号一行）"""
	lines = [f'⏰ {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}', '']

	# 按状态分组
	rewarded = []  # 获得签到奖励
	usage_only = []  # 已签到但有消耗
	no_change = []  # 已签到无变化
	failed = []  # 失败

	for key in sorted(account_details.keys()):
		d = account_details[key]
		if not d.get('success', False):
			failed.append(d)
		elif d.get('check_in_reward', 0) != 0:
			rewarded.append(d)
		elif d.get('usage_increase', 0) != 0:
			usage_only.append(d)
		else:
			no_change.append(d)

	# 成功区域
	if success_count > 0:
		lines.append(f'**✅ 成功 ({success_count}/{total_count})**')

		for d in rewarded:
			after = d.get('after_quota', 0)
			reward = d['check_in_reward']
			lines.append(f'  🎁 {d["name"]} ({d.get("provider_name", "")}) ${after:.2f} (+${reward:.2f})')

		for d in usage_only:
			after = d.get('after_quota', 0)
			usage = d['usage_increase']
			lines.append(f'  📉 {d["name"]} ({d.get("provider_name", "")}) ${after:.2f} (消耗 ${usage:.2f})')

		if no_change:
			if len(no_change) <= 3:
				for d in no_change:
					after = d.get('after_quota')
					bal = f' ${after:.2f}' if after is not None else ''
					lines.append(f'  ✔️ {d["name"]} ({d.get("provider_name", "")}){bal}')
			else:
				names = [d['name'] for d in no_change]
				preview = ', '.join(names[:5])
				suffix = f' 等{len(names)}个' if len(names) > 5 else ''
				lines.append(f'  ✔️ 已签到无变化: {preview}{suffix}')

	# 失败区域
	if failed:
		lines.append('')
		lines.append(f'**❌ 失败 ({len(failed)}/{total_count})**')
		for d in failed:
			error = d.get('error_message', '未知错误') or '未知错误'
			if len(error) > 50:
				error = error[:50] + '...'
			lines.append(f'  ✖ {d["name"]} ({d.get("provider_name", "")}): {error}')

	return '\n'.join(lines)


PLAYWRIGHT_BROWSER_ARGS = [
	'--disable-blink-features=AutomationControlled',
	'--disable-dev-shm-usage',
	'--disable-web-security',
	'--disable-features=VizDisplayCompositor',
	'--no-sandbox',
]

PLAYWRIGHT_USER_AGENT = (
	'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
)

# CDP screenX/screenY patch: Chromium's Input.dispatchMouseEvent sets screenX=x, screenY=y
# (client coords), but real mouse events have screen offsets. Turnstile detects this difference.
CDP_MOUSE_PATCH_JS = """
(() => {
    if (window.__cdpMousePatched) return;
    const rX = () => 800 + Math.floor(Math.random() * 400);
    const rY = () => 400 + Math.floor(Math.random() * 200);
    Object.defineProperty(MouseEvent.prototype, 'screenX', { get: rX });
    Object.defineProperty(MouseEvent.prototype, 'screenY', { get: rY });
    window.__cdpMousePatched = true;
})();
"""


def _parse_user_info_json(data: dict) -> dict:
	"""解析 /api/user/self 响应 JSON"""
	if data.get('success'):
		user_data = data.get('data', {})
		quota = round(user_data.get('quota', 0) / 500000, 2)
		used_quota = round(user_data.get('used_quota', 0) / 500000, 2)
		return {
			'success': True,
			'quota': quota,
			'used_quota': used_quota,
			'display': f'💰 Current balance: ${quota}, Used: ${used_quota}',
		}
	return {'success': False, 'error': 'API returned success=false'}


async def check_in_with_playwright(
	account: AccountConfig,
	account_name: str,
	provider_config,
):
	"""通过 Playwright 浏览器内 fetch 执行签到（绕过 Cloudflare TLS 指纹校验）"""
	user_cookies = parse_cookies(account.cookies)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None, None

	print(f'[INFO] {account_name}: Using Playwright browser for API calls (Cloudflare bypass)')

	async with async_playwright() as p:
		import tempfile

		with tempfile.TemporaryDirectory() as temp_dir:
			context = await p.chromium.launch_persistent_context(
				user_data_dir=temp_dir,
				headless=False,
				user_agent=PLAYWRIGHT_USER_AGENT,
				viewport={'width': 1920, 'height': 1080},
				args=PLAYWRIGHT_BROWSER_ARGS,
			)

			try:
				# 注入 session cookie
				hostname = urlparse(provider_config.domain).hostname
				for name, value in user_cookies.items():
					await context.add_cookies(
						[
							{
								'name': name,
								'value': value,
								'domain': hostname,
								'path': '/',
							}
						]
					)

				page = await context.new_page()

				# 导航到站点，通过 Cloudflare challenge
				print(f'[PROCESSING] {account_name}: Navigating to pass Cloudflare challenge...')
				await page.goto(f'{provider_config.domain}/', wait_until='networkidle')
				try:
					await page.wait_for_function('document.readyState === "complete"', timeout=10000)
				except Exception:
					await page.wait_for_timeout(5000)

				# 使用浏览器内 fetch 调用 API（共享 Chrome TLS 指纹）
				api_user_key = provider_config.api_user_key
				api_user = account.api_user

				# 获取签到前用户信息
				user_info_before = None
				for attempt in range(1, MAX_RETRIES + 1):
					result = await page.evaluate(
						"""async ([path, key, user]) => {
							try {
								const r = await fetch(path, {headers: {[key]: user}});
								if (!r.ok) return {success: false, error: 'HTTP ' + r.status};
								return await r.json();
							} catch(e) { return {success: false, error: e.message}; }
						}""",
						[provider_config.user_info_path, api_user_key, api_user],
					)
					parsed = _parse_user_info_json(result) if result.get('success') else result
					if parsed.get('success'):
						user_info_before = parsed
						print(user_info_before['display'])
						break
					if attempt < MAX_RETRIES:
						print(
							f'[RETRY] {account_name}: Failed to get user info, retrying in {RETRY_DELAY}s ({attempt}/{MAX_RETRIES})'
						)
						await page.wait_for_timeout(RETRY_DELAY * 1000)
					else:
						user_info_before = parsed
						print(parsed.get('error', 'Unknown error'))

				# 执行签到
				success = False
				if provider_config.needs_manual_check_in():
					sign_in_path = provider_config.sign_in_path
					print(f'[NETWORK] {account_name}: Executing check-in via browser fetch')
					checkin_result = await page.evaluate(
						"""async ([path, fallbackPath, key, user]) => {
							const headers = {
								'Content-Type': 'application/json',
								'X-Requested-With': 'XMLHttpRequest',
								[key]: user
							};
							try {
								let r = await fetch(path, {method: 'POST', headers});
								if (r.status === 404 && path !== fallbackPath) {
									r = await fetch(fallbackPath, {method: 'POST', headers});
								}
								const status = r.status;
								let body;
								try { body = await r.json(); } catch(e) { body = {_raw: await r.text()}; }
								return {status, body};
							} catch(e) { return {status: 0, body: {error: e.message}}; }
						}""",
						[sign_in_path, NEW_API_CHECKIN_PATH, api_user_key, api_user],
					)
					status = checkin_result.get('status', 0)
					body = checkin_result.get('body', {})
					print(f'[RESPONSE] {account_name}: Response status code {status}')

					if status == 200:
						if body.get('ret') == 1 or body.get('code') == 0 or body.get('success'):
							print(f'[SUCCESS] {account_name}: Check-in successful!')
							success = True
						else:
							error_msg = body.get('msg', body.get('message', 'Unknown error'))
							already_checked_keywords = [
								'已经签到',
								'已签到',
								'重复签到',
								'already checked',
								'already signed',
							]
							if any(kw in str(error_msg).lower() for kw in already_checked_keywords):
								print(f'[SUCCESS] {account_name}: Already checked in today')
								success = True
							else:
								print(f'[FAILED] {account_name}: Check-in failed - {error_msg}')
					else:
						print(f'[FAILED] {account_name}: Check-in failed - HTTP {status}')
				else:
					print(f'[INFO] {account_name}: Check-in completed automatically (triggered by user info request)')
					success = True

				# 获取签到后用户信息
				result_after = await page.evaluate(
					"""async ([path, key, user]) => {
						try {
							const r = await fetch(path, {headers: {[key]: user}});
							if (!r.ok) return {success: false, error: 'HTTP ' + r.status};
							return await r.json();
						} catch(e) { return {success: false, error: e.message}; }
					}""",
					[provider_config.user_info_path, api_user_key, api_user],
				)
				user_info_after = _parse_user_info_json(result_after) if result_after.get('success') else result_after

				await context.close()
				return success, user_info_before, user_info_after

			except Exception as e:
				print(f'[FAILED] {account_name}: Playwright check-in error - {str(e)[:100]}')
				await context.close()
				return False, None, None



# ─── Heibai check-in: pure API + cap.js PoW solver (no browser needed) ──────

CAP_API_ENDPOINT = 'https://cap.hybgzs.com/f96f595e4c/'


def _cap_fnv1a(s: str) -> int:
	"""FNV-1a hash (cap.js variant)."""
	h = 2166136261
	for c in s:
		h ^= ord(c)
		h = (h + ((h << 1) + (h << 4) + (h << 7) + (h << 8) + (h << 24))) & 0xFFFFFFFF
	return h


def _cap_prng(seed: str, length: int) -> str:
	"""cap.js PRNG: FNV-1a seeded xorshift → hex string."""
	state = _cap_fnv1a(seed)

	def xorshift():
		nonlocal state
		state ^= (state << 13) & 0xFFFFFFFF
		state ^= (state >> 17)
		state ^= (state << 5) & 0xFFFFFFFF
		return state & 0xFFFFFFFF

	result = ''
	while len(result) < length:
		result += format(xorshift(), '08x')
	return result[:length]


def _solve_cap_challenge(token: str, c: int, s_len: int, d_len: int) -> list[int]:
	"""Solve cap.js PoW challenges: find nonces where SHA256(salt+nonce) starts with target."""
	import hashlib

	solutions = []
	for i in range(1, c + 1):
		salt = _cap_prng(f'{token}{i}', s_len)
		target = _cap_prng(f'{token}{i}d', d_len)
		for nonce in range(1_000_000):
			h = hashlib.sha256(f'{salt}{nonce}'.encode()).hexdigest()
			if h.startswith(target):
				solutions.append(nonce)
				break
		else:
			solutions.append(0)
	return solutions


def check_in_heibai_api(
	account,
	account_name: str,
	provider_config,
):
	"""Heibai check-in via direct API + cap.js PoW solver — no browser needed.

	Flow: /api/checkin/status → cap challenge → solve PoW → redeem → /api/checkin
	"""
	user_cookies = parse_cookies(account.cookies)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None, None

	domain = provider_config.domain
	session = httpx.Client(http2=True, timeout=30.0)
	session.cookies.update(user_cookies)

	try:
		# Check balance before
		user_info_before = None
		try:
			resp = session.get(f'{domain}/api/wallet/balance')
			data = resp.json()
			if data.get('success') and data.get('data'):
				total = data['data'].get('total', 0)
				quota = round(total / 500000, 2)
				user_info_before = {'success': True, 'quota': quota, 'used_quota': 0, 'display': f'💰 Current balance: ${quota}'}
				print(user_info_before['display'])
		except Exception as e:
			print(f'[WARN] {account_name}: Balance check failed: {str(e)[:50]}')

		# Check if check-in is enabled
		status_resp = session.get(f'{domain}/api/checkin/status')
		status = status_resp.json()
		if not status.get('success') or not status.get('enabled'):
			print(f'[FAILED] {account_name}: Check-in disabled')
			return False, user_info_before, None

		cap_required = status.get('capRequired', False)
		cap_token = ''

		if cap_required:
			print(f'[PROCESSING] {account_name}: Solving PoW captcha...')
			# Get challenge
			challenge_resp = session.post(CAP_API_ENDPOINT + 'challenge')
			challenge = challenge_resp.json()
			token = challenge['token']
			c = challenge['challenge']['c']
			s_len = challenge['challenge']['s']
			d_len = challenge['challenge']['d']
			print(f'[INFO] {account_name}: Challenge: {c} puzzles, difficulty={d_len}')

			# Solve
			solutions = _solve_cap_challenge(token, c, s_len, d_len)
			print(f'[INFO] {account_name}: PoW solved ({c} puzzles)')

			# Redeem
			redeem_resp = session.post(
				CAP_API_ENDPOINT + 'redeem',
				json={'token': token, 'solutions': solutions},
			)
			redeem = redeem_resp.json()
			if not redeem.get('success') or not redeem.get('token'):
				print(f'[FAILED] {account_name}: PoW redeem failed: {redeem.get("message", "unknown")}')
				return False, user_info_before, None
			cap_token = redeem['token']
			print(f'[SUCCESS] {account_name}: PoW token obtained')

		# Check in
		print(f'[PROCESSING] {account_name}: Executing check-in...')
		checkin_resp = session.post(
			f'{domain}/api/checkin',
			json={'capToken': cap_token},
		)
		result = checkin_resp.json()

		if checkin_resp.status_code == 200 and result.get('success'):
			msg = result.get('data', {}).get('message', 'Check-in successful')
			consecutive = result.get('data', {}).get('consecutiveDays', 0)
			print(f'[SUCCESS] {account_name}: {msg} (连续{consecutive}天)')

			# Get balance after
			user_info_after = None
			try:
				resp = session.get(f'{domain}/api/wallet/balance')
				data = resp.json()
				if data.get('success') and data.get('data'):
					total = data['data'].get('total', 0)
					quota = round(total / 500000, 2)
					user_info_after = {'success': True, 'quota': quota, 'used_quota': 0, 'display': f'💰 Current balance: ${quota}'}
			except Exception:
				pass

			return True, user_info_before, user_info_after
		else:
			error = result.get('error', checkin_resp.text[:100])
			if '已经签到' in error or '已签到' in error:
				print(f'[SUCCESS] {account_name}: Already checked in today')
				return True, user_info_before, user_info_before
			print(f'[FAILED] {account_name}: Check-in failed: {error}')
			return False, user_info_before, None

	except Exception as e:
		print(f'[FAILED] {account_name}: Heibai API check-in error: {str(e)[:100]}')
		return False, None, None
	finally:
		session.close()


async def check_in_account(account: AccountConfig, account_index: int, app_config: AppConfig):
	"""为单个账号执行签到操作"""
	account_name = account.get_display_name(account_index)
	print(f'\n[PROCESSING] Starting to process {account_name}')

	provider_config = app_config.get_provider(account.provider)
	if not provider_config:
		print(f'[FAILED] {account_name}: Provider "{account.provider}" not found in configuration')
		return False, None, None

	print(f'[INFO] {account_name}: Using provider "{account.provider}" ({provider_config.domain})')

	# 自定义签到（heibai）— 纯 API + PoW 验证码，无需浏览器
	if provider_config.needs_browser_checkin():
		return check_in_heibai_api(account, account_name, provider_config)

	# Cloudflare 防护站点：通过 Playwright 浏览器内 fetch 执行所有请求
	if provider_config.needs_playwright():
		return await check_in_with_playwright(account, account_name, provider_config)

	user_cookies = parse_cookies(account.cookies)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None, None

	all_cookies = await prepare_cookies(account_name, provider_config, user_cookies)
	if not all_cookies:
		return False, None, None

	client = httpx.Client(http2=True, timeout=30.0)

	try:
		client.cookies.update(all_cookies)

		headers = {
			'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36',
			'Accept': 'application/json, text/plain, */*',
			'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
			'Accept-Encoding': 'gzip, deflate, br, zstd',
			'Referer': provider_config.domain,
			'Origin': provider_config.domain,
			'Connection': 'keep-alive',
			'Sec-Fetch-Dest': 'empty',
			'Sec-Fetch-Mode': 'cors',
			'Sec-Fetch-Site': 'same-origin',
			provider_config.api_user_key: account.api_user,
		}

		user_info_url = f'{provider_config.domain}{provider_config.user_info_path}'

		# 获取用户信息（带重试，防止网络抖动）
		user_info_before = None
		for attempt in range(1, MAX_RETRIES + 1):
			user_info_before = get_user_info(client, headers, user_info_url)
			if user_info_before and user_info_before.get('success'):
				print(user_info_before['display'])
				break
			# 自动检测 Cloudflare：httpx 的 TLS 指纹被 CF 拒绝，回退到 Playwright 浏览器
			if user_info_before and user_info_before.get('cloudflare'):
				print(f'[INFO] {account_name}: Cloudflare WAF detected, switching to Playwright browser')
				client.close()
				return await check_in_with_playwright(account, account_name, provider_config)
			if attempt < MAX_RETRIES:
				print(
					f'[RETRY] {account_name}: Failed to get user info, retrying in {RETRY_DELAY}s ({attempt}/{MAX_RETRIES})'
				)
				time.sleep(RETRY_DELAY)
			elif user_info_before:
				print(user_info_before.get('error', 'Unknown error'))

		if provider_config.needs_manual_check_in():
			success = execute_check_in(client, account_name, provider_config, headers)
			# 签到后再次获取用户信息，用于计算签到收益
			user_info_after = get_user_info(client, headers, user_info_url)
			return success, user_info_before, user_info_after
		else:
			print(f'[INFO] {account_name}: Check-in completed automatically (triggered by user info request)')
			# 自动签到的情况，再次获取用户信息
			user_info_after = get_user_info(client, headers, user_info_url)
			return True, user_info_before, user_info_after

	except Exception as e:
		print(f'[FAILED] {account_name}: Error occurred during check-in process - {str(e)[:50]}...')
		return False, None, None
	finally:
		client.close()


async def main():
	"""主函数"""
	print('[SYSTEM] AnyRouter.top multi-account auto check-in script started (using Playwright)')
	print(f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')

	app_config = AppConfig.load_from_env()
	print(f'[INFO] Loaded {len(app_config.providers)} provider configuration(s)')

	accounts = load_accounts_config()
	if not accounts:
		print('[FAILED] Unable to load account configuration, program exits')
		sys.exit(1)

	# Auto-register providers for any account carrying a domain field (injected by plugin)
	app_config.auto_register_from_accounts(accounts)

	print(f'[INFO] Found {len(accounts)} account configurations')

	last_balance_hash = load_balance_hash()

	success_count = 0
	total_count = len(accounts)
	current_balances = {}
	account_check_in_details = {}  # 存储每个账号的签到详情
	need_notify = False  # 是否需要发送通知
	balance_changed = False  # 余额是否有变化

	for i, account in enumerate(accounts):
		account_key = f'account_{i + 1}'
		try:
			success, user_info_before, user_info_after = await check_in_account(account, i, app_config)
			if success:
				success_count += 1

			if not success:
				account_name = account.get_display_name(i)
				print(f'[WARN] {account_name} check-in failed')

			# 存储签到前后的余额信息
			if user_info_after and user_info_after.get('success'):
				current_quota = user_info_after['quota']
				current_used = user_info_after['used_quota']
				current_balances[account_key] = {'quota': current_quota, 'used': current_used}

				# 计算签到收益
				if user_info_before and user_info_before.get('success'):
					before_quota = user_info_before['quota']
					before_used = user_info_before['used_quota']
					after_quota = user_info_after['quota']
					after_used = user_info_after['used_quota']

					# 计算总额度（余额 + 历史消耗）
					total_before = before_quota + before_used
					total_after = after_quota + after_used

					# 签到获得的额度 = 总额度增加量
					check_in_reward = total_after - total_before

					# 本次消耗 = 历史消耗增加量
					usage_increase = after_used - before_used

					# 余额变化
					balance_change = after_quota - before_quota

					provider_config_for_detail = app_config.get_provider(account.provider)
					account_check_in_details[account_key] = {
						'name': account.get_display_name(i),
						'provider_name': account.provider,
						'provider_domain': provider_config_for_detail.domain if provider_config_for_detail else '',
						'before_quota': before_quota,
						'before_used': before_used,
						'after_quota': after_quota,
						'after_used': after_used,
						'check_in_reward': check_in_reward,
						'usage_increase': usage_increase,
						'balance_change': balance_change,
						'success': success,
					}

			provider_config_for_detail = app_config.get_provider(account.provider)
			if account_key not in account_check_in_details:
				account_check_in_details[account_key] = {
					'name': account.get_display_name(i),
					'provider_name': account.provider,
					'provider_domain': provider_config_for_detail.domain if provider_config_for_detail else '',
					'before_quota': user_info_before['quota']
					if user_info_before and user_info_before.get('success')
					else None,
					'before_used': user_info_before['used_quota']
					if user_info_before and user_info_before.get('success')
					else None,
					'after_quota': user_info_after['quota']
					if user_info_after and user_info_after.get('success')
					else None,
					'after_used': user_info_after['used_quota']
					if user_info_after and user_info_after.get('success')
					else None,
					'check_in_reward': 0,
					'usage_increase': 0,
					'balance_change': 0,
					'success': success,
					'error_message': None
					if success
					else (user_info_after.get('error') if user_info_after else 'Unknown error'),
				}

		except Exception as e:
			account_name = account.get_display_name(i)
			print(f'[FAILED] {account_name} processing exception: {e}')
			provider_config_for_detail = app_config.get_provider(account.provider)
			account_check_in_details[account_key] = {
				'name': account_name,
				'provider_name': account.provider,
				'provider_domain': provider_config_for_detail.domain if provider_config_for_detail else '',
				'before_quota': None,
				'before_used': None,
				'after_quota': None,
				'after_used': None,
				'check_in_reward': 0,
				'usage_increase': 0,
				'balance_change': 0,
				'success': False,
				'error_message': str(e)[:100],
			}

	# 检查余额变化
	current_balance_hash = generate_balance_hash(current_balances) if current_balances else None
	if current_balance_hash:
		if last_balance_hash is None:
			# 首次运行
			balance_changed = True
			need_notify = True
			print('[NOTIFY] First run detected, will send notification with current balances')
		elif current_balance_hash != last_balance_hash:
			# 余额有变化
			balance_changed = True
			need_notify = True
			print('[NOTIFY] Balance changes detected, will send notification')
		else:
			print('[INFO] No balance changes detected')

	# 全部失败时强制通知（严重问题）
	if success_count == 0:
		need_notify = True
		print('[NOTIFY] All accounts failed, will send notification')

	# 保存当前余额hash
	if current_balance_hash:
		save_balance_hash(current_balance_hash)

	# 仅在余额变化、首次运行或全部失败时发送通知
	if need_notify and account_check_in_details:
		success_rate = success_count / total_count if total_count else 0
		if success_rate == 1:
			card_color = 'green'
		elif success_rate > 0:
			card_color = 'orange'
		else:
			card_color = 'red'

		card_title = f'签到报告 ✅{success_count}/{total_count}' if success_count > 0 else f'签到报告 ❌0/{total_count}'
		notify_content = format_compact_notification(account_check_in_details, success_count, total_count)

		print(notify_content)
		notify.push_message(card_title, notify_content, msg_type=card_color)
		print('[NOTIFY] Notification sent')
	else:
		print('[INFO] No meaningful changes, notification skipped')

	# 设置退出码
	sys.exit(0 if success_count > 0 else 1)


def run_main():
	"""运行主函数的包装函数"""
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		print('\n[WARNING] Program interrupted by user')
		sys.exit(1)
	except Exception as e:
		print(f'\n[FAILED] Error occurred during program execution: {e}')
		sys.exit(1)


if __name__ == '__main__':
	run_main()
