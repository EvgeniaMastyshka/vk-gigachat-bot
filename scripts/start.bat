@echo off
chcp 65001 >nul
cd /d "%~dp0.."

if not exist ".env" (
    echo Файл .env не найден. Скопируйте .env.example в .env и заполните ключи.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Виртуальное окружение не найдено, создаю...
    python -m venv .venv
    if errorlevel 1 (
        echo Не удалось создать .venv. Проверьте, что Python установлен.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
    if errorlevel 1 (
        echo Не удалось установить зависимости.
        pause
        exit /b 1
    )
)

set "PYTHONPATH=src"
".venv\Scripts\python.exe" -m vk_gigachat_bot

echo.
echo Бот остановлен.
pause
