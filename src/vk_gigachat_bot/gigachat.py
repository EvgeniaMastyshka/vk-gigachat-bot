"""Минимальный клиент GigaChat REST API.

Документация:
- авторизация: https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api
- получение токена: https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-token
- генерация ответа: https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/post-chat

Клиент сам получает access token по ключу авторизации и обновляет его
до истечения 30-минутного срока. Наружу токен не выводится.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import requests

from .config import Config

logger = logging.getLogger(__name__)


class GigaChatError(RuntimeError):
    """Базовая ошибка интеграции с GigaChat."""


class GigaChatAuthError(GigaChatError):
    """Не удалось получить или обновить access token."""


class GigaChatAPIError(GigaChatError):
    """GigaChat API вернул ошибку."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"GigaChat API вернул HTTP {status_code}: {message}")


def _short(text: str, limit: int = 300) -> str:
    """Обрезает текст ответа для лога, чтобы не раздувать сообщения."""
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _normalize_expires_at(value: Any) -> float:
    """Приводит expires_at к Unix-времени в секундах.

    В разных версиях ответа OAuth поле приходит то в секундах, то в
    миллисекундах. Определяем по величине.
    """
    try:
        expires_at = float(value)
    except (TypeError, ValueError):
        return time.time() + 30 * 60

    if expires_at <= 0:
        return time.time() + 30 * 60
    if expires_at > 100_000_000_000:
        expires_at /= 1000.0
    return expires_at


def _retry_after(response: requests.Response, default: float = 5.0) -> float:
    raw = response.headers.get("Retry-After")
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(1.0, min(value, 60.0))


