"""Тесты подготовки текста: снятие Markdown и разбиение под лимит VK."""

from vk_gigachat_bot.text_utils import clean_reply, split_vk_message


def test_clean_reply_removes_markdown() -> None:
    raw = "**Курс** по `вайб-кодингу`\n\n\n__Важно__"
    assert clean_reply(raw) == "Курс по вайб-кодингу\n\nВажно"


def test_clean_reply_keeps_plain_text() -> None:
    text = "Здравствуйте! Чем помочь?"
    assert clean_reply(text) == text


def test_split_vk_message_returns_single_chunk_for_short_text() -> None:
    assert split_vk_message("привет") == ["привет"]


def test_split_vk_message_ignores_empty_text() -> None:
    assert split_vk_message("   \n  ") == []


def test_split_vk_message_respects_limit_and_keeps_words() -> None:
    text = "\n\n".join(f"Пункт {i}: " + "слово " * 40 for i in range(30))

    chunks = split_vk_message(text, limit=500)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)
    assert " ".join(chunks).split() == text.split()
