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


def format_check_in_notification(detail: dict) -> str:
	"""格式化签到通知消息"""
	provider_info = ''
	if detail.get('provider_name') or detail.get('provider_domain'):
		pname = detail.get('provider_name', '')
		pdomain = detail.get('provider_domain', '')
		provider_info = f'  🌐 平台: {pname} ({pdomain})\n' if pdomain else f'  🌐 平台: {pname}\n'

	lines = [
		f'[CHECK-IN] {detail["name"]}',
		'  ━━━━━━━━━━━━━━━━━━━━',
	]
	if provider_info:
		lines.append(provider_info.rstrip('\n'))

	before_quota = detail.get('before_quota')
	before_used = detail.get('before_used')
	after_quota = detail.get('after_quota')
	after_used = detail.get('after_used')
	error_message = detail.get('error_message')
	success = detail.get('success', False)

	if before_quota is not None and before_used is not None:
		lines.extend(
			[
				'  📍 签到前',
				f'     💵 余额: ${before_quota:.2f}  |  📊 累计消耗: ${before_used:.2f}',
			]
		)
	if after_quota is not None and after_used is not None:
		lines.extend(
			[
				'  📍 签到后',
				f'     💵 余额: ${after_quota:.2f}  |  📊 累计消耗: ${after_used:.2f}',
			]
		)

	if not success:
		lines.append('  ━━━━━━━━━━━━━━━━━━━━')
		lines.append('  ❌ 签到失败')
		if error_message:
			lines.append(f'  ⚠️ 错误信息: {error_message}')
		return '\n'.join(lines)

	# 判断是否有变化
	has_reward = detail.get('check_in_reward', 0) != 0
	has_usage = detail.get('usage_increase', 0) != 0

	if has_reward or has_usage:
		lines.append('  ━━━━━━━━━━━━━━━━━━━━')

		if not has_reward and has_usage:
			lines.append('  ℹ️  今日已签到（期间有使用）')
		if has_reward:
			lines.append(f'  🎁 签到获得: +${detail["check_in_reward"]:.2f}')
		if has_usage:
			lines.append(f'  📉 期间消耗: ${detail["usage_increase"]:.2f}')
		if detail.get('balance_change', 0) != 0:
			change_symbol = '+' if detail['balance_change'] > 0 else ''
			change_emoji = '📈' if detail['balance_change'] > 0 else '📉'
			lines.append(f'  {change_emoji} 余额变化: {change_symbol}${detail["balance_change"]:.2f}')
	else:
		lines.extend(['  ━━━━━━━━━━━━━━━━━━━━', '  ℹ️  今日已签到，无变化'])

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


