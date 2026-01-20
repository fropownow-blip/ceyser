import os
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Dict, List, Tuple

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# =========================
# ENV
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "").strip()  # must be numeric string
PORT = int(os.environ.get("PORT", "10000"))  # Render gives PORT for web services

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is empty. Set environment variable BOT_TOKEN.")
if not ADMIN_CHAT_ID.isdigit():
    raise RuntimeError("ADMIN_CHAT_ID is missing or not numeric. Set env ADMIN_CHAT_ID to your Telegram numeric chat id.")

ADMIN_CHAT_ID_INT = int(ADMIN_CHAT_ID)

# =========================
# CONFIG
# =========================
BRAND = "Chaser"
VOLUME = "30 мл"

# All flavors you provided (30 ml only)
FLAVORS = [
    "ЧЕРЕШНЯ NEW",
    "ГРЕЙПФРУТ LIMITED",
    "КАКТУС LIMITED",
    "ЛІЧІ LIMITED",
    "ВИНОГРАД",
    "ВИШНЯ",
    "ВИШНЯ МЕНТОЛ",
    "ГРАНАТ",
    "ДИНЯ",
    "ЖОВТА МАЛИНА",
    "ЖОВТА ЧЕРЕШНЯ",
    "ЖОВТИЙ ДРАГОНФРУТ",
    "КАВУН",
    "КАВУН МЕНТОЛ",
    "ЛИМОН",
    "КІВІ",
    "М'ЯТА",
    "ПЕРСИК",
    "ПОЛУНИЦЯ",
    "СМОРОДИНА МЕНТОЛ",
    "ЯГОДИ",
]

# Simple description template (you can rewrite later)
def flavor_description(flavor: str) -> str:
    return f"**{BRAND} {VOLUME}**\nСмак: **{flavor}**\n\nНатисни «➕ В корзину», щоб додати."

# Optional product photo path (put file in repo)
PHOTO_PATH = "assets/chaser.png"  # you can rename to .jpg too


