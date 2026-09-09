
import os
import html
import logging
import secrets
import sqlite3
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOOTSTRAP_ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
DATABASE_FILE = os.getenv("DATABASE_FILE", "shop.db")

# This username is used only as a bootstrap authorization fallback.
# The admin panel itself stores the customer-facing support username
# separately, so changing the displayed username does not lock you out.
DEFAULT_BOOTSTRAP_ADMIN_USERNAME = "berizienuhq"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ============================================================
# DATABASE
# ============================================================

def db():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn, table_name):
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }


def ensure_column(conn, table_name, column_name, definition):
    if column_name not in table_columns(conn, table_name):
        conn.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
        )


def init_db():
    conn = db()
    cur = conn.cursor()

    # Core configuration.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    # Generic customer-facing categories.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            button_text TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            visibility INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    ensure_column(conn, "categories", "visibility", "INTEGER NOT NULL DEFAULT 1")

    # Exchange currencies / payment methods.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS currencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            button_text TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    # Products/offers.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            button_text TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            enabled INTEGER NOT NULL DEFAULT 1,
            visibility INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    ensure_column(conn, "products", "category_id", "INTEGER")
    ensure_column(conn, "products", "description", "TEXT NOT NULL DEFAULT ''")
    ensure_column(conn, "products", "visibility", "INTEGER NOT NULL DEFAULT 1")

    # Price matrix: currency x product.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            currency_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price TEXT NOT NULL DEFAULT 'NA',
            PRIMARY KEY(currency_id, product_id)
        )
        """
    )

    # Price for arbitrary/custom amounts.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS custom_prices (
            currency_id INTEGER PRIMARY KEY,
            price TEXT NOT NULL DEFAULT 'NA'
        )
        """
    )

    # Editable customer/admin text templates.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS texts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    # Editable customer button labels.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS buttons (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    # Orders.
    cur.execute(
        """
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
        )
        """
    )

    # Migrate older order tables without breaking an existing database.
    ensure_column(conn, "orders", "category", "TEXT NOT NULL DEFAULT ''")
    ensure_column(
        conn,
        "orders",
        "status",
        "TEXT NOT NULL DEFAULT 'awaiting_confirmation'",
    )

    # Optional multi-admin list.
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            telegram_id INTEGER PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )

    # Seed settings. Existing customized values are preserved.
    defaults = {
        "shop_name": "SRPExchange",
        "admin_username": "@berizienuhq",
        "order_recipient_chat_id": BOOTSTRAP_ADMIN_CHAT_ID or "",
        "max_custom_amount": "1000000",
        "delete_user_messages": "1",
    }

    for key, value in defaults.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO settings(key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    # Upgrade the old default brand automatically.
    current_name = cur.execute(
        "SELECT value FROM settings WHERE key = 'shop_name'"
    ).fetchone()
    if current_name and current_name["value"] == "R$ EXCHANGE":
        cur.execute(
            "UPDATE settings SET value = 'SRPExchange' WHERE key = 'shop_name'"
        )

    # Seed categories only when none exist.
    category_count = cur.execute(
        "SELECT COUNT(*) AS n FROM categories"
    ).fetchone()["n"]

    if category_count == 0:
        cur.execute(
            """
            INSERT INTO categories
            (name, button_text, description, enabled, sort_order)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                "Robux",
                "💎 Robux",
                "Choose a Robux amount to exchange.",
                1,
            ),
        )

    # Seed currencies only when none exist.
    currency_count = cur.execute(
        "SELECT COUNT(*) AS n FROM currencies"
    ).fetchone()["n"]

    if currency_count == 0:
        currencies = [
            ("GRAM", "💎 GRAM", 1),
            ("Telegram Stars", "⭐ Telegram Stars", 2),
        ]
        cur.executemany(
            """
            INSERT INTO currencies
            (name, button_text, enabled, sort_order)
            VALUES (?, ?, 1, ?)
            """,
            currencies,
        )

    # Seed products only when none exist.
    product_count = cur.execute(
        "SELECT COUNT(*) AS n FROM products"
    ).fetchone()["n"]

    if product_count == 0:
        category_id = cur.execute(
            "SELECT id FROM categories ORDER BY sort_order, id LIMIT 1"
        ).fetchone()["id"]

        products = [
            ("200 Robux", "200 Robux", 200, category_id, 1),
            ("500 Robux", "500 Robux", 500, category_id, 2),
            ("700 Robux", "700 Robux", 700, category_id, 3),
            ("1,000 Robux", "1,000 Robux", 1000, category_id, 4),
        ]

        cur.executemany(
            """
            INSERT INTO products
            (name, button_text, amount, category_id, enabled, sort_order)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            products,
        )

    # Backfill old products into the first category if needed.
    first_category = cur.execute(
        "SELECT id FROM categories ORDER BY sort_order, id LIMIT 1"
    ).fetchone()
    if first_category:
        cur.execute(
            """
            UPDATE products
            SET category_id = ?
            WHERE category_id IS NULL
            """,
            (first_category["id"],),
        )

    # Make sure every product/currency combination has a price row.
    currencies = cur.execute("SELECT id FROM currencies").fetchall()
    products = cur.execute("SELECT id FROM products").fetchall()

    for currency in currencies:
        for product in products:
            cur.execute(
                """
                INSERT OR IGNORE INTO prices(currency_id, product_id, price)
                VALUES (?, ?, 'NA')
                """,
                (currency["id"], product["id"]),
            )

    # Seed editable screens if they do not exist yet.
    text_defaults = {
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
            "Choose how you want to pay for your exchange."
        ),
        "product": (
            "📦 <b>SELECT YOUR AMOUNT</b>\n\n"
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
            "3️⃣ Choose an amount or enter a custom amount.\n"
            "4️⃣ Send your Roblox username.\n"
            "5️⃣ Your order is sent to the team and awaits confirmation."
        ),
        "confirmation": (
            "✅ <b>ORDER SENT</b>\n\n"
            "🔐 Order code: <code>{order_number}</code>\n\n"
            "Your order has been sent and is now <b>awaiting confirmation</b>.\n\n"
            "For your security, only trust a message that references this exact order code.\n\n"
            "<b>{shop_name}</b> will contact you here when your order is confirmed."
        ),
        "cancelled": (
            "❌ <b>CANCELLED</b>\n\n"
            "Your current action has been cancelled."
        ),
        "no_categories": (
            "🗂️ <b>NO CATEGORIES AVAILABLE</b>\n\n"
            "There are currently no exchange categories available."
        ),
        "no_products": (
            "📦 <b>NO PRODUCTS AVAILABLE</b>\n\n"
            "There are currently no products in this category."
        ),
        "invalid_amount": (
            "⚠️ Please enter a valid amount between 1 and {max_custom_amount}."
        ),
        "invalid_username": (
            "⚠️ That doesn't look like a valid Roblox username.\n\n"
            "Please try again."
        ),
        "order_error": (
            "⚠️ <b>ORDER NOT CREATED</b>\n\n"
            "Something went wrong while creating your order. Please try again."
        ),
        "no_session": (
            "Please open the shop again with /start."
        ),
        "admin_new_order": (
            "🔔 <b>NEW ORDER</b>\n\n"
            "🔐 Security code: <code>{order_number}</code>\n"
            "📦 Category: <b>{category}</b>\n"
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
        "admin_no_recipient": (
            "⚠️ <b>ORDER SAVED — ADMIN NOTIFIED FAILED</b>\n\n"
            "Order <code>{order_number}</code> is stored in the database,\n"
            "but the configured admin chat could not be reached.\n\n"
            "Reason: <code>{error}</code>"
        ),
    }

    # If an old confirmation template exists, keep it unless it still has
    # the old generic wording. New installs use the safer anti-impersonation
    # wording above.
    for key, value in text_defaults.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO texts(key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    button_defaults = {
        "exchange": "💱 Exchange",
        "how": "ℹ️ How It Works",
        "custom": "✏️ Custom Amount",
        "back": "↩️ Back",
        "home": "🏠 Main Menu",
        "new_order": "💱 New Order",
        "cancel": "❌ Cancel",
        "categories": "🗂️ Categories",
    }

    for key, value in button_defaults.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO buttons(key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    # Bootstrap the current owner as an admin when possible.
    if BOOTSTRAP_ADMIN_CHAT_ID:
        try:
            admin_id = int(BOOTSTRAP_ADMIN_CHAT_ID)
            cur.execute(
                """
                INSERT OR IGNORE INTO admins
                (telegram_id, label, enabled, created_at)
                VALUES (?, ?, 1, ?)
                """,
                (
                    admin_id,
                    "Bootstrap admin",
                    datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                ),
            )
        except ValueError:
            logger.warning("ADMIN_CHAT_ID is not a numeric Telegram chat ID.")

    conn.commit()
    conn.close()


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_setting(key, default=""):
    conn = db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO settings(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, str(value)),
    )
    conn.commit()
    conn.close()


def get_text(key, default=""):
    conn = db()
    row = conn.execute(
        "SELECT value FROM texts WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_text(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO texts(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def get_button(key, default=None):
    fallback = default if default is not None else key
    conn = db()
    row = conn.execute(
        "SELECT value FROM buttons WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()
    return row["value"] if row else fallback


def set_button(key, value):
    conn = db()
    conn.execute(
        """
        INSERT INTO buttons(key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def get_categories(enabled_only=False):
    conn = db()
    sql = (
        """
        SELECT * FROM categories
        WHERE enabled = 1
          AND visibility = 1
        ORDER BY sort_order, id
        """
        if enabled_only
        else
        """
        SELECT * FROM categories
        ORDER BY sort_order, id
        """
    )
    rows = conn.execute(sql).fetchall()
    conn.close()
    return rows


def get_category(category_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM categories WHERE id = ?",
        (category_id,),
    ).fetchone()
    conn.close()
    return row


def get_currencies(enabled_only=False):
    conn = db()
    sql = (
        """
        SELECT * FROM currencies
        WHERE enabled = 1
        ORDER BY sort_order, id
        """
        if enabled_only
        else
        """
        SELECT * FROM currencies
        ORDER BY sort_order, id
        """
    )
    rows = conn.execute(sql).fetchall()
    conn.close()
    return rows


def get_currency(currency_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM currencies WHERE id = ?",
        (currency_id,),
    ).fetchone()
    conn.close()
    return row


def get_products(category_id=None, enabled_only=False):
    conn = db()
    query = "SELECT * FROM products"
    args = []
    conditions = []

    if category_id is not None:
        conditions.append("category_id = ?")
        args.append(category_id)

    if enabled_only:
        conditions.append("enabled = 1")
        conditions.append("visibility = 1")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY sort_order, id"

    rows = conn.execute(query, tuple(args)).fetchall()
    conn.close()
    return rows


def get_product(product_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    conn.close()
    return row


def get_price(currency_id, product_id):
    conn = db()
    row = conn.execute(
        """
        SELECT price
        FROM prices
        WHERE currency_id = ?
          AND product_id = ?
        """,
        (currency_id, product_id),
    ).fetchone()
    conn.close()
    return row["price"] if row else "NA"


def set_price(currency_id, product_id, price):
    conn = db()
    conn.execute(
        """
        INSERT INTO prices(currency_id, product_id, price)
        VALUES (?, ?, ?)
        ON CONFLICT(currency_id, product_id)
        DO UPDATE SET price = excluded.price
        """,
        (currency_id, product_id, price.strip() or "NA"),
    )
    conn.commit()
    conn.close()


def get_custom_price(currency_id):
    conn = db()
    row = conn.execute(
        "SELECT price FROM custom_prices WHERE currency_id = ?",
        (currency_id,),
    ).fetchone()
    conn.close()
    return row["price"] if row else "NA"


def set_custom_price(currency_id, price):
    conn = db()
    conn.execute(
        """
        INSERT INTO custom_prices(currency_id, price)
        VALUES (?, ?)
        ON CONFLICT(currency_id)
        DO UPDATE SET price = excluded.price
        """,
        (currency_id, price.strip() or "NA"),
    )
    conn.commit()
    conn.close()


def get_orders(limit=30):
    conn = db()
    rows = conn.execute(
        """
        SELECT *
        FROM orders
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def get_order(order_number):
    conn = db()
    row = conn.execute(
        "SELECT * FROM orders WHERE order_number = ?",
        (order_number,),
    ).fetchone()
    conn.close()
    return row


def set_order_status(order_number, status):
    conn = db()
    conn.execute(
        "UPDATE orders SET status = ? WHERE order_number = ?",
        (status, order_number),
    )
    conn.commit()
    conn.close()


def add_admin(telegram_id, label=""):
    conn = db()
    conn.execute(
        """
        INSERT INTO admins(telegram_id, label, enabled, created_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(telegram_id)
        DO UPDATE SET label = excluded.label, enabled = 1
        """,
        (
            telegram_id,
            label,
            datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()


def remove_admin(telegram_id):
    conn = db()
    conn.execute(
        "DELETE FROM admins WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()
    conn.close()


def get_admins():
    conn = db()
    rows = conn.execute(
        """
        SELECT *
        FROM admins
        ORDER BY created_at, telegram_id
        """
    ).fetchall()
    conn.close()
    return rows


# ============================================================
# SECURITY / AUTH
# ============================================================

def is_admin(user):
    if not user:
        return False

    # Preserve the environment bootstrap admin.
    if BOOTSTRAP_ADMIN_CHAT_ID:
        try:
            if user.id == int(BOOTSTRAP_ADMIN_CHAT_ID):
                return True
        except ValueError:
            pass

    if user.username and user.username.lower() == DEFAULT_BOOTSTRAP_ADMIN_USERNAME.lower():
        return True

    conn = db()
    row = conn.execute(
        """
        SELECT 1
        FROM admins
        WHERE telegram_id = ?
          AND enabled = 1
        """,
        (user.id,),
    ).fetchone()
    conn.close()
    return row is not None


# ============================================================
# SESSION / CLEAN SCREEN
# ============================================================

sessions = {}
# Last customer/admin screen message per user. Kept outside sessions so
# clearing a workflow never loses the message that must be deleted next.
screen_messages = {}


def session_for(user_id):
    return sessions.setdefault(user_id, {})


async def safe_delete(bot, chat_id, message_id):
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (BadRequest, Forbidden, TelegramError):
        pass


async def remember_screen(
    bot,
    chat_id,
    user_id,
    text,
    reply_markup=None,
    parse_mode="HTML",
    delete_previous=True,
):
    # IMPORTANT: the screen message must NOT live inside `sessions`.
    # Workflows frequently call sessions.pop(...) when they finish, and
    # doing that used to erase the ID of the previous bot message. The next
    # /start therefore could not delete it, causing messages to pile up.
    previous_message_id = screen_messages.get(user_id)

    if delete_previous and previous_message_id:
        await safe_delete(bot, chat_id, previous_message_id)

    message = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=parse_mode,
        reply_markup=reply_markup,
    )

    screen_messages[user_id] = message.message_id
    return message


async def edit_screen(
    query,
    user_id,
    text,
    reply_markup=None,
    parse_mode="HTML",
):
    bot = query.get_bot()
    chat_id = query.message.chat_id

    try:
        # Inline navigation edits ONE existing screen instead of creating a
        # new message. This is the cleanest Telegram UX.
        await query.edit_message_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        screen_messages[user_id] = query.message.message_id
    except BadRequest as error:
        # Telegram returns this when the requested content is identical.
        if "Message is not modified" in str(error):
            screen_messages[user_id] = query.message.message_id
            return

        # If the old screen disappeared (manual deletion, message expiry,
        # etc.), create exactly ONE replacement and remember its ID.
        try:
            await safe_delete(
                bot,
                chat_id,
                screen_messages.get(user_id),
            )
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            screen_messages[user_id] = message.message_id
        except TelegramError:
            raise


async def clear_user_message(update):
    """Best-effort cleanup.

    Telegram permissions vary by chat type. In private chats this may fail,
    so the exception is intentionally ignored.
    """
    if not update.message:
        return
    if get_setting("delete_user_messages", "1") != "1":
        return
    await safe_delete(
        update.get_bot(),
        update.effective_chat.id,
        update.message.message_id,
    )


# ============================================================
# FORMATTING
# ============================================================

def clean(value):
    return html.escape(str(value))


def render_text(key, **extra):
    values = {
        "shop_name": clean(get_setting("shop_name", "SRPExchange")),
        "admin_username": clean(get_setting("admin_username", "@berizienuhq")),
        "max_custom_amount": clean(get_setting("max_custom_amount", "1000000")),
        "order_recipient_chat_id": clean(
            get_setting("order_recipient_chat_id", "")
        ),
    }
    values.update(
        {
            key_: (
                clean(value)
                if isinstance(value, str)
                else value
            )
            for key_, value in extra.items()
        }
    )

    template = get_text(key, "")
    if not template:
        return ""

    try:
        return template.format(**values)
    except (KeyError, ValueError, IndexError):
        # A malformed admin template should never crash the bot.
        return template


# ============================================================
# CUSTOMER KEYBOARDS
# ============================================================

def two_column_keyboard(buttons, bottom=None):
    rows = []
    row = []

    for button in buttons:
        row.append(button)
        if len(row) == 2:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    if bottom:
        rows.extend(bottom)

    return InlineKeyboardMarkup(rows)


def main_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_button("exchange", "💱 Exchange"),
                    callback_data="exchange",
                )
            ],
            [
                InlineKeyboardButton(
                    get_button("how", "ℹ️ How It Works"),
                    callback_data="how",
                )
            ],
        ]
    )


def category_keyboard():
    buttons = [
        InlineKeyboardButton(
            category["button_text"],
            callback_data=f"category:{category['id']}",
        )
        for category in get_categories(True)
    ]
    return two_column_keyboard(
        buttons,
        bottom=[
            [
                InlineKeyboardButton(
                    get_button("home", "🏠 Main Menu"),
                    callback_data="home",
                )
            ]
        ],
    )


def currency_keyboard():
    buttons = [
        InlineKeyboardButton(
            currency["button_text"],
            callback_data=f"currency:{currency['id']}",
        )
        for currency in get_currencies(True)
    ]

    return two_column_keyboard(
        buttons,
        bottom=[
            [
                InlineKeyboardButton(
                    get_button("back", "↩️ Back"),
                    callback_data="exchange",
                )
            ]
        ],
    )


def product_keyboard(category_id, currency_id):
    session_products = get_products(category_id, True)
    buttons = []

    for product in session_products:
        price = get_price(currency_id, product["id"])
        label = product["button_text"]

        # Price is appended only when configured, keeping buttons compact.
        if price and price.upper() != "NA":
            label = f"{label} · {price}"

        buttons.append(
            InlineKeyboardButton(
                label,
                callback_data=f"product:{product['id']}",
            )
        )

    buttons.append(
        InlineKeyboardButton(
            get_button("custom", "✏️ Custom Amount"),
            callback_data="custom",
        )
    )

    return two_column_keyboard(
        buttons,
        bottom=[
            [
                InlineKeyboardButton(
                    get_button("back", "↩️ Back"),
                    callback_data="currency_back",
                )
            ]
        ],
    )


def cancel_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    get_button("cancel", "❌ Cancel"),
                    callback_data="home",
                )
            ]
        ]
    )


