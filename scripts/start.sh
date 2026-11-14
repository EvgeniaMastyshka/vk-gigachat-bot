#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "Нет .env: скопируйте .env.example в .env и заполните ключи." >&2
    exit 1
fi

if [ ! -d .venv ]; then
    python3 -m venv .venv
    .venv/bin/pip install --disable-pip-version-check -r requirements.txt
fi

PYTHONPATH=src exec .venv/bin/python -m vk_gigachat_bot
