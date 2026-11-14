"""VK-бот сообщества Зерокодер с ответами через GigaChat API.

Бот слушает Bots Long Poll API сообщества и отвечает в «Сообщениях сообщества»:
для ответа используется peer_id входящего сообщения, поэтому бот работает
и в личных сообщениях сообщества, и в беседах, куда его добавили.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import secrets
import signal
import sys
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import vk_api
from vk_api.bot_longpoll import VkBotEventType, VkBotLongPoll
from vk_api.exceptions import ApiError

from .config import Config, ConfigError
from .gigachat import (
    GigaChatAPIError,
    GigaChatAuthError,
    GigaChatClient,
    GigaChatError,
)
from .prompts import (
    ATTACHMENT_ONLY_TEXT,
    CLEAR_COMMANDS,
    EMPTY_MESSAGE_TEXT,
    GREETING,
    GREETING_COMMANDS,
    HELP_COMMANDS,
    HELP_TEXT,
    RESET_COMMANDS,
    RESET_TEXT,
    UNKNOWN_COMMAND_TEXT,
    build_system_prompt,
)
from .text_utils import clean_reply, split_vk_message

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_BASE_PATH = Path(
    os.getenv("KNOWLEDGE_BASE_PATH") or PROJECT_ROOT / "data" / "knowledge_base.md"
)

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "bot.log"


def setup_logging(level: str) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    try:
        LOG_DIR.mkdir(exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        handlers.append(file_handler)
    except OSError as exc:
        print(f"Не удалось открыть файл лога {LOG_FILE}: {exc}", file=sys.stderr)

    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=log_level, handlers=handlers, force=True)


def load_knowledge_base() -> str:
    try:
        return KNOWLEDGE_BASE_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.error("Не удалось прочитать базу знаний %s: %s", KNOWLEDGE_BASE_PATH, exc)
        return ""


class VkBot:
    def __init__(
        self,
        config: Config,
        gigachat: GigaChatClient,
        knowledge_base: str,
    ) -> None:
        self._config = config
        self._gigachat = gigachat
        self._system_prompt = build_system_prompt(knowledge_base)

        self._vk_session = vk_api.VkApi(
            token=config.vk_token,
            api_version=config.vk_api_version,
        )
        self._vk = self._vk_session.get_api()
        self._vk_lock = threading.Lock()

        self._history: dict[int, list[dict[str, str]]] = {}
        self._history_lock = threading.Lock()

        self._peer_locks: dict[int, threading.Lock] = {}
        self._peer_locks_guard = threading.Lock()

        self._seen_events: OrderedDict[str, None] = OrderedDict()
        self._seen_events_lock = threading.Lock()

        self._executor = ThreadPoolExecutor(
            max_workers=config.bot_workers,
            thread_name_prefix="vk-msg",
        )

    def close(self) -> None:
        # Дожидаемся уже начатых ответов, новые задачи отменяем.
        self._executor.shutdown(wait=True, cancel_futures=True)

    def run(self) -> None:
        logger.info(
            "Бот запущен: сообщество=%s, Long Poll API, модель GigaChat=%s",
            self._config.vk_group_id,
            self._config.gigachat_model,
        )

        while True:
            try:
                longpoll = VkBotLongPoll(
                    self._vk_session,
                    self._config.vk_group_id,
                    wait=25,
                )
                logger.info("Long Poll подключён, ожидаю сообщения сообщества...")

                for event in longpoll.listen():
                    if event.type != VkBotEventType.MESSAGE_NEW:
                        continue

                    event_id = str(event.raw.get("event_id") or "")
                    if event_id and self._is_duplicate_event(event_id):
                        logger.debug("Пропускаю повторное событие %s", event_id)
                        continue

                    self._executor.submit(self._handle_event_safe, event)

            except KeyboardInterrupt:
                logger.info("Получен сигнал остановки.")
                break
            except ApiError as exc:
                if exc.code in {5, 15, 27, 100}:
                    logger.error(
                        "VK API отклонил подключение (код %s): %s",
                        exc.code,
                        exc,
                    )
                    logger.error(
                        "Проверьте VK_TOKEN, VK_GROUP_ID, право «Сообщения сообщества» "
                        "и включённый Bots Long Poll API."
                    )
                    return
                logger.error(
                    "Ошибка VK API (код %s): %s. Переподключение через 5 секунд.",
                    exc.code,
                    exc,
                )
                time.sleep(5)
            except Exception as exc:
                logger.error(
                    "Long Poll прерван (%s: %s). Переподключение через 5 секунд.",
                    type(exc).__name__,
                    exc,
                )
                time.sleep(5)

    def _is_duplicate_event(self, event_id: str) -> bool:
        """Защита от повторной обработки события при переподключении Long Poll."""
        with self._seen_events_lock:
            if event_id in self._seen_events:
                return True
            self._seen_events[event_id] = None
            while len(self._seen_events) > 2000:
                self._seen_events.popitem(last=False)
        return False

    def _get_peer_lock(self, peer_id: int) -> threading.Lock:
        with self._peer_locks_guard:
            lock = self._peer_locks.get(peer_id)
            if lock is None:
                lock = threading.Lock()
                self._peer_locks[peer_id] = lock
            return lock

    def _handle_event_safe(self, event: Any) -> None:
        try:
            self._handle_event(event)
        except Exception:
            logger.exception("Не удалось обработать входящее событие VK.")

    def _handle_event(self, event: Any) -> None:
        message = event.message
        if message is None:
            return

        # Исходящие сообщения сообщества игнорируем, чтобы бот не отвечал сам себе.
        if message.get("out"):
            return

        try:
            from_id = int(message.get("from_id"))
            peer_id = int(message.get("peer_id"))
        except (TypeError, ValueError):
            logger.warning("Событие без корректных from_id/peer_id, пропускаю.")
            return

        # from_id <= 0 — это сообщение от сообщества/служебное, а не от пользователя.
        if from_id <= 0 or peer_id <= 0:
            return

        text = str(message.get("text") or "").strip()
        attachments = message.get("attachments") or []

        logger.info(
            "Входящее сообщение: peer_id=%s, from_id=%s, длина текста=%s, вложений=%s",
            peer_id,
            from_id,
            len(text),
            len(attachments),
        )

        # Один диалог обрабатывается последовательно, разные диалоги — параллельно.
        with self._get_peer_lock(peer_id):
            self._process_message(peer_id, text, bool(attachments))

    def _process_message(self, peer_id: int, text: str, has_attachments: bool) -> None:
        if not text:
            self._send(peer_id, ATTACHMENT_ONLY_TEXT if has_attachments else EMPTY_MESSAGE_TEXT)
            return

        command = text.lower()

        if command in RESET_COMMANDS:
            self._clear_history(peer_id)
            self._send(peer_id, GREETING)
            return

        if command in CLEAR_COMMANDS:
            self._clear_history(peer_id)
            self._send(peer_id, RESET_TEXT)
            return

        if command in HELP_COMMANDS:
            self._send(peer_id, HELP_TEXT)
            return

        if command in GREETING_COMMANDS:
            self._send(peer_id, GREETING)
            return

        if command.startswith("/"):
            self._send(peer_id, UNKNOWN_COMMAND_TEXT)
            return

        self._set_typing(peer_id)
        reply = self._generate_reply(peer_id, text)
        self._send(peer_id, reply)

    def _generate_reply(self, peer_id: int, text: str) -> str:
        history = self._get_history(peer_id)
        history.append({"role": "user", "content": text})

        # Две попытки нужны только для случая, когда контекст переполнен (HTTP 422).
        for attempt in range(2):
            messages = [{"role": "system", "content": self._system_prompt}]
            messages.extend(history[-self._config.max_history_messages :])

            try:
                reply = self._gigachat.chat(
                    messages,
                    temperature=self._config.gigachat_temperature,
                    max_tokens=self._config.gigachat_max_tokens,
                )
            except GigaChatAuthError as exc:
                history.pop()
                logger.error("Ошибка авторизации GigaChat: %s", exc)
                return (
                    "Извините, сейчас не получается получить ответ: "
                    "сервис GigaChat временно недоступен. Администратор уже видит ошибку."
                )
            except GigaChatAPIError as exc:
                if exc.status_code == 422 and attempt == 0 and len(history) > 1:
                    logger.warning(
                        "GigaChat вернул 422: контекст переполнен. Сокращаю историю и повторяю."
                    )
                    history[:] = history[-1:]
                    continue

                history.pop()
                logger.error("Ошибка GigaChat API: %s", exc)
                return (
                    "Извините, не получилось сформировать ответ. "
                    "Попробуйте, пожалуйста, ещё раз через минуту."
                )
            except GigaChatError as exc:
                history.pop()
                logger.error("Ошибка GigaChat: %s", exc)
                return (
                    "Извините, сервис ответов временно недоступен. "
                    "Попробуйте, пожалуйста, ещё раз через минуту."
                )
            else:
                reply = clean_reply(reply)
                history.append({"role": "assistant", "content": reply})
                self._trim_history(history)
                return reply

        history.pop()
        return "Извините, не получилось сформировать ответ. Попробуйте ещё раз."

    def _get_history(self, peer_id: int) -> list[dict[str, str]]:
        with self._history_lock:
            return self._history.setdefault(peer_id, [])

    def _clear_history(self, peer_id: int) -> None:
        with self._history_lock:
            self._history.pop(peer_id, None)

    def _trim_history(self, history: list[dict[str, str]]) -> None:
        limit = self._config.max_history_messages
        if len(history) > limit:
            del history[:-limit]

    def _set_typing(self, peer_id: int) -> None:
        """Показывает пользователю статус «печатает», пока GigaChat готовит ответ."""
        try:
            with self._vk_lock:
                self._vk.messages.setActivity(
                    type="typing",
                    peer_id=peer_id,
                    group_id=self._config.vk_group_id,
                )
        except Exception as exc:
            # Это необязательная функция: если VK её не принял, просто пишем в DEBUG.
            logger.debug("Не удалось отправить статус «печатает»: %s", exc)

    def _send(self, peer_id: int, text: str) -> None:
        if not text.strip():
            return

        for chunk in split_vk_message(text):
            try:
                with self._vk_lock:
                    # peer_id — ключевой параметр: ответ уходит в тот же диалог
                    # «Сообщений сообщества», включая беседы (peer_id 2000000000+).
                    self._vk.messages.send(
                        peer_id=peer_id,
                        message=chunk,
                        random_id=secrets.randbelow(2**31 - 1) + 1,
                    )
            except Exception as exc:
                logger.error(
                    "Не удалось отправить сообщение в VK (peer_id=%s): %s",
                    peer_id,
                    exc,
                )
                return


def _raise_keyboard_interrupt(signum: int, frame: Any) -> None:
    raise KeyboardInterrupt


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return 1

    setup_logging(config.log_level)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _raise_keyboard_interrupt)
        except (ValueError, OSError):
            pass

    logger.info("=== Запуск VK-бота с GigaChat ===")
    logger.info(
        "GigaChat: base_url=%s, model=%s, scope=%s",
        config.gigachat_base_url,
        config.gigachat_model,
        config.gigachat_scope,
    )
    logger.info(
        "VK: group_id=%s, api_version=%s, workers=%s",
        config.vk_group_id,
        config.vk_api_version,
        config.bot_workers,
    )

    knowledge_base = load_knowledge_base()
    if not knowledge_base:
        logger.warning(
            "База знаний пуста. Бот будет отвечать без информации о курсах — "
            "проверьте файл %s.",
            KNOWLEDGE_BASE_PATH.name,
        )

    client = GigaChatClient(config)
    bot: VkBot | None = None
    try:
        bot = VkBot(config, client, knowledge_base)
        bot.run()
    except KeyboardInterrupt:
        logger.info("Остановка по сигналу.")
    finally:
        if bot is not None:
            bot.close()
        client.close()

    logger.info("Бот остановлен.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