async def _solve_turnstile(page, account_name: str) -> bool:
	"""查找并解决 Cloudflare Turnstile 验证

	Turnstile widget structure (from parent page):
	  input[name="cf-turnstile-response"]  (hidden token input)
	    → parent div (.cf-turnstile wrapper)
	      → shadowRoot
	        → iframe (challenges.cloudflare.com)
	          → body → shadowRoot → input (the checkbox)

	The iframe is inside a shadow DOM, so normal CSS selectors can't find it.
	We use JS shadow DOM traversal to locate and click it.
	"""
	print(f'[PROCESSING] {account_name}: Looking for Turnstile verification...')

	for attempt in range(20):
		# Strategy 0: Check if token already exists (managed mode auto-resolved)
		try:
			token_check = await page.evaluate("""() => {
				try { const r = turnstile.getResponse(); if (r) return 'has_token'; } catch(e) {}
				const inp = document.querySelector('input[name="cf-turnstile-response"]');
				return (inp && inp.value) ? 'has_token' : null;
			}""")
			if token_check == 'has_token':
				print(f'[SUCCESS] {account_name}: Turnstile already solved (token present)')
				return True
		except Exception:
			pass

		# Strategy 1: Use Turnstile JS API to trigger and wait for resolution
		if attempt == 0:
			try:
				await page.evaluate("""() => {
					try { turnstile.reset(); } catch(e) {}
					try { turnstile.execute(); } catch(e) {}
					// Also try to render if there's a container
					try {
						const container = document.querySelector('input[name="cf-turnstile-response"]')?.parentElement;
						if (container) turnstile.render(container);
					} catch(e) {}
				}""")
				print(f'[INFO] {account_name}: Called turnstile.reset()/execute()/render()')
			except Exception:
				pass

		# Strategy 1: Shadow DOM traversal — find iframe inside wrapper's shadowRoot
		try:
			iframe_box = await page.evaluate("""() => {
				// Path: input[name="cf-turnstile-response"] → parent → shadowRoot → iframe
				const resp = document.querySelector('input[name="cf-turnstile-response"]');
				if (resp) {
					const wrapper = resp.parentElement;
					if (wrapper && wrapper.shadowRoot) {
						const iframe = wrapper.shadowRoot.querySelector('iframe');
						if (iframe) {
							const rect = iframe.getBoundingClientRect();
							if (rect.width > 0 && rect.height > 0) {
								return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, method: 'shadow_dom' };
							}
						}
					}
				}
				// Fallback: try [data-sitekey] wrapper
				const sitekey = document.querySelector('[data-sitekey]');
				if (sitekey && sitekey.shadowRoot) {
					const iframe = sitekey.shadowRoot.querySelector('iframe');
					if (iframe) {
						const rect = iframe.getBoundingClientRect();
						if (rect.width > 0 && rect.height > 0) {
							return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, method: 'sitekey_shadow' };
						}
					}
				}
				// Fallback: try .cf-turnstile wrapper
				const cfDiv = document.querySelector('.cf-turnstile');
				if (cfDiv && cfDiv.shadowRoot) {
					const iframe = cfDiv.shadowRoot.querySelector('iframe');
					if (iframe) {
						const rect = iframe.getBoundingClientRect();
						if (rect.width > 0 && rect.height > 0) {
							return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, method: 'cf_turnstile_shadow' };
						}
					}
				}
				return null;
			}""")

			if iframe_box:
				cx = iframe_box['x'] + iframe_box['width'] / 2
				cy = iframe_box['y'] + iframe_box['height'] / 2
				print(f'[INFO] {account_name}: Found Turnstile via {iframe_box["method"]} ({iframe_box["width"]:.0f}x{iframe_box["height"]:.0f}), clicking ({cx:.0f},{cy:.0f})...')
				await page.mouse.click(cx, cy)
				await page.wait_for_timeout(3000)

				# Verify solution
				solved = await page.evaluate("""() => {
					try { const r = turnstile.getResponse(); if (r) return true; } catch(e) {}
					const inp = document.querySelector('input[name="cf-turnstile-response"]');
					return !!(inp && inp.value);
				}""")
				if solved:
					print(f'[SUCCESS] {account_name}: Turnstile solved after click')
					return True
		except Exception as e:
			if attempt < 2:
				print(f'[WARN] {account_name}: Shadow DOM traversal error: {str(e)[:80]}')

		# Strategy 2: Inner-frame element click (legacy fallback)
		for frame in page.frames:
			if 'challenges.cloudflare.com' not in frame.url:
				continue
			try:
				result = await frame.evaluate("""() => {
					const body = document.body;
					if (body && body.shadowRoot) {
						const inp = body.shadowRoot.querySelector('input');
						if (inp) { inp.click(); return 'clicked_shadow'; }
					}
					const inp = document.querySelector('input[type="checkbox"], input');
					if (inp) { inp.click(); return 'clicked_input'; }
					const clickable = document.querySelector('[role="checkbox"], [tabindex], button');
					if (clickable) { clickable.click(); return 'clicked_element'; }
					return 'no_element';
				}""")
				if result.startswith('clicked'):
					print(f'[INFO] {account_name}: Turnstile inner click: {result}')
					await page.wait_for_timeout(3000)
					return True
				elif attempt < 3:
					print(f'[INFO] {account_name}: Turnstile inner: {result} (attempt {attempt + 1})')
			except Exception:
				pass
			break  # Only process first matching frame

		# Retry turnstile.execute() periodically
		if attempt in (5, 10, 15):
			try:
				await page.evaluate('try { turnstile.execute() } catch(e) {}')
			except Exception:
				pass

		await page.wait_for_timeout(1500)

	print(f'[FAILED] {account_name}: Turnstile not solved after 20 attempts')
	return False