# ============================================================
# ADMIN KEYBOARDS
# ============================================================

def admin_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📦 Products", callback_data="admin_products"),
                InlineKeyboardButton("🗂️ Categories", callback_data="admin_categories"),
            ],
            [
                InlineKeyboardButton("💱 Currencies", callback_data="admin_currencies"),
                InlineKeyboardButton("💰 Prices", callback_data="admin_prices"),
            ],
            [
                InlineKeyboardButton("📝 Texts / Steps", callback_data="admin_texts"),
                InlineKeyboardButton("🔘 Buttons", callback_data="admin_buttons"),
            ],
            [
                InlineKeyboardButton("🏪 Shop Settings", callback_data="admin_settings"),
                InlineKeyboardButton("👮 Admins", callback_data="admin_admins"),
            ],
            [
                InlineKeyboardButton("📋 Orders", callback_data="admin_orders"),
            ],
            [
                InlineKeyboardButton("🏠 Shop Preview", callback_data="home"),
            ],
        ]
    )


def back_to_admin():
    return [
        [
            InlineKeyboardButton("⚙️ Admin Panel", callback_data="admin")
        ]
    ]


# ============================================================
# START / ADMIN
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await clear_user_message(update)
    sessions.pop(user_id, None)

    # /start is sent by the user; remember that command message may have
    # failed deletion and ignore the failure.
    await remember_screen(
        context.bot,
        update.effective_chat.id,
        user_id,
        render_text("welcome"),
        main_keyboard(),
    )


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user):
        await clear_user_message(update)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            update.effective_user.id,
            "⛔ <b>ACCESS DENIED</b>",
        )
        return

    await clear_user_message(update)
    sessions.pop(update.effective_user.id, None)

    await remember_screen(
        context.bot,
        update.effective_chat.id,
        update.effective_user.id,
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "Everything important can be managed from this menu.\n"
        "Changes are saved instantly and used immediately by the shop.",
        admin_keyboard(),
    )


# ============================================================
# CUSTOMER SCREENS
# ============================================================

async def show_exchange(query):
    await edit_screen(
        query,
        query.from_user.id,
        render_text("category"),
        category_keyboard(),
    )


async def show_how(query):
    await edit_screen(
        query,
        query.from_user.id,
        render_text("how"),
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        get_button("exchange", "💱 Exchange"),
                        callback_data="exchange",
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_button("back", "↩️ Back"),
                        callback_data="home",
                    )
                ],
            ]
        ),
    )


async def show_categories(query):
    categories = get_categories(True)
    if not categories:
        await edit_screen(
            query,
            query.from_user.id,
            render_text("no_categories"),
            InlineKeyboardMarkup(back_to_admin() if is_admin(query.from_user) else [
                [
                    InlineKeyboardButton(
                        get_button("home", "🏠 Main Menu"),
                        callback_data="home",
                    )
                ]
            ]),
        )
        return

    await edit_screen(
        query,
        query.from_user.id,
        render_text("category"),
        category_keyboard(),
    )


async def show_currency_step(query, category_id):
    category = get_category(category_id)

    if (
        not category
        or not category["enabled"]
        or not category["visibility"]
    ):
        await query.answer(
            "This category is not currently public.",
            show_alert=True,
        )
        return

    products = get_products(category_id, True)
    if not products:
        await edit_screen(
            query,
            query.from_user.id,
            render_text(
                "no_products",
            ),
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            get_button("back", "↩️ Back"),
                            callback_data="exchange",
                        )
                    ]
                ]
            ),
        )
        return

    session_for(query.from_user.id).update(
        {
            "category_id": category_id,
            "category_name": category["name"],
            "waiting": "currency",
        }
    )

    extra = "\n\n" + clean(category["description"]) if category["description"] else ""
    text = render_text("currency") + extra

    await edit_screen(
        query,
        query.from_user.id,
        text,
        currency_keyboard(),
    )


async def show_products_step(query, currency_id):
    session = sessions.get(query.from_user.id, {})
    category_id = session.get("category_id")
    currency = get_currency(currency_id)

    if not category_id or not currency or not currency["enabled"]:
        await query.answer(
            "Please start the order again.",
            show_alert=True,
        )
        return

    products = get_products(category_id, True)
    if not products:
        await edit_screen(
            query,
            query.from_user.id,
            render_text("no_products"),
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            get_button("back", "↩️ Back"),
                            callback_data="exchange",
                        )
                    ]
                ]
            ),
        )
        return

    session.update(
        {
            "currency_id": currency_id,
            "currency_name": currency["name"],
            "waiting": "product",
        }
    )

    await edit_screen(
        query,
        query.from_user.id,
        render_text("product"),
        product_keyboard(category_id, currency_id),
    )


# ============================================================
# ADMIN: CATEGORIES
# ============================================================

async def show_admin_categories(query):
    rows = [
        [
            InlineKeyboardButton(
                "➕ Add Category",
                callback_data="add_category",
            )
        ]
    ]

    categories = get_categories(False)
    if categories:
        for category in categories:
            status = "🟢" if category["enabled"] else "🔴"
            visibility = "🌐" if category["visibility"] else "🔒"
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{status} {visibility} {category['button_text']}",
                        callback_data=f"edit_category:{category['id']}",
                    )
                ]
            )
    else:
        rows.append(
            [InlineKeyboardButton("No categories yet", callback_data="noop")]
        )

    rows.extend(back_to_admin())

    await edit_screen(
        query,
        query.from_user.id,
        "🗂️ <b>CATEGORIES</b>\n\n"
        "Create unlimited categories and put products inside them.\n\n"
        "🌐 Public = customers can see it\n"
        "🔒 Private = admins only",
        InlineKeyboardMarkup(rows),
    )


def category_admin_keyboard(category_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔤 Edit Name",
                    callback_data=f"rename_category:{category_id}",
                ),
                InlineKeyboardButton(
                    "🔘 Edit Button",
                    callback_data=f"category_button:{category_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "📝 Edit Description",
                    callback_data=f"category_desc:{category_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "📦 Manage Products",
                    callback_data=f"category_products:{category_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🟢 / 🔴 Enable / Disable",
                    callback_data=f"toggle_category:{category_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🌐 / 🔒 Public / Private",
                    callback_data=f"toggle_category_visibility:{category_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬆️ Up",
                    callback_data=f"category_up:{category_id}",
                ),
                InlineKeyboardButton(
                    "⬇️ Down",
                    callback_data=f"category_down:{category_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Delete Category",
                    callback_data=f"delete_category:{category_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Categories",
                    callback_data="admin_categories",
                )
            ],
        ]
    )


async def show_edit_category(query, category_id):
    category = get_category(category_id)
    if not category:
        await query.answer("Category not found.", show_alert=True)
        return

    products = get_products(category_id, False)
    status = "🟢 Enabled" if category["enabled"] else "🔴 Disabled"
    visibility = "🌐 Public" if category["visibility"] else "🔒 Private"

    await edit_screen(
        query,
        query.from_user.id,
        "🗂️ <b>EDIT CATEGORY</b>\n\n"
        f"🏷️ Name: <b>{clean(category['name'])}</b>\n"
        f"🔘 Button: <b>{clean(category['button_text'])}</b>\n"
        f"📦 Products: <b>{len(products)}</b>\n"
        f"📌 Status: <b>{status}</b>\n"
        f"👁️ Visibility: <b>{visibility}</b>",
        category_admin_keyboard(category_id),
    )


async def category_product_list(query, category_id):
    category = get_category(category_id)
    if not category:
        await query.answer("Category not found.", show_alert=True)
        return

    rows = [
        [
            InlineKeyboardButton(
                "➕ Add Product",
                callback_data=f"add_product:{category_id}",
            )
        ]
    ]

    products = get_products(category_id, False)
    for product in products:
        status = "🟢" if product["enabled"] else "🔴"
        visibility = "🌐" if product["visibility"] else "🔒"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{status} {visibility} {product['button_text']}",
                    callback_data=f"edit_product:{product['id']}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "↩️ Category",
                callback_data=f"edit_category:{category_id}",
            )
        ]
    )

    await edit_screen(
        query,
        query.from_user.id,
        f"📦 <b>{clean(category['name'])}</b>\n\n"
        "Manage the products inside this category.",
        InlineKeyboardMarkup(rows),
    )


# ============================================================
# ADMIN: PRODUCTS
# ============================================================

async def show_admin_products(query):
    rows = []
    categories = get_categories(False)

    for category in categories:
        rows.append(
            [
                InlineKeyboardButton(
                    f"🗂️ {category['name']}",
                    callback_data=f"category_products:{category['id']}",
                )
            ]
        )

    rows.extend(back_to_admin())

    await edit_screen(
        query,
        query.from_user.id,
        "📦 <b>PRODUCTS</b>\n\n"
        "Choose a category to add, edit, disable or remove products.\n\n"
        "🌐 Public = customers can see it\n"
        "🔒 Private = admins only",
        InlineKeyboardMarkup(rows),
    )


def product_admin_keyboard(product_id):
    product = get_product(product_id)
    category_id = product["category_id"] if product else 0

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔤 Edit Name",
                    callback_data=f"rename_product:{product_id}",
                ),
                InlineKeyboardButton(
                    "🔘 Edit Button",
                    callback_data=f"product_button:{product_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🔢 Change Amount",
                    callback_data=f"amount_product:{product_id}",
                ),
                InlineKeyboardButton(
                    "📝 Edit Description",
                    callback_data=f"product_desc:{product_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗂️ Move Category",
                    callback_data=f"move_product:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "💰 Edit Prices",
                    callback_data=f"product_prices:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🟢 / 🔴 Enable / Disable",
                    callback_data=f"toggle_product:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🌐 / 🔒 Public / Private",
                    callback_data=f"toggle_product_visibility:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬆️ Up",
                    callback_data=f"product_up:{product_id}",
                ),
                InlineKeyboardButton(
                    "⬇️ Down",
                    callback_data=f"product_down:{product_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Delete Product",
                    callback_data=f"delete_product:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Products",
                    callback_data=(
                        f"category_products:{category_id}"
                        if category_id
                        else "admin_products"
                    ),
                )
            ],
        ]
    )


async def show_edit_product(query, product_id):
    product = get_product(product_id)
    if not product:
        await query.answer("Product not found.", show_alert=True)
        return

    category = get_category(product["category_id"]) if product["category_id"] else None
    status = "🟢 Enabled" if product["enabled"] else "🔴 Disabled"
    visibility = "🌐 Public" if product["visibility"] else "🔒 Private"

    await edit_screen(
        query,
        query.from_user.id,
        "📦 <b>EDIT PRODUCT</b>\n\n"
        f"🏷️ Name: <b>{clean(product['name'])}</b>\n"
        f"🔘 Button: <b>{clean(product['button_text'])}</b>\n"
        f"🔢 Amount: <b>{product['amount']:,} Robux</b>\n"
        f"🗂️ Category: <b>{clean(category['name']) if category else 'None'}</b>\n"
        f"📌 Status: <b>{status}</b>\n"
        f"👁️ Visibility: <b>{visibility}</b>",
        product_admin_keyboard(product_id),
    )


