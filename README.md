# Telegram-бот магазину Chaser 30 мл

## Створення бота в BotFather
1. Відкрийте @BotFather у Telegram.
2. Відправте команду `/newbot`.
3. Вкажіть назву та username бота.
4. Отримайте токен і збережіть його як `BOT_TOKEN`.

## Налаштування ENV у Render
1. Створіть новий сервіс (Background Worker).
2. У вкладці **Environment** додайте змінні:
   - `BOT_TOKEN` — токен з BotFather.
   - `ADMIN_CHAT_ID` — ваш Telegram user_id.
   - `PHOTO_URL` — (опціонально) URL фото товару.
   - `DB_PATH` — (опціонально) шлях до SQLite (наприклад, `bot.db`).
3. Переконайтесь, що у сервісі встановлено `python-telegram-bot==20.7`.

## Локальний запуск
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export BOT_TOKEN="ваш_токен"
export ADMIN_CHAT_ID="ваш_id"
python bot.py
```

## Встановлення фото через /setphoto
1. Надішліть боту фото товару.
2. Дайте відповідь на це фото командою `/setphoto`.
3. Бот збереже `file_id` у базі `settings`.

> Якщо задано `PHOTO_URL`, воно має пріоритет над `file_id`.

## Керування складом
- Переглянути список смаків: `/list`
- Переглянути склад: `/stock`
- Встановити кількість: `/setstock <id> <qty>`

Приклад:
```
/setstock 3 12
```

## Примітки
- Склад та корзини зберігаються у SQLite (`bot.db`) і не скидаються після рестарту.
- Товари із нульовим залишком не відображаються у меню.
