import os
import html
import sqlite3
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.error import BadRequest, Forbidden, TelegramError
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
BOOTSTRAP_ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()

# Railway: use a Volume mounted at /data for real persistence.
# You can override this with DATABASE_FILE.
DEFAULT_DB = "/data/srpexchange.db" if os.path.isdir("/data") else "srpexchange.db"
DATABASE_FILE = os.getenv("DATABASE_FILE", DEFAULT_DB).strip()

BOOTSTRAP_ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "berizienuhq").strip().lstrip("@")
TIMEZONE_NAME = os.getenv("TIMEZONE", "Europe/Zurich")
try:
    BOT_TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    BOT_TZ = ZoneInfo("UTC")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("SRPExchange")

# In-memory workflow/session state only. Shop data is SQLite-persistent.
sessions = {}
screen_messages = {}

# ============================================================
# DATABASE
# ============================================================


def db():
    directory = os.path.dirname(os.path.abspath(DATABASE_FILE))
    if directory and directory != ".":
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DATABASE_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def table_columns(conn, table_name):
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def ensure_column(conn, table_name, column_name, definition):
    if column_name not in table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def now_string():
    return datetime.now(BOT_TZ).strftime("%d.%m.%Y %H:%M:%S")


DEFAULT_SETTINGS = {
    "shop_name": "SRPExchange",
    "admin_username": "@berizienuhq",
    "order_recipient_chat_id": BOOTSTRAP_ADMIN_CHAT_ID,
    "max_custom_amount": "1000000",
    "delete_user_messages": "1",
    "show_admin_button": "1",
}

DEFAULT_TEXTS = {
    "welcome": (
        "🛍️ <b>{shop_name}</b>\n\n"
        "Welcome! Choose an option below to get started."
    ),
    "category": (
        "🗂️ <b>SELECT A CATEGORY</b>\n\n"
        "Choose what you would like to exchange."
    ),
    "currency": (
        "💱 <b>SELECT PAYMENT METHOD</b>\n\n"
        "Choose the currency you want to use."
    ),
    "product": (
        "📦 <b>{category}</b>\n\n"
        "Choose an available option below."
    ),
    "custom": (
        "✏️ <b>CUSTOM AMOUNT</b>\n\n"
        "Send the amount of Robux you want.\n\n"
        "Example: <code>2500</code>"
    ),
    "username": (
        "👤 <b>ROBLOX USERNAME</b>\n\n"
        "Send your Roblox username."
    ),
    "how": (
        "ℹ️ <b>HOW IT WORKS</b>\n\n"
        "1️⃣ Choose a category.\n"
        "2️⃣ Choose a payment method.\n"
        "3️⃣ Choose an offer or enter a custom amount.\n"
        "4️⃣ Enter your Roblox username.\n"
        "5️⃣ Your order is sent to the admin."
    ),
    "confirmation": (
        "✅ <b>ORDER {order_number}</b>\n\n"
        "We have received your order.\n\n"
        "📩 Please wait for a DM from <b>{admin_username}</b> "
        "to finalise the exchange.\n\n"
        "Thank you for using <b>{shop_name}</b>."
    ),
    "cancelled": "❌ <b>CANCELLED</b>\n\nYour current action has been cancelled.",
    "no_categories": "🗂️ <b>NO CATEGORIES</b>\n\nThere are currently no available categories.",
    "no_currencies": "💱 <b>NO CURRENCIES</b>\n\nThere are currently no available payment methods.",
    "no_products": "📦 <b>NO PRODUCTS</b>\n\nThere are currently no available products here.",
    "invalid_amount": "⚠️ Please enter a valid amount between 1 and {max_custom_amount}.",
    "invalid_username": (
        "⚠️ That doesn't look like a valid Roblox username.\n\n"
        "Please try again."
    ),
    "order_error": (
        "⚠️ <b>ORDER NOT CREATED</b>\n\n"
        "Something went wrong while creating your order. Please try again."
    ),
    "no_session": "Please open the shop again with /start.",
    "admin_new_order": (
        "🔔 <b>NEW ORDER</b>\n\n"
        "🔐 Order: <code>{order_number}</code>\n"
        "🗂️ Category: <b>{category}</b>\n"
        "💱 Payment method: <b>{currency}</b>\n"
        "📦 Product: <b>{product}</b>\n"
        "💰 Amount: <b>{amount:,} Robux</b>\n"
        "💵 Price: <b>{price}</b>\n"
        "👤 Roblox username: <code>{roblox_username}</code>\n"
        "📅 Created: <b>{created_at}</b>\n"
        "⏳ Status: <b>Awaiting confirmation</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "👤 Customer: <b>{customer_name}</b>\n"
        "📱 Telegram: <b>{customer_username}</b>\n"
        "🆔 Chat ID: <code>{telegram_id}</code>"
    ),
    "admin_send_failed": (
        "⚠️ <b>ORDER SAVED</b>\n\n"
        "Order <code>{order_number}</code> was saved, but the configured admin chat "
        "could not be notified.\n\nReason: <code>{error}</code>"
    ),
}

DEFAULT_BUTTONS = {
    "exchange": "💱 Exchange",
    "how": "ℹ️ How It Works",
    "back": "↩️ Back",
    "home": "🏠 Main Menu",
    "new_order": "💱 New Order",
    "cancel": "❌ Cancel",
    "custom": "✏️ Custom Amount",
    "admin": "⚙️ Admin Panel",
    "categories": "🗂️ Categories",
    "currencies": "💱 Currencies",
    "products": "📦 Products",
    "prices": "💰 Prices",
    "texts": "📝 Texts",
    "buttons": "🔘 Buttons",
    "settings": "🏪 Shop Settings",
    "emojis": "✨ Custom Emojis",
    "orders": "📋 Orders",
    "admins": "👮 Admins",
    "add": "➕ Add",
    "edit": "✏️ Edit",
    "delete": "🗑️ Delete",
    "enable": "🟢 Enable",
    "disable": "🔴 Disable",
}

TEXT_LABELS = {
    "welcome": "👋 Welcome screen",
    "category": "🗂️ Category screen",
    "currency": "💱 Currency screen",
    "product": "📦 Product screen",
    "custom": "✏️ Custom amount screen",
    "username": "👤 Username screen",
    "how": "ℹ️ How it works",
    "confirmation": "✅ Order confirmation",
    "cancelled": "❌ Cancelled message",
    "no_categories": "🗂️ Empty categories",
    "no_currencies": "💱 Empty currencies",
    "no_products": "📦 Empty products",
    "invalid_amount": "⚠️ Invalid amount",
    "invalid_username": "⚠️ Invalid username",
    "order_error": "⚠️ Order creation error",
    "no_session": "🔄 No active session",
    "admin_new_order": "🔔 Admin new-order message",
    "admin_send_failed": "⚠️ Admin notification failure",
}

