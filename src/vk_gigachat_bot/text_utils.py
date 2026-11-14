"""Подготовка текста ответа под ограничения VK."""

from __future__ import annotations

import re

# VK отклоняет сообщения длиннее 4096 символов, берём запас.
VK_MESSAGE_LIMIT = 4000

_MD_CODE = re.compile(r"`([^`]+)`")
_MD_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_MD_UNDERSCORE = re.compile(r"(?<!\w)__(.+?)__(?!\w)", re.DOTALL)


def clean_reply(text: str) -> str:
    """Убирает Markdown, который GigaChat иногда добавляет вопреки инструкции.

    VK показывает сообщения как обычный текст, поэтому «**курс**» выглядел бы
    как звёздочки. Заодно убираем лишние пустые строки.
    """
    text = _MD_CODE.sub(r"\1", text)
    text = _MD_BOLD.sub(r"\1", text)
    text = _MD_UNDERSCORE.sub(r"\1", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_vk_message(text: str, limit: int = VK_MESSAGE_LIMIT) -> list[str]:
    """Делит длинный ответ на части, чтобы уложиться в лимит сообщения VK."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = limit

        chunk = remaining[:cut].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[cut:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks
