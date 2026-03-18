import json
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from utils.config import AccountConfig, AppConfig


def test_builtin_providers_only_include_runtime_defaults(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)

	config = AppConfig.load_from_env()

	assert {'anyrouter', 'agentrouter'} <= set(config.providers)
	assert 'freestyle' not in config.providers
	assert 'xingyungept' not in config.providers
	assert 'sorai' not in config.providers
	assert 'apikey' not in config.providers


def test_providers_env_can_add_extra_provider(monkeypatch):
	monkeypatch.setenv(
		'PROVIDERS',
		json.dumps({'apikey': {'domain': 'https://custom.apikey.example', 'sign_in_path': '/custom/signin'}}),
	)

	config = AppConfig.load_from_env()
	provider = config.get_provider('apikey')

	assert provider is not None
	assert provider.domain == 'https://custom.apikey.example'
	assert provider.sign_in_path == '/custom/signin'


def test_auto_register_from_accounts_still_registers_unknown_provider(monkeypatch):
	monkeypatch.delenv('PROVIDERS', raising=False)
	config = AppConfig.load_from_env()
	account = AccountConfig(
		cookies={'session': 'test-session'},
		api_user='760',
		provider='computetoken',
		domain='https://computetoken.ai',
	)

	assert config.get_provider('computetoken') is None

	config.auto_register_from_accounts([account])
	provider = config.get_provider('computetoken')

	assert provider is not None
	assert provider.domain == 'https://computetoken.ai'