# ============================================================
# ADMIN: CURRENCIES
# ============================================================

async def show_admin_currencies(query):
    rows = [
        [
            InlineKeyboardButton(
                "➕ Add Payment Method",
                callback_data="add_currency",
            )
        ]
    ]

    for currency in get_currencies(False):
        status = "🟢" if currency["enabled"] else "🔴"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{status} {currency['button_text']}",
                    callback_data=f"edit_currency:{currency['id']}",
                )
            ]
        )

    rows.extend(back_to_admin())

    await edit_screen(
        query,
        query.from_user.id,
        "💱 <b>PAYMENT METHODS</b>\n\n"
        "Add, rename, reorder, enable or delete payment methods.",
        InlineKeyboardMarkup(rows),
    )


def currency_admin_keyboard(currency_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔤 Edit Name",
                    callback_data=f"rename_currency:{currency_id}",
                ),
                InlineKeyboardButton(
                    "🔘 Edit Button",
                    callback_data=f"currency_button:{currency_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🟢 / 🔴 Enable / Disable",
                    callback_data=f"toggle_currency:{currency_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "⬆️ Up",
                    callback_data=f"currency_up:{currency_id}",
                ),
                InlineKeyboardButton(
                    "⬇️ Down",
                    callback_data=f"currency_down:{currency_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "💰 Edit Prices",
                    callback_data=f"prices_currency:{currency_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Delete Payment Method",
                    callback_data=f"delete_currency:{currency_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Payment Methods",
                    callback_data="admin_currencies",
                )
            ],
        ]
    )


async def show_edit_currency(query, currency_id):
    currency = get_currency(currency_id)
    if not currency:
        await query.answer("Payment method not found.", show_alert=True)
        return

    status = "🟢 Enabled" if currency["enabled"] else "🔴 Disabled"

    await edit_screen(
        query,
        query.from_user.id,
        "💱 <b>EDIT PAYMENT METHOD</b>\n\n"
        f"🏷️ Name: <b>{clean(currency['name'])}</b>\n"
        f"🔘 Button: <b>{clean(currency['button_text'])}</b>\n"
        f"📌 Status: <b>{status}</b>",
        currency_admin_keyboard(currency_id),
    )


# ============================================================
# ADMIN: PRICES
# ============================================================

async def show_admin_prices(query):
    rows = [
        [
            InlineKeyboardButton(
                f"💰 {currency['name']}",
                callback_data=f"prices_currency:{currency['id']}",
            )
        ]
        for currency in get_currencies(False)
    ]

    rows.append(
        [
            InlineKeyboardButton(
                "↩️ Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await edit_screen(
        query,
        query.from_user.id,
        "💰 <b>PRICE MANAGEMENT</b>\n\n"
        "Prices are linked to payment methods and products.\n"
        "Change a price once and the customer flow updates immediately.",
        InlineKeyboardMarkup(rows),
    )


async def show_currency_prices(query, currency_id):
    currency = get_currency(currency_id)
    if not currency:
        await query.answer("Payment method not found.", show_alert=True)
        return

    rows = []
    for product in get_products(None, False):
        price = get_price(currency_id, product["id"])
        category = (
            get_category(product["category_id"])
            if product["category_id"]
            else None
        )
        prefix = f"{category['name']} · " if category else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{prefix}{product['button_text']} → {price}",
                    callback_data=f"set_price:{currency_id}:{product['id']}",
                )
            ]
        )

    custom = get_custom_price(currency_id)
    rows.append(
        [
            InlineKeyboardButton(
                f"✏️ Custom Amount → {custom}",
                callback_data=f"set_custom:{currency_id}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "↩️ Payment Methods",
                callback_data="admin_currencies",
            )
        ]
    )

    await edit_screen(
        query,
        query.from_user.id,
        f"💰 <b>PRICES · {clean(currency['name'])}</b>\n\n"
        "Tap any price to change it.",
        InlineKeyboardMarkup(rows),
    )


async def show_product_prices(query, product_id):
    product = get_product(product_id)
    if not product:
        await query.answer("Product not found.", show_alert=True)
        return

    rows = []
    for currency in get_currencies(False):
        rows.append(
            [
                InlineKeyboardButton(
                    f"{currency['name']} → {get_price(currency['id'], product_id)}",
                    callback_data=f"set_price:{currency['id']}:{product_id}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                "↩️ Product",
                callback_data=f"edit_product:{product_id}",
            )
        ]
    )

    await edit_screen(
        query,
        query.from_user.id,
        f"💰 <b>PRICES · {clean(product['button_text'])}</b>\n\n"
        "Choose a payment method to edit its price.",
        InlineKeyboardMarkup(rows),
    )


# ============================================================
# ADMIN: TEXTS / BUTTONS / SETTINGS
# ============================================================

TEXT_NAMES = {
    "welcome": "👋 Welcome",
    "category": "🗂️ Category Step",
    "currency": "💱 Payment Method Step",
    "product": "📦 Product Step",
    "custom": "✏️ Custom Amount Step",
    "username": "👤 Roblox Username Step",
    "how": "ℹ️ How It Works",
    "confirmation": "✅ Order Sent / Confirmation",
    "cancelled": "❌ Cancelled",
    "no_categories": "🗂️ No Categories",
    "no_products": "📦 No Products",
    "invalid_amount": "⚠️ Invalid Amount",
    "invalid_username": "⚠️ Invalid Username",
    "order_error": "⚠️ Order Error",
    "no_session": "ℹ️ No Session",
    "admin_new_order": "🔔 Admin New Order",
    "admin_no_recipient": "⚠️ Admin Notification Error",
}

BUTTON_NAMES = {
    "exchange": "💱 Exchange",
    "how": "ℹ️ How It Works",
    "custom": "✏️ Custom Amount",
    "back": "↩️ Back",
    "home": "🏠 Main Menu",
    "new_order": "💱 New Order",
    "cancel": "❌ Cancel",
    "categories": "🗂️ Categories",
}


async def show_texts(query):
    rows = []
    for key, label in TEXT_NAMES.items():
        rows.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"edit_text:{key}",
                )
            ]
        )

    rows.extend(back_to_admin())

    await edit_screen(
        query,
        query.from_user.id,
        "📝 <b>TEXTS / STEPS</b>\n\n"
        "Every customer and admin message is editable here.\n\n"
        "Use the documented placeholders shown before editing.",
        InlineKeyboardMarkup(rows),
    )


async def show_buttons(query):
    rows = []
    for key, label in BUTTON_NAMES.items():
        rows.append(
            [
                InlineKeyboardButton(
                    f"{label}: {get_button(key)}",
                    callback_data=f"edit_button:{key}",
                )
            ]
        )

    rows.extend(back_to_admin())

    await edit_screen(
        query,
        query.from_user.id,
        "🔘 <b>BUTTON EDITOR</b>\n\n"
        "Rename the labels without touching the code.",
        InlineKeyboardMarkup(rows),
    )


async def show_settings(query):
    await edit_screen(
        query,
        query.from_user.id,
        "🏪 <b>SHOP SETTINGS</b>\n\n"
        f"🏷️ Shop name: <b>{clean(get_setting('shop_name'))}</b>\n"
        f"👤 Support username: <b>{clean(get_setting('admin_username'))}</b>\n"
        f"🆔 Order recipient: <code>{clean(get_setting('order_recipient_chat_id') or 'not set')}</code>\n"
        f"🔢 Max custom amount: <b>{clean(get_setting('max_custom_amount', '1000000'))}</b>\n"
        f"🧹 Delete user messages: <b>{'ON' if get_setting('delete_user_messages', '1') == '1' else 'OFF'}</b>\n",
        InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🏷️ Shop Name",
                        callback_data="change_shop_name",
                    ),
                    InlineKeyboardButton(
                        "👤 Support Username",
                        callback_data="change_admin_username",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🆔 Order Recipient",
                        callback_data="change_recipient",
                    ),
                    InlineKeyboardButton(
                        "🔢 Custom Amount Limit",
                        callback_data="change_max_amount",
                    ),
                ],
                [
                    InlineKeyboardButton(
                        "🧹 Toggle Chat Cleanup",
                        callback_data="toggle_cleanup",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "↩️ Admin Panel",
                        callback_data="admin",
                    )
                ],
            ]
        ),
    )


async def show_admins(query):
    admins = get_admins()
    rows = [
        [
            InlineKeyboardButton(
                "➕ Add Admin",
                callback_data="add_admin",
            )
        ]
    ]

    for admin_row in admins:
        label = admin_row["label"] or str(admin_row["telegram_id"])
        rows.append(
            [
                InlineKeyboardButton(
                    f"👮 {label} · {admin_row['telegram_id']}",
                    callback_data=f"remove_admin_confirm:{admin_row['telegram_id']}",
                )
            ]
        )

    rows.extend(back_to_admin())

    await edit_screen(
        query,
        query.from_user.id,
        "👮 <b>ADMINS</b>\n\n"
        "Tap an admin to remove them.\n"
        "The environment bootstrap admin always keeps access.",
        InlineKeyboardMarkup(rows),
    )


# ============================================================
# ADMIN INPUT STARTERS
# ============================================================

def start_admin_action(user_id, action, **data):
    sessions[user_id] = {"action": action, **data}


async def ask_text_input(query, action, prompt, **data):
    start_admin_action(query.from_user.id, action, **data)
    await edit_screen(
        query,
        query.from_user.id,
        prompt,
    )


async def start_add_category(query):
    await ask_text_input(
        query,
        "add_category_name",
        "➕ <b>ADD CATEGORY</b>\n\nSend the category name.\n\nExample: <code>Robux</code>\n\n/cancel to stop.",
    )


