"""Diagnostic: inspect + try to solve the Aliyun WAF slider on agentrouter.org.

GitHub runner (datacenter) IPs get an Aliyun WAF "Verification" slider page.
This script dumps the slider DOM, attempts a human-like drag, and reports
whether API fetches return JSON afterwards. Screenshots saved to ./debug_shots.
"""

import asyncio
import json
import os
import random

from playwright.async_api import async_playwright

DOMAIN = 'https://agentrouter.org'
SHOT_DIR = 'debug_shots'


async def dump_captcha_dom(page):
	"""List elements that look like slider/captcha widgets."""
	return await page.evaluate(
		"""() => {
			const out = [];
			const rx = /slide|slider|nc_|captcha|verify|puzzle|drag/i;
			for (const el of document.querySelectorAll('*')) {
				const idc = (el.id || '') + ' ' + (el.className || '');
				if (typeof idc === 'string' && rx.test(idc)) {
					const r = el.getBoundingClientRect();
					out.push({
						tag: el.tagName, id: el.id,
						cls: String(el.className).slice(0, 60),
						x: Math.round(r.x), y: Math.round(r.y),
						w: Math.round(r.width), h: Math.round(r.height),
						text: (el.textContent || '').slice(0, 40).trim(),
					});
				}
			}
			return out.slice(0, 40);
		}"""
	)


async def try_drag(page, handle_box, distance):
	"""Human-like drag: overshoot slightly, jittered steps, settle back."""
	start_x = handle_box['x'] + handle_box['w'] / 2
	start_y = handle_box['y'] + handle_box['h'] / 2
	await page.mouse.move(start_x, start_y, steps=random.randint(8, 15))
	await page.mouse.down()
	await page.wait_for_timeout(random.randint(80, 200))

	moved = 0.0
	target = distance + random.uniform(2, 6)  # slight overshoot
	while moved < target:
		step = min(random.uniform(8, 28), target - moved)
		moved += step
		jitter_y = start_y + random.uniform(-3, 3)
		await page.mouse.move(start_x + moved, jitter_y, steps=random.randint(1, 3))
		await page.wait_for_timeout(random.randint(8, 30))
	# settle back to the exact end
	await page.mouse.move(start_x + distance, start_y, steps=3)
	await page.wait_for_timeout(random.randint(100, 250))
	await page.mouse.up()


async def fetch_user_info(page, api_user, token):
	return await page.evaluate(
		"""async ([user, token]) => {
			const headers = {'new-api-user': user};
			if (token) headers['Authorization'] = token;
			try {
				const r = await fetch('/api/user/self', {headers});
				const text = await r.text();
				return {status: r.status, snippet: text.slice(0, 300)};
			} catch (e) { return {status: 0, snippet: 'fetch error: ' + e.message}; }
		}""",
		[api_user, token],
	)


async def main():
	os.makedirs(SHOT_DIR, exist_ok=True)
	account = json.loads(os.getenv('DEBUG_ACCOUNT') or '{}')
	api_user = str(account.get('api_user', ''))
	token = account.get('access_token', '')

	async with async_playwright() as p:
		import tempfile

		with tempfile.TemporaryDirectory() as tmp:
			ctx = await p.chromium.launch_persistent_context(
				user_data_dir=tmp,
				headless=False,
				user_agent=(
					'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
					'(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36'
				),
				viewport={'width': 1920, 'height': 1080},
				args=[
					'--disable-blink-features=AutomationControlled',
					'--disable-dev-shm-usage',
					'--no-sandbox',
				],
			)
			await ctx.add_init_script(
				"Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
			)
			page = await ctx.new_page()

			resp = await page.goto(f'{DOMAIN}/', wait_until='domcontentloaded', timeout=60000)
			print(f'goto status: {resp.status if resp else "?"}')
			await page.wait_for_timeout(6000)  # let the slider widget render

			title = await page.title()
			print(f'title: {title!r}')
			await page.screenshot(path=f'{SHOT_DIR}/01_initial.png')

			if 'verification' not in title.lower():
				print('No verification page — IP not challenged. Fetching directly.')
				r = await fetch_user_info(page, api_user, token)
				print(f'fetch -> HTTP {r["status"]}: {r["snippet"]}')
				await ctx.close()
				return

			elements = await dump_captcha_dom(page)
			print(f'\ncaptcha-ish DOM elements ({len(elements)}):')
			for el in elements:
				print(f'  {el}')

			# Heuristic: the drag handle is a small (~40px) element inside a wide track
			handle = None
			track_w = 320
			for el in elements:
				if el['w'] and 20 <= el['w'] <= 80 and 20 <= el['h'] <= 80:
					handle = el
				if el['w'] and el['w'] >= 200:
					track_w = max(track_w, 0) if el['w'] > 500 else el['w']
			if not handle:
				print('\nNo obvious drag handle found; dumping full body for analysis:')
				print((await page.content())[:3000])
				await ctx.close()
				return

			distance = track_w - handle['w'] + 4
			print(f'\nAttempting drag: handle={handle["id"] or handle["cls"]} distance={distance}px')
			for attempt in range(1, 4):
				await try_drag(page, handle, distance)
				await page.wait_for_timeout(4000)
				title = await page.title()
				await page.screenshot(path=f'{SHOT_DIR}/02_after_drag_{attempt}.png')
				print(f'after drag {attempt}: title={title!r}')
				if 'verification' not in title.lower():
					print('Slider PASSED — page reloaded past WAF')
					break
				# re-locate handle (widget may have reset/re-rendered)
				elements = await dump_captcha_dom(page)
				handle = next(
					(el for el in elements if el['w'] and 20 <= el['w'] <= 80 and 20 <= el['h'] <= 80),
					None,
				)
				if not handle:
					print('handle vanished after drag; stopping')
					break

			cookies = {c['name']: c['value'][:16] for c in await ctx.cookies()}
			print(f'cookies now: {list(cookies)}')
			r = await fetch_user_info(page, api_user, token)
			print(f'\nfetch /api/user/self -> HTTP {r["status"]}')
			print(f'body snippet: {r["snippet"]}')

			await ctx.close()


asyncio.run(main())