async def _get_wallet_balance(page, account_name: str, domain: str) -> dict:
	"""通过 /api/wallet/balance 获取 heibai 余额"""
	try:
		result = await page.evaluate(
			"""async (domain) => {
				try {
					const r = await fetch(domain + '/api/wallet/balance', {credentials: 'include'});
					if (!r.ok) return {success: false, error: 'HTTP ' + r.status};
					return await r.json();
				} catch(e) { return {success: false, error: e.message}; }
			}""",
			domain,
		)
		if result.get('success') and result.get('data'):
			total = result['data'].get('total', 0)
			quota = round(total / 500000, 2)
			return {
				'success': True,
				'quota': quota,
				'used_quota': 0,
				'display': f'💰 Current balance: ${quota}',
			}
		return {'success': False, 'error': result.get('error', 'Unknown error')}
	except Exception as e:
		return {'success': False, 'error': f'Failed to get balance: {str(e)[:50]}'}


# ─── DrissionPage (real Chrome) check-in for Turnstile-protected sites ────────


def _get_wallet_balance_dp(tab, account_name: str, domain: str) -> dict:
	"""通过 DrissionPage 在页面内执行 fetch 获取 heibai 余额"""
	try:
		result = tab.run_js(
			'''return fetch(arguments[0] + '/api/wallet/balance', {credentials: 'include'})
				.then(r => r.ok ? r.json() : {success: false, error: 'HTTP ' + r.status})
				.catch(e => ({success: false, error: e.message}))''',
			domain,
		)
		if result and result.get('success') and result.get('data'):
			total = result['data'].get('total', 0)
			quota = round(total / 500000, 2)
			return {
				'success': True,
				'quota': quota,
				'used_quota': 0,
				'display': f'💰 Current balance: ${quota}',
			}
		return {'success': False, 'error': result.get('error', 'Unknown error') if result else 'No response'}
	except Exception as e:
		return {'success': False, 'error': f'Failed to get balance: {str(e)[:50]}'}


def _solve_turnstile_dp(tab, account_name: str) -> bool:
	"""使用 DrissionPage (real Chrome) 解决 Cloudflare Turnstile

	基于 grok_register.py 验证方案：
	0. 先 turnstile.reset() 触发验证流程
	1. 轮询 turnstile.getResponse() / input 检查 token
	2. shadow DOM 遍历找到 iframe → 注入 CDP mouse patch → 点击 checkbox
	3. 点击后检查页面是否已完成签到（auto-submit 后页面可能导航）
	"""
	print(f'[PROCESSING] {account_name}: Looking for Turnstile verification (DrissionPage)...')

	# Trigger reset first
	try:
		tab.run_js('try { turnstile.reset() } catch(e) { }')
	except Exception:
		pass

	clicked = False
	for attempt in range(25):
		# Check if token already present
		try:
			token = tab.run_js(
				'try { return turnstile.getResponse() } catch(e) { return null }'
			)
			if token and len(str(token)) > 20:
				print(f'[SUCCESS] {account_name}: Turnstile solved (attempt {attempt + 1})')
				return True
		except Exception:
			pass

		# Also check input field
		try:
			token = tab.run_js('''
				const inp = document.querySelector('input[name="cf-turnstile-response"]');
				return (inp && inp.value && inp.value.length > 20) ? inp.value : null;
			''')
			if token:
				print(f'[SUCCESS] {account_name}: Turnstile solved via input (attempt {attempt + 1})')
				return True
		except Exception:
			pass

		# Check if page already completed check-in (Turnstile solved + auto-submitted)
		try:
			body_text = tab.ele('tag:body').text or ''
			if '今日已签到' in body_text or '签到成功' in body_text:
				print(f'[SUCCESS] {account_name}: Check-in completed (page navigated after Turnstile, attempt {attempt + 1})')
				return True
			# Diagnostic: log page state periodically after click
			if clicked and attempt in (2, 5, 10, 15):
				snippet = body_text[:200].replace('\n', ' ').strip()
				print(f'[DEBUG] {account_name}: attempt={attempt + 1} URL={tab.url} body=[{snippet}]')
		except Exception as e:
			if clicked and attempt <= 5:
				print(f'[DEBUG] {account_name}: Page access error: {str(e)[:80]}')

		# After first successful click, wait longer and focus on token/page checks
		if clicked:
			time.sleep(2)
			# After 8 polls, allow re-clicking
			if attempt >= 8 and attempt % 4 == 0:
				clicked = False
			else:
				continue

		# Shadow DOM iframe click approach (from grok_register.py)
		try:
			ci = tab.ele('@name=cf-turnstile-response')
			wrapper = ci.parent()
			iframe = wrapper.shadow_root.ele('tag:iframe')
			# Inject CDP mouse patch directly into iframe
			iframe.run_js(
				"if(!window.dtp){window.dtp=1;"
				"var r=function(a,b){return Math.floor(Math.random()*(b-a+1))+a;};"
				"Object.defineProperty(MouseEvent.prototype,'screenX',{value:r(800,1200)});"
				"Object.defineProperty(MouseEvent.prototype,'screenY',{value:r(400,600)});}"
			)
			iframe_body = iframe.ele('tag:body').shadow_root
			iframe_body.ele('tag:input').click()
			clicked = True
			print(f'[INFO] {account_name}: Clicked Turnstile checkbox in iframe shadow DOM (attempt {attempt + 1})')
			time.sleep(3)  # Wait longer after click for Turnstile to process
			continue
		except Exception as e:
			if attempt < 5:
				print(f'[INFO] {account_name}: Shadow DOM click: {str(e)[:80]}')

		# Retry execute periodically
		if attempt in (5, 10, 15, 20):
			try:
				tab.run_js('try { turnstile.execute() } catch(e) {}')
			except Exception:
				pass

		time.sleep(1.5)

	print(f'[FAILED] {account_name}: Turnstile not solved after 25 attempts')
	return False


