"""Diagnostic: what page does a GitHub runner actually get from agentrouter.org?

Prints page title, final URL, cookies set by the WAF, and the raw response
snippet of an in-browser /api/user/self fetch. Safe to run anywhere.
"""

import asyncio
import json
import os

from playwright.async_api import async_playwright

DOMAIN = 'https://agentrouter.org'


async def main():
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

			# Poll for up to 30s: challenge pages usually resolve within this window
			for i in range(7):
				title = await page.title()
				url = page.url
				cookies = {c['name']: c['value'][:18] for c in await ctx.cookies()}
				print(f'[{i * 5}s] title={title!r} url={url} cookies={list(cookies)}')
				body_head = (await page.content())[:300].replace('\n', ' ')
				print(f'      body: {body_head}')
				if 'just a moment' not in title.lower() and 'checking' not in title.lower():
					if i >= 1:
						break
				await page.wait_for_timeout(5000)

			# In-browser fetch of user info, dumping raw text
			result = await page.evaluate(
				"""async ([user, token]) => {
					const headers = {'new-api-user': user};
					if (token) headers['Authorization'] = token;
					try {
						const r = await fetch('/api/user/self', {headers});
						const text = await r.text();
						return {status: r.status, snippet: text.slice(0, 400)};
					} catch (e) { return {status: 0, snippet: 'fetch error: ' + e.message}; }
				}""",
				[api_user, token],
			)
			print(f'\nfetch /api/user/self -> HTTP {result["status"]}')
			print(f'body snippet: {result["snippet"]}')

			await ctx.close()


asyncio.run(main())
