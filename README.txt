📦 Инструкция по запуску Telegram-бота автозапчастей с Google Таблицей

1. Установите зависимости:
   pip install python-telegram-bot==20.3 gspread oauth2client

2. Получите токен Telegram-бота:
   - Перейдите в https://t.me/BotFather
   - Создайте нового бота /newbot и получите TOKEN
   - Впишите его в main.py вместо ВАШ_ТОКЕН_БОТА

3. Создайте Google Таблицу:
   - Назовите лист "Запросы"
   - Таблица должна содержать заголовки:
     Дата | Telegram | Марка | Модель | Год | Объём | Топливо | VIN | Запчасти

4. Настройте доступ к Google API:
   - Перейдите на https://console.cloud.google.com/
   - Создайте проект и включите API:
       ✅ Google Sheets API
       ✅ Google Drive API
   - Создайте сервисный аккаунт, скачайте credentials.json
   - Поделитесь таблицей с email из credentials.json (доступ "Редактор")
   - Впишите ID таблицы в main.py вместо ВАШ_ID_ТАБЛИЦЫ

5. Запуск бота:
   python main.py

Бот будет работать в Telegram и записывать запросы клиентов в Google Таблицу.