async def start_add_product(query, category_id):
    await ask_text_input(
        query,
        "add_product_name",
        "➕ <b>ADD PRODUCT</b>\n\n"
        "Send the product name.\n\n"
        "Example: <code>2,000 Robux</code>",
        category_id=category_id,
    )


async def start_add_currency(query):
    await ask_text_input(
        query,
        "add_currency_name",
        "➕ <b>ADD PAYMENT METHOD</b>\n\n"
        "Send the payment method name.\n\n"
        "Example: <code>USDT</code>",
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

ADMIN_PREFIXES = (
    "admin",
    "add_",
    "edit_",
    "rename_",
    "amount_",
    "toggle_",
    "delete_",
    "product_",
    "category_",
    "currency_",
    "move_",
    "set_price:",
    "set_custom:",
    "prices_currency:",
    "change_",
    "remove_admin",
)


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    user = query.from_user
    user_id = user.id

    # --------------------------------------------------------
    # CUSTOMER
    # --------------------------------------------------------

    if data == "noop":
        return

    if data == "home":
        sessions.pop(user_id, None)
        await edit_screen(
            query,
            user_id,
            render_text("welcome"),
            main_keyboard(),
        )
        return

    if data == "exchange":
        sessions.pop(user_id, None)
        await show_exchange(query)
        return

    if data == "how":
        await show_how(query)
        return

    if data == "currency_back":
        session = sessions.get(user_id)
        if not session:
            await show_exchange(query)
            return
        await show_currency_step(query, session["category_id"])
        return

    if data.startswith("category:"):
        category_id = int(data.split(":", 1)[1])
        category = get_category(category_id)
        if (
            not category
            or not category["enabled"]
            or not category["visibility"]
        ):
            await query.answer(
                "This category is not currently public.",
                show_alert=True,
            )
            return
        await show_currency_step(query, category_id)
        return

    if data.startswith("currency:"):
        currency_id = int(data.split(":", 1)[1])
        await show_products_step(query, currency_id)
        return

    if data.startswith("product:"):
        product_id = int(data.split(":", 1)[1])
        session = sessions.get(user_id)

        if not session or session.get("waiting") != "product":
            await query.answer(
                "Please start a new order.",
                show_alert=True,
            )
            return

        product = get_product(product_id)
        if (
            not product
            or not product["enabled"]
            or not product["visibility"]
            or product["category_id"] != session.get("category_id")
        ):
            await query.answer(
                "This product is unavailable.",
                show_alert=True,
            )
            return

        price = get_price(session["currency_id"], product_id)

        session.update(
            {
                "product_id": product_id,
                "product": product["name"],
                "amount": product["amount"],
                "price": price,
                "waiting": "username",
            }
        )

        await edit_screen(
            query,
            user_id,
            render_text("username"),
            cancel_keyboard(),
        )
        return

    if data == "custom":
        session = sessions.get(user_id)
        if not session or not session.get("currency_id"):
            await query.answer(
                "Please start a new order.",
                show_alert=True,
            )
            return

        session["waiting"] = "custom_amount"
        await edit_screen(
            query,
            user_id,
            render_text("custom"),
            cancel_keyboard(),
        )
        return

    # --------------------------------------------------------
    # ADMIN ACCESS CHECK
    # --------------------------------------------------------

    if data.startswith(ADMIN_PREFIXES):
        if not is_admin(user):
            await query.answer(
                "⛔ Access denied.",
                show_alert=True,
            )
            return

    # --------------------------------------------------------
    # ADMIN HOME
    # --------------------------------------------------------

    if data == "admin":
        await edit_screen(
            query,
            user_id,
            "⚙️ <b>ADMIN PANEL</b>\n\n"
            "Manage your shop directly from Telegram.",
            admin_keyboard(),
        )
        return

    # --------------------------------------------------------
    # CATEGORIES
    # --------------------------------------------------------

    if data == "admin_categories":
        await show_admin_categories(query)
        return

    if data == "add_category":
        await start_add_category(query)
        return

    if data.startswith("edit_category:"):
        await show_edit_category(
            query,
            int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("category_products:"):
        await category_product_list(
            query,
            int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("rename_category:"):
        await ask_text_input(
            query,
            "rename_category",
            "🔤 <b>RENAME CATEGORY</b>\n\nSend the new category name.",
            category_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("category_button:"):
        await ask_text_input(
            query,
            "category_button",
            "🔘 <b>CATEGORY BUTTON</b>\n\nSend the new button text.",
            category_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("category_desc:"):
        await ask_text_input(
            query,
            "category_desc",
            "📝 <b>CATEGORY DESCRIPTION</b>\n\n"
            "Send the description shown under the currency step.\n"
            "Send <code>-</code> for no description.",
            category_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("toggle_category_visibility:"):
        category_id = int(data.split(":", 1)[1])
        conn = db()
        conn.execute(
            """
            UPDATE categories
            SET visibility = CASE WHEN visibility = 1 THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (category_id,),
        )
        conn.commit()
        conn.close()
        await show_edit_category(query, category_id)
        return

    if data.startswith("toggle_category:"):
        category_id = int(data.split(":", 1)[1])
        conn = db()
        conn.execute(
            """
            UPDATE categories
            SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (category_id,),
        )
        conn.commit()
        conn.close()
        await show_edit_category(query, category_id)
        return

    if data.startswith("delete_category:"):
        category_id = int(data.split(":", 1)[1])
        category = get_category(category_id)

        if not category:
            await query.answer("Category not found.", show_alert=True)
            return

        product_count = len(get_products(category_id, False))
        if product_count:
            await query.answer(
                "Move or delete the products in this category first.",
                show_alert=True,
            )
            return

        conn = db()
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
        conn.close()
        await show_admin_categories(query)
        return

    if data.startswith("category_up:") or data.startswith("category_down:"):
        category_id = int(data.split(":", 1)[1])
        direction = -1 if data.startswith("category_up:") else 1

        conn = db()
        current = conn.execute(
            "SELECT * FROM categories WHERE id = ?",
            (category_id,),
        ).fetchone()

        if current:
            neighbor = conn.execute(
                """
                SELECT * FROM categories
                WHERE (sort_order < ? AND ? = -1)
                   OR (sort_order > ? AND ? = 1)
                ORDER BY sort_order
                LIMIT 1
                """,
                (
                    current["sort_order"],
                    direction,
                    current["sort_order"],
                    direction,
                ),
            ).fetchone()

            if neighbor:
                conn.execute(
                    "UPDATE categories SET sort_order = ? WHERE id = ?",
                    (neighbor["sort_order"], current["id"]),
                )
                conn.execute(
                    "UPDATE categories SET sort_order = ? WHERE id = ?",
                    (current["sort_order"], neighbor["id"]),
                )
                conn.commit()

        conn.close()
        await show_admin_categories(query)
        return

    # --------------------------------------------------------
    # PRODUCTS
    # --------------------------------------------------------

    if data == "admin_products":
        await show_admin_products(query)
        return

    if data.startswith("add_product:"):
        await start_add_product(
            query,
            int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("edit_product:"):
        await show_edit_product(
            query,
            int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("rename_product:"):
        await ask_text_input(
            query,
            "rename_product",
            "🔤 <b>EDIT PRODUCT NAME</b>\n\nSend the new name.",
            product_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("product_button:"):
        await ask_text_input(
            query,
            "product_button",
            "🔘 <b>PRODUCT BUTTON</b>\n\nSend the new button text.",
            product_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("amount_product:"):
        await ask_text_input(
            query,
            "change_product_amount",
            "🔢 <b>CHANGE AMOUNT</b>\n\n"
            "Send the new Robux amount.\n"
            "Example: <code>2500</code>",
            product_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("product_desc:"):
        await ask_text_input(
            query,
            "product_desc",
            "📝 <b>PRODUCT DESCRIPTION</b>\n\n"
            "Send a description, or <code>-</code> for none.",
            product_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("move_product:"):
        product_id = int(data.split(":", 1)[1])
        rows = []
        product = get_product(product_id)

        if not product:
            await query.answer("Product not found.", show_alert=True)
            return

        for category in get_categories(False):
            rows.append(
                [
                    InlineKeyboardButton(
                        f"🗂️ {category['name']}",
                        callback_data=f"move_to:{product_id}:{category['id']}",
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    "↩️ Product",
                    callback_data=f"edit_product:{product_id}",
                )
            ]
        )
        await edit_screen(
            query,
            user_id,
            "🗂️ <b>MOVE PRODUCT</b>\n\nChoose its new category.",
            InlineKeyboardMarkup(rows),
        )
        return

    if data.startswith("move_to:"):
        _, product_id, category_id = data.split(":")
        product_id = int(product_id)
        category_id = int(category_id)

        conn = db()
        conn.execute(
            "UPDATE products SET category_id = ? WHERE id = ?",
            (category_id, product_id),
        )
        conn.commit()
        conn.close()

        await show_edit_product(query, product_id)
        return

    if data.startswith("toggle_product_visibility:"):
        product_id = int(data.split(":", 1)[1])
        conn = db()
        conn.execute(
            """
            UPDATE products
            SET visibility = CASE WHEN visibility = 1 THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (product_id,),
        )
        conn.commit()
        conn.close()
        await show_edit_product(query, product_id)
        return

    if data.startswith("toggle_product:"):
        product_id = int(data.split(":", 1)[1])

        conn = db()
        conn.execute(
            """
            UPDATE products
            SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (product_id,),
        )
        conn.commit()
        conn.close()

        await show_edit_product(query, product_id)
        return

    if data.startswith("delete_product:"):
        product_id = int(data.split(":", 1)[1])

        conn = db()
        conn.execute(
            "DELETE FROM prices WHERE product_id = ?",
            (product_id,),
        )
        conn.execute(
            "DELETE FROM products WHERE id = ?",
            (product_id,),
        )
        conn.commit()
        conn.close()

        await show_admin_products(query)
        return

    if data.startswith("product_prices:"):
        await show_product_prices(
            query,
            int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("product_up:") or data.startswith("product_down:"):
        product_id = int(data.split(":", 1)[1])
        direction = -1 if data.startswith("product_up:") else 1

        product = get_product(product_id)
        if product:
            conn = db()
            current = conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()

            neighbor = conn.execute(
                """
                SELECT *
                FROM products
                WHERE category_id = ?
                  AND (
                      (sort_order < ? AND ? = -1)
                      OR
                      (sort_order > ? AND ? = 1)
                  )
                ORDER BY sort_order
                LIMIT 1
                """,
                (
                    current["category_id"],
                    current["sort_order"],
                    direction,
                    current["sort_order"],
                    direction,
                ),
            ).fetchone()

            if neighbor:
                conn.execute(
                    "UPDATE products SET sort_order = ? WHERE id = ?",
                    (neighbor["sort_order"], current["id"]),
                )
                conn.execute(
                    "UPDATE products SET sort_order = ? WHERE id = ?",
                    (current["sort_order"], neighbor["id"]),
                )
                conn.commit()
            conn.close()

        await show_edit_product(query, product_id)
        return

    # --------------------------------------------------------
    # CURRENCIES
    # --------------------------------------------------------

    if data == "admin_currencies":
        await show_admin_currencies(query)
        return

    if data == "add_currency":
        await start_add_currency(query)
        return

    if data.startswith("edit_currency:"):
        await show_edit_currency(
            query,
            int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("rename_currency:"):
        await ask_text_input(
            query,
            "rename_currency",
            "🔤 <b>EDIT PAYMENT METHOD NAME</b>\n\nSend the new name.",
            currency_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("currency_button:"):
        await ask_text_input(
            query,
            "currency_button",
            "🔘 <b>PAYMENT BUTTON</b>\n\nSend the new button text.",
            currency_id=int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("toggle_currency:"):
        currency_id = int(data.split(":", 1)[1])
        conn = db()
        conn.execute(
            """
            UPDATE currencies
            SET enabled = CASE WHEN enabled = 1 THEN 0 ELSE 1 END
            WHERE id = ?
            """,
            (currency_id,),
        )
        conn.commit()
        conn.close()
        await show_edit_currency(query, currency_id)
        return

    if data.startswith("delete_currency:"):
        currency_id = int(data.split(":", 1)[1])
        conn = db()
        conn.execute(
            "DELETE FROM prices WHERE currency_id = ?",
            (currency_id,),
        )
        conn.execute(
            "DELETE FROM custom_prices WHERE currency_id = ?",
            (currency_id,),
        )
        conn.execute(
            "DELETE FROM currencies WHERE id = ?",
            (currency_id,),
        )
        conn.commit()
        conn.close()
        await show_admin_currencies(query)
        return

    if data.startswith("prices_currency:"):
        await show_currency_prices(
            query,
            int(data.split(":", 1)[1]),
        )
        return

    if data.startswith("currency_up:") or data.startswith("currency_down:"):
        currency_id = int(data.split(":", 1)[1])
        direction = -1 if data.startswith("currency_up:") else 1

        conn = db()
        current = conn.execute(
            "SELECT * FROM currencies WHERE id = ?",
            (currency_id,),
        ).fetchone()

        if current:
            neighbor = conn.execute(
                """
                SELECT *
                FROM currencies
                WHERE (sort_order < ? AND ? = -1)
                   OR (sort_order > ? AND ? = 1)
                ORDER BY sort_order
                LIMIT 1
                """,
                (
                    current["sort_order"],
                    direction,
                    current["sort_order"],
                    direction,
                ),
            ).fetchone()

            if neighbor:
                conn.execute(
                    "UPDATE currencies SET sort_order = ? WHERE id = ?",
                    (neighbor["sort_order"], current["id"]),
                )
                conn.execute(
                    "UPDATE currencies SET sort_order = ? WHERE id = ?",
                    (current["sort_order"], neighbor["id"]),
                )
                conn.commit()

        conn.close()
        await show_admin_currencies(query)
        return

    # --------------------------------------------------------
    # PRICES
    # --------------------------------------------------------

    if data == "admin_prices":
        await show_admin_prices(query)
        return

    if data.startswith("set_price:"):
        _, currency_id, product_id = data.split(":")
        await ask_text_input(
            query,
            "set_price",
            "💰 <b>SET PRICE</b>\n\n"
            "Send the new price exactly as it should appear.\n\n"
            "Examples:\n"
            "<code>50</code>\n"
            "<code>50 ⭐</code>\n"
            "<code>100 Stars</code>\n"
            "<code>NA</code>",
            currency_id=int(currency_id),
            product_id=int(product_id),
        )
        return

    if data.startswith("set_custom:"):
        await ask_text_input(
            query,
            "set_custom_price",
            "✏️ <b>CUSTOM AMOUNT PRICE</b>\n\n"
            "Send the price shown for custom amounts.\n\n"
            "Example: <code>NA</code>",
            currency_id=int(data.split(":", 1)[1]),
        )
        return

    # --------------------------------------------------------
    # TEXTS / BUTTONS / SETTINGS
    # --------------------------------------------------------

    if data == "admin_texts":
        await show_texts(query)
        return

    if data.startswith("edit_text:"):
        key = data.split(":", 1)[1]
        current = get_text(key)

        placeholder_help = (
            "Available placeholders:\n"
            "<code>{shop_name}</code> <code>{admin_username}</code> "
            "<code>{order_number}</code> <code>{category}</code> "
            "<code>{currency}</code> <code>{product}</code> "
            "<code>{amount}</code> <code>{price}</code> "
            "<code>{roblox_username}</code> <code>{customer_name}</code> "
            "<code>{customer_username}</code> <code>{telegram_id}</code> "
            "<code>{created_at}</code> <code>{max_custom_amount}</code>"
        )

        await ask_text_input(
            query,
            "edit_text",
            "📝 <b>EDIT TEXT</b>\n\n"
            f"<b>{clean(TEXT_NAMES.get(key, key))}</b>\n\n"
            "<b>Current:</b>\n"
            f"<code>{clean(current)}</code>\n\n"
            "Send the new text. HTML is supported.\n\n"
            f"{placeholder_help}\n\n"
            "/cancel to stop.",
            key=key,
        )
        return

    if data == "admin_buttons":
        await show_buttons(query)
        return

    if data.startswith("edit_button:"):
        key = data.split(":", 1)[1]
        await ask_text_input(
            query,
            "edit_button",
            "🔘 <b>EDIT BUTTON</b>\n\n"
            f"Current: <b>{clean(get_button(key))}</b>\n\n"
            "Send the new button text.",
            key=key,
        )
        return

    if data == "admin_settings":
        await show_settings(query)
        return

    if data == "change_shop_name":
        await ask_text_input(
            query,
            "change_shop_name",
            "🏷️ <b>SHOP NAME</b>\n\n"
            "Send the new shop name.",
        )
        return

    if data == "change_admin_username":
        await ask_text_input(
            query,
            "change_admin_username",
            "👤 <b>SUPPORT USERNAME</b>\n\n"
            "Send the username customers should recognize.\n"
            "Example: <code>@yourusername</code>",
        )
        return

    if data == "change_recipient":
        await ask_text_input(
            query,
            "change_recipient",
            "🆔 <b>ORDER RECIPIENT CHAT ID</b>\n\n"
            "Send the numeric Telegram chat ID that should receive new orders.",
        )
        return

    if data == "change_max_amount":
        await ask_text_input(
            query,
            "change_max_amount",
            "🔢 <b>MAX CUSTOM AMOUNT</b>\n\n"
            "Send the maximum allowed custom Robux amount.\n"
            "Example: <code>1000000</code>",
        )
        return

    if data == "toggle_cleanup":
        current = get_setting("delete_user_messages", "1")
        set_setting("delete_user_messages", "0" if current == "1" else "1")
        await show_settings(query)
        return

    # --------------------------------------------------------
    # ADMINS
    # --------------------------------------------------------

    if data == "admin_admins":
        await show_admins(query)
        return

    if data == "add_admin":
        await ask_text_input(
            query,
            "add_admin_id",
            "➕ <b>ADD ADMIN</b>\n\n"
            "Send the admin's numeric Telegram ID.\n\n"
            "Example: <code>123456789</code>",
        )
        return

    if data.startswith("remove_admin_confirm:"):
        target_id = int(data.split(":", 1)[1])
        await edit_screen(
            query,
            user_id,
            f"⚠️ <b>REMOVE ADMIN?</b>\n\n"
            f"Telegram ID: <code>{target_id}</code>",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Remove",
                            callback_data=f"remove_admin:{target_id}",
                        ),
                        InlineKeyboardButton(
                            "↩️ Keep",
                            callback_data="admin_admins",
                        ),
                    ]
                ]
            ),
        )
        return

    if data.startswith("remove_admin:"):
        target_id = int(data.split(":", 1)[1])

        if BOOTSTRAP_ADMIN_CHAT_ID:
            try:
                if target_id == int(BOOTSTRAP_ADMIN_CHAT_ID):
                    await query.answer(
                        "The bootstrap admin cannot be removed.",
                        show_alert=True,
                    )
                    return
            except ValueError:
                pass

        remove_admin(target_id)
        await show_admins(query)
        return

    # --------------------------------------------------------
    # ORDERS
    # --------------------------------------------------------

    if data == "admin_orders":
        orders = get_orders(25)

        if not orders:
            await edit_screen(
                query,
                user_id,
                "📋 <b>ORDERS</b>\n\nNo orders yet.",
                InlineKeyboardMarkup(back_to_admin()),
            )
            return

        rows = []
        for order in orders:
            status_icon = (
                "⏳"
                if order["status"] == "awaiting_confirmation"
                else "✅"
                if order["status"] == "confirmed"
                else "❌"
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        f"{status_icon} {order['order_number']} · {order['roblox_username']}",
                        callback_data=f"order:{order['order_number']}",
                    )
                ]
            )

        rows.extend(back_to_admin())

        await edit_screen(
            query,
            user_id,
            "📋 <b>RECENT ORDERS</b>\n\n"
            "Tap an order to view its full details.",
            InlineKeyboardMarkup(rows),
        )
        return

    if data.startswith("order:"):
        order_number = data.split(":", 1)[1]
        order = get_order(order_number)

        if not order:
            await query.answer("Order not found.", show_alert=True)
            return

        await edit_screen(
            query,
            user_id,
            "🔔 <b>ORDER DETAILS</b>\n\n"
            f"🔐 Code: <code>{clean(order['order_number'])}</code>\n"
            f"🗂️ Category: <b>{clean(order['category'])}</b>\n"
            f"💱 Payment: <b>{clean(order['currency'])}</b>\n"
            f"📦 Product: <b>{clean(order['product'])}</b>\n"
            f"💰 Amount: <b>{order['robux_amount']:,} Robux</b>\n"
            f"💵 Price: <b>{clean(order['price'])}</b>\n"
            f"👤 Roblox: <code>{clean(order['roblox_username'])}</code>\n"
            f"👤 Customer: <b>{clean(order['telegram_name'])}</b>\n"
            f"📱 Telegram: <b>{clean('@' + order['telegram_username']) if order['telegram_username'] else 'No username'}</b>\n"
            f"🆔 Chat ID: <code>{order['telegram_id']}</code>\n"
            f"📅 Created: <b>{clean(order['created_at'])}</b>\n"
            f"⏳ Status: <b>{clean(order['status'])}</b>",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Confirmed",
                            callback_data=f"order_status:confirmed:{order_number}",
                        ),
                        InlineKeyboardButton(
                            "❌ Rejected",
                            callback_data=f"order_status:rejected:{order_number}",
                        ),
                    ],
                    [
                        InlineKeyboardButton(
                            "↩️ Orders",
                            callback_data="admin_orders",
                        )
                    ],
                ]
            ),
        )
        return

    if data.startswith("order_status:"):
        _, status, order_number = data.split(":", 2)
        order = get_order(order_number)
        if not order:
            await query.answer("Order not found.", show_alert=True)
            return

        set_order_status(order_number, status)

        # Notify customer using the same secret code.
        notification = {
            "confirmed": (
                "✅ <b>ORDER CONFIRMED</b>\n\n"
                "🔐 Code: <code>{order_number}</code>\n\n"
                "Your order has been confirmed."
            ),
            "rejected": (
                "❌ <b>ORDER REJECTED</b>\n\n"
                "🔐 Code: <code>{order_number}</code>\n\n"
                "Your order was rejected by the team. Please contact support if you need help."
            ),
        }[status].format(order_number=clean(order_number))

        try:
            await context.bot.send_message(
                chat_id=order["telegram_id"],
                text=notification,
                parse_mode="HTML",
            )
        except TelegramError as error:
            logger.warning(
                "Could not notify customer for order %s: %s",
                order_number,
                error,
            )

        await edit_screen(
            query,
            user_id,
            "✅ <b>ORDER UPDATED</b>\n\n"
            f"Order <code>{clean(order_number)}</code> is now <b>{clean(status)}</b>.",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📋 Orders",
                            callback_data="admin_orders",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⚙️ Admin Panel",
                            callback_data="admin",
                        )
                    ],
                ]
            ),
        )
        return


# ============================================================
# ADMIN TEXT INPUT
# ============================================================

async def handle_admin_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session,
    text,
):
    user = update.effective_user
    user_id = user.id
    action = session.get("action")

    if action == "add_category_name":
        name = text.strip()
        if not name:
            return

        try:
            conn = db()
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS n FROM categories"
            ).fetchone()["n"]

            cursor = conn.execute(
                """
                INSERT INTO categories
                (name, button_text, description, enabled, sort_order)
                VALUES (?, ?, '', 1, ?)
                """,
                (name, name, max_order + 1),
            )
            category_id = cursor.lastrowid
            conn.commit()
            conn.close()
        except sqlite3.IntegrityError:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ <b>CATEGORY ALREADY EXISTS</b>\n\n"
                "Choose another name.",
            )
            return

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>CATEGORY CREATED</b>\n\n"
            f"🗂️ {clean(name)}",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🗂️ Categories",
                            callback_data="admin_categories",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⚙️ Admin Panel",
                            callback_data="admin",
                        )
                    ],
                ]
            ),
        )
        return

    if action == "rename_category":
        category_id = session["category_id"]
        try:
            conn = db()
            conn.execute(
                "UPDATE categories SET name = ? WHERE id = ?",
                (text, category_id),
            )
            conn.commit()
            conn.close()
        except sqlite3.IntegrityError:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Another category already uses that name.",
            )
            return

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>CATEGORY UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🗂️ Categories",
                        callback_data="admin_categories",
                    )
                ]]
            ),
        )
        return

    if action == "category_button":
        conn = db()
        conn.execute(
            "UPDATE categories SET button_text = ? WHERE id = ?",
            (text, session["category_id"]),
        )
        conn.commit()
        conn.close()

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>CATEGORY BUTTON UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🗂️ Categories",
                        callback_data="admin_categories",
                    )
                ]]
            ),
        )
        return

    if action == "category_desc":
        description = "" if text == "-" else text
        conn = db()
        conn.execute(
            "UPDATE categories SET description = ? WHERE id = ?",
            (description, session["category_id"]),
        )
        conn.commit()
        conn.close()

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>CATEGORY DESCRIPTION UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🗂️ Categories",
                        callback_data="admin_categories",
                    )
                ]]
            ),
        )
        return

    if action == "add_product_name":
        session["product_name"] = text
        session["action"] = "add_product_amount"

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "🔢 <b>PRODUCT AMOUNT</b>\n\n"
            "Send the amount of Robux.\n"
            "Example: <code>2000</code>",
        )
        return

    if action == "add_product_amount":
        cleaned = text.replace(",", "").replace(" ", "")

        if not cleaned.isdigit():
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Please enter numbers only.\n\nExample: <code>2000</code>",
            )
            return

        amount = int(cleaned)
        if amount <= 0:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Amount must be greater than 0.",
            )
            return

        category_id = session["category_id"]

        conn = db()
        max_order = conn.execute(
            """
            SELECT COALESCE(MAX(sort_order), 0) AS n
            FROM products
            WHERE category_id = ?
            """,
            (category_id,),
        ).fetchone()["n"]

        cursor = conn.execute(
            """
            INSERT INTO products
            (name, button_text, amount, category_id, description, enabled, sort_order)
            VALUES (?, ?, ?, ?, '', 1, ?)
            """,
            (
                session["product_name"],
                session["product_name"],
                amount,
                category_id,
                max_order + 1,
            ),
        )
        product_id = cursor.lastrowid

        currencies = conn.execute("SELECT id FROM currencies").fetchall()
        for currency in currencies:
            conn.execute(
                """
                INSERT OR IGNORE INTO prices(currency_id, product_id, price)
                VALUES (?, ?, 'NA')
                """,
                (currency["id"], product_id),
            )

        conn.commit()
        conn.close()
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>PRODUCT CREATED</b>\n\n"
            f"📦 {clean(session['product_name'])}\n"
            f"🔢 {amount:,} Robux",
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📦 Products",
                            callback_data=f"category_products:{category_id}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⚙️ Admin Panel",
                            callback_data="admin",
                        )
                    ],
                ]
            ),
        )
        return

    if action == "rename_product":
        conn = db()
        conn.execute(
            "UPDATE products SET name = ? WHERE id = ?",
            (text, session["product_id"]),
        )
        conn.commit()
        conn.close()

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>PRODUCT NAME UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "📦 Products",
                        callback_data="admin_products",
                    )
                ]]
            ),
        )
        return

    if action == "product_button":
        conn = db()
        conn.execute(
            "UPDATE products SET button_text = ? WHERE id = ?",
            (text, session["product_id"]),
        )
        conn.commit()
        conn.close()

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>PRODUCT BUTTON UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "📦 Products",
                        callback_data="admin_products",
                    )
                ]]
            ),
        )
        return

    if action == "change_product_amount":
        cleaned = text.replace(",", "").replace(" ", "")
        if not cleaned.isdigit() or int(cleaned) <= 0:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Enter a positive whole number.",
            )
            return

        amount = int(cleaned)
        conn = db()
        conn.execute(
            "UPDATE products SET amount = ? WHERE id = ?",
            (amount, session["product_id"]),
        )
        conn.commit()
        conn.close()

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            f"✅ <b>AMOUNT UPDATED</b>\n\n"
            f"New amount: <b>{amount:,} Robux</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "📦 Products",
                        callback_data="admin_products",
                    )
                ]]
            ),
        )
        return

    if action == "product_desc":
        description = "" if text == "-" else text
        conn = db()
        conn.execute(
            "UPDATE products SET description = ? WHERE id = ?",
            (description, session["product_id"]),
        )
        conn.commit()
        conn.close()

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>PRODUCT DESCRIPTION UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "📦 Products",
                        callback_data="admin_products",
                    )
                ]]
            ),
        )
        return

    if action == "add_currency_name":
        name = text.strip()
        if not name:
            return

        try:
            conn = db()
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS n FROM currencies"
            ).fetchone()["n"]

            cursor = conn.execute(
                """
                INSERT INTO currencies
                (name, button_text, enabled, sort_order)
                VALUES (?, ?, 1, ?)
                """,
                (name, name, max_order + 1),
            )
            currency_id = cursor.lastrowid

            products = conn.execute(
                "SELECT id FROM products"
            ).fetchall()

            for product in products:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO prices(currency_id, product_id, price)
                    VALUES (?, ?, 'NA')
                    """,
                    (currency_id, product["id"]),
                )

            conn.execute(
                """
                INSERT OR IGNORE INTO custom_prices(currency_id, price)
                VALUES (?, 'NA')
                """,
                (currency_id,),
            )

            conn.commit()
            conn.close()
        except sqlite3.IntegrityError:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ That payment method already exists.",
            )
            return

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>PAYMENT METHOD CREATED</b>\n\n"
            f"💱 {clean(name)}",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "💱 Payment Methods",
                        callback_data="admin_currencies",
                    )
                ]]
            ),
        )
        return

    if action == "rename_currency":
        currency_id = session["currency_id"]
        try:
            conn = db()
            conn.execute(
                "UPDATE currencies SET name = ? WHERE id = ?",
                (text, currency_id),
            )
            conn.commit()
            conn.close()
        except sqlite3.IntegrityError:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Another payment method already uses that name.",
            )
            return

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>PAYMENT METHOD UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "💱 Payment Methods",
                        callback_data="admin_currencies",
                    )
                ]]
            ),
        )
        return

    if action == "currency_button":
        conn = db()
        conn.execute(
            "UPDATE currencies SET button_text = ? WHERE id = ?",
            (text, session["currency_id"]),
        )
        conn.commit()
        conn.close()

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>PAYMENT BUTTON UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "💱 Payment Methods",
                        callback_data="admin_currencies",
                    )
                ]]
            ),
        )
        return

    if action == "set_price":
        price = text.strip() or "NA"
        set_price(
            session["currency_id"],
            session["product_id"],
            price,
        )

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            f"✅ <b>PRICE UPDATED</b>\n\n"
            f"New price: <b>{clean(price)}</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "💰 Prices",
                        callback_data="admin_prices",
                    )
                ]]
            ),
        )
        return

    if action == "set_custom_price":
        price = text.strip() or "NA"
        set_custom_price(
            session["currency_id"],
            price,
        )

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            f"✅ <b>CUSTOM PRICE UPDATED</b>\n\n"
            f"New price: <b>{clean(price)}</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "💰 Prices",
                        callback_data="admin_prices",
                    )
                ]]
            ),
        )
        return

    if action == "edit_text":
        set_text(session["key"], text)
        key = session["key"]
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            f"✅ <b>TEXT UPDATED</b>\n\n"
            f"Section: <b>{clean(TEXT_NAMES.get(key, key))}</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "📝 Texts / Steps",
                        callback_data="admin_texts",
                    )
                ]]
            ),
        )
        return

    if action == "edit_button":
        set_button(session["key"], text)
        key = session["key"]
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            f"✅ <b>BUTTON UPDATED</b>\n\n"
            f"Button: <b>{clean(BUTTON_NAMES.get(key, key))}</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🔘 Buttons",
                        callback_data="admin_buttons",
                    )
                ]]
            ),
        )
        return

    if action == "change_shop_name":
        set_setting("shop_name", text)
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>SHOP NAME UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🏪 Settings",
                        callback_data="admin_settings",
                    )
                ]]
            ),
        )
        return

    if action == "change_admin_username":
        username = text if text.startswith("@") else "@" + text
        set_setting("admin_username", username)
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>SUPPORT USERNAME UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🏪 Settings",
                        callback_data="admin_settings",
                    )
                ]]
            ),
        )
        return

    if action == "change_recipient":
        cleaned = text.strip()
        if not cleaned.lstrip("-").isdigit():
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Chat ID must be numeric.",
            )
            return

        set_setting("order_recipient_chat_id", cleaned)
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>ORDER RECIPIENT UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🏪 Settings",
                        callback_data="admin_settings",
                    )
                ]]
            ),
        )
        return

    if action == "change_max_amount":
        cleaned = text.replace(",", "").replace(" ", "")
        if not cleaned.isdigit() or int(cleaned) <= 0:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Please enter a positive whole number.",
            )
            return

        set_setting("max_custom_amount", str(int(cleaned)))
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>CUSTOM AMOUNT LIMIT UPDATED</b>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "🏪 Settings",
                        callback_data="admin_settings",
                    )
                ]]
            ),
        )
        return

    if action == "add_admin_id":
        cleaned = text.strip()
        if not cleaned.isdigit():
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                "⚠️ Telegram ID must contain numbers only.",
            )
            return

        target_id = int(cleaned)
        add_admin(target_id)

        sessions.pop(user_id, None)
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            "✅ <b>ADMIN ADDED</b>\n\n"
            f"🆔 <code>{target_id}</code>",
            InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(
                        "👮 Admins",
                        callback_data="admin_admins",
                    )
                ]]
            ),
        )
        return


# ============================================================
# CUSTOMER TEXT INPUT / ORDER CREATION
# ============================================================

def generate_order_number():
    # 10 random uppercase base32-ish characters, with no predictable
    # sequence. Example: SRP-X7KQ9M2P4A
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    for _ in range(20):
        token = "".join(secrets.choice(alphabet) for _ in range(10))
        candidate = f"SRP-{token}"

        if not get_order(candidate):
            return candidate

    raise RuntimeError("Could not generate a unique order number.")


async def create_order(update, context, session, username):
    user = update.effective_user
    user_id = user.id

    currency = get_currency(session.get("currency_id"))
    category = get_category(session.get("category_id"))

    if not currency or not category:
        return None

    order_number = generate_order_number()
    created_at = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    telegram_username = user.username or ""
    telegram_name = user.full_name or ""

    conn = db()
    conn.execute(
        """
        INSERT INTO orders
        (
            order_number,
            telegram_id,
            telegram_username,
            telegram_name,
            category,
            currency,
            product,
            robux_amount,
            price,
            roblox_username,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_number,
            user_id,
            telegram_username,
            telegram_name,
            category["name"],
            currency["name"],
            session["product"],
            int(session["amount"]),
            session["price"],
            username,
            "awaiting_confirmation",
            created_at,
        ),
    )
    conn.commit()
    conn.close()

    recipient = get_setting("order_recipient_chat_id", "").strip()

    if not recipient and BOOTSTRAP_ADMIN_CHAT_ID:
        recipient = BOOTSTRAP_ADMIN_CHAT_ID

    if recipient:
        try:
            admin_text = render_text(
                "admin_new_order",
                order_number=order_number,
                category=category["name"],
                currency=currency["name"],
                product=session["product"],
                amount=int(session["amount"]),
                price=session["price"],
                roblox_username=username,
                created_at=created_at,
                customer_name=telegram_name,
                customer_username=(
                    f"@{telegram_username}"
                    if telegram_username
                    else "No username"
                ),
                telegram_id=user_id,
            )

            await context.bot.send_message(
                chat_id=int(recipient),
                text=admin_text,
                parse_mode="HTML",
            )

            return {
                "order_number": order_number,
                "admin_notified": True,
                "admin_error": "",
            }

        except (TelegramError, ValueError) as error:
            logger.error(
                "Admin notification failed for order %s: %s",
                order_number,
                error,
            )
            return {
                "order_number": order_number,
                "admin_notified": False,
                "admin_error": str(error),
            }

    return {
        "order_number": order_number,
        "admin_notified": False,
        "admin_error": "No order recipient chat ID is configured.",
    }


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    session = sessions.get(user_id)

    # Remove the user's text message when permitted.
    await clear_user_message(update)

    if text.lower() == "/cancel":
        sessions.pop(user_id, None)

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            render_text("cancelled"),
            main_keyboard(),
        )
        return

    # --------------------------------------------------------
    # ADMIN INPUT
    # --------------------------------------------------------

    if is_admin(user) and session and session.get("action"):
        await handle_admin_input(
            update,
            context,
            session,
            text,
        )
        return

    # --------------------------------------------------------
    # CUSTOMER INPUT
    # --------------------------------------------------------

    if not session:
        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            render_text("no_session"),
            main_keyboard(),
        )
        return

    if session.get("waiting") == "custom_amount":
        cleaned = text.replace(",", "").replace(" ", "")

        if not cleaned.isdigit():
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                render_text(
                    "invalid_amount",
                    max_custom_amount=get_setting(
                        "max_custom_amount",
                        "1000000",
                    ),
                ),
                cancel_keyboard(),
            )
            return

        amount = int(cleaned)
        max_amount = int(
            get_setting("max_custom_amount", "1000000")
        )

        if amount <= 0 or amount > max_amount:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                render_text(
                    "invalid_amount",
                    max_custom_amount=max_amount,
                ),
                cancel_keyboard(),
            )
            return

        session["amount"] = amount
        session["product"] = "Custom Amount"
        session["price"] = get_custom_price(
            session["currency_id"]
        )
        session["waiting"] = "username"

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            render_text("username"),
            cancel_keyboard(),
        )
        return

    if session.get("waiting") == "username":
        username = text.lstrip("@")

        if (
            len(username) < 3
            or len(username) > 20
            or not all(
                character.isalnum() or character == "_"
                for character in username
            )
        ):
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                render_text("invalid_username"),
                cancel_keyboard(),
            )
            return

        try:
            order_result = await create_order(
                update,
                context,
                session,
                username,
            )
        except Exception:
            logger.exception("Failed to create order")
            order_result = None

        if not order_result:
            await remember_screen(
                context.bot,
                update.effective_chat.id,
                user_id,
                render_text("order_error"),
                main_keyboard(),
            )
            return

        sessions.pop(user_id, None)

        # If admin notification failed, the order still exists and is visible
        # inside the admin Orders panel after the recipient is fixed.
        if not order_result["admin_notified"]:
            logger.warning(
                "Order %s created without a successful admin notification: %s",
                order_result["order_number"],
                order_result["admin_error"],
            )

        await remember_screen(
            context.bot,
            update.effective_chat.id,
            user_id,
            render_text(
                "confirmation",
                order_number=order_result["order_number"],
            ),
            InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            get_button("new_order", "💱 New Order"),
                            callback_data="exchange",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            get_button("home", "🏠 Main Menu"),
                            callback_data="home",
                        )
                    ],
                ]
            ),
        )
        return


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(update, context):
    logger.error(
        "Unhandled exception:",
        exc_info=context.error,
    )


# ============================================================
# RUN
# ============================================================

def run():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN is missing from Railway Variables."
        )

    if BOT_TOKEN == "BOT_TOKEN":
        raise RuntimeError(
            "BOT_TOKEN is still set to the placeholder 'BOT_TOKEN'."
        )

    init_db()
    logger.info("Database initialized.")

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("admin", admin)
    )

    application.add_handler(
        CallbackQueryHandler(callback_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    application.add_error_handler(error_handler)

    logger.info("SRPExchange bot starting...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    run()
