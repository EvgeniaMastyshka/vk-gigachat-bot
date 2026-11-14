"""Загрузка и проверка настроек бота из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"

# .env читается из папки проекта, а не из текущей рабочей директории.
# Переменные, уже заданные в окружении сервера, имеют приоритет.
load_dotenv(ENV_FILE)


class ConfigError(RuntimeError):
    """Некорректная или неполная конфигурация."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(
            f"Не задана обязательная переменная {name}. "
            f"Добавьте её в файл {ENV_FILE.name} в корне проекта."
        )
    return value


def _optional(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ConfigError(f"{name} должна быть целым числом.") from exc

    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} должна быть в диапазоне от {minimum} до {maximum}.")
    return value


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        value = default
    else:
        try:
            value = float(raw.strip().replace(",", "."))
        except ValueError as exc:
            raise ConfigError(f"{name} должна быть числом.") from exc

    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} должна быть в диапазоне от {minimum} до {maximum}.")
    return value


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default

    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on", "да"}:
        return True
    if value in {"0", "false", "no", "off", "нет"}:
        return False
    raise ConfigError(f"{name}: ожидается true/false (или 1/0).")


@dataclass(frozen=True)
class Config:
    """Все настройки приложения в одном объекте."""

    # Секреты намеренно исключены из repr, чтобы случайно не попасть в лог.
    gigachat_auth_key: str = field(repr=False)
    vk_token: str = field(repr=False)

    gigachat_scope: str
    gigachat_model: str
    gigachat_base_url: str
    gigachat_oauth_url: str
    gigachat_temperature: float
    gigachat_max_tokens: int
    gigachat_timeout: float
    gigachat_verify_ssl: bool
    gigachat_ca_bundle: str | None

    vk_group_id: int
    vk_api_version: str
    bot_workers: int
    max_history_messages: int
    log_level: str

    @property
    def gigachat_verify(self) -> object:
        """Значение для параметра verify библиотеки requests."""
        return self.gigachat_ca_bundle or self.gigachat_verify_ssl

    @classmethod
    def from_env(cls) -> Config:
        auth_key = _required("GIGACHAT_AUTH_KEY")
        vk_token = _required("VK_TOKEN")

        scope = _optional("GIGACHAT_SCOPE", "GIGACHAT_API_PERS").upper()
        allowed_scopes = {"GIGACHAT_API_PERS", "GIGACHAT_API_B2B", "GIGACHAT_API_CORP"}
        if scope not in allowed_scopes:
            raise ConfigError(
                "GIGACHAT_SCOPE должна быть одной из: "
                + ", ".join(sorted(allowed_scopes))
            )

        base_url = _optional("GIGACHAT_BASE_URL", "https://api.giga.chat").rstrip("/")
        oauth_url = _optional(
            "GIGACHAT_OAUTH_URL",
            "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        ).rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            raise ConfigError("GIGACHAT_BASE_URL должна начинаться с http:// или https://.")
        if not oauth_url.startswith(("http://", "https://")):
            raise ConfigError("GIGACHAT_OAUTH_URL должна начинаться с http:// или https://.")

        group_id_raw = _required("VK_GROUP_ID").lstrip("-").strip()
        for prefix in ("club", "public"):
            if group_id_raw.lower().startswith(prefix):
                group_id_raw = group_id_raw[len(prefix) :]
                break
        try:
            group_id = int(group_id_raw)
        except ValueError as exc:
            raise ConfigError(
                "VK_GROUP_ID должен быть числовым ID сообщества без минуса, например 123456789."
            ) from exc
        if group_id <= 0:
            raise ConfigError("VK_GROUP_ID должен быть положительным числом.")

        ca_bundle_raw = os.getenv("GIGACHAT_CA_BUNDLE", "").strip()
        ca_bundle: str | None = None
        if ca_bundle_raw:
            ca_path = Path(ca_bundle_raw).expanduser()
            # Относительный путь считается от папки проекта, а не от текущей
            # рабочей директории: бот можно запускать из любого места.
            if not ca_path.is_absolute():
                ca_path = PROJECT_ROOT / ca_path
            if not ca_path.is_file():
                raise ConfigError(
                    "GIGACHAT_CA_BUNDLE указывает на несуществующий файл. "
                    "Укажите путь к корневому сертификату или оставьте переменную пустой."
                )
            ca_bundle = str(ca_path)

        log_level = _optional("LOG_LEVEL", "INFO").upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigError("LOG_LEVEL должна быть DEBUG, INFO, WARNING, ERROR или CRITICAL.")

        return cls(
            gigachat_auth_key=auth_key,
            vk_token=vk_token,
            gigachat_scope=scope,
            gigachat_model=_optional("GIGACHAT_MODEL", "GigaChat-2-Max"),
            gigachat_base_url=base_url,
            gigachat_oauth_url=oauth_url,
            gigachat_temperature=_float("GIGACHAT_TEMPERATURE", 0.7, 0.0, 2.0),
            gigachat_max_tokens=_int("GIGACHAT_MAX_TOKENS", 1024, 1, 8192),
            gigachat_timeout=_float("GIGACHAT_TIMEOUT", 60.0, 5.0, 300.0),
            gigachat_verify_ssl=_bool("GIGACHAT_VERIFY_SSL", True),
            gigachat_ca_bundle=ca_bundle,
            vk_group_id=group_id,
            vk_api_version=_optional("VK_API_VERSION", "5.199"),
            bot_workers=_int("BOT_WORKERS", 4, 1, 16),
            max_history_messages=_int("MAX_HISTORY_MESSAGES", 12, 2, 50),
            log_level=log_level,
        )
