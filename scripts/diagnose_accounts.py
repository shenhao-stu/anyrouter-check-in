#!/usr/bin/env python3
"""Temporary diagnostic runner for GitHub Actions.

Runs each account in an isolated subprocess with a hard timeout, so one
hung account cannot block the whole job.  Output is redacted before it is
re-emitted by the parent process.  This file is intended for the temporary
branch only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import select
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# When executed as scripts/diagnose_accounts.py, sys.path[0] is scripts/.
# Add the repository root so checkin.py and utils/ are importable in GitHub Actions.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
	sys.path.insert(0, str(REPO_ROOT))

from checkin import check_in_account
from utils.config import AppConfig, load_accounts_config

RESULT_PREFIX = 'GA_DIAG_RESULT '


def env_int(name: str, default: int) -> int:
	"""Parse an integer env var, treating unset/blank/invalid as default."""
	value = os.getenv(name)
	if value is None or value.strip() == '':
		return default
	try:
		return int(value)
	except ValueError:
		print(f'[DIAG] Ignoring invalid integer env {name}={value!r}; using {default}', flush=True)
		return default


def safe_text(value: Any, max_len: int = 500) -> str:
	text = '' if value is None else str(value)
	text = re.sub(r'[\r\n\t]+', ' ', text)
	return text[:max_len]


def compact_user_info(info: Any) -> dict[str, Any] | None:
	if not isinstance(info, dict):
		return None
	out: dict[str, Any] = {'success': bool(info.get('success'))}
	for key in ('quota', 'used_quota', 'display'):
		if key in info:
			out[key] = safe_text(info.get(key), 160)
	error = info.get('error') or info.get('message')
	if error:
		out['error'] = safe_text(error, 220)
	return out


def load_secret_masks() -> list[str]:
	masks: list[str] = []
	for key, value in os.environ.items():
		if not value or len(value) < 8:
			continue
		if key.startswith('ANYROUTER_') or key in {'PROVIDERS'}:
			masks.append(value)
		elif any(token in key for token in ('TOKEN', 'KEY', 'PASS', 'WEBHOOK', 'SECRET')):
			masks.append(value)
	# Longest first so substrings do not reveal tails.
	return sorted(set(masks), key=len, reverse=True)


def redact_line(line: str, masks: list[str]) -> str:
	redacted = line.rstrip('\n')
	for value in masks:
		if value and value in redacted:
			redacted = redacted.replace(value, '[REDACTED]')
	# Defense in depth for common cookie/key material if an exception prints it.
	redacted = re.sub(r'(?i)(session|token|key|cookie|authorization|auth|password|passwd|pass)=([^;\s,}]{8,})', r'\1=[REDACTED]', redacted)
	redacted = re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{12,}', r'\1[REDACTED]', redacted)
	return redacted


def print_account_inventory(accounts: list[Any], app_config: AppConfig) -> None:
	print(f'[DIAG] Loaded account count: {len(accounts)}')
	for idx, account in enumerate(accounts, 1):
		provider_config = app_config.get_provider(account.provider)
		domain = provider_config.domain if provider_config else account.domain or ''
		api_user = account.api_user or ''
		masked_user = api_user[:3] + '***' + api_user[-2:] if len(api_user) > 6 else ('***' if api_user else '')
		print(f'[DIAG] #{idx:02d} name={account.get_display_name(idx-1)!r} provider={account.provider!r} domain={domain!r} api_user={masked_user}')


async def run_one(index: int) -> int:
	app_config = AppConfig.load_from_env()
	accounts = load_accounts_config()
	if not accounts:
		print(RESULT_PREFIX + json.dumps({'index': index, 'status': 'load_failed'}, ensure_ascii=False), flush=True)
		return 2
	app_config.auto_register_from_accounts(accounts)
	if index < 1 or index > len(accounts):
		print(RESULT_PREFIX + json.dumps({'index': index, 'status': 'bad_index', 'total': len(accounts)}, ensure_ascii=False), flush=True)
		return 2
	account = accounts[index - 1]
	provider_config = app_config.get_provider(account.provider)
	started = time.time()
	result: dict[str, Any] = {
		'index': index,
		'name': account.get_display_name(index - 1),
		'provider': account.provider,
		'domain': provider_config.domain if provider_config else account.domain or '',
		'status': 'unknown',
	}
	try:
		success, before, after = await check_in_account(account, index - 1, app_config)
		before_c = compact_user_info(before)
		after_c = compact_user_info(after)
		result.update({
			'status': 'success' if success else 'failed',
			'checkin_success': bool(success),
			'login_before': before_c.get('success') if before_c else None,
			'login_after': after_c.get('success') if after_c else None,
			'before': before_c,
			'after': after_c,
		})
	except Exception as exc:
		result.update({'status': 'exception', 'error': safe_text(exc, 240)})
	finally:
		result['elapsed_sec'] = round(time.time() - started, 1)
		print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False, sort_keys=True), flush=True)
	return 0 if result.get('status') == 'success' else 1


def run_parent(timeout_sec: int) -> int:
	app_config = AppConfig.load_from_env()
	accounts = load_accounts_config()
	if not accounts:
		print('[DIAG] No account configuration loaded')
		return 2
	app_config.auto_register_from_accounts(accounts)
	print(f'[DIAG] Diagnostic started at {datetime.now().isoformat(timespec="seconds")}')
	print_account_inventory(accounts, app_config)
	masks = load_secret_masks()
	results: list[dict[str, Any]] = []
	for idx in range(1, len(accounts) + 1):
		print(f'\n[DIAG] === BEGIN account #{idx:02d} timeout={timeout_sec}s ===', flush=True)
		env = os.environ.copy()
		env['PYTHONUNBUFFERED'] = '1'
		cmd = [sys.executable, '-u', __file__, '--one', str(idx)]
		proc = subprocess.Popen(
			cmd,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			text=True,
			env=env,
			bufsize=1,
			start_new_session=True,
		)
		marker: dict[str, Any] | None = None
		collected: list[str] = []
		deadline = time.time() + timeout_sec
		assert proc.stdout is not None
		while True:
			line = ''
			ready, _, _ = select.select([proc.stdout], [], [], 0.2)
			if ready:
				line = proc.stdout.readline()
			if line:
				if line.startswith(RESULT_PREFIX):
					try:
						marker = json.loads(line[len(RESULT_PREFIX):])
					except json.JSONDecodeError as exc:
						marker = {'index': idx, 'status': 'bad_marker', 'error': safe_text(exc)}
				else:
					out_line = redact_line(line, masks)
					collected.append(out_line)
					print(out_line, flush=True)
			if proc.poll() is not None:
				# Drain any tail.
				for tail in proc.stdout.readlines():
					if tail.startswith(RESULT_PREFIX):
						try:
							marker = json.loads(tail[len(RESULT_PREFIX):])
						except json.JSONDecodeError as exc:
							marker = {'index': idx, 'status': 'bad_marker', 'error': safe_text(exc)}
					else:
						out_line = redact_line(tail, masks)
						collected.append(out_line)
						print(out_line, flush=True)
				break
			if time.time() >= deadline:
				print(f'[DIAG] TIMEOUT account #{idx:02d}: killing isolated process group', flush=True)
				try:
					os.killpg(proc.pid, signal.SIGTERM)
				except Exception:
					proc.terminate()
				try:
					proc.wait(timeout=10)
				except subprocess.TimeoutExpired:
					try:
						os.killpg(proc.pid, signal.SIGKILL)
					except Exception:
						proc.kill()
					proc.wait(timeout=10)
				marker = {'index': idx, 'status': 'timeout', 'elapsed_sec': timeout_sec, 'tail': collected[-8:]}
				break
			time.sleep(0.1)
		if marker is None:
			marker = {'index': idx, 'status': 'no_marker', 'returncode': proc.returncode, 'tail': collected[-8:]}
		marker['returncode'] = proc.returncode
		results.append(marker)
		print('[DIAG] SUMMARY ' + json.dumps(marker, ensure_ascii=False, sort_keys=True), flush=True)
		print(f'[DIAG] === END account #{idx:02d} ===', flush=True)

	ok = sum(1 for r in results if r.get('status') == 'success')
	failed = sum(1 for r in results if r.get('status') in {'failed', 'exception', 'no_marker', 'bad_marker'})
	timeouts = sum(1 for r in results if r.get('status') == 'timeout')
	login_ok = sum(1 for r in results if r.get('login_after') is True or (r.get('login_after') is None and r.get('login_before') is True))
	login_bad = sum(1 for r in results if r.get('login_after') is False or (r.get('login_after') is None and r.get('login_before') is False))
	print('\n[DIAG] FINAL_JSON ' + json.dumps({
		'total': len(results),
		'checkin_success': ok,
		'failed': failed,
		'timeouts': timeouts,
		'login_ok': login_ok,
		'login_bad': login_bad,
		'results': results,
	}, ensure_ascii=False, sort_keys=True), flush=True)
	return 0 if timeouts == 0 else 124


def main() -> None:
	parser = argparse.ArgumentParser()
	parser.add_argument('--one', type=int, default=None)
	parser.add_argument('--timeout', type=int, default=env_int('GA_DIAG_ACCOUNT_TIMEOUT', 180))
	args = parser.parse_args()
	if args.one is not None:
		raise SystemExit(asyncio.run(run_one(args.one)))
	raise SystemExit(run_parent(args.timeout))


if __name__ == '__main__':
	main()