def check_in_with_drissionpage(
	account,
	account_name: str,
	provider_config,
):
	"""通过 DrissionPage (real Chrome) 执行签到（含 Cloudflare Turnstile 验证）

	使用真实 Chrome + WARP + turnstilePatch 扩展 + shadow DOM iframe 点击方案过盾。
	"""
	import pathlib

	from DrissionPage import Chromium, ChromiumOptions

	user_cookies = parse_cookies(account.cookies)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None, None

	print(f'[INFO] {account_name}: Using DrissionPage (real Chrome) with Turnstile bypass')

	# Configure Chrome
	co = ChromiumOptions()
	co.auto_port()
	co.set_argument('--no-sandbox')
	co.set_argument('--disable-dev-shm-usage')
	co.set_argument('--disable-blink-features=AutomationControlled')
	co.set_argument('--window-size=1280,900')
	co.set_user_agent(PLAYWRIGHT_USER_AGENT)

	# Load turnstilePatch extension
	ext_path = str(pathlib.Path(__file__).parent / 'turnstilePatch')
	if os.path.isdir(ext_path):
		co.add_extension(ext_path)
	else:
		print(f'[WARN] {account_name}: turnstilePatch extension not found at {ext_path}')

	browser = Chromium(co)
	page = browser.get_tab()

	try:
		domain = provider_config.domain
		hostname = urlparse(domain).hostname

		# Navigate to domain root to establish context, then set cookies
		page.get(domain)
		time.sleep(1)

		for name, value in user_cookies.items():
			page.set.cookies({
				'name': name,
				'value': value,
				'domain': hostname,
				'path': '/',
				'secure': True,
			})

		# Navigate to check-in page
		checkin_url = f'{domain}{provider_config.checkin_page_path}'
		print(f'[PROCESSING] {account_name}: Navigating to check-in page...')
		page.get(checkin_url)
		time.sleep(3)

		# Check session expiry
		if '/login' in page.url or '/auth/signin' in page.url:
			print(f'[FAILED] {account_name}: Session expired - redirected to login')
			browser.quit()
			return False, None, None

		# Get balance before check-in
		user_info_before = _get_wallet_balance_dp(page, account_name, domain)
		if user_info_before.get('success'):
			print(user_info_before['display'])

		# Check if already checked in
		already_el = page.ele('text=今日已签到', timeout=2)
		if already_el:
			print(f'[SUCCESS] {account_name}: Already checked in today')
			browser.quit()
			return True, user_info_before, user_info_before

		# Find check-in button
		checkin_btn = page.ele('tag:button@@text():立即签到', timeout=3) or page.ele('tag:button@@text():签到', timeout=2)
		if not checkin_btn:
			print(f'[FAILED] {account_name}: Check-in button not found on page')
			browser.quit()
			return False, user_info_before, None

		# Click check-in button
		print(f'[PROCESSING] {account_name}: Clicking check-in button...')
		checkin_btn.click()
		time.sleep(2)

		# Solve Turnstile
		turnstile_solved = _solve_turnstile_dp(page, account_name)
		if not turnstile_solved:
			print(f'[FAILED] {account_name}: Failed to solve Turnstile verification')
			browser.quit()
			return False, user_info_before, None

		# Wait for check-in completion
		print(f'[PROCESSING] {account_name}: Waiting for check-in completion...')
		success = False
		signed_el = page.ele('text=今日已签到', timeout=15)
		if signed_el:
			print(f'[SUCCESS] {account_name}: Check-in successful!')
			success = True
		else:
			body_text = page.ele('tag:body').text or ''
			if '今日已签到' in body_text or '签到成功' in body_text:
				print(f'[SUCCESS] {account_name}: Check-in successful!')
				success = True
			else:
				print(f'[FAILED] {account_name}: Check-in result unclear')

		# Get balance after check-in
		time.sleep(2)
		user_info_after = _get_wallet_balance_dp(page, account_name, domain)

		browser.quit()
		return success, user_info_before, user_info_after

	except Exception as e:
		print(f'[FAILED] {account_name}: DrissionPage check-in error - {str(e)[:100]}')
		try:
			browser.quit()
		except Exception:
			pass
		return False, None, None


