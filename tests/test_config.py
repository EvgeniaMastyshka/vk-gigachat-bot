"""Тесты загрузки конфигурации из переменных окружения."""


import pytest

from vk_gigachat_bot.config import Config, ConfigError

REQUIRED: dict[str, str] = {
    "GIGACHAT_AUTH_KEY": "test-auth-key",
    "VK_TOKEN": "test-vk-token",
    "VK_GROUP_ID": "123456789",
}

OPTIONAL = (
    "GIGACHAT_SCOPE",
    "GIGACHAT_MODEL",
    "GIGACHAT_BASE_URL",
    "GIGACHAT_OAUTH_URL",
    "GIGACHAT_TEMPERATURE",
    "GIGACHAT_MAX_TOKENS",
    "GIGACHAT_TIMEOUT",
    "GIGACHAT_VERIFY_SSL",
    "GIGACHAT_CA_BUNDLE",
    "VK_API_VERSION",
    "BOT_WORKERS",
    "MAX_HISTORY_MESSAGES",
    "LOG_LEVEL",
)


@pytest.fixture()
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (*REQUIRED, *OPTIONAL):
        monkeypatch.delenv(name, raising=False)
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    return monkeypatch


def test_defaults(env: pytest.MonkeyPatch) -> None:
    config = Config.from_env()

    assert config.vk_group_id == 123456789
    assert config.gigachat_scope == "GIGACHAT_API_PERS"
    assert config.gigachat_model == "GigaChat-2-Max"
    assert config.gigachat_base_url == "https://api.giga.chat"
    assert config.bot_workers == 4
    assert config.max_history_messages == 12
    assert config.log_level == "INFO"


def test_group_id_accepts_minus_and_club_prefix(env: pytest.MonkeyPatch) -> None:
    env.setenv("VK_GROUP_ID", "-club123456789")

    assert Config.from_env().vk_group_id == 123456789


def test_missing_required_variable_raises(env: pytest.MonkeyPatch) -> None:
    env.delenv("VK_TOKEN")

    with pytest.raises(ConfigError, match="VK_TOKEN"):
        Config.from_env()


def test_invalid_scope_raises(env: pytest.MonkeyPatch) -> None:
    env.setenv("GIGACHAT_SCOPE", "GIGACHAT_UNKNOWN")

    with pytest.raises(ConfigError, match="GIGACHAT_SCOPE"):
        Config.from_env()


def test_invalid_log_level_raises(env: pytest.MonkeyPatch) -> None:
    env.setenv("LOG_LEVEL", "VERBOSE")

    with pytest.raises(ConfigError, match="LOG_LEVEL"):
        Config.from_env()


def test_secrets_are_hidden_in_repr(env: pytest.MonkeyPatch) -> None:
    config = Config.from_env()

    assert "test-auth-key" not in repr(config)
    assert "test-vk-token" not in repr(config)
