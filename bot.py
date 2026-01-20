import os
import sqlite3
from typing import Dict, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

FLAVORS: List[Dict[str, object]] = [
    {
        "id": 1,
        "name": "ЧЕРЕШНЯ",
        "tag": "NEW",
        "description": "Солодка черешня з м'яким ягідним післясмаком.",
    },
    {
        "id": 2,
        "name": "ГРЕЙПФРУТ",
        "tag": "LIMITED",
        "description": "Освіжаючий гіркуватий грейпфрут з легкою кислинкою.",
    },
    {
        "id": 3,
        "name": "КАКТУС",
        "tag": "LIMITED",
        "description": "Екзотичний кактус із прохолодною солодкістю.",
    },
    {
        "id": 4,
        "name": "ЛІЧІ",
        "tag": "LIMITED",
        "description": "Ніжний лічі з квітковими нотами.",
    },
    {
        "id": 5,
        "name": "ВИНОГРАД",
        "tag": None,
        "description": "Соковитий виноград із класичною солодкістю.",
    },
    {
        "id": 6,
        "name": "ВИШНЯ",
        "tag": None,
        "description": "Яскрава вишня з балансом кислинки та цукру.",
    },
    {
        "id": 7,
        "name": "ВИШНЯ МЕНТОЛ",
        "tag": None,
        "description": "Вишня з прохолодним ментоловим шлейфом.",
    },
    {
        "id": 8,
        "name": "ГРАНАТ",
        "tag": None,
        "description": "Насичений гранат з терпкими нотами.",
    },
    {
        "id": 9,
        "name": "ДИНЯ",
        "tag": None,
        "description": "Медова диня з м'якою фруктовою солодкістю.",
    },
    {
        "id": 10,
        "name": "ЖОВТА МАЛИНА",
        "tag": None,
        "description": "Жовта малина з ніжною ягідною кислинкою.",
    },
    {
        "id": 11,
        "name": "ЖОВТА ЧЕРЕШНЯ",
        "tag": None,
        "description": "Стигла жовта черешня з карамельним відтінком.",
    },
    {
        "id": 12,
        "name": "ЖОВТИЙ ДРАГОНФРУТ",
        "tag": None,
        "description": "Жовтий драгонфрут з тропічною свіжістю.",
    },
    {
        "id": 13,
        "name": "КАВУН",
        "tag": None,
        "description": "Свіжий кавун з соковитою літньою солодкістю.",
    },
    {
        "id": 14,
        "name": "КАВУН МЕНТОЛ",
        "tag": None,
        "description": "Кавун із прохолодним ментоловим ефектом.",
    },
    {
        "id": 15,
        "name": "ЛИМОН",
        "tag": None,
        "description": "Яскравий лимон з виразною цитрусовою кислинкою.",
    },
    {
        "id": 16,
        "name": "КІВІ",
        "tag": None,
        "description": "Свіжий ківі з тропічною кисло-солодкою нотою.",
    },
    {
        "id": 17,
        "name": "М'ЯТА",
        "tag": None,
        "description": "Чиста м'ята з прохолодним фінішем.",
    },
    {
        "id": 18,
        "name": "ПЕРСИК",
        "tag": None,
        "description": "Соковитий персик з оксамитовою солодкістю.",
    },
    {
        "id": 19,
        "name": "ПОЛУНИЦЯ",
        "tag": None,
        "description": "Класична полуниця з приємною ягідною солодкістю.",
    },
    {
        "id": 20,
        "name": "СМОРОДИНА МЕНТОЛ",
        "tag": None,
        "description": "Чорна смородина з прохолодним ментоловим акцентом.",
    },
    {
        "id": 21,
        "name": "ЯГОДИ",
        "tag": None,
        "description": "Мікс ягід з соковитим ароматом.",
    },
]

FLAVOR_MAP = {flavor["id"]: flavor for flavor in FLAVORS}


def get_db_path() -> str:
    return os.getenv("DB_PATH", "bot.db")