async def check_in_with_turnstile_browser(
	account: AccountConfig,
	account_name: str,
	provider_config,
):
	"""[DEPRECATED] Playwright-based Turnstile bypass — replaced by check_in_with_drissionpage().
	Kept for reference/rollback. Playwright Chromium is detected by Turnstile managed mode.

	通过 Playwright 浏览器执行签到（含 Cloudflare Turnstile 验证）

	适用于非 NewAPI/OneAPI 格式的自定义签到站点（如 heibai）。
	流程：导航到签到页 -> 获取余额 -> 点击签到按钮 -> 解决 Turnstile -> 等待完成 -> 获取更新余额
	"""
	user_cookies = parse_cookies(account.cookies)
	if not user_cookies:
		print(f'[FAILED] {account_name}: Invalid configuration format')
		return False, None, None

	print(f'[INFO] {account_name}: Using Playwright browser with Turnstile bypass')

	async with async_playwright() as p:
		import tempfile

		with tempfile.TemporaryDirectory() as temp_dir:
			context = await p.chromium.launch_persistent_context(
				user_data_dir=temp_dir,
				headless=False,
				user_agent=PLAYWRIGHT_USER_AGENT,
				viewport={'width': 1280, 'height': 900},
				args=PLAYWRIGHT_BROWSER_ARGS,
			)

			try:
				# 注入 session cookies（__Host- 和 __Secure- 前缀需要 secure=True）
				hostname = urlparse(provider_config.domain).hostname
				for name, value in user_cookies.items():
					await context.add_cookies(
						[
							{
								'name': name,
								'value': value,
								'domain': hostname,
								'path': '/',
								'secure': True,
							}
						]
					)

				page = await context.new_page()
				await page.add_init_script(CDP_MOUSE_PATCH_JS)

				# 导航到签到页面
				checkin_url = f'{provider_config.domain}{provider_config.checkin_page_path}'
				print(f'[PROCESSING] {account_name}: Navigating to check-in page...')
				try:
					await page.goto(checkin_url, wait_until='domcontentloaded', timeout=30000)
				except Exception:
					pass  # networkidle 可能超时，页面已加载即可
				await page.wait_for_timeout(3000)

				# 检查是否被重定向到登录页面（session 过期）
				if '/login' in page.url or '/auth/signin' in page.url:
					print(f'[FAILED] {account_name}: Session expired - redirected to login')
					await context.close()
					return False, None, None

				# 获取签到前余额
				user_info_before = await _get_wallet_balance(page, account_name, provider_config.domain)
				if user_info_before.get('success'):
					print(user_info_before['display'])

				# 检查是否已签到
				already_signed = page.locator('text=今日已签到')
				checkin_btn = page.locator('button:has-text("立即签到"), button:has-text("签到"):not(:has-text("今日已签到"))')

				if await already_signed.count() > 0:
					print(f'[SUCCESS] {account_name}: Already checked in today')
					await context.close()
					return True, user_info_before, user_info_before

				if await checkin_btn.count() == 0:
					print(f'[FAILED] {account_name}: Check-in button not found on page')
					await context.close()
					return False, user_info_before, None

				# 如果 Turnstile 已经弹出（覆盖按钮），先解决它
				has_turnstile_before = any(
					'challenges.cloudflare.com' in f.url for f in page.frames
				)
				if has_turnstile_before:
					print(f'[INFO] {account_name}: Turnstile overlay detected before click, solving first...')
					await _solve_turnstile(page, account_name)
					await page.wait_for_timeout(2000)

				# 点击签到按钮
				print(f'[PROCESSING] {account_name}: Clicking check-in button...')
				try:
					await checkin_btn.first.click(timeout=10000)
				except Exception as e:
					# 按钮可能被遮挡或未完全渲染，使用 force click
					print(f'[INFO] {account_name}: Normal click failed ({type(e).__name__}), trying force click...')
					try:
						await checkin_btn.first.click(timeout=5000, force=True)
					except Exception as click_err:
						print(f'[FAILED] {account_name}: Check-in button not clickable: {str(click_err)[:80]}')
						await context.close()
						return False, user_info_before, None
				await page.wait_for_timeout(2000)

				# 解决 Turnstile 验证（点击后弹出）
				turnstile_solved = await _solve_turnstile(page, account_name)
				if not turnstile_solved:
					print(f'[FAILED] {account_name}: Failed to solve Turnstile verification')
					await context.close()
					return False, user_info_before, None

				# 等待签到完成
				print(f'[PROCESSING] {account_name}: Waiting for check-in completion...')
				success = False
				try:
					await page.wait_for_selector('text=今日已签到', timeout=15000)
					print(f'[SUCCESS] {account_name}: Check-in successful!')
					success = True
				except Exception:
					body_text = await page.locator('body').inner_text()
					if '今日已签到' in body_text or '签到成功' in body_text:
						print(f'[SUCCESS] {account_name}: Check-in successful!')
						success = True
					else:
						print(f'[FAILED] {account_name}: Check-in result unclear')

				# 等待余额更新
				await page.wait_for_timeout(2000)
				user_info_after = await _get_wallet_balance(page, account_name, provider_config.domain)

				await context.close()
				return success, user_info_before, user_info_after

			except Exception as e:
				print(f'[FAILED] {account_name}: Turnstile browser check-in error - {str(e)[:100]}')
				await context.close()
				return False, None, None