# =========================
# DB (SQLite)
# =========================
DB_PATH = os.environ.get("DB_PATH", "data.db")  # you can set to /var/data/data.db if you attach Render Disk

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock (
        flavor TEXT PRIMARY KEY,
        qty INTEGER NOT NULL DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cart (
        user_id INTEGER NOT NULL,
        flavor TEXT NOT NULL,
        qty INTEGER NOT NULL,
        PRIMARY KEY (user_id, flavor)
    )
    """)

    # Ensure all flavors exist in stock table
    for f in FLAVORS:
        cur.execute("INSERT OR IGNORE INTO stock(flavor, qty) VALUES(?, 0)", (f,))
    conn.commit()
    conn.close()

def normalize_flavor(text: str) -> str:
    # Accept underscores as spaces, trim, uppercase Ukrainian/RU kept as is
    t = (text or "").strip()
    t = t.replace("_", " ")
    t = " ".join(t.split())
    return t

def get_stock_all() -> Dict[str, int]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT flavor, qty FROM stock")
    rows = cur.fetchall()
    conn.close()
    return {r["flavor"]: int(r["qty"]) for r in rows}

def get_stock(flavor: str) -> int:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT qty FROM stock WHERE flavor = ?", (flavor,))
    row = cur.fetchone()
    conn.close()
    return int(row["qty"]) if row else 0

def set_stock(flavor: str, qty: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO stock(flavor, qty) VALUES(?, ?) ON CONFLICT(flavor) DO UPDATE SET qty=excluded.qty", (flavor, qty))
    conn.commit()
    conn.close()

def add_stock(flavor: str, qty: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE stock SET qty = MAX(qty + ?, 0) WHERE flavor = ?", (qty, flavor))
    conn.commit()
    conn.close()

def cart_get(user_id: int) -> Dict[str, int]:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT flavor, qty FROM cart WHERE user_id = ?", (user_id,))
    rows = cur.fetchall()
    conn.close()
    return {r["flavor"]: int(r["qty"]) for r in rows}

def cart_set(user_id: int, flavor: str, qty: int):
    conn = db()
    cur = conn.cursor()
    if qty <= 0:
        cur.execute("DELETE FROM cart WHERE user_id=? AND flavor=?", (user_id, flavor))
    else:
        cur.execute("""
            INSERT INTO cart(user_id, flavor, qty)
            VALUES(?, ?, ?)
            ON CONFLICT(user_id, flavor) DO UPDATE SET qty=excluded.qty
        """, (user_id, flavor, qty))
    conn.commit()
    conn.close()

def cart_add(user_id: int, flavor: str, delta: int):
    current = cart_get(user_id).get(flavor, 0)
    cart_set(user_id, flavor, current + delta)

def cart_clear(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def checkout(user_id: int) -> Tuple[bool, str, List[Tuple[str,int]]]:
    """
    Atomically:
    - verify stock is enough
    - decrement stock
    - clear cart
    """
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT flavor, qty FROM cart WHERE user_id = ?", (user_id,))
    items = [(r["flavor"], int(r["qty"])) for r in cur.fetchall()]
    if not items:
        conn.close()
        return False, "Корзина пуста.", []

    try:
        conn.execute("BEGIN IMMEDIATE")

        # check stock
        for flavor, q in items:
            cur.execute("SELECT qty FROM stock WHERE flavor=?", (flavor,))
            row = cur.fetchone()
            available = int(row["qty"]) if row else 0
            if q > available:
                conn.rollback()
                conn.close()
                return False, f"Немає в наявності достатньо: {flavor} (потрібно {q}, є {available}).", items

        # deduct
        for flavor, q in items:
            cur.execute("UPDATE stock SET qty = qty - ? WHERE flavor=?", (q, flavor))

        # clear cart
        cur.execute("DELETE FROM cart WHERE user_id=?", (user_id,))
        conn.commit()
        conn.close()
        return True, "OK", items
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f"Помилка оформлення: {e}", items


# =========================
# UI builders
# =========================
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{BRAND} {VOLUME}", callback_data="cat:30")],
        [InlineKeyboardButton("🧺 Корзина", callback_data="cart:view")],
    ])

def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Меню", callback_data="menu")]])

def flavors_kb() -> InlineKeyboardMarkup:
    st = get_stock_all()
    buttons = []
    for f in FLAVORS:
        qty = st.get(f, 0)
        if qty > 0:
            buttons.append([InlineKeyboardButton(f"{f} ({qty} шт.)", callback_data=f"flavor:{f}")])
    buttons.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu")])
    buttons.append([InlineKeyboardButton("🧺 Корзина", callback_data="cart:view")])
    return InlineKeyboardMarkup(buttons)

def flavor_actions_kb(flavor: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ В корзину", callback_data=f"cart:add:{flavor}")],
        [InlineKeyboardButton("🧺 Корзина", callback_data="cart:view")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="cat:30")],
    ])

def cart_kb(cart: Dict[str, int]) -> InlineKeyboardMarkup:
    rows = []
    for flavor, qty in cart.items():
        rows.append([
            InlineKeyboardButton("➖", callback_data=f"cart:dec:{flavor}"),
            InlineKeyboardButton(f"{flavor} × {qty}", callback_data=f"noop"),
            InlineKeyboardButton("➕", callback_data=f"cart:inc:{flavor}"),
        ])
    if cart:
        rows.append([InlineKeyboardButton("✅ Замовити", callback_data="order:confirm")])
        rows.append([InlineKeyboardButton("🗑 Очистити", callback_data="cart:clear")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="cat:30")])
    rows.append([InlineKeyboardButton("⬅️ Меню", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


# =========================
# Helpers
# =========================
async def safe_answer(query, text=""):
    try:
        await query.answer(text=text)
    except Exception:
        pass

def user_profile_text(u) -> str:
    # tg deep link works even without username
    link = f"tg://user?id={u.id}"
    name = " ".join([x for x in [u.first_name, u.last_name] if x]) or "Без імені"
    username = f"@{u.username}" if u.username else "немає username"
    return f"👤 Клієнт: {name}\n🔗 Профіль: {link}\n🆔 ID: {u.id}\n👤 Username: {username}"

def order_text(items: List[Tuple[str,int]]) -> str:
    lines = ["🧾 **Нове замовлення**", f"Товар: **{BRAND} {VOLUME}**", ""]
    for f, q in items:
        lines.append(f"• {f} × {q}")
    return "\n".join(lines)

async def send_product_photo_if_exists(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if os.path.exists(PHOTO_PATH):
        try:
            with open(PHOTO_PATH, "rb") as f:
                await update.effective_chat.send_photo(photo=InputFile(f))
        except Exception:
            pass


# =========================
# Commands
# =========================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_product_photo_if_exists(update, context)
    await update.message.reply_text(
        f"Привіт! 👋\nВибери товар:",
        reply_markup=main_menu_kb()
    )

def is_admin(update: Update) -> bool:
    return update.effective_user and update.effective_user.id == ADMIN_CHAT_ID_INT

async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔️ Команда тільки для адміна.")
        return

    st = get_stock_all()
    lines = [f"📦 Склад: **{BRAND} {VOLUME}**", ""]
    for f in FLAVORS:
        lines.append(f"• {f}: {st.get(f, 0)}")
    lines.append("")
    lines.append("Команди:")
    lines.append("/setstock <смак> <кількість>")
    lines.append("/addstock <смак> <кількість>")
    lines.append("Приклад: /setstock ВИШНЯ_МЕНТОЛ 20")
    await update.message.reply_text("\n".join(lines))

async def cmd_setstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔️ Команда тільки для адміна.")
        return

    # Accept formats:
    # /setstock ВИШНЯ_МЕНТОЛ 20
    # /setstock ВИШНЯ МЕНТОЛ 20
    parts = update.message.text.split(maxsplit=2)
    if len(parts) < 3:
        await update.message.reply_text("Формат: /setstock <смак> <кількість>\nПриклад: /setstock ВИШНЯ_МЕНТОЛ 20")
        return

    # parts[1..] contains flavor and qty, but flavor may have spaces if user did maxsplit=2 => good
    tail = parts[2].strip()
    # Here parts = ["/setstock", flavor_or_part, rest]
    # We want last token of rest as qty if rest has spaces.
    # Better parse: remove "/setstock " then split last as qty
    raw = update.message.text[len("/setstock"):].strip()
    if not raw:
        await update.message.reply_text("Формат: /setstock <смак> <кількість>")
        return

    toks = raw.split()
    if len(toks) < 2:
        await update.message.reply_text("Формат: /setstock <смак> <кількість>")
        return

    qty_str = toks[-1]
    flavor_raw = " ".join(toks[:-1])
    flavor = normalize_flavor(flavor_raw)

    if not qty_str.isdigit():
        await update.message.reply_text("Кількість має бути числом.")
        return

    qty = int(qty_str)

    # Try to match flavor from list (case-insensitive)
    matched = None
    for f in FLAVORS:
        if f.upper() == flavor.upper():
            matched = f
            break

    if not matched:
        await update.message.reply_text("Не знайшов такий смак. Перевір написання.")
        return

    set_stock(matched, qty)
    await update.message.reply_text(f"✅ Встановлено: {matched} = {qty}")

async def cmd_addstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        await update.message.reply_text("⛔️ Команда тільки для адміна.")
        return

    raw = update.message.text[len("/addstock"):].strip()
    toks = raw.split()
    if len(toks) < 2:
        await update.message.reply_text("Формат: /addstock <смак> <кількість>\nПриклад: /addstock БАНАН 5")
        return

    qty_str = toks[-1]
    flavor_raw = " ".join(toks[:-1])
    flavor = normalize_flavor(flavor_raw)

    try:
        qty = int(qty_str)
    except ValueError:
        await update.message.reply_text("Кількість має бути числом (можна від'ємне).")
        return

    matched = None
    for f in FLAVORS:
        if f.upper() == flavor.upper():
            matched = f
            break

    if not matched:
        await update.message.reply_text("Не знайшов такий смак. Перевір написання.")
        return

    add_stock(matched, qty)
    await update.message.reply_text(f"✅ Додано: {matched} ({qty:+d}). Тепер: {get_stock(matched)}")


# =========================
# Callback router
# =========================
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer(query)
    data = query.data or ""

    # MENU
    if data == "menu":
        await query.edit_message_text("Вибери товар:", reply_markup=main_menu_kb())
        return

    # CATEGORY (only 30)
    if data == "cat:30":
        kb = flavors_kb()
        # if no items
        st = get_stock_all()
        if not any(st.get(f, 0) > 0 for f in FLAVORS):
            await query.edit_message_text("Наразі немає в наявності 😕", reply_markup=back_to_menu_kb())
            return
        await query.edit_message_text(f"Смаки {BRAND} {VOLUME} (показує тільки те, що є на складі):", reply_markup=kb)
        return

    # FLAVOR VIEW
    if data.startswith("flavor:"):
        flavor = data.split(":", 1)[1]
        if get_stock(flavor) <= 0:
            await query.edit_message_text("Цього смаку вже нема в наявності 😕", reply_markup=flavors_kb())
            return

        text = flavor_description(flavor)
        # send photo separately if exists, then edit text
        try:
            if os.path.exists(PHOTO_PATH):
                # If current message has no photo, we send a new photo message
                with open(PHOTO_PATH, "rb") as f:
                    await query.message.reply_photo(photo=InputFile(f), caption=text, parse_mode="Markdown", reply_markup=flavor_actions_kb(flavor))
                # keep old message as list screen
                return
        except Exception:
            pass

        # fallback: text only
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=flavor_actions_kb(flavor))
        return

    # CART VIEW
    if data == "cart:view":
        cart = cart_get(update.effective_user.id)
        if not cart:
            await query.edit_message_text("🧺 Корзина пуста.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="cat:30")],
                [InlineKeyboardButton("⬅️ Меню", callback_data="menu")],
            ]))
            return

        lines = ["🧺 **Твоя корзина:**", ""]
        for f, q in cart.items():
            lines.append(f"• {f} × {q}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=cart_kb(cart))
        return

    # CART EDIT
    if data.startswith("cart:add:"):
        flavor = data.split(":", 2)[2]
        if get_stock(flavor) <= 0:
            await query.message.reply_text("Цього смаку вже нема в наявності 😕")
            return

        # Add 1 but not beyond stock
        user_id = update.effective_user.id
        current_in_cart = cart_get(user_id).get(flavor, 0)
        if current_in_cart + 1 > get_stock(flavor):
            await query.message.reply_text("Більше додати не можна — не вистачає на складі.")
            return

        cart_add(user_id, flavor, 1)
        await query.message.reply_text(f"✅ Додано в корзину: {flavor} (1 шт.)")
        return

    if data.startswith("cart:inc:"):
        flavor = data.split(":", 2)[2]
        user_id = update.effective_user.id
        current = cart_get(user_id).get(flavor, 0)
        if current + 1 > get_stock(flavor):
            await query.message.reply_text("Більше додати не можна — не вистачає на складі.")
            return
        cart_add(user_id, flavor, 1)
        cart = cart_get(user_id)
        await query.edit_message_text(
            "\n".join(["🧺 **Твоя корзина:**", ""] + [f"• {f} × {q}" for f, q in cart.items()]),
            parse_mode="Markdown",
            reply_markup=cart_kb(cart)
        )
        return

    if data.startswith("cart:dec:"):
        flavor = data.split(":", 2)[2]
        user_id = update.effective_user.id
        cart_add(user_id, flavor, -1)
        cart = cart_get(user_id)
        if not cart:
            await query.edit_message_text("🧺 Корзина пуста.", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Назад", callback_data="cat:30")],
                [InlineKeyboardButton("⬅️ Меню", callback_data="menu")],
            ]))
            return
        await query.edit_message_text(
            "\n".join(["🧺 **Твоя корзина:**", ""] + [f"• {f} × {q}" for f, q in cart.items()]),
            parse_mode="Markdown",
            reply_markup=cart_kb(cart)
        )
        return

    if data == "cart:clear":
        cart_clear(update.effective_user.id)
        await query.edit_message_text("🗑 Корзина очищена.", reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="cat:30")],
            [InlineKeyboardButton("⬅️ Меню", callback_data="menu")],
        ]))
        return

    # ORDER
    if data == "order:confirm":
        user_id = update.effective_user.id
        ok, msg, items = checkout(user_id)
        if not ok:
            await query.message.reply_text(f"❌ {msg}")
            return

        # Send to admin: profile + order
        u = update.effective_user
        admin_text = user_profile_text(u) + "\n\n" + order_text(items)

        try:
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID_INT, text=admin_text, parse_mode="Markdown")
        except Exception:
            # still ok for user, but warn
            await query.message.reply_text("⚠️ Не зміг надіслати повідомлення адміну. Перевір ADMIN_CHAT_ID.")
            return

        # User confirmation
        await query.edit_message_text("✅ Замовлення прийнято! Чекайте повідомлення від менеджера 🙌", reply_markup=back_to_menu_kb())
        return

    if data == "noop":
        return

    # Unknown
    await query.message.reply_text("Невідома дія. Натисни /start.")


# =========================
# Minimal HTTP server (for Render Web Service)
# =========================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

def start_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        server.serve_forever()
    except Exception:
        pass


# =========================
# Main
# =========================
def main():
    init_db()

    # Start health server in background (so Render Web Service doesn't kill it)
    t = threading.Thread(target=start_health_server, daemon=True)
    t.start()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("setstock", cmd_setstock))
    app.add_handler(CommandHandler("addstock", cmd_addstock))

    app.add_handler(CallbackQueryHandler(on_callback))

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
