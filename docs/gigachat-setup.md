# Настройка GigaChat API

Бот работает с официальным GigaChat API: получает access token по ключу
авторизации и отправляет запросы на генерацию ответа.

## 1. Получите Authorization Key

1. Откройте [GigaChat Studio](https://developers.sber.ru/studio/).
2. Перейдите в проект **GigaChat API** (или создайте его).
3. В левом меню выберите **Настройки API**.
4. Нажмите **Получить ключ**.
5. Сохраните:
   - **Authorization Key** — готовая строка для заголовка `Authorization: Basic ...`;
   - **Client ID**;
   - **Client Secret**.

> Authorization Key и Client Secret показываются один раз. При утере или
> компрометации нажмите **Получить новый ключ**; старый можно оставить
> действующим до 250 минут.

## 2. Впишите ключ в `.env`

```dotenv
GIGACHAT_AUTH_KEY=сюда_вставить_Authorization_Key
```

Правила:

- без префикса `Basic `;
- без кавычек, если их нет в самом ключе;
- не вставляйте ключ в `bot.py`, README, `.env.example` или сообщения чата.

**Access token в `.env` не нужен:** бот получает его сам и обновляет каждые
30 минут.

## 3. Если у вас только Client ID и Client Secret

Authorization Key — это `Base64(Client ID:Client Secret)`.

PowerShell:

```powershell
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("CLIENT_ID:CLIENT_SECRET"))
```

Linux/macOS:

```bash
printf '%s' 'CLIENT_ID:CLIENT_SECRET' | base64 -w0
```

## 4. Выберите scope

| Значение | Для кого |
|---|---|
| `GIGACHAT_API_PERS` | физические лица |
| `GIGACHAT_API_B2B` | ИП и юрлица по платным пакетам |
| `GIGACHAT_API_CORP` | ИП и юрлица по схеме pay-as-you-go |

Scope должен соответствовать типу аккаунта, иначе OAuth вернёт `401` или `403`.

## Адреса API

- генерация: `https://api.giga.chat` — актуальный адрес с 17 июля 2026 года;
- OAuth: `https://ngw.devices.sberbank.ru:9443/api/v2/oauth` — по-прежнему
  используется для получения токена;
- старый `https://gigachat.devices.sberbank.ru` оставлен для старых подключений.

> Модель `GigaChat-3-Ultra` доступна только физическим лицам в freemium-режиме.
> Для `GIGACHAT_API_B2B` и `GIGACHAT_API_CORP` выбирайте модель своего тарифа:
> [документация по моделям](https://developers.sber.ru/docs/ru/gigachat/models/main).

## SSL-сертификаты

Если в логах появляется `CERTIFICATE_VERIFY_FAILED`, серверу не хватает
корневых сертификатов Минцифры. В проекте они уже лежат в `certs/`:

```text
certs/russian_trusted_root_ca.pem   # корневой сертификат
certs/russian_trusted_sub_ca.pem    # промежуточный сертификат
certs/russian_trusted_ca.pem        # оба в одном файле — его и указываем
```

Варианты решения:

1. Установить сертификаты в системное хранилище сервера.
2. Указать PEM-файл в `.env` (относительный путь считается от корня проекта):

```dotenv
GIGACHAT_CA_BUNDLE=certs/russian_trusted_ca.pem
```

3. Перезапустить бота.

Скачать сертификаты заново:

- `https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt`
- `https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt`

Не отключайте проверку SSL в production. `GIGACHAT_VERIFY_SSL=false` допустимо
только для краткой диагностики на тестовом стенде.
