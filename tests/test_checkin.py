import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import checkin
from utils.config import AccountConfig, AppConfig, ProviderConfig


@pytest.mark.asyncio
async def test_check_in_account_returns_three_values_when_provider_missing():
	account = AccountConfig(cookies={'session': 'test-session'}, api_user='12345', provider='missing-provider')

	result = await checkin.check_in_account(account, 0, AppConfig(providers={}))

	assert result == (False, None, None)


@pytest.mark.asyncio
async def test_check_in_account_returns_three_values_when_cookies_invalid():
	account = AccountConfig(cookies={}, api_user='12345')
	app_config = AppConfig(providers={'anyrouter': ProviderConfig(name='anyrouter', domain='https://anyrouter.top')})

	result = await checkin.check_in_account(account, 0, app_config)

	assert result == (False, None, None)


@pytest.mark.asyncio
async def test_check_in_account_returns_three_values_when_prepare_cookies_fails(monkeypatch):
	async def fake_prepare_cookies(*args, **kwargs):
		return None

	monkeypatch.setattr(checkin, 'prepare_cookies', fake_prepare_cookies)
	account = AccountConfig(cookies={'session': 'test-session'}, api_user='12345')
	app_config = AppConfig(providers={'anyrouter': ProviderConfig(name='anyrouter', domain='https://anyrouter.top')})

	result = await checkin.check_in_account(account, 0, app_config)

	assert result == (False, None, None)


@pytest.mark.asyncio
async def test_main_handles_missing_provider_without_unpack_exception(monkeypatch, capsys):
	account = AccountConfig(cookies={'session': 'test-session'}, api_user='12345', provider='missing-provider')

	monkeypatch.setattr(checkin, 'load_accounts_config', lambda: [account])
	monkeypatch.setattr(checkin, 'load_balance_hash', lambda: None)
	monkeypatch.setattr(checkin, 'save_balance_hash', lambda balance_hash: None)
	monkeypatch.setattr(checkin.notify, 'push_message', lambda *args, **kwargs: None)

	with pytest.raises(SystemExit) as exc_info:
		await checkin.main()

	assert exc_info.value.code == 1
	output = capsys.readouterr().out
	assert 'Provider "missing-provider" not found in configuration' in output
	assert 'not enough values to unpack' not in output