def get_db() -> sqlite3.Connection:
    connection = sqlite3.connect(get_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    connection = get_db()
    with connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS stock (flavor_id INTEGER PRIMARY KEY, qty INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS carts (user_id INTEGER NOT NULL, flavor_id INTEGER NOT NULL, qty INTEGER NOT NULL, PRIMARY KEY (user_id, flavor_id))"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        existing = connection.execute("SELECT COUNT(*) AS count FROM stock").fetchone()["count"]
        if existing == 0:
            connection.executemany(
                "INSERT INTO stock (flavor_id, qty) VALUES (?, ?)",
                [(flavor["id"], 5) for flavor in FLAVORS],
            )
    connection.close()


def get_stock(connection: sqlite3.Connection) -> Dict[int, int]:
    rows = connection.execute("SELECT flavor_id, qty FROM stock").fetchall()
    return {row["flavor_id"]: row["qty"] for row in rows}


def get_cart(connection: sqlite3.Connection, user_id: int) -> Dict[int, int]:
    rows = connection.execute(
        "SELECT flavor_id, qty FROM carts WHERE user_id = ?", (user_id,)
    ).fetchall()
    return {row["flavor_id"]: row["qty"] for row in rows}


def get_setting(connection: sqlite3.Connection, key: str) -> Optional[str]:
    row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(connection: sqlite3.Connection, key: str, value: str) -> None:
    connection.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def get_photo_source(connection: sqlite3.Connection) -> Optional[str]:
    photo_url = os.getenv("PHOTO_URL")
    if photo_url:
        return photo_url
    return get_setting(connection, "PHOTO_FILE_ID")


def format_flavor_card(flavor_id: int, stock_qty: int) -> str:
    flavor = FLAVOR_MAP[flavor_id]
    tag = f"[{flavor['tag']}] " if flavor.get("tag") else ""
    return (
        f"{tag}{flavor['name']}\n"
        f"{flavor['description']}\n"
        f"Залишок: {stock_qty}"
    )


def build_main_menu(stock: Dict[int, int]) -> InlineKeyboardMarkup:
    buttons = []
    for flavor in FLAVORS:
        qty = stock.get(flavor["id"], 0)
        if qty > 0:
            buttons.append(
                [InlineKeyboardButton(flavor["name"], callback_data=f"flavor:{flavor['id']}")]
            )
    buttons.append([InlineKeyboardButton("🧺 Корзина", callback_data="cart:view")])
    return InlineKeyboardMarkup(buttons)


def build_flavor_keyboard(flavor_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ В корзину", callback_data=f"cart:add:{flavor_id}")],
            [InlineKeyboardButton("🧺 Корзина", callback_data="cart:view")],
            [InlineKeyboardButton("⬅️ До смаків", callback_data="menu:main")],
        ]
    )


def build_cart_keyboard(cart: Dict[int, int]) -> InlineKeyboardMarkup:
    rows = []
    for flavor_id, qty in cart.items():
        name = FLAVOR_MAP[flavor_id]["name"]
        rows.append(
            [
                InlineKeyboardButton("➖", callback_data=f"cart:dec:{flavor_id}"),
                InlineKeyboardButton(f"{name} × {qty}", callback_data="noop"),
                InlineKeyboardButton("➕", callback_data=f"cart:inc:{flavor_id}"),
            ]
        )
    rows.append([InlineKeyboardButton("✅ Оформити замовлення", callback_data="cart:checkout")])
    rows.append([InlineKeyboardButton("🗑 Очистити корзину", callback_data="cart:clear")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def cart_summary(cart: Dict[int, int]) -> str:
    if not cart:
        return "Корзина порожня."
    lines = ["Ваші товари:"]
    for flavor_id, qty in cart.items():
        name = FLAVOR_MAP[flavor_id]["name"]
        lines.append(f"- {name} × {qty}")
    return "\n".join(lines)


def ensure_admin(user_id: int, admin_id: int) -> bool:
    return user_id == admin_id


def parse_admin_id() -> int:
    value = os.getenv("ADMIN_CHAT_ID")
    if not value:
        raise RuntimeError("ENV ADMIN_CHAT_ID is required")
    return int(value)


def parse_bot_token() -> str:
    value = os.getenv("BOT_TOKEN")
    if not value:
        raise RuntimeError("ENV BOT_TOKEN is required")
    return value


def get_username_text(update: Update) -> str:
    username = update.effective_user.username
    return username if username else "нема username"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await show_main_menu(update, context, edit=False)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool) -> None:
    connection = get_db()
    stock = get_stock(connection)
    connection.close()
    text = "Оберіть смак Chaser 30 мл:"
    keyboard = build_main_menu(stock)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)


async def show_flavor(update: Update, context: ContextTypes.DEFAULT_TYPE, flavor_id: int) -> None:
    connection = get_db()
    stock = get_stock(connection)
    photo = get_photo_source(connection)
    connection.close()
    qty = stock.get(flavor_id, 0)
    text = format_flavor_card(flavor_id, qty)
    keyboard = build_flavor_keyboard(flavor_id)
    if update.callback_query:
        if photo:
            media = InputMediaPhoto(media=photo, caption=text)
            await update.callback_query.edit_message_media(media=media, reply_markup=keyboard)
        else:
            await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
    else:
        if photo:
            await update.message.reply_photo(photo=photo, caption=text, reply_markup=keyboard)
        else:
            await update.message.reply_text(text, reply_markup=keyboard)


async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    connection = get_db()
    cart = get_cart(connection, update.effective_user.id)
    connection.close()
    keyboard = build_cart_keyboard(cart)
    text = cart_summary(cart)
    if update.callback_query:
        await update.callback_query.edit_message_text(text=text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data
    if data == "menu:main":
        await show_main_menu(update, context, edit=True)
        return
    if data == "cart:view":
        await show_cart(update, context)
        return
    if data.startswith("flavor:"):
        flavor_id = int(data.split(":")[1])
        await show_flavor(update, context, flavor_id)
        return
    if data == "noop":
        return
    if data.startswith("cart:add:"):
        flavor_id = int(data.split(":")[2])
        await add_to_cart(update, context, flavor_id, delta=1, show_product=True)
        return
    if data.startswith("cart:inc:"):
        flavor_id = int(data.split(":")[2])
        await add_to_cart(update, context, flavor_id, delta=1, show_product=False)
        return
    if data.startswith("cart:dec:"):
        flavor_id = int(data.split(":")[2])
        await add_to_cart(update, context, flavor_id, delta=-1, show_product=False)
        return
    if data == "cart:clear":
        await clear_cart(update, context)
        return
    if data == "cart:checkout":
        await checkout(update, context)
        return


async def add_to_cart(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    flavor_id: int,
    delta: int,
    show_product: bool,
) -> None:
    user_id = update.effective_user.id
    connection = get_db()
    with connection:
        stock = get_stock(connection)
        cart = get_cart(connection, user_id)
        current = cart.get(flavor_id, 0)
        available = stock.get(flavor_id, 0)
        new_qty = current + delta
        if new_qty < 0:
            new_qty = 0
        if new_qty > available:
            new_qty = available
        if new_qty == 0:
            connection.execute(
                "DELETE FROM carts WHERE user_id = ? AND flavor_id = ?", (user_id, flavor_id)
            )
        else:
            connection.execute(
                "INSERT INTO carts (user_id, flavor_id, qty) VALUES (?, ?, ?) ON CONFLICT(user_id, flavor_id) DO UPDATE SET qty = excluded.qty",
                (user_id, flavor_id, new_qty),
            )
    connection.close()
    if show_product:
        await show_flavor(update, context, flavor_id)
    else:
        await show_cart(update, context)


async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    connection = get_db()
    with connection:
        connection.execute("DELETE FROM carts WHERE user_id = ?", (user_id,))
    connection.close()
    await show_cart(update, context)


async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    connection = get_db()
    with connection:
        cart = get_cart(connection, user_id)
        if not cart:
            await show_cart(update, context)
            return
        stock = get_stock(connection)
        for flavor_id, qty in cart.items():
            available = stock.get(flavor_id, 0)
            if qty > available:
                cart[flavor_id] = available
        for flavor_id, qty in cart.items():
            connection.execute(
                "UPDATE stock SET qty = qty - ? WHERE flavor_id = ?", (qty, flavor_id)
            )
        connection.execute("DELETE FROM carts WHERE user_id = ?", (user_id,))
    connection.close()
    await update.callback_query.edit_message_text(
        text="✅ Замовлення прийнято! Чекайте повідомлення від менеджера."
    )
    admin_id = parse_admin_id()
    profile_link = f"tg://user?id={user_id}"
    username_text = get_username_text(update)
    lines = [
        "Нове замовлення:",
        f"Профіль: {profile_link}",
        f"user_id: {user_id}",
        f"username: {username_text}",
        "Позиції:",
    ]
    for flavor_id, qty in cart.items():
        if qty <= 0:
            continue
        name = FLAVOR_MAP[flavor_id]["name"]
        lines.append(f"- {name} × {qty}")
    await context.bot.send_message(chat_id=admin_id, text="\n".join(lines))


async def list_flavors(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = parse_admin_id()
    if not ensure_admin(update.effective_user.id, admin_id):
        return
    lines = ["Смаки:"]
    for flavor in FLAVORS:
        lines.append(f"{flavor['id']}: {flavor['name']}")
    await update.message.reply_text("\n".join(lines))


async def show_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = parse_admin_id()
    if not ensure_admin(update.effective_user.id, admin_id):
        return
    connection = get_db()
    stock = get_stock(connection)
    connection.close()
    lines = ["Склад:"]
    for flavor in FLAVORS:
        qty = stock.get(flavor["id"], 0)
        lines.append(f"{flavor['id']}: {flavor['name']} — {qty}")
    await update.message.reply_text("\n".join(lines))


async def set_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = parse_admin_id()
    if not ensure_admin(update.effective_user.id, admin_id):
        return
    if len(context.args) != 2:
        await update.message.reply_text("Використання: /setstock <id> <qty>")
        return
    try:
        flavor_id = int(context.args[0])
        qty = int(context.args[1])
    except ValueError:
        await update.message.reply_text("ID та qty мають бути числами.")
        return
    if flavor_id not in FLAVOR_MAP:
        await update.message.reply_text("Невірний ID смаку.")
        return
    if qty < 0:
        await update.message.reply_text("qty має бути >= 0.")
        return
    connection = get_db()
    with connection:
        connection.execute(
            "INSERT INTO stock (flavor_id, qty) VALUES (?, ?) ON CONFLICT(flavor_id) DO UPDATE SET qty = excluded.qty",
            (flavor_id, qty),
        )
    connection.close()
    await update.message.reply_text(f"Оновлено склад для {FLAVOR_MAP[flavor_id]['name']} → {qty}")


async def set_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    admin_id = parse_admin_id()
    if not ensure_admin(update.effective_user.id, admin_id):
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Будь ласка, відповідайте на повідомлення з фото.")
        return
    file_id = update.message.reply_to_message.photo[-1].file_id
    connection = get_db()
    with connection:
        set_setting(connection, "PHOTO_FILE_ID", file_id)
    connection.close()
    await update.message.reply_text("Фото збережено.")


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("Невідома команда.")


def main() -> None:
    token = parse_bot_token()
    parse_admin_id()
    init_db()
    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("list", list_flavors))
    app.add_handler(CommandHandler("stock", show_stock))
    app.add_handler(CommandHandler("setstock", set_stock))
    app.add_handler(CommandHandler("setphoto", set_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.COMMAND, unknown))

    app.run_polling()


if __name__ == "__main__":
    main()