async def check_in_account(account: AccountConfig, account_index: int, app_config: AppConfig):
	"""为单个账号执行签到操作"""
	account_name = account.get_display_name(account_index)
	print(f'\n[PROCESSING] Starting to process {account_name}')

	provider_config = app_config.get_provider(account.provider)
	if not provider_config:
		print(f'[FAILED] {account_name}: Provider "{account.provider}" not found in configuration')
		return False, None, None

	print(f'[INFO] {account_name}: Using provider "{account.provider}" ({provider_config.domain})')

	# 自定义浏览器签到（含 Turnstile 验证，如 heibai）— 使用 DrissionPage (real Chrome)
	if provider_config.needs_browser_checkin():
		return await asyncio.to_thread(check_in_with_drissionpage, account, account_name, provider_config)

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
	notification_content = []
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
				need_notify = True
				account_name = account.get_display_name(i)
				print(f'[NOTIFY] {account_name} failed, will send notification')

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
			need_notify = True  # 异常也需要通知
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

	# 只要需要发送通知，就将所有账号统一渲染为同一种卡片内容
	if need_notify:
		for i, account in enumerate(accounts):
			account_key = f'account_{i + 1}'
			if account_key not in account_check_in_details:
				continue
			detail = account_check_in_details[account_key]
			notification_content.append(format_check_in_notification(detail))

	# 保存当前余额hash
	if current_balance_hash:
		save_balance_hash(current_balance_hash)

	if need_notify and notification_content:
		# 构建通知内容
		summary = [
			'[STATS] Check-in result statistics:',
			f'[SUCCESS] Success: {success_count}/{total_count}',
			f'[FAIL] Failed: {total_count - success_count}/{total_count}',
		]

		if success_count == total_count:
			summary.append('[SUCCESS] All accounts check-in successful!')
		elif success_count > 0:
			summary.append('[WARN] Some accounts check-in successful')
		else:
			summary.append('[ERROR] All accounts check-in failed')

		time_info = f'[TIME] Execution time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'
		success_rate = success_count / total_count if total_count else 0
		if success_rate == 1:
			card_color = 'green'
		elif success_rate > 0:
			card_color = 'orange'
		else:
			card_color = 'red'
		card_title = 'AnyRouter Check-in Results'

		notify_content = '\n\n'.join([time_info, '\n\n'.join(notification_content), '\n'.join(summary)])

		print(notify_content)
		notify.push_message(card_title, notify_content, msg_type=card_color)
		print('[NOTIFY] Notification sent due to failures or balance changes')
	else:
		print('[INFO] All accounts successful and no balance changes detected, notification skipped')

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
