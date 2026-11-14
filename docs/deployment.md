# Развёртывание

Бот — долгоживущий процесс: Long Poll должен работать постоянно. Подойдёт любой
VPS с Python 3.10+.

Нужны только **исходящие** соединения:

- `api.giga.chat:443`;
- `ngw.devices.sberbank.ru:9443`;
- `api.vk.com:443` и серверы Long Poll VK (обычно `*.vk.com:443`).

Входящие порты открывать не нужно: используется Long Poll, а не Callback API.

## Linux: systemd

`/etc/systemd/system/vk-gigachat-bot.service`:

```ini
[Unit]
Description=VK GigaChat bot (Zerocoder)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=botuser
Group=botuser
WorkingDirectory=/opt/zerocoder-bot
EnvironmentFile=/opt/zerocoder-bot/.env
Environment=PYTHONPATH=/opt/zerocoder-bot/src
ExecStart=/opt/zerocoder-bot/.venv/bin/python -m vk_gigachat_bot
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

Подготовка:

```bash
sudo useradd --system --home /opt/zerocoder-bot --shell /usr/sbin/nologin botuser
sudo chown -R botuser:botuser /opt/zerocoder-bot
sudo chmod 600 /opt/zerocoder-bot/.env
sudo systemctl daemon-reload
sudo systemctl enable --now vk-gigachat-bot
```

Логи:

```bash
sudo journalctl -u vk-gigachat-bot -f
```

Обновление:

```bash
cd /opt/zerocoder-bot
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart vk-gigachat-bot
```

## Windows Server

Можно запустить как службу через [NSSM](https://nssm.cc/) или как задачу
в **Планировщике заданий** с запуском при старте системы.

Пример для NSSM:

```powershell
nssm install VkGigaChatBot C:\bots\zerocoder\.venv\Scripts\python.exe -m vk_gigachat_bot
nssm set VkGigaChatBot AppDirectory C:\bots\zerocoder
nssm set VkGigaChatBot AppEnvironmentExtra PYTHONPATH=C:\bots\zerocoder\src
nssm start VkGigaChatBot
```

`.env` должен лежать в `C:\bots\zerocoder\.env`. Не указывайте ключи
в аргументах командной строки — они видны в списке процессов.

## Проверка после запуска

```text
=== Запуск VK-бота с GigaChat ===
GigaChat: base_url=https://api.giga.chat, model=GigaChat-2-Max, scope=GIGACHAT_API_PERS
VK: group_id=123456789, api_version=5.199, workers=4
Long Poll подключён, ожидаю сообщения сообщества...
```

Access token GigaChat бот получает лениво — при первом сообщении:

```text
Получен новый access token GigaChat, действует до 14:35:00
```

Сам токен в лог не выводится.
