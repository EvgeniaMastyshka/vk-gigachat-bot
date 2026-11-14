"""Тесты системного промпта и приветствия."""

from vk_gigachat_bot.prompts import GREETING, build_system_prompt


def test_system_prompt_contains_persona_and_knowledge() -> None:
    prompt = build_system_prompt("Курс по нейросетям: 8 недель, онлайн.")

    assert "Алина" in prompt
    assert "Зерокодер" in prompt
    assert "БАЗА ЗНАНИЙ" in prompt
    assert "Курс по нейросетям: 8 недель, онлайн." in prompt


def test_system_prompt_forbids_markdown() -> None:
    prompt = build_system_prompt("")

    assert "Markdown" in prompt


def test_greeting_introduces_assistant() -> None:
    assert "Алина" in GREETING
    assert "Зерокодер" in GREETING