def _extract_text(content: Any) -> str:
    """Достаёт текст из строки или из массива частей ответа."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return ""


class GigaChatClient:
    """Клиент для генерации ответов через GigaChat API."""

    def __init__(self, config: Config) -> None:
        self._config = config
        # requests.Session не гарантирует потокобезопасность, поэтому
        # у каждого рабочего потока будет своя сессия.
        self._thread_local = threading.local()
        self._sessions: list[requests.Session] = []
        self._sessions_lock = threading.Lock()
        self._token_lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._session_id = str(uuid.uuid4())

    def _get_session(self) -> requests.Session:
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = requests.Session()
            self._thread_local.session = session
            with self._sessions_lock:
                self._sessions.append(session)
        return session

    def close(self) -> None:
        with self._sessions_lock:
            for session in self._sessions:
                session.close()
            self._sessions.clear()

    def get_access_token(self, force: bool = False) -> str:
        """Возвращает действующий access token, при необходимости обновляет его."""
        with self._token_lock:
            if (
                not force
                and self._access_token
                and time.time() < self._expires_at - 60
            ):
                return self._access_token

            return self._request_access_token()

    def _request_access_token(self) -> str:
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "RqUID": str(uuid.uuid4()),
            "Authorization": f"Basic {self._config.gigachat_auth_key}",
            "User-Agent": "zerocoder-vk-bot/1.0",
        }

        try:
            response = self._get_session().post(
                self._config.gigachat_oauth_url,
                headers=headers,
                data={"scope": self._config.gigachat_scope},
                timeout=self._config.gigachat_timeout,
                verify=self._config.gigachat_verify,
            )
        except requests.RequestException as exc:
            raise GigaChatAuthError(
                "Не удалось подключиться к OAuth GigaChat. "
                "Проверьте сеть, доступ к ngw.devices.sberbank.ru:9443 и SSL-сертификаты."
            ) from exc

        if response.status_code != 200:
            raise GigaChatAuthError(
                f"OAuth GigaChat вернул HTTP {response.status_code}. "
                "Проверьте GIGACHAT_AUTH_KEY и GIGACHAT_SCOPE. "
                f"Ответ: {_short(response.text)}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise GigaChatAuthError("OAuth GigaChat вернул ответ, который не является JSON.") from exc

        if not isinstance(payload, dict):
            raise GigaChatAuthError("OAuth GigaChat вернул неожиданный формат ответа.")

        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise GigaChatAuthError("OAuth GigaChat не вернул access_token.")

        self._access_token = token
        self._expires_at = _normalize_expires_at(payload.get("expires_at"))

        # Если сервер вернул уже истёкшее время, не зацикливаемся на нём.
        if self._expires_at <= time.time() + 60:
            self._expires_at = time.time() + 5 * 60

        logger.info(
            "Получен новый access token GigaChat, действует до %s",
            time.strftime("%H:%M:%S", time.localtime(self._expires_at)),
        )
        return token

    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Отправляет историю сообщений и возвращает текст ответа модели."""
        payload: dict[str, Any] = {
            "model": self._config.gigachat_model,
            "messages": [dict(message) for message in messages],
            "stream": False,
            "repetition_penalty": 1.0,
        }

        if temperature is not None:
            payload["temperature"] = max(0.0, min(2.0, float(temperature)))
        if max_tokens is not None:
            payload["max_tokens"] = max(1, int(max_tokens))

        return self._send_chat(payload)

    def _send_chat(self, payload: dict[str, Any]) -> str:
        auth_retry_available = True
        rate_limit_retries = 2
        server_error_retries = 2

        while True:
            token = self.get_access_token()
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "zerocoder-vk-bot/1.0",
                "X-Client-ID": "zerocoder-vk-bot",
                "X-Request-ID": str(uuid.uuid4()),
                "X-Session-ID": self._session_id,
            }

            try:
                response = self._get_session().post(
                    f"{self._config.gigachat_base_url}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=self._config.gigachat_timeout,
                    verify=self._config.gigachat_verify,
                )
            except requests.RequestException as exc:
                if server_error_retries > 0:
                    server_error_retries -= 1
                    logger.warning(
                        "Сетевая ошибка при запросе к GigaChat, повтор через 3 секунды."
                    )
                    time.sleep(3)
                    continue
                raise GigaChatError(
                    "Не удалось подключиться к GigaChat API после нескольких попыток."
                ) from exc

            if response.status_code == 401 and auth_retry_available:
                logger.warning("GigaChat отклонил access token (401), обновляю токен.")
                auth_retry_available = False
                self.get_access_token(force=True)
                continue

            if response.status_code == 429 and rate_limit_retries > 0:
                delay = _retry_after(response)
                rate_limit_retries -= 1
                logger.warning(
                    "GigaChat вернул 429 (слишком много запросов), пауза %.0f секунд.",
                    delay,
                )
                time.sleep(delay)
                continue

            if 500 <= response.status_code < 600 and server_error_retries > 0:
                server_error_retries -= 1
                logger.warning(
                    "GigaChat вернул HTTP %s, повтор через 3 секунды.",
                    response.status_code,
                )
                time.sleep(3)
                continue

            if response.status_code >= 400:
                raise GigaChatAPIError(response.status_code, _short(response.text))

            return self._parse_response(response)

    def _parse_response(self, response: requests.Response) -> str:
        try:
            data = response.json()
        except ValueError as exc:
            raise GigaChatAPIError(response.status_code, "Ответ GigaChat не является JSON.") from exc

        # На случай обёртки вида {"value": {...}} в некоторых версиях API.
        if (
            isinstance(data, dict)
            and "choices" not in data
            and isinstance(data.get("value"), dict)
        ):
            data = data["value"]

        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise GigaChatAPIError(response.status_code, "В ответе GigaChat нет поля choices.")

        first_choice = choices[0] if isinstance(choices, list) else {}
        message = first_choice.get("message") if isinstance(first_choice, dict) else {}
        content = _extract_text(message.get("content") if isinstance(message, dict) else None)
        if not content.strip():
            raise GigaChatAPIError(response.status_code, "GigaChat вернул пустой ответ.")

        usage = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(usage, dict):
            usage = {}
        logger.info(
            "GigaChat ответил: model=%s, total_tokens=%s",
            data.get("model") if isinstance(data, dict) else None,
            usage.get("total_tokens"),
        )
        return content.strip()
