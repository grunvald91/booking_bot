@echo off
chcp 65001 >nul
echo === Деплой Booking бота на сервер ===
echo.

set SERVER=root@155.212.162.47
set REMOTE_PATH=/root/booking_bot

echo 1. Копирование файлов на сервер...
scp -r bot database webapp migrations requirements.txt run.sh .env.production %SERVER%:%REMOTE_PATH%/

echo 2. Настройка на сервере...
ssh %SERVER% "cd %REMOTE_PATH% && cp .env.production .env"

echo 3. Установка зависимостей...
ssh %SERVER% "cd %REMOTE_PATH% && source venv/bin/activate && pip install -r requirements.txt"

echo 4. Миграция базы данных (добавление полей подписки)...
ssh %SERVER% "cd %REMOTE_PATH% && source venv/bin/activate && python migrations/add_subscription_fields.py"

echo 5. Перезапуск сервиса...
ssh %SERVER% "systemctl restart booking_bot"

echo.
echo === Статус сервиса ===
ssh %SERVER% "systemctl status booking_bot --no-pager"

echo.
echo === Деплой завершен! ===
echo Проверить логи: ssh %SERVER% journalctl -u booking_bot -f
pause