BUTTON_LABELS = {k: k.replace("_", " ").title() for k in DEFAULT_BUTTONS}


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            button_text TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            parent_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS currencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            button_text TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            button_text TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            category_id INTEGER REFERENCES categories(id) ON DELETE RESTRICT,
            description TEXT NOT NULL DEFAULT '',
            is_custom INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS prices (
            currency_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price TEXT NOT NULL DEFAULT 'NA',
            PRIMARY KEY(currency_id, product_id),
            FOREIGN KEY(currency_id) REFERENCES currencies(id) ON DELETE CASCADE,
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS custom_prices (
            currency_id INTEGER PRIMARY KEY,
            price TEXT NOT NULL DEFAULT 'NA',
            FOREIGN KEY(currency_id) REFERENCES currencies(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS texts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS buttons (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS custom_emojis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            emoji_id TEXT NOT NULL,
            fallback TEXT NOT NULL DEFAULT '✨',
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            telegram_id INTEGER NOT NULL,
            telegram_username TEXT,
            telegram_name TEXT,
            category TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL,
            product TEXT NOT NULL,
            robux_amount INTEGER NOT NULL DEFAULT 0,
            price TEXT NOT NULL,
            roblox_username TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'awaiting_confirmation',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        """
    )

    # Migrations from the previous SRPExchange builds.
    ensure_column(conn, "categories", "parent_id", "INTEGER")
    ensure_column(conn, "categories", "description", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "categories", "button_text", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "categories", "enabled", "INTEGER NOT NULL DEFAULT 1")
    ensure_column(conn, "categories", "sort_order", "INTEGER NOT NULL DEFAULT 0")

    ensure_column(conn, "products", "category_id", "INTEGER")
    ensure_column(conn, "products", "description", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "products", "is_custom", "INTEGER NOT NULL DEFAULT 0")

    ensure_column(conn, "orders", "category", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "orders", "status", "TEXT NOT NULL DEFAULT 'awaiting_confirmation'")

    for key, value in DEFAULT_SETTINGS.items():
        cur.execute(
            "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
            (key, value),
        )

    # Preserve old shop name only if it was an old generic value.
    old_name = cur.execute(
        "SELECT value FROM settings WHERE key='shop_name'"
    ).fetchone()
    if old_name and old_name["value"] == "R$ EXCHANGE":
        cur.execute("UPDATE settings SET value='SRPExchange' WHERE key='shop_name'")

    for key, value in DEFAULT_TEXTS.items():
        cur.execute(
            "INSERT OR IGNORE INTO texts(key, value) VALUES (?, ?)",
            (key, value),
        )

    for key, value in DEFAULT_BUTTONS.items():
        cur.execute(
            "INSERT OR IGNORE INTO buttons(key, value) VALUES (?, ?)",
            (key, value),
        )

    # Repair empty button_text in migrated categories.
    cur.execute(
        "UPDATE categories SET button_text=name WHERE TRIM(button_text)=''"
    )

    # Seed default category only when none exists.
    category_count = cur.execute("SELECT COUNT(*) AS n FROM categories").fetchone()["n"]
    if category_count == 0:
        cur.execute(
            """
            INSERT INTO categories(name, button_text, description, enabled, sort_order, parent_id)
            VALUES (?, ?, ?, 1, 1, NULL)
            """,
            ("Robux", "💎 Robux", "Choose a Robux amount to exchange.",),
        )

    # Seed default currencies only when none exist.
    currency_count = cur.execute("SELECT COUNT(*) AS n FROM currencies").fetchone()["n"]
    if currency_count == 0:
        cur.executemany(
            """
            INSERT INTO currencies(name, button_text, enabled, sort_order)
            VALUES (?, ?, 1, ?)
            """,
            [
                ("GRAM", "💎 GRAM", 1),
                ("Telegram Stars", "⭐ Telegram Stars", 2),
            ],
        )

    # Put old products into first category when they have no category.
    first_category = cur.execute(
        "SELECT id FROM categories ORDER BY sort_order, id LIMIT 1"
    ).fetchone()
    if first_category:
        cur.execute(
            "UPDATE products SET category_id=? WHERE category_id IS NULL",
            (first_category["id"],),
        )

    # Seed old default offers only on a totally empty products table.
    product_count = cur.execute("SELECT COUNT(*) AS n FROM products").fetchone()["n"]
    if product_count == 0 and first_category:
        cur.executemany(
            """
            INSERT INTO products(name, button_text, amount, enabled, sort_order, category_id, description, is_custom)
            VALUES (?, ?, ?, 1, ?, ?, '', ?)
            """,
            [
                ("200 Robux", "200 Robux", 200, 1, first_category["id"], 0),
                ("500 Robux", "500 Robux", 500, 2, first_category["id"], 0),
                ("700 Robux", "700 Robux", 700, 3, first_category["id"], 0),
                ("1,000 Robux", "1,000 Robux", 1000, 4, first_category["id"], 0),
                ("Custom Amount", "✏️ Custom Amount", 0, 5, first_category["id"], 1),
            ],
        )

    # Always ensure every product has a currency price row.
    currencies = cur.execute("SELECT id FROM currencies").fetchall()
    products = cur.execute("SELECT id FROM products").fetchall()
    for c in currencies:
        for p in products:
            cur.execute(
                "INSERT OR IGNORE INTO prices(currency_id, product_id, price) VALUES (?, ?, 'NA')",
                (c["id"], p["id"]),
            )
        cur.execute(
            "INSERT OR IGNORE INTO custom_prices(currency_id, price) VALUES (?, 'NA')",
            (c["id"],),
        )

    # Bootstrap admin from Railway variable.
    if BOOTSTRAP_ADMIN_CHAT_ID:
        try:
            admin_id = int(BOOTSTRAP_ADMIN_CHAT_ID)
            cur.execute(
                """
                INSERT OR IGNORE INTO admins(telegram_id, label, enabled, created_at)
                VALUES (?, ?, 1, ?)
                """,
                (admin_id, "Bootstrap admin", now_string()),
            )
        except ValueError:
            logger.warning("ADMIN_CHAT_ID must be numeric; username bootstrap may be used.")

    conn.commit()
    conn.close()


# ============================================================
# DATABASE HELPERS
# ============================================================


def get_setting(key, default=""):
    conn = db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO settings(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_text(key, default=""):
    conn = db()
    row = conn.execute("SELECT value FROM texts WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_text(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO texts(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def get_button(key, default=None):
    fallback = key if default is None else default
    conn = db()
    row = conn.execute("SELECT value FROM buttons WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else fallback


def set_button(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO buttons(key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def get_categories(parent_id=None, enabled_only=False):
    conn = db()
    if parent_id is None:
        parent_clause = "parent_id IS NULL"
        args = []
    else:
        parent_clause = "parent_id=?"
        args = [parent_id]
    extra = " AND enabled=1" if enabled_only else ""
    rows = conn.execute(
        f"SELECT * FROM categories WHERE {parent_clause}{extra} ORDER BY sort_order, id",
        tuple(args),
    ).fetchall()
    conn.close()
    return rows


def get_all_categories(enabled_only=False):
    conn = db()
    extra = "WHERE enabled=1" if enabled_only else ""
    rows = conn.execute(
        f"SELECT * FROM categories {extra} ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return rows


def get_category(category_id):
    conn = db()
    row = conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    conn.close()
    return row


def get_category_children(category_id, enabled_only=False):
    return get_categories(category_id, enabled_only)


def get_products(category_id=None, enabled_only=False):
    conn = db()
    conditions = []
    args = []
    if category_id is not None:
        conditions.append("category_id=?")
        args.append(category_id)
    if enabled_only:
        conditions.append("enabled=1")
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = conn.execute(
        f"SELECT * FROM products{where} ORDER BY sort_order, id", tuple(args)
    ).fetchall()
    conn.close()
    return rows


def get_all_products():
    return get_products()


def get_product(product_id):
    conn = db()
    row = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
    conn.close()
    return row


def get_currencies(enabled_only=False):
    conn = db()
    extra = "WHERE enabled=1" if enabled_only else ""
    rows = conn.execute(
        f"SELECT * FROM currencies {extra} ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return rows


def get_currency(currency_id):
    conn = db()
    row = conn.execute("SELECT * FROM currencies WHERE id=?", (currency_id,)).fetchone()
    conn.close()
    return row


def get_price(currency_id, product_id):
    conn = db()
    row = conn.execute(
        "SELECT price FROM prices WHERE currency_id=? AND product_id=?",
        (currency_id, product_id),
    ).fetchone()
    conn.close()
    return row["price"] if row else "NA"


def set_price(currency_id, product_id, price):
    conn = db()
    conn.execute(
        """
        INSERT INTO prices(currency_id, product_id, price) VALUES (?, ?, ?)
        ON CONFLICT(currency_id, product_id) DO UPDATE SET price=excluded.price
        """,
        (currency_id, product_id, price.strip() or "NA"),
    )
    conn.commit()
    conn.close()


def get_custom_price(currency_id):
    conn = db()
    row = conn.execute(
        "SELECT price FROM custom_prices WHERE currency_id=?",
        (currency_id,),
    ).fetchone()
    conn.close()
    return row["price"] if row else "NA"


def set_custom_price(currency_id, price):
    conn = db()
    conn.execute(
        """
        INSERT INTO custom_prices(currency_id, price) VALUES (?, ?)
        ON CONFLICT(currency_id) DO UPDATE SET price=excluded.price
        """,
        (currency_id, price.strip() or "NA"),
    )
    conn.commit()
    conn.close()


def get_orders(limit=40):
    conn = db()
    rows = conn.execute(
        "SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_order(order_number):
    conn = db()
    row = conn.execute(
        "SELECT * FROM orders WHERE order_number=?", (order_number,)
    ).fetchone()
    conn.close()
    return row


def set_order_status(order_number, status):
    conn = db()
    conn.execute(
        "UPDATE orders SET status=? WHERE order_number=?",
        (status, order_number),
    )
    conn.commit()
    conn.close()


def get_admins():
    conn = db()
    rows = conn.execute(
        "SELECT * FROM admins ORDER BY created_at, telegram_id"
    ).fetchall()
    conn.close()
    return rows


def add_admin(telegram_id, label=""):
    conn = db()
    conn.execute(
        """
        INSERT INTO admins(telegram_id, label, enabled, created_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET label=excluded.label, enabled=1
        """,
        (telegram_id, label, now_string()),
    )
    conn.commit()
    conn.close()


def remove_admin(telegram_id):
    conn = db()
    conn.execute("DELETE FROM admins WHERE telegram_id=?", (telegram_id,))
    conn.commit()
    conn.close()


# ============================================================
# CUSTOM EMOJI HELPERS
# ============================================================


def get_emojis(enabled_only=False):
    conn = db()
    extra = "WHERE enabled=1" if enabled_only else ""
    rows = conn.execute(
        f"SELECT * FROM custom_emojis {extra} ORDER BY sort_order, id"
    ).fetchall()
    conn.close()
    return rows


def get_emoji(emoji_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM custom_emojis WHERE id=?", (emoji_id,)
    ).fetchone()
    conn.close()
    return row


def get_emoji_by_name(name):
    conn = db()
    row = conn.execute(
        "SELECT * FROM custom_emojis WHERE lower(name)=lower(?)", (name,)
    ).fetchone()
    conn.close()
    return row


def add_emoji(name, emoji_id, fallback):
    conn = db()
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM custom_emojis"
    ).fetchone()["n"]
    conn.execute(
        """
        INSERT INTO custom_emojis(name, emoji_id, fallback, enabled, sort_order, created_at)
        VALUES (?, ?, ?, 1, ?, ?)
        """,
        (name, emoji_id, fallback, next_order, now_string()),
    )
    conn.commit()
    conn.close()


def update_emoji_name(emoji_id, name):
    conn = db()
    conn.execute("UPDATE custom_emojis SET name=? WHERE id=?", (name, emoji_id))
    conn.commit()
    conn.close()


def delete_emoji(emoji_id):
    conn = db()
    conn.execute("DELETE FROM custom_emojis WHERE id=?", (emoji_id,))
    conn.commit()
    conn.close()


def toggle_emoji(emoji_id):
    conn = db()
    conn.execute(
        "UPDATE custom_emojis SET enabled=CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?",
        (emoji_id,),
    )
    conn.commit()
    conn.close()


# ============================================================
# AUTH / FORMATTING
# ============================================================


def is_admin(user):
    if not user:
        return False
    # Admin authorization is ID-based only. Usernames can change and should
    # never be sufficient to grant control of the shop.
    if BOOTSTRAP_ADMIN_CHAT_ID:
        try:
            if user.id == int(BOOTSTRAP_ADMIN_CHAT_ID):
                return True
        except ValueError:
            pass
    conn = db()
    row = conn.execute(
        "SELECT 1 FROM admins WHERE telegram_id=? AND enabled=1",
        (user.id,),
    ).fetchone()
    conn.close()
    return row is not None


def esc(value):
    return html.escape(str(value))


CUSTOM_EMOJI_TOKEN_RE = re.compile(r"\{\{emoji:([A-Za-z0-9_-]+)\}\}")


def replace_emoji_tokens(text):
    """Replace {{emoji:name}} with Telegram HTML custom-emoji tags."""
    def repl(match):
        name = match.group(1)
        row = get_emoji_by_name(name)
        if not row or not row["enabled"]:
            return match.group(0)
        fallback = esc(row["fallback"] or "✨")
        return f'<tg-emoji emoji-id="{esc(row["emoji_id"])}">{fallback}</tg-emoji>'
    return CUSTOM_EMOJI_TOKEN_RE.sub(repl, text)


def render_text(key, **values):
    data = {
        "shop_name": esc(get_setting("shop_name", "SRPExchange")),
        "admin_username": esc(get_setting("admin_username", "@berizienuhq")),
        "max_custom_amount": esc(get_setting("max_custom_amount", "1000000")),
    }
    for k, v in values.items():
        # Most dynamic values appear inside HTML. Keep markup safe.
        data[k] = esc(v) if isinstance(v, str) else v
    template = get_text(key, "")
    try:
        rendered = template.format(**data)
    except Exception:
        rendered = template
    return replace_emoji_tokens(rendered)


def text_label(key):
    return TEXT_LABELS.get(key, key.replace("_", " ").title())


def user_display(user):
    if getattr(user, "username", None):
        return "@" + user.username
    return user.full_name or str(user.id)


def valid_roblox_username(value):
    username = value.lstrip("@").strip()
    return 3 <= len(username) <= 20 and bool(re.fullmatch(r"[A-Za-z0-9_]+", username))


def current_category_path(category_id):
    pieces = []
    current = get_category(category_id)
    seen = set()
    while current and current["id"] not in seen:
        seen.add(current["id"])
        pieces.append(current["name"])
        current = get_category(current["parent_id"]) if current["parent_id"] else None
    return " / ".join(reversed(pieces))


def would_create_cycle(category_id, new_parent_id):
    if new_parent_id is None:
        return False
    if category_id == new_parent_id:
        return True
    current = get_category(new_parent_id)
    seen = set()
    while current:
        if current["id"] in seen:
            return True
        seen.add(current["id"])
        if current["id"] == category_id:
            return True
        current = get_category(current["parent_id"]) if current["parent_id"] else None
    return False


# ============================================================
# SCREEN / UX HELPERS
# ============================================================


def kb(rows):
    return InlineKeyboardMarkup(rows)


def two_col(buttons, bottom=None):
    rows = []
    current = []
    for button in buttons:
        current.append(button)
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    if bottom:
        rows.extend(bottom)
    return kb(rows)


def admin_bottom():
    return [[InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")]]


def back_button(callback="home"):
    return InlineKeyboardButton(get_button("back", "↩️ Back"), callback_data=callback)


async def safe_delete(bot, chat_id, message_id):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (BadRequest, Forbidden, TelegramError):
        pass


async def send_or_edit_screen(bot, chat_id, user_id, text, reply_markup=None):
    message_id = screen_messages.get(user_id)
    if message_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return
        except BadRequest as error:
            if "Message is not modified" in str(error):
                return
        except TelegramError:
            pass
    message = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )
    screen_messages[user_id] = message.message_id


async def edit_screen(query, text, reply_markup=None):
    user_id = query.from_user.id
    chat_id = query.message.chat_id
    try:
        await query.edit_message_text(
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        screen_messages[user_id] = query.message.message_id
    except BadRequest as error:
        if "Message is not modified" in str(error):
            screen_messages[user_id] = query.message.message_id
            return
        await send_or_edit_screen(query.get_bot(), chat_id, user_id, text, reply_markup)


async def cleanup_user_message(update):
    if not update.message:
        return
    if get_setting("delete_user_messages", "1") != "1":
        return
    await safe_delete(update.get_bot(), update.effective_chat.id, update.message.message_id)


# ============================================================
# CUSTOMER KEYBOARDS / SCREENS
# ============================================================


def main_keyboard(user):
    rows = [
        [InlineKeyboardButton(get_button("exchange", "💱 Exchange"), callback_data="exchange")],
        [InlineKeyboardButton(get_button("how", "ℹ️ How It Works"), callback_data="how")],
    ]
    if is_admin(user) and get_setting("show_admin_button", "1") == "1":
        rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def category_keyboard(parent_id=None, include_back=True):
    categories = get_categories(parent_id, True)
    rows = [
        [InlineKeyboardButton(c["button_text"], callback_data=f"cat:{c['id']}")]
        for c in categories
    ]
    if include_back:
        rows.append([back_button("home") if parent_id is None else back_button(f"catback:{parent_id}")])
    return kb(rows)


def currency_keyboard(category_id):
    rows = [
        [InlineKeyboardButton(c["button_text"], callback_data=f"cur:{category_id}:{c['id']}")]
        for c in get_currencies(True)
    ]
    rows.append([back_button("exchange")])
    return kb(rows)


def product_keyboard(category_id, currency_id):
    products = get_products(category_id, True)
    buttons = [
        InlineKeyboardButton(p["button_text"], callback_data=f"prod:{currency_id}:{p['id']}")
        for p in products
        if not p["is_custom"]
    ]
    rows = []
    row = []
    for button in buttons:
        row.append(button)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    custom_products = [p for p in products if p["is_custom"]]
    for p in custom_products:
        rows.append([InlineKeyboardButton(p["button_text"], callback_data=f"prod:{currency_id}:{p['id']}")])
    rows.append([back_button(f"curback:{category_id}")])
    return kb(rows)


def cancel_keyboard():
    return kb([[InlineKeyboardButton(get_button("cancel", "❌ Cancel"), callback_data="home")]])


def order_end_keyboard():
    return kb([
        [InlineKeyboardButton(get_button("new_order", "💱 New Order"), callback_data="exchange")],
        [InlineKeyboardButton(get_button("home", "🏠 Main Menu"), callback_data="home")],
    ])


async def show_home_query(query):
    sessions.pop(query.from_user.id, None)
    await edit_screen(query, render_text("welcome"), main_keyboard(query.from_user))


async def show_exchange(query):
    categories = get_categories(None, True)
    if not categories:
        await edit_screen(query, render_text("no_categories"), kb([[back_button("home")]]))
        return
    await edit_screen(query, render_text("category"), category_keyboard(None, True))


async def show_category(query, category_id):
    category = get_category(category_id)
    if not category or not category["enabled"]:
        await query.answer("This category is unavailable.", show_alert=True)
        return

    children = get_category_children(category_id, True)
    products = get_products(category_id, True)

    if children:
        rows = [[InlineKeyboardButton(c["button_text"], callback_data=f"cat:{c['id']}")] for c in children]
        if products:
            rows.append([InlineKeyboardButton("📦 Products", callback_data=f"catprod:{category_id}")])
        rows.append([back_button("exchange") if category["parent_id"] is None else back_button(f"catback:{category['parent_id']}")])
        text = category["description"] or render_text("category")
        await edit_screen(query, f"🗂️ <b>{esc(category['name'])}</b>\n\n{esc(text)}", kb(rows))
        return

    # No children: proceed to currency selection for this category.
    session = sessions.setdefault(query.from_user.id, {})
    session["category_id"] = category_id
    session.pop("currency_id", None)
    await edit_screen(
        query,
        render_text("currency"),
        currency_keyboard(category_id),
    )


async def show_category_products(query, category_id, currency_id=None):
    category = get_category(category_id)
    if not category:
        await query.answer("Category not found.", show_alert=True)
        return
    if currency_id is None:
        session = sessions.get(query.from_user.id, {})
        currency_id = session.get("currency_id")
    products = get_products(category_id, True)
    if not products:
        await edit_screen(query, render_text("no_products"), kb([[back_button("exchange")]]))
        return
    session = sessions.setdefault(query.from_user.id, {})
    session["category_id"] = category_id
    if currency_id:
        session["currency_id"] = currency_id
    await edit_screen(
        query,
        render_text("product", category=category["name"]),
        product_keyboard(category_id, currency_id),
    )


async def show_how(query):
    await edit_screen(
        query,
        render_text("how"),
        kb([
            [InlineKeyboardButton(get_button("exchange", "💱 Exchange"), callback_data="exchange")],
            [back_button("home")],
        ]),
    )


# ============================================================
# ADMIN PANEL KEYBOARDS / SCREENS
# ============================================================


def admin_keyboard():
    return kb([
        [InlineKeyboardButton(get_button("categories", "🗂️ Categories"), callback_data="a:cats")],
        [InlineKeyboardButton(get_button("products", "📦 Products"), callback_data="a:products")],
        [InlineKeyboardButton(get_button("currencies", "💱 Currencies"), callback_data="a:currencies"),
         InlineKeyboardButton(get_button("prices", "💰 Prices"), callback_data="a:prices")],
        [InlineKeyboardButton(get_button("texts", "📝 Texts"), callback_data="a:texts"),
         InlineKeyboardButton(get_button("buttons", "🔘 Buttons"), callback_data="a:buttons")],
        [InlineKeyboardButton(get_button("emojis", "✨ Custom Emojis"), callback_data="a:emojis")],
        [InlineKeyboardButton(get_button("settings", "🏪 Shop Settings"), callback_data="a:settings"),
         InlineKeyboardButton(get_button("admins", "👮 Admins"), callback_data="a:admins")],
        [InlineKeyboardButton(get_button("orders", "📋 Orders"), callback_data="a:orders")],
        [InlineKeyboardButton(get_button("home", "🏠 Main Menu"), callback_data="home")],
    ])


def admin_categories_keyboard(parent_id=None):
    children = get_categories(parent_id, False)
    rows = [[InlineKeyboardButton(
        f"{'🟢' if c['enabled'] else '🔴'} {c['button_text']}",
        callback_data=f"acat:{c['id']}"
    )] for c in children]
    rows.append([InlineKeyboardButton("➕ Add Category Here", callback_data=f"acat_add:{parent_id if parent_id is not None else 'root'}")])
    if parent_id is None:
        rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    else:
        parent = get_category(parent_id)
        back = parent["parent_id"] if parent else None
        rows.append([InlineKeyboardButton("↩️ Parent Category", callback_data=f"acats:{back if back is not None else 'root'}")])
    return kb(rows)


def category_edit_keyboard(category_id):
    category = get_category(category_id)
    parent = category["parent_id"] if category else None
    return kb([
        [InlineKeyboardButton("🔤 Rename", callback_data=f"cedit_name:{category_id}"),
         InlineKeyboardButton("🔘 Button", callback_data=f"cedit_button:{category_id}")],
        [InlineKeyboardButton("📝 Description", callback_data=f"cedit_desc:{category_id}"),
         InlineKeyboardButton("📁 Add Subcategory", callback_data=f"acat_add:{category_id}")],
        [InlineKeyboardButton("↪️ Move", callback_data=f"cedit_move:{category_id}"),
         InlineKeyboardButton("↕️ Reorder", callback_data=f"cedit_order:{category_id}")],
        [InlineKeyboardButton("🟢 / 🔴 Enable", callback_data=f"ctoggle:{category_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"cdelete:{category_id}")],
        [InlineKeyboardButton("📂 Open", callback_data=f"acats:{category_id}")],
        [InlineKeyboardButton("↩️ Categories", callback_data=f"acats:{parent if parent is not None else 'root'}")],
    ])


def admin_products_keyboard():
    rows = [[InlineKeyboardButton("➕ Add Product", callback_data="apickcat")]]
    for p in get_all_products():
        cat = get_category(p["category_id"])
        location = cat["name"] if cat else "No category"
        status = "🟢" if p["enabled"] else "🔴"
        custom = " ✏️" if p["is_custom"] else ""
        rows.append([InlineKeyboardButton(
            f"{status} {p['button_text']} · {location}{custom}",
            callback_data=f"a_product:{p['id']}"
        )])
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def product_edit_keyboard(product_id):
    return kb([
        [InlineKeyboardButton("🔤 Name", callback_data=f"p_name:{product_id}"),
         InlineKeyboardButton("🔘 Button", callback_data=f"p_button:{product_id}")],
        [InlineKeyboardButton("🔢 Amount", callback_data=f"p_amount:{product_id}"),
         InlineKeyboardButton("💰 Prices", callback_data=f"p_prices:{product_id}")],
        [InlineKeyboardButton("📝 Description", callback_data=f"p_desc:{product_id}"),
         InlineKeyboardButton("📂 Move", callback_data=f"p_move:{product_id}")],
        [InlineKeyboardButton("🟢 / 🔴 Enable", callback_data=f"ptoggle:{product_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"pdelete:{product_id}")],
        [InlineKeyboardButton("↕️ Reorder", callback_data=f"p_order:{product_id}")],
        [InlineKeyboardButton("↩️ Products", callback_data="a:products")],
    ])


def admin_currency_keyboard():
    rows = [[InlineKeyboardButton("➕ Add Currency", callback_data="curadd")]]
    for c in get_currencies(False):
        rows.append([InlineKeyboardButton(
            f"{'🟢' if c['enabled'] else '🔴'} {c['button_text']}",
            callback_data=f"cedit:{c['id']}"
        )])
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def currency_edit_keyboard(currency_id):
    return kb([
        [InlineKeyboardButton("🔤 Name", callback_data=f"c_name:{currency_id}"),
         InlineKeyboardButton("🔘 Button", callback_data=f"c_button:{currency_id}")],
        [InlineKeyboardButton("🟢 / 🔴 Enable", callback_data=f"ctogglecur:{currency_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"cdeletecur:{currency_id}")],
        [InlineKeyboardButton("↕️ Reorder", callback_data=f"corder:{currency_id}")],
        [InlineKeyboardButton("↩️ Currencies", callback_data="a:currencies")],
    ])


def admin_prices_keyboard():
    rows = []
    for c in get_currencies(False):
        rows.append([InlineKeyboardButton(
            f"💰 {c['name']}", callback_data=f"pricecur:{c['id']}")])
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def admin_texts_keyboard():
    rows = [[InlineKeyboardButton(text_label(k), callback_data=f"text:{k}")] for k in TEXT_LABELS]
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def admin_buttons_keyboard():
    rows = [[InlineKeyboardButton(
        f"{BUTTON_LABELS.get(k,k)}: {get_button(k)}",
        callback_data=f"button:{k}")
    ] for k in DEFAULT_BUTTONS]
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def settings_keyboard():
    return kb([
        [InlineKeyboardButton("🏷️ Shop Name", callback_data="set:shop_name")],
        [InlineKeyboardButton("👤 Support Username", callback_data="set:admin_username")],
        [InlineKeyboardButton("🆔 Order Recipient Chat ID", callback_data="set:recipient")],
        [InlineKeyboardButton("🔢 Max Custom Amount", callback_data="set:max_amount")],
        [InlineKeyboardButton(
            f"🧹 User message cleanup: {'ON' if get_setting('delete_user_messages','1')=='1' else 'OFF'}",
            callback_data="toggle:cleanup",
        )],
        [InlineKeyboardButton(
            f"⚙️ Admin button in shop: {'ON' if get_setting('show_admin_button','1')=='1' else 'OFF'}",
            callback_data="toggle:admin_button",
        )],
        [InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")],
    ])


def admin_orders_keyboard():
    rows = []
    for o in get_orders(30):
        icon = "⏳" if o["status"] == "awaiting_confirmation" else "✅" if o["status"] == "confirmed" else "❌"
        rows.append([InlineKeyboardButton(
            f"{icon} {o['order_number']} · {o['roblox_username']}",
            callback_data=f"order:{o['order_number']}")])
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def admin_emoji_keyboard():
    rows = [[InlineKeyboardButton("➕ Add Custom Emoji", callback_data="emoji_add")]]
    for e in get_emojis(False):
        status = "🟢" if e["enabled"] else "🔴"
        rows.append([InlineKeyboardButton(
            f"{status} {e['fallback']} {e['name']}",
            callback_data=f"emoji:{e['id']}")])
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


def emoji_edit_keyboard(emoji_id):
    return kb([
        [InlineKeyboardButton("🔤 Rename", callback_data=f"emoji_name:{emoji_id}")],
        [InlineKeyboardButton("🟢 / 🔴 Enable", callback_data=f"emoji_toggle:{emoji_id}"),
         InlineKeyboardButton("🗑️ Delete", callback_data=f"emoji_delete:{emoji_id}")],
        [InlineKeyboardButton("↩️ Emojis", callback_data="a:emojis")],
    ])


def admins_keyboard():
    rows = [[InlineKeyboardButton("➕ Add Admin", callback_data="adminadd")]]
    for a in get_admins():
        rows.append([InlineKeyboardButton(
            f"👮 {a['label'] or a['telegram_id']} · {a['telegram_id']}",
            callback_data=f"adminremove:{a['telegram_id']}")])
    rows.append([InlineKeyboardButton(get_button("admin", "⚙️ Admin Panel"), callback_data="admin")])
    return kb(rows)


# ============================================================
# ADMIN SCREEN RENDERERS
# ============================================================


async def show_admin(query):
    await edit_screen(
        query,
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "Your entire shop can be managed from Telegram.\n"
        "Changes are saved immediately.",
        admin_keyboard(),
    )


async def show_admin_categories(query, parent_id=None):
    if parent_id == "root":
        parent_id = None
    title = "ROOT CATEGORIES" if parent_id is None else current_category_path(parent_id)
    children = get_categories(parent_id, False)
    body = (
        "Tap a category to edit it or open it.\n"
        "Categories can contain unlimited subcategories.\n\n"
        f"Current location: <b>{esc(title)}</b>"
    )
    if not children:
        body += "\n\nNo categories here yet."
    await edit_screen(query, "🗂️ <b>CATEGORIES</b>\n\n" + body, admin_categories_keyboard(parent_id))


async def show_category_edit(query, category_id):
    c = get_category(category_id)
    if not c:
        await query.answer("Category not found.", show_alert=True)
        return
    children = get_category_children(category_id, False)
    products = get_products(category_id, False)
    await edit_screen(
        query,
        "🗂️ <b>EDIT CATEGORY</b>\n\n"
        f"🏷️ Name: <b>{esc(c['name'])}</b>\n"
        f"🔘 Button: <b>{esc(c['button_text'])}</b>\n"
        f"📝 Description: <b>{esc(c['description'] or '—')}</b>\n"
        f"📂 Subcategories: <b>{len(children)}</b>\n"
        f"📦 Products: <b>{len(products)}</b>\n"
        f"📌 Status: <b>{'Enabled' if c['enabled'] else 'Disabled'}</b>",
        category_edit_keyboard(category_id),
    )


async def show_admin_products(query):
    products = get_all_products()
    summary = "\n".join(
        f"{'🟢' if p['enabled'] else '🔴'} {esc(p['button_text'])} — {p['amount']:,} Robux"
        for p in products[:20]
    ) or "No products yet."
    await edit_screen(query, "📦 <b>PRODUCTS</b>\n\nTap a product to edit it.\n\n" + summary, admin_products_keyboard())


async def show_product_edit(query, product_id):
    p = get_product(product_id)
    if not p:
        await query.answer("Product not found.", show_alert=True)
        return
    c = get_category(p["category_id"])
    location = current_category_path(c["id"]) if c else "No category"
    kind = "Custom amount" if p["is_custom"] else f"{p['amount']:,} Robux"
    await edit_screen(
        query,
        "📦 <b>EDIT PRODUCT</b>\n\n"
        f"🏷️ Name: <b>{esc(p['name'])}</b>\n"
        f"🔘 Button: <b>{esc(p['button_text'])}</b>\n"
        f"🔢 Type: <b>{kind}</b>\n"
        f"📝 Description: <b>{esc(p['description'] or '—')}</b>\n"
        f"📂 Category: <b>{esc(location)}</b>\n"
        f"📌 Status: <b>{'Enabled' if p['enabled'] else 'Disabled'}</b>",
        product_edit_keyboard(product_id),
    )


async def show_admin_currencies(query):
    await edit_screen(
        query,
        "💱 <b>CURRENCIES</b>\n\n"
        "Add, rename, reorder, enable/disable or delete any payment method.",
        admin_currency_keyboard(),
    )


async def show_currency_edit(query, currency_id):
    c = get_currency(currency_id)
    if not c:
        await query.answer("Currency not found.", show_alert=True)
        return
    await edit_screen(
        query,
        "💱 <b>EDIT CURRENCY</b>\n\n"
        f"🏷️ Name: <b>{esc(c['name'])}</b>\n"
        f"🔘 Button: <b>{esc(c['button_text'])}</b>\n"
        f"📌 Status: <b>{'Enabled' if c['enabled'] else 'Disabled'}</b>",
        currency_edit_keyboard(currency_id),
    )


async def show_price_currency(query, currency_id):
    c = get_currency(currency_id)
    if not c:
        await query.answer("Currency not found.", show_alert=True)
        return
    rows = []
    for p in get_all_products():
        price = get_price(currency_id, p["id"])
        rows.append([InlineKeyboardButton(
            f"{p['button_text']} → {price}",
            callback_data=f"setprice:{currency_id}:{p['id']}")])
    rows.append([InlineKeyboardButton(
        f"✏️ Custom Amount Price → {get_custom_price(currency_id)}",
        callback_data=f"setcustomprice:{currency_id}")])
    rows.append([InlineKeyboardButton("↩️ Prices", callback_data="a:prices")])
    await edit_screen(query, f"💰 <b>{esc(c['name'])} PRICES</b>\n\nTap a price to change it.", kb(rows))


async def show_texts(query):
    await edit_screen(query, "📝 <b>TEXT EDITOR</b>\n\nTap any message to replace it. HTML formatting is supported.\n\nCustom emoji syntax: <code>{{emoji:name}}</code>", admin_texts_keyboard())


async def show_buttons(query):
    await edit_screen(query, "🔘 <b>BUTTON EDITOR</b>\n\nTap any button label to replace it.", admin_buttons_keyboard())


async def show_settings(query):
    recipient = get_setting("order_recipient_chat_id", "") or "Not configured"
    await edit_screen(
        query,
        "🏪 <b>SHOP SETTINGS</b>\n\n"
        f"🏷️ Shop name: <b>{esc(get_setting('shop_name'))}</b>\n"
        f"👤 Support username: <b>{esc(get_setting('admin_username'))}</b>\n"
        f"🆔 Order recipient: <code>{esc(recipient)}</code>\n"
        f"🔢 Max custom amount: <b>{esc(get_setting('max_custom_amount'))}</b>\n"
        f"🧹 Delete user messages: <b>{'ON' if get_setting('delete_user_messages','1')=='1' else 'OFF'}</b>\n"
        f"⚙️ Admin button in shop: <b>{'ON' if get_setting('show_admin_button','1')=='1' else 'OFF'}</b>",
        settings_keyboard(),
    )


async def show_orders(query):
    await edit_screen(query, "📋 <b>RECENT ORDERS</b>\n\nTap an order to view details and change its status.", admin_orders_keyboard())


async def show_emojis(query):
    await edit_screen(
        query,
        "✨ <b>CUSTOM EMOJIS</b>\n\n"
        "Add a Telegram custom emoji by sending it when prompted.\n\n"
        "Use saved emojis inside any editable text with:\n"
        "<code>{{emoji:name}}</code>",
        admin_emoji_keyboard(),
    )


async def show_emoji_edit(query, emoji_id):
    e = get_emoji(emoji_id)
    if not e:
        await query.answer("Emoji not found.", show_alert=True)
        return
    await edit_screen(
        query,
        "✨ <b>EDIT CUSTOM EMOJI</b>\n\n"
        f"🏷️ Name: <b>{esc(e['name'])}</b>\n"
        f"👀 Preview: {e['fallback']}\n"
        f"🆔 Telegram emoji ID: <code>{esc(e['emoji_id'])}</code>\n"
        f"📌 Status: <b>{'Enabled' if e['enabled'] else 'Disabled'}</b>\n\n"
        f"Token: <code>{{{{emoji:{esc(e['name'])}}}}}</code>",
        emoji_edit_keyboard(emoji_id),
    )


async def show_admins(query):
    await edit_screen(
        query,
        "👮 <b>ADMINS</b>\n\n"
        "The bootstrap admin from ADMIN_CHAT_ID cannot be removed from this panel.",
        admins_keyboard(),
    )


# ============================================================
# ADMIN INPUT STATE
# ============================================================


def start_input(user_id, action, **data):
    sessions[user_id] = {"action": action, **data}


async def ask_input(query, action, prompt, **data):
    start_input(query.from_user.id, action, **data)
    await edit_screen(query, prompt, cancel_keyboard())


# ============================================================
# CUSTOMER ORDER CREATION
# ============================================================


def create_order(user, session, roblox_username):
    category = get_category(session["category_id"])
    currency = get_currency(session["currency_id"])
    product = get_product(session["product_id"])
    if not category or not currency or not product:
        raise ValueError("Missing order item")

    amount = int(session["amount"])
    price = session["price"]
    conn = db()
    cursor = conn.execute(
        """
        INSERT INTO orders(
            order_number, telegram_id, telegram_username, telegram_name,
            category, currency, product, robux_amount, price,
            roblox_username, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_confirmation', ?)
        """,
        (
            "TEMP",
            user.id,
            user.username,
            user.full_name,
            category["name"],
            currency["name"],
            product["name"],
            amount,
            price,
            roblox_username,
            now_string(),
        ),
    )
    order_id = cursor.lastrowid
    order_number = f"#{order_id:04d}"
    conn.execute("UPDATE orders SET order_number=? WHERE id=?", (order_number, order_id))
    conn.commit()
    conn.close()
    return get_order(order_number)


# ============================================================
# /START / ADMIN COMMANDS
# ============================================================


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    sessions.pop(user_id, None)
    await cleanup_user_message(update)
    await send_or_edit_screen(
        update.get_bot(),
        update.effective_chat.id,
        user_id,
        render_text("welcome"),
        main_keyboard(update.effective_user),
    )


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await cleanup_user_message(update)
        await send_or_edit_screen(
            update.get_bot(), update.effective_chat.id, update.effective_user.id,
            "⛔ <b>ACCESS DENIED</b>",
            kb([[back_button("home")]]),
        )
        return
    sessions.pop(update.effective_user.id, None)
    await cleanup_user_message(update)
    await send_or_edit_screen(
        update.get_bot(), update.effective_chat.id, update.effective_user.id,
        "⚙️ <b>ADMIN PANEL</b>\n\nEverything is managed directly from Telegram.",
        admin_keyboard(),
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    user = query.from_user
    user_id = user.id

    # Customer navigation.
    if data == "noop":
        return
    if data == "home":
        await show_home_query(query)
        return
    if data == "exchange":
        sessions.pop(user_id, None)
        await show_exchange(query)
        return
    if data == "how":
        await show_how(query)
        return
    if data.startswith("cat:"):
        await show_category(query, int(data.split(":",1)[1]))
        return
    if data.startswith("catback:"):
        parent = data.split(":",1)[1]
        await show_category(query, int(parent))
        return
    if data.startswith("catprod:"):
        cid = int(data.split(":",1)[1])
        session = sessions.setdefault(user_id, {})
        if not session.get("currency_id"):
            # Go to currency selection for this category.
            category = get_category(cid)
            if category:
                session["category_id"] = cid
                await edit_screen(query, render_text("currency"), currency_keyboard(cid))
            return
        await show_category_products(query, cid)
        return
    if data.startswith("cur:"):
        _, category_id, currency_id = data.split(":")
        category_id = int(category_id); currency_id = int(currency_id)
        currency = get_currency(currency_id)
        category = get_category(category_id)
        if not currency or not currency["enabled"] or not category or not category["enabled"]:
            await query.answer("This option is unavailable.", show_alert=True)
            return
        sessions[user_id] = {"category_id": category_id, "currency_id": currency_id, "waiting": "product"}
        await show_category_products(query, category_id, currency_id)
        return
    if data.startswith("curback:"):
        category_id = int(data.split(":",1)[1])
        await show_category(query, category_id)
        return
    if data.startswith("prod:"):
        _, currency_id, product_id = data.split(":")
        currency_id = int(currency_id); product_id = int(product_id)
        session = sessions.get(user_id)
        product = get_product(product_id)
        if not session or not product or not product["enabled"]:
            await query.answer("Please start a new order.", show_alert=True)
            return
        if product["category_id"] != session.get("category_id"):
            await query.answer("This product is not in the current category.", show_alert=True)
            return
        session["currency_id"] = currency_id
        session["product_id"] = product_id
        session["price"] = get_price(currency_id, product_id)
        if product["is_custom"]:
            session["waiting"] = "custom_amount"
            await edit_screen(query, render_text("custom"), cancel_keyboard())
        else:
            session["amount"] = product["amount"]
            session["waiting"] = "username"
            await edit_screen(query, render_text("username"), cancel_keyboard())
        return

    # Everything below is admin-only.
    admin_prefixes = (
        "admin", "a:", "acat", "cedit", "cdelete", "ctoggle", "p_", "ptoggle", "pdelete",
        "apickcat", "curadd", "cedit:", "c_name", "c_button", "ctogglecur", "cdeletecur", "corder",
        "pricecur", "setprice", "setcustomprice", "text:", "button:", "set:", "toggle:", "emoji", "order:",
        "orderstatus:", "adminadd", "adminremove", "acats", "category", "move_")
    if data.startswith(admin_prefixes) and not is_admin(user):
        await query.answer("⛔ Access denied.", show_alert=True)
        return

    if data == "admin":
        sessions.pop(user_id, None)
        await show_admin(query)
        return

    # ---- Categories ----
    if data == "a:cats":
        await show_admin_categories(query, None)
        return
    if data.startswith("acats:"):
        value = data.split(":",1)[1]
        await show_admin_categories(query, None if value == "root" else int(value))
        return
    if data.startswith("acat:"):
        await show_category_edit(query, int(data.split(":",1)[1]))
        return
    if data.startswith("acat_add:"):
        raw = data.split(":",1)[1]
        parent_id = None if raw == "root" else int(raw)
        await ask_input(query, "add_category", "➕ <b>ADD CATEGORY</b>\n\nSend the category name.", parent_id=parent_id)
        return
    if data.startswith("cedit_name:"):
        await ask_input(query, "rename_category", "🔤 <b>RENAME CATEGORY</b>\n\nSend the new category name.", category_id=int(data.split(":",1)[1]))
        return
    if data.startswith("cedit_button:"):
        await ask_input(query, "category_button", "🔘 <b>CATEGORY BUTTON</b>\n\nSend the exact button text.", category_id=int(data.split(":",1)[1]))
        return
    if data.startswith("cedit_desc:"):
        await ask_input(query, "category_desc", "📝 <b>CATEGORY DESCRIPTION</b>\n\nSend the description, or <code>-</code> for none.", category_id=int(data.split(":",1)[1]))
        return
    if data.startswith("cedit_move:"):
        category_id = int(data.split(":",1)[1])
        rows = []
        for c in get_all_categories(False):
            if c["id"] == category_id or would_create_cycle(category_id, c["id"]):
                continue
            rows.append([InlineKeyboardButton(f"📂 {c['name']}", callback_data=f"cmove:{category_id}:{c['id']}")])
        rows.append([InlineKeyboardButton("🌳 Root", callback_data=f"cmove:{category_id}:root")])
        rows.append([InlineKeyboardButton("↩️ Category", callback_data=f"acat:{category_id}")])
        await edit_screen(query, "↪️ <b>MOVE CATEGORY</b>\n\nChoose its new parent.", kb(rows))
        return
    if data.startswith("cmove:"):
        _, category_id, parent = data.split(":")
        category_id = int(category_id)
        parent_id = None if parent == "root" else int(parent)
        if would_create_cycle(category_id, parent_id):
            await query.answer("That move would create a category loop.", show_alert=True)
            return
        conn = db()
        conn.execute("UPDATE categories SET parent_id=? WHERE id=?", (parent_id, category_id))
        conn.commit(); conn.close()
        await show_category_edit(query, category_id)
        return
    if data.startswith("ctoggle:"):
        cid = int(data.split(":",1)[1])
        conn = db(); conn.execute("UPDATE categories SET enabled=CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?", (cid,)); conn.commit(); conn.close()
        await show_category_edit(query, cid)
        return
    if data.startswith("cdelete:"):
        cid = int(data.split(":",1)[1])
        children = get_category_children(cid, False)
        products = get_products(cid, False)
        if children or products:
            await query.answer("Delete or move its subcategories and products first.", show_alert=True)
            return
        category = get_category(cid)
        parent = category["parent_id"] if category else None
        conn = db(); conn.execute("DELETE FROM categories WHERE id=?", (cid,)); conn.commit(); conn.close()
        await show_admin_categories(query, parent)
        return

    # ---- Products ----
    if data == "a:products":
        await show_admin_products(query)
        return
    if data == "apickcat":
        rows = [[InlineKeyboardButton(f"📂 {c['name']}", callback_data=f"paddcat:{c['id']}")] for c in get_all_categories(False)]
        rows.append([InlineKeyboardButton("↩️ Products", callback_data="a:products")])
        await edit_screen(query, "➕ <b>ADD PRODUCT</b>\n\nChoose the category/subcategory where it belongs.", kb(rows))
        return
    if data.startswith("paddcat:"):
        await ask_input(query, "add_product_name", "➕ <b>ADD PRODUCT</b>\n\nSend the product name.", category_id=int(data.split(":",1)[1]))
        return
    if data.startswith("a_product:"):
        await show_product_edit(query, int(data.split(":",1)[1]))
        return
    if data.startswith("p_name:"):
        await ask_input(query, "product_name", "🔤 <b>PRODUCT NAME</b>\n\nSend the new product name.", product_id=int(data.split(":",1)[1]))
        return
    if data.startswith("p_button:"):
        await ask_input(query, "product_button", "🔘 <b>PRODUCT BUTTON</b>\n\nSend the exact button text.", product_id=int(data.split(":",1)[1]))
        return
    if data.startswith("p_amount:"):
        await ask_input(query, "product_amount", "🔢 <b>ROBux AMOUNT</b>\n\nSend a positive whole number.\nSend <code>custom</code> to make it a custom-amount product.", product_id=int(data.split(":",1)[1]))
        return
    if data.startswith("p_desc:"):
        await ask_input(query, "product_desc", "📝 <b>PRODUCT DESCRIPTION</b>\n\nSend a description, or <code>-</code> for none.", product_id=int(data.split(":",1)[1]))
        return
    if data.startswith("p_move:"):
        pid = int(data.split(":",1)[1])
        rows = [[InlineKeyboardButton(f"📂 {c['name']}", callback_data=f"pmove:{pid}:{c['id']}")] for c in get_all_categories(False)]
        rows.append([InlineKeyboardButton("↩️ Product", callback_data=f"a_product:{pid}")])
        await edit_screen(query, "📂 <b>MOVE PRODUCT</b>\n\nChoose its new category or subcategory.", kb(rows))
        return
    if data.startswith("pmove:"):
        _, pid, cid = data.split(":")
        conn = db(); conn.execute("UPDATE products SET category_id=? WHERE id=?", (int(cid), int(pid))); conn.commit(); conn.close()
        await show_product_edit(query, int(pid))
        return
    if data.startswith("ptoggle:"):
        pid = int(data.split(":",1)[1])
        conn = db(); conn.execute("UPDATE products SET enabled=CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?", (pid,)); conn.commit(); conn.close()
        await show_product_edit(query, pid)
        return
    if data.startswith("pdelete:"):
        pid = int(data.split(":",1)[1])
        conn = db(); conn.execute("DELETE FROM prices WHERE product_id=?", (pid,)); conn.execute("DELETE FROM products WHERE id=?", (pid,)); conn.commit(); conn.close()
        await show_admin_products(query)
        return
    if data.startswith("p_prices:"):
        pid = int(data.split(":",1)[1])
        p = get_product(pid)
        if not p:
            await query.answer("Product not found.", show_alert=True); return
        rows = []
        for c in get_currencies(False):
            price = get_custom_price(c["id"]) if p["is_custom"] else get_price(c["id"], pid)
            rows.append([InlineKeyboardButton(f"{c['name']} → {price}", callback_data=f"setprice:{c['id']}:{pid}")])
        rows.append([InlineKeyboardButton("↩️ Product", callback_data=f"a_product:{pid}")])
        await edit_screen(query, f"💰 <b>PRICES — {esc(p['button_text'])}</b>\n\nChoose a currency.", kb(rows))
        return

    # ---- Currencies ----
    if data == "a:currencies":
        await show_admin_currencies(query); return
    if data == "curadd":
        await ask_input(query, "add_currency", "➕ <b>ADD CURRENCY</b>\n\nSend the currency/payment method name.")
        return
    if data.startswith("cedit:"):
        await show_currency_edit(query, int(data.split(":",1)[1])); return
    if data.startswith("c_name:"):
        await ask_input(query, "currency_name", "🔤 <b>CURRENCY NAME</b>\n\nSend the new name.", currency_id=int(data.split(":",1)[1])); return
    if data.startswith("c_button:"):
        await ask_input(query, "currency_button", "🔘 <b>CURRENCY BUTTON</b>\n\nSend the exact button text.", currency_id=int(data.split(":",1)[1])); return
    if data.startswith("ctogglecur:"):
        cid = int(data.split(":",1)[1])
        conn = db(); conn.execute("UPDATE currencies SET enabled=CASE WHEN enabled=1 THEN 0 ELSE 1 END WHERE id=?", (cid,)); conn.commit(); conn.close()
        await show_currency_edit(query, cid); return
    if data.startswith("cdeletecur:"):
        cid = int(data.split(":",1)[1])
        if len(get_currencies(False)) <= 1:
            await query.answer("Keep at least one currency.", show_alert=True); return
        conn = db(); conn.execute("DELETE FROM prices WHERE currency_id=?", (cid,)); conn.execute("DELETE FROM custom_prices WHERE currency_id=?", (cid,)); conn.execute("DELETE FROM currencies WHERE id=?", (cid,)); conn.commit(); conn.close()
        await show_admin_currencies(query); return

    # ---- Prices ----
    if data == "a:prices":
        await edit_screen(query, "💰 <b>PRICE MANAGEMENT</b>\n\nChoose a currency, then choose a product price.", admin_prices_keyboard()); return
    if data.startswith("pricecur:"):
        await show_price_currency(query, int(data.split(":",1)[1])); return
    if data.startswith("setprice:"):
        _, cid, pid = data.split(":")
        await ask_input(query, "set_price", "💰 <b>SET PRICE</b>\n\nSend the new price exactly as it should appear.\n\nExamples: <code>50</code> · <code>50 ⭐</code> · <code>NA</code>", currency_id=int(cid), product_id=int(pid)); return
    if data.startswith("setcustomprice:"):
        await ask_input(query, "set_custom_price", "✏️ <b>CUSTOM AMOUNT PRICE</b>\n\nSend the price text.\n\nExample: <code>NA</code>", currency_id=int(data.split(":",1)[1])); return

    # ---- Texts / Buttons / Settings ----
    if data == "a:texts":
        await show_texts(query); return
    if data.startswith("text:"):
        key = data.split(":",1)[1]
        await ask_input(
            query,
            "edit_text",
            "📝 <b>EDIT TEXT</b>\n\n"
            f"<b>{esc(text_label(key))}</b>\n\n"
            f"Current:\n<code>{esc(get_text(key))}</code>\n\n"
            "HTML is supported.\n"
            "Custom emoji example: <code>{{emoji:smile}}</code>\n"
            "Dynamic placeholders are available for templates.",
            key=key,
        ); return
    if data == "a:buttons":
        await show_buttons(query); return
    if data.startswith("button:"):
        key = data.split(":",1)[1]
        await ask_input(query, "edit_button", "🔘 <b>EDIT BUTTON</b>\n\n" f"Current:\n<b>{esc(get_button(key))}</b>\n\nSend the new button text.", key=key); return
    if data == "a:settings":
        await show_settings(query); return
    if data == "toggle:cleanup":
        set_setting("delete_user_messages", "0" if get_setting("delete_user_messages","1") == "1" else "1")
        await show_settings(query); return
    if data == "toggle:admin_button":
        set_setting("show_admin_button", "0" if get_setting("show_admin_button","1") == "1" else "1")
        await show_settings(query); return
    if data.startswith("set:"):
        key = data.split(":",1)[1]
        prompts = {
            "shop_name": "🏷️ <b>SHOP NAME</b>\n\nSend the new shop name.",
            "admin_username": "👤 <b>SUPPORT USERNAME</b>\n\nSend the username shown to customers. Example: <code>@yourusername</code>",
            "recipient": "🆔 <b>ORDER RECIPIENT CHAT ID</b>\n\nSend the numeric Telegram chat ID that receives new orders.",
            "max_amount": "🔢 <b>MAX CUSTOM AMOUNT</b>\n\nSend the maximum allowed custom Robux amount.",
        }
        await ask_input(query, f"setting:{key}", prompts[key]); return

    # ---- Custom emoji manager ----
    if data == "a:emojis":
        await show_emojis(query); return
    if data == "emoji_add":
        await ask_input(query, "add_emoji_name", "✨ <b>ADD CUSTOM EMOJI</b>\n\nFirst send a short name for this emoji.\n\nExample: <code>smile</code>"); return
    if data.startswith("emoji:"):
        await show_emoji_edit(query, int(data.split(":",1)[1])); return
    if data.startswith("emoji_name:"):
        await ask_input(query, "emoji_rename", "🔤 <b>RENAME CUSTOM EMOJI</b>\n\nSend the new token name. Letters, numbers, _ and - only.", emoji_id=int(data.split(":",1)[1])); return
    if data.startswith("emoji_toggle:"):
        eid = int(data.split(":",1)[1]); toggle_emoji(eid); await show_emoji_edit(query, eid); return
    if data.startswith("emoji_delete:"):
        eid = int(data.split(":",1)[1]); delete_emoji(eid); await show_emojis(query); return

    # ---- Admins ----
    if data == "a:admins":
        await show_admins(query); return
    if data == "adminadd":
        await ask_input(query, "add_admin", "➕ <b>ADD ADMIN</b>\n\nSend the admin's numeric Telegram ID."); return
    if data.startswith("adminremove:"):
        target = int(data.split(":",1)[1])
        if BOOTSTRAP_ADMIN_CHAT_ID:
            try:
                if target == int(BOOTSTRAP_ADMIN_CHAT_ID):
                    await query.answer("The bootstrap admin cannot be removed.", show_alert=True); return
            except ValueError:
                pass
        remove_admin(target); await show_admins(query); return

    # ---- Orders ----
    if data == "a:orders":
        await show_orders(query); return
    if data.startswith("order:"):
        order_number = data.split(":",1)[1]
        o = get_order(order_number)
        if not o:
            await query.answer("Order not found.", show_alert=True); return
        status = esc(o["status"])
        await edit_screen(
            query,
            "🔔 <b>ORDER DETAILS</b>\n\n"
            f"🔐 Order: <code>{esc(o['order_number'])}</code>\n"
            f"🗂️ Category: <b>{esc(o['category'])}</b>\n"
            f"💱 Payment: <b>{esc(o['currency'])}</b>\n"
            f"📦 Product: <b>{esc(o['product'])}</b>\n"
            f"💰 Amount: <b>{o['robux_amount']:,} Robux</b>\n"
            f"💵 Price: <b>{esc(o['price'])}</b>\n"
            f"👤 Roblox: <code>{esc(o['roblox_username'])}</code>\n"
            f"👤 Customer: <b>{esc(o['telegram_name'] or '')}</b>\n"
            f"📱 Telegram: <b>{esc('@'+o['telegram_username']) if o['telegram_username'] else 'No username'}</b>\n"
            f"🆔 Chat ID: <code>{o['telegram_id']}</code>\n"
            f"📅 Created: <b>{esc(o['created_at'])}</b>\n"
            f"📌 Status: <b>{status}</b>",
            kb([
                [InlineKeyboardButton("✅ Confirmed", callback_data=f"orderstatus:confirmed:{order_number}"),
                 InlineKeyboardButton("❌ Rejected", callback_data=f"orderstatus:rejected:{order_number}")],
                [InlineKeyboardButton("⏳ Awaiting", callback_data=f"orderstatus:awaiting_confirmation:{order_number}")],
                [InlineKeyboardButton("↩️ Orders", callback_data="a:orders")],
            ]),
        )
        return
    if data.startswith("orderstatus:"):
        _, status, order_number = data.split(":",2)
        o = get_order(order_number)
        if not o:
            await query.answer("Order not found.", show_alert=True); return
        set_order_status(order_number, status)
        # Notify the customer. This works because they placed the order and interacted with the bot.
        customer_notice = {
            "confirmed": "✅ <b>ORDER CONFIRMED</b>\n\nYour order <code>{}</code> has been confirmed.",
            "rejected": "❌ <b>ORDER REJECTED</b>\n\nYour order <code>{}</code> was rejected. Please contact the support account if you need help.",
            "awaiting_confirmation": "⏳ <b>ORDER UPDATED</b>\n\nYour order <code>{}</code> is still awaiting confirmation.",
        }[status].format(esc(order_number))
        try:
            await context.bot.send_message(chat_id=o["telegram_id"], text=customer_notice, parse_mode="HTML")
        except TelegramError as error:
            logger.warning("Customer status notification failed for %s: %s", order_number, error)
        await query.answer("Order updated.")
        await show_orders(query)
        return

    # Reorder callbacks intentionally handled as text input because they are clearer.
    if data.startswith("cedit_order:"):
        await ask_input(query, "category_order", "↕️ <b>CATEGORY ORDER</b>\n\nSend a whole-number sort position. Lower numbers appear first.", category_id=int(data.split(":",1)[1])); return
    if data.startswith("p_order:"):
        await ask_input(query, "product_order", "↕️ <b>PRODUCT ORDER</b>\n\nSend a whole-number sort position. Lower numbers appear first.", product_id=int(data.split(":",1)[1])); return
    if data.startswith("corder:"):
        await ask_input(query, "currency_order", "↕️ <b>CURRENCY ORDER</b>\n\nSend a whole-number sort position. Lower numbers appear first.", currency_id=int(data.split(":",1)[1])); return


# ============================================================
# TEXT MESSAGE HANDLER
# ============================================================


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return
    user = update.effective_user
    user_id = user.id
    session = sessions.get(user_id)

    # /cancel is handled here for sessions, even though it starts with '/'.
    if message.text and message.text.strip().lower() == "/cancel":
        sessions.pop(user_id, None)
        await cleanup_user_message(update)
        await send_or_edit_screen(
            context.bot, update.effective_chat.id, user_id,
            render_text("cancelled"),
            main_keyboard(user),
        )
        return

    # --------------------------------------------------------
    # CUSTOM EMOJI SECOND STAGE
    # --------------------------------------------------------
    # This must run before generic admin text handling because a Telegram
    # custom-emoji message is represented by an entity carrying emoji_id.
    if is_admin(user) and session and session.get("action") == "add_emoji_value":
        await cleanup_user_message(update)
        entities = message.entities or []
        custom_entities = [e for e in entities if e.type == MessageEntity.CUSTOM_EMOJI]
        if not custom_entities:
            await send_or_edit_screen(
                context.bot, update.effective_chat.id, user_id,
                "⚠️ I couldn't detect a Telegram custom emoji in that message.\n\nSend the custom emoji itself and try again.",
                cancel_keyboard(),
            )
            return
        entity = custom_entities[0]
        emoji_id = entity.custom_emoji_id
        fallback = "✨"
        if message.text:
            start = entity.offset
            end = entity.offset + entity.length
            try:
                fallback = message.text[start:end] or "✨"
            except Exception:
                fallback = "✨"
        name = session["emoji_name"]
        add_emoji(name, emoji_id, fallback)
        sessions.pop(user_id, None)
        await send_or_edit_screen(
            context.bot, update.effective_chat.id, user_id,
            "✅ <b>CUSTOM EMOJI SAVED</b>\n\n"
            f"Name: <b>{esc(name)}</b>\n"
            f"Token: <code>{{{{emoji:{esc(name)}}}}}</code>",
            kb([[InlineKeyboardButton("✨ Emojis", callback_data="a:emojis")],[InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")]]),
        )
        return

    # --------------------------------------------------------
    # ADMIN INPUT
    # --------------------------------------------------------
    if is_admin(user) and session and session.get("action"):
        action = session["action"]
        raw = message.text or ""
        value = raw.strip()
        await cleanup_user_message(update)

        try:
            # Categories
            if action == "add_category":
                parent_id = session.get("parent_id")
                if not value:
                    raise ValueError("Name cannot be empty.")
                conn = db()
                sort_order = conn.execute(
                    "SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM categories WHERE parent_id IS ?",
                    (parent_id,),
                ).fetchone()["n"]
                cur = conn.execute(
                    "INSERT INTO categories(name, button_text, description, enabled, sort_order, parent_id) VALUES (?, ?, '', 1, ?, ?)",
                    (value, value, sort_order, parent_id),
                )
                cid = cur.lastrowid
                conn.commit(); conn.close()
                sessions.pop(user_id, None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id,
                    "✅ <b>CATEGORY CREATED</b>\n\n" f"📂 {esc(value)}", kb([[InlineKeyboardButton("🗂️ Categories", callback_data=f"acats:{parent_id if parent_id is not None else 'root'}")],[InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")]]))
                return

            if action == "rename_category":
                cid = session["category_id"]
                conn = db(); conn.execute("UPDATE categories SET name=? WHERE id=?", (value, cid)); conn.commit(); conn.close()
                sessions.pop(user_id, None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Category renamed.", kb([[InlineKeyboardButton("📂 Category", callback_data=f"acat:{cid}")]])); return

            if action == "category_button":
                cid = session["category_id"]
                conn = db(); conn.execute("UPDATE categories SET button_text=? WHERE id=?", (value, cid)); conn.commit(); conn.close()
                sessions.pop(user_id, None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Category button updated.", kb([[InlineKeyboardButton("📂 Category", callback_data=f"acat:{cid}")]])); return

            if action == "category_desc":
                cid = session["category_id"]; desc = "" if value == "-" else value
                conn = db(); conn.execute("UPDATE categories SET description=? WHERE id=?", (desc, cid)); conn.commit(); conn.close()
                sessions.pop(user_id, None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Category description updated.", kb([[InlineKeyboardButton("📂 Category", callback_data=f"acat:{cid}")]])); return

            if action == "category_order":
                n = int(value); cid = session["category_id"]
                conn = db(); conn.execute("UPDATE categories SET sort_order=? WHERE id=?", (n,cid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Category order updated.", kb([[InlineKeyboardButton("📂 Category", callback_data=f"acat:{cid}")]])); return

            # Products
            if action == "add_product_name":
                if not value: raise ValueError("Product name cannot be empty.")
                session["product_name"] = value
                session["action"] = "add_product_amount"
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id,
                    "🔢 <b>PRODUCT AMOUNT</b>\n\nSend a whole number, or <code>custom</code> for an arbitrary amount.", cancel_keyboard())
                return

            if action == "add_product_amount":
                custom = value.lower() == "custom"
                if custom:
                    amount = 0
                else:
                    cleaned = value.replace(",", "").replace(" ", "")
                    if not cleaned.isdigit() or int(cleaned) <= 0:
                        raise ValueError("Use a positive whole number or custom.")
                    amount = int(cleaned)
                cid = session["category_id"]
                conn = db()
                sort_order = conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM products WHERE category_id=?", (cid,)).fetchone()["n"]
                cur = conn.execute(
                    "INSERT INTO products(name, button_text, amount, enabled, sort_order, category_id, description, is_custom) VALUES (?, ?, ?, 1, ?, ?, '', ?)",
                    (session["product_name"], session["product_name"], amount, sort_order, cid, int(custom)),
                )
                pid = cur.lastrowid
                for c in conn.execute("SELECT id FROM currencies").fetchall():
                    conn.execute("INSERT OR IGNORE INTO prices(currency_id,product_id,price) VALUES (?,?, 'NA')", (c["id"], pid))
                conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id,
                    "✅ <b>PRODUCT CREATED</b>\n\n" f"📦 {esc(session['product_name'])}\n" f"🔢 {'Custom amount' if custom else f'{amount:,} Robux'}",
                    kb([[InlineKeyboardButton("📦 Products", callback_data="a:products")],[InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")]]))
                return

            if action == "product_name":
                pid=session["product_id"]; conn=db(); conn.execute("UPDATE products SET name=? WHERE id=?", (value,pid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Product name updated.", kb([[InlineKeyboardButton("📦 Product", callback_data=f"a_product:{pid}")]])); return

            if action == "product_button":
                pid=session["product_id"]; conn=db(); conn.execute("UPDATE products SET button_text=? WHERE id=?", (value,pid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Product button updated.", kb([[InlineKeyboardButton("📦 Product", callback_data=f"a_product:{pid}")]])); return

            if action == "product_amount":
                pid=session["product_id"]; is_custom=value.lower()=="custom"
                if is_custom: amount=0
                else:
                    cleaned=value.replace(",","").replace(" ","")
                    if not cleaned.isdigit() or int(cleaned)<=0: raise ValueError("Use a positive whole number or custom.")
                    amount=int(cleaned)
                conn=db(); conn.execute("UPDATE products SET amount=?, is_custom=? WHERE id=?", (amount,int(is_custom),pid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Product amount/type updated.", kb([[InlineKeyboardButton("📦 Product", callback_data=f"a_product:{pid}")]])); return

            if action == "product_desc":
                pid=session["product_id"]; desc="" if value=="-" else value
                conn=db(); conn.execute("UPDATE products SET description=? WHERE id=?", (desc,pid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Product description updated.", kb([[InlineKeyboardButton("📦 Product", callback_data=f"a_product:{pid}")]])); return

            if action == "product_order":
                pid=session["product_id"]; n=int(value)
                conn=db(); conn.execute("UPDATE products SET sort_order=? WHERE id=?", (n,pid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Product order updated.", kb([[InlineKeyboardButton("📦 Product", callback_data=f"a_product:{pid}")]])); return

            # Currencies
            if action == "add_currency":
                conn=db(); sort_order=conn.execute("SELECT COALESCE(MAX(sort_order),0)+1 AS n FROM currencies").fetchone()["n"]
                conn.execute("INSERT INTO currencies(name,button_text,enabled,sort_order) VALUES (?,?,1,?)", (value,value,sort_order))
                cid=conn.execute("SELECT id FROM currencies WHERE name=?",(value,)).fetchone()["id"]
                for p in conn.execute("SELECT id FROM products").fetchall():
                    conn.execute("INSERT OR IGNORE INTO prices(currency_id,product_id,price) VALUES (?,?, 'NA')", (cid,p["id"]))
                conn.execute("INSERT OR IGNORE INTO custom_prices(currency_id,price) VALUES (?, 'NA')", (cid,)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ <b>CURRENCY CREATED</b>\n\n" f"💱 {esc(value)}", kb([[InlineKeyboardButton("💱 Currencies", callback_data="a:currencies")],[InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")]])); return

            if action == "currency_name":
                cid=session["currency_id"]; conn=db(); conn.execute("UPDATE currencies SET name=? WHERE id=?",(value,cid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Currency name updated.", kb([[InlineKeyboardButton("💱 Currency", callback_data=f"cedit:{cid}")]])); return

            if action == "currency_button":
                cid=session["currency_id"]; conn=db(); conn.execute("UPDATE currencies SET button_text=? WHERE id=?",(value,cid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Currency button updated.", kb([[InlineKeyboardButton("💱 Currency", callback_data=f"cedit:{cid}")]])); return

            if action == "currency_order":
                cid=session["currency_id"]; n=int(value); conn=db(); conn.execute("UPDATE currencies SET sort_order=? WHERE id=?",(n,cid)); conn.commit(); conn.close(); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Currency order updated.", kb([[InlineKeyboardButton("💱 Currency", callback_data=f"cedit:{cid}")]])); return

            # Prices
            if action == "set_price":
                set_price(session["currency_id"], session["product_id"], value or "NA"); cid=session["currency_id"]
                sessions.pop(user_id,None); await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Price updated.", kb([[InlineKeyboardButton("💰 Prices", callback_data=f"pricecur:{cid}")]])); return

            if action == "set_custom_price":
                cid=session["currency_id"]; set_custom_price(cid, value or "NA"); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Custom amount price updated.", kb([[InlineKeyboardButton("💰 Prices", callback_data=f"pricecur:{cid}")]])); return

            # Text/button editors
            if action == "edit_text":
                set_text(session["key"], raw); key=session["key"]; sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Text updated.\n\nPreview:\n" + render_text(key), kb([[InlineKeyboardButton("📝 Texts", callback_data="a:texts")],[InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")]])); return

            if action == "edit_button":
                set_button(session["key"], value); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Button text updated.", kb([[InlineKeyboardButton("🔘 Buttons", callback_data="a:buttons")]])); return

            # Settings
            if action.startswith("setting:"):
                setting = action.split(":",1)[1]
                if setting == "shop_name": set_setting("shop_name", value)
                elif setting == "admin_username": set_setting("admin_username", value if value.startswith("@") else "@"+value)
                elif setting == "recipient":
                    int(value)  # validation only
                    set_setting("order_recipient_chat_id", value)
                elif setting == "max_amount":
                    n=int(value)
                    if n<=0: raise ValueError("Maximum must be positive.")
                    set_setting("max_custom_amount", n)
                else: raise ValueError("Unknown setting.")
                sessions.pop(user_id,None); await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Setting updated.", settings_keyboard()); return

            # Custom emoji flow: name -> actual emoji message.
            if action == "add_emoji_name":
                name=value.lower()
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name): raise ValueError("Use 1-32 letters, numbers, _ or - only.")
                if get_emoji_by_name(name): raise ValueError("That emoji name already exists.")
                session["emoji_name"] = name
                session["action"] = "add_emoji_value"
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id,
                    "✨ <b>SEND THE CUSTOM EMOJI</b>\n\nNow send the Telegram custom emoji by itself (or in a short message).\n\nI will detect its custom emoji ID automatically.", cancel_keyboard())
                return

            if action == "emoji_rename":
                name=value.lower()
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name): raise ValueError("Invalid token name.")
                existing=get_emoji_by_name(name)
                if existing and existing["id"] != session["emoji_id"]: raise ValueError("That name is already used.")
                update_emoji_name(session["emoji_id"], name); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Custom emoji renamed.", kb([[InlineKeyboardButton("✨ Emojis", callback_data="a:emojis")]])); return

            # Admins
            if action == "add_admin":
                target=int(value); add_admin(target, "Admin"); sessions.pop(user_id,None)
                await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, "✅ Admin added.", admins_keyboard()); return

            raise ValueError("Unknown admin action.")

        except sqlite3.IntegrityError as error:
            logger.warning("Admin input integrity error: %s", error)
            await send_or_edit_screen(context.bot, update.effective_chat.id, user_id,
                "⚠️ <b>Could not save that.</b>\n\nIt may already exist or contain a duplicate value.", cancel_keyboard())
            return
        except (ValueError, TypeError) as error:
            await send_or_edit_screen(context.bot, update.effective_chat.id, user_id,
                f"⚠️ <b>Invalid input</b>\n\n{esc(error)}\n\nPlease try again.", cancel_keyboard())
            return

    # --------------------------------------------------------
    # CUSTOMER INPUT
    # --------------------------------------------------------
    if not session:
        await cleanup_user_message(update)
        await send_or_edit_screen(
            context.bot, update.effective_chat.id, user_id,
            render_text("no_session"), main_keyboard(user)
        )
        return

    text = (message.text or "").strip()
    await cleanup_user_message(update)

    if session.get("waiting") == "custom_amount":
        cleaned = text.replace(",", "").replace(" ", "")
        try:
            amount = int(cleaned)
        except ValueError:
            amount = 0
        max_amount = int(get_setting("max_custom_amount", "1000000"))
        if amount < 1 or amount > max_amount:
            await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, render_text("invalid_amount"), cancel_keyboard())
            return
        session["amount"] = amount
        session["waiting"] = "username"
        await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, render_text("username"), cancel_keyboard())
        return

    if session.get("waiting") == "username":
        if not valid_roblox_username(text):
            await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, render_text("invalid_username"), cancel_keyboard())
            return
        try:
            order = create_order(user, session, text.lstrip("@"))
        except Exception as error:
            logger.exception("Order creation failed")
            sessions.pop(user_id, None)
            await send_or_edit_screen(context.bot, update.effective_chat.id, user_id, render_text("order_error"), main_keyboard(user))
            return

        admin_chat = get_setting("order_recipient_chat_id", "").strip()
        if not admin_chat and BOOTSTRAP_ADMIN_CHAT_ID:
            admin_chat = BOOTSTRAP_ADMIN_CHAT_ID
        admin_message = render_text(
            "admin_new_order",
            order_number=order["order_number"],
            category=order["category"],
            currency=order["currency"],
            product=order["product"],
            amount=order["robux_amount"],
            price=order["price"],
            roblox_username=order["roblox_username"],
            created_at=order["created_at"],
            customer_name=order["telegram_name"] or "Unknown",
            customer_username=("@" + order["telegram_username"]) if order["telegram_username"] else "No username",
            telegram_id=order["telegram_id"],
        )
        notify_error = None
        if admin_chat:
            try:
                await context.bot.send_message(chat_id=int(admin_chat), text=admin_message, parse_mode="HTML")
            except Exception as error:
                notify_error = error
                logger.error("Could not notify admin for %s: %s", order["order_number"], error)
        else:
            notify_error = "No order recipient chat ID is configured."

        sessions.pop(user_id, None)
        if notify_error:
            # Still confirm the order was stored; don't pretend delivery to the admin succeeded.
            await send_or_edit_screen(
                context.bot, update.effective_chat.id, user_id,
                render_text("admin_send_failed", order_number=order["order_number"], error=str(notify_error)),
                order_end_keyboard(),
            )
            return

        await send_or_edit_screen(
            context.bot, update.effective_chat.id, user_id,
            render_text("confirmation", order_number=order["order_number"]),
            order_end_keyboard(),
        )
        return


# ============================================================
# STARTUP VALIDATION / ERROR HANDLER
# ============================================================


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception", exc_info=context.error)


def validate_config():
    if not BOT_TOKEN or BOT_TOKEN == "BOT_TOKEN" or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("BOT_TOKEN is missing or still a placeholder. Set the real token in Railway Variables.")
    if BOOTSTRAP_ADMIN_CHAT_ID and not BOOTSTRAP_ADMIN_CHAT_ID.lstrip("-").isdigit():
        logger.warning("ADMIN_CHAT_ID is not numeric; set it to your Telegram numeric ID for reliable admin access and order delivery.")


def main():
    validate_config()
    init_db()
    logger.info("Database: %s", DATABASE_FILE)
    logger.info("SRPExchange v3 starting...")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("cancel", text_handler))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    application.add_error_handler(error_handler)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
