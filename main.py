import os
import html
import sqlite3
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

DATABASE_FILE = os.getenv("DATABASE_FILE", "shop.db")

DEFAULT_ADMIN_USERNAME = "berizienuhq"

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
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS currencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            button_text TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            button_text TEXT NOT NULL,
            amount INTEGER NOT NULL,
            enabled INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            currency_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price TEXT NOT NULL DEFAULT 'NA',
            PRIMARY KEY(currency_id, product_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS custom_prices (
            currency_id INTEGER PRIMARY KEY,
            price TEXT NOT NULL DEFAULT 'NA'
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS texts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS buttons (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            telegram_id INTEGER NOT NULL,
            telegram_username TEXT,
            telegram_name TEXT,
            currency TEXT NOT NULL,
            product TEXT NOT NULL,
            robux_amount INTEGER NOT NULL,
            price TEXT NOT NULL,
            roblox_username TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    settings = {
        "shop_name": "R$ EXCHANGE",
        "admin_username": "@berizienuhq",
    }

    for key, value in settings.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO settings(key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    currencies = [
        ("GRAM", "💎 GRAM", 1),
        ("Telegram Stars", "⭐ Telegram Stars", 2),
    ]

    for name, button_text, order in currencies:
        cur.execute(
            """
            INSERT OR IGNORE INTO currencies
            (name, button_text, enabled, sort_order)
            VALUES (?, ?, 1, ?)
            """,
            (name, button_text, order),
        )

    products = [
        ("200 R$", "200 R$", 200, 1),
        ("500 R$", "500 R$", 500, 2),
        ("700 R$", "700 R$", 700, 3),
        ("1,000 R$", "1,000 R$", 1000, 4),
    ]

    for name, button_text, amount, order in products:
        cur.execute(
            """
            INSERT OR IGNORE INTO products
            (name, button_text, amount, enabled, sort_order)
            VALUES (?, ?, ?, 1, ?)
            """,
            (name, button_text, amount, order),
        )

    texts = {
        "welcome": (
            "🛍️ <b>{shop_name}</b>\n\n"
            "Welcome!\n\n"
            "Choose what you'd like to do:"
        ),
        "currency": (
            "💱 <b>SELECT CURRENCY</b>\n\n"
            "Choose the currency you want to exchange:"
        ),
        "product": (
            "💰 <b>SELECT AMOUNT</b>\n\n"
            "Choose the amount of Robux:"
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
        "confirmation": (
            "✅ <b>ORDER {order_id}</b>\n\n"
            "We have received your order.\n\n"
            "📩 Please wait for a DM from "
            "<b>{admin_username}</b> "
            "to finalise the exchange.\n\n"
            "Thank you for using <b>{shop_name}</b>."
        ),
        "how": (
            "ℹ️ <b>HOW IT WORKS</b>\n\n"
            "1️⃣ Select a currency.\n"
            "2️⃣ Select your Robux amount.\n"
            "3️⃣ Enter your Roblox username.\n"
            "4️⃣ Your order is created.\n"
            "5️⃣ Wait for a DM from "
            "<b>{admin_username}</b>."
        ),
    }

    for key, value in texts.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO texts(key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    buttons = {
        "exchange": "💱 Exchange",
        "how": "ℹ️ How It Works",
        "custom": "✏️ Custom Amount",
        "back": "↩️ Back",
        "home": "🏠 Main Menu",
        "new_order": "💱 New Order",
        "cancel": "❌ Cancel",
    }

    for key, value in buttons.items():
        cur.execute(
            """
            INSERT OR IGNORE INTO buttons(key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

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
        (key, value),
    )

    conn.commit()
    conn.close()


def get_text(key):
    conn = db()
    row = conn.execute(
        "SELECT value FROM texts WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()

    return row["value"] if row else ""


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


def get_button(key):
    conn = db()
    row = conn.execute(
        "SELECT value FROM buttons WHERE key = ?",
        (key,),
    ).fetchone()
    conn.close()

    return row["value"] if row else key


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


def get_currencies(enabled_only=False):
    conn = db()

    if enabled_only:
        rows = conn.execute(
            """
            SELECT * FROM currencies
            WHERE enabled = 1
            ORDER BY sort_order, id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM currencies
            ORDER BY sort_order, id
            """
        ).fetchall()

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


def get_products(enabled_only=False):
    conn = db()

    if enabled_only:
        rows = conn.execute(
            """
            SELECT * FROM products
            WHERE enabled = 1
            ORDER BY sort_order, id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM products
            ORDER BY sort_order, id
            """
        ).fetchall()

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
        SELECT price FROM prices
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
        (currency_id, product_id, price),
    )

    conn.commit()
    conn.close()


def get_custom_price(currency_id):
    conn = db()

    row = conn.execute(
        """
        SELECT price FROM custom_prices
        WHERE currency_id = ?
        """,
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
        (currency_id, price),
    )

    conn.commit()
    conn.close()


# ============================================================
# ADMIN
# ============================================================

def is_admin(user):
    if not user:
        return False

    if ADMIN_CHAT_ID:
        try:
            if user.id == int(ADMIN_CHAT_ID):
                return True
        except ValueError:
            pass

    if user.username:
        if user.username.lower() == DEFAULT_ADMIN_USERNAME.lower():
            return True

    return False


# ============================================================
# SESSION
# ============================================================

sessions = {}


# ============================================================
# FORMATTING
# ============================================================

def shop_text(key, **extra):
    values = {
        "shop_name": get_setting("shop_name", "R$ EXCHANGE"),
        "admin_username": get_setting(
            "admin_username",
            "@berizienuhq",
        ),
    }

    values.update(extra)

    text = get_text(key)

    try:
        return text.format(**values)
    except Exception:
        return text


def clean(value):
    return html.escape(str(value))


# ============================================================
# CUSTOMER KEYBOARDS
# ============================================================

def main_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                get_button("exchange"),
                callback_data="exchange",
            )
        ],
        [
            InlineKeyboardButton(
                get_button("how"),
                callback_data="how",
            )
        ],
    ])


def currency_keyboard():
    rows = []

    for currency in get_currencies(True):
        rows.append([
            InlineKeyboardButton(
                currency["button_text"],
                callback_data=f"currency:{currency['id']}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            get_button("back"),
            callback_data="home",
        )
    ])

    return InlineKeyboardMarkup(rows)


def product_keyboard():
    rows = []
    current = []

    for product in get_products(True):

        current.append(
            InlineKeyboardButton(
                product["button_text"],
                callback_data=f"product:{product['id']}",
            )
        )

        if len(current) == 2:
            rows.append(current)
            current = []

    if current:
        rows.append(current)

    rows.append([
        InlineKeyboardButton(
            get_button("custom"),
            callback_data="custom",
        )
    ])

    rows.append([
        InlineKeyboardButton(
            get_button("back"),
            callback_data="exchange",
        )
    ])

    return InlineKeyboardMarkup(rows)


# ============================================================
# START
# ============================================================

async def start(update, context):

    sessions.pop(update.effective_user.id, None)

    await update.message.reply_text(
        shop_text("welcome"),
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ============================================================
# ADMIN PANEL
# ============================================================

def admin_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📦 Products",
                callback_data="admin_products",
            )
        ],
        [
            InlineKeyboardButton(
                "💱 Currencies",
                callback_data="admin_currencies",
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Prices",
                callback_data="admin_prices",
            )
        ],
        [
            InlineKeyboardButton(
                "📝 Texts",
                callback_data="admin_texts",
            )
        ],
        [
            InlineKeyboardButton(
                "🔘 Buttons",
                callback_data="admin_buttons",
            )
        ],
        [
            InlineKeyboardButton(
                "🏪 Shop Settings",
                callback_data="admin_settings",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Orders",
                callback_data="admin_orders",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Shop",
                callback_data="home",
            )
        ],
    ])


async def admin(update, context):

    if not is_admin(update.effective_user):
        await update.message.reply_text(
            "⛔ You don't have permission to access the admin panel."
        )
        return

    await update.message.reply_text(
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "Manage your entire shop from here.\n\n"
        "Changes are saved automatically.",
        parse_mode="HTML",
        reply_markup=admin_keyboard(),
    )


# ============================================================
# ADMIN PRODUCT PANEL
# ============================================================

def product_admin_keyboard():
    rows = [
        [
            InlineKeyboardButton(
                "➕ Add Product",
                callback_data="add_product",
            )
        ]
    ]

    for product in get_products():

        status = "🟢" if product["enabled"] else "🔴"

        rows.append([
            InlineKeyboardButton(
                f"{status} {product['button_text']}",
                callback_data=f"edit_product:{product['id']}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "↩️ Admin Panel",
            callback_data="admin",
        )
    ])

    return InlineKeyboardMarkup(rows)


async def show_products(query):

    products = get_products()

    if products:
        description = (
            "Tap a product to edit it.\n\n"
            + "\n".join(
                f"• {p['button_text']} — {p['amount']:,} R$"
                for p in products
            )
        )
    else:
        description = "No products yet."

    await query.edit_message_text(
        "📦 <b>PRODUCTS</b>\n\n" + description,
        parse_mode="HTML",
        reply_markup=product_admin_keyboard(),
    )


# ============================================================
# ADD PRODUCT
# ============================================================

async def add_product_start(query):

    user_id = query.from_user.id

    sessions[user_id] = {
        "action": "add_product_name"
    }

    await query.edit_message_text(
        "➕ <b>ADD PRODUCT</b>\n\n"
        "Send the text you want to appear on the product button.\n\n"
        "Example:\n"
        "<code>💎 2,000 R$</code>\n\n"
        "Send /cancel to stop.",
        parse_mode="HTML",
    )


# ============================================================
# EDIT PRODUCT
# ============================================================

def edit_product_keyboard(product_id):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔤 Rename Button",
                callback_data=f"rename_product:{product_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🔢 Change Amount",
                callback_data=f"amount_product:{product_id}",
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
                "🗑️ Delete Product",
                callback_data=f"delete_product:{product_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Products",
                callback_data="admin_products",
            )
        ],
    ])


async def show_edit_product(query, product_id):

    product = get_product(product_id)

    if not product:
        await query.answer("Product not found.", show_alert=True)
        return

    status = "🟢 Enabled" if product["enabled"] else "🔴 Disabled"

    await query.edit_message_text(
        "📦 <b>EDIT PRODUCT</b>\n\n"
        f"🔘 Button: <b>{clean(product['button_text'])}</b>\n"
        f"🔢 Amount: <b>{product['amount']:,} R$</b>\n"
        f"📌 Status: <b>{status}</b>",
        parse_mode="HTML",
        reply_markup=edit_product_keyboard(product_id),
    )


# ============================================================
# CURRENCY ADMIN PANEL
# ============================================================

def currency_admin_keyboard():

    rows = [
        [
            InlineKeyboardButton(
                "➕ Add Currency",
                callback_data="add_currency",
            )
        ]
    ]

    for currency in get_currencies():

        status = "🟢" if currency["enabled"] else "🔴"

        rows.append([
            InlineKeyboardButton(
                f"{status} {currency['button_text']}",
                callback_data=f"edit_currency:{currency['id']}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "↩️ Admin Panel",
            callback_data="admin",
        )
    ])

    return InlineKeyboardMarkup(rows)


async def show_currencies(query):

    await query.edit_message_text(
        "💱 <b>CURRENCIES</b>\n\n"
        "Add, rename, enable, disable or delete currencies.",
        parse_mode="HTML",
        reply_markup=currency_admin_keyboard(),
    )


# ============================================================
# ADD CURRENCY
# ============================================================

async def add_currency_start(query):

    sessions[query.from_user.id] = {
        "action": "add_currency_name"
    }

    await query.edit_message_text(
        "➕ <b>ADD CURRENCY</b>\n\n"
        "Send the currency name.\n\n"
        "Example:\n"
        "<code>TON</code>",
        parse_mode="HTML",
    )


# ============================================================
# EDIT CURRENCY
# ============================================================

def edit_currency_keyboard(currency_id):

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔤 Rename",
                callback_data=f"rename_currency:{currency_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🔘 Change Button",
                callback_data=f"currency_button:{currency_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🟢 / 🔴 Enable / Disable",
                callback_data=f"toggle_currency:{currency_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🗑️ Delete Currency",
                callback_data=f"delete_currency:{currency_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Currencies",
                callback_data="admin_currencies",
            )
        ],
    ])


async def show_edit_currency(query, currency_id):

    currency = get_currency(currency_id)

    if not currency:
        await query.answer(
            "Currency not found.",
            show_alert=True,
        )
        return

    status = (
        "🟢 Enabled"
        if currency["enabled"]
        else "🔴 Disabled"
    )

    await query.edit_message_text(
        "💱 <b>EDIT CURRENCY</b>\n\n"
        f"🏷️ Name: <b>{clean(currency['name'])}</b>\n"
        f"🔘 Button: <b>{clean(currency['button_text'])}</b>\n"
        f"📌 Status: <b>{status}</b>",
        parse_mode="HTML",
        reply_markup=edit_currency_keyboard(currency_id),
    )


# ============================================================
# PRICE PANEL
# ============================================================

async def show_prices(query):

    currencies = get_currencies()

    rows = []

    for currency in currencies:

        rows.append([
            InlineKeyboardButton(
                f"💰 {currency['name']}",
                callback_data=f"prices_currency:{currency['id']}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "↩️ Admin Panel",
            callback_data="admin",
        )
    ])

    await query.edit_message_text(
        "💰 <b>PRICE MANAGEMENT</b>\n\n"
        "Choose a currency to edit its prices.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def show_currency_prices(query, currency_id):

    currency = get_currency(currency_id)

    if not currency:
        return

    rows = []

    for product in get_products():

        price = get_price(
            currency_id,
            product["id"],
        )

        rows.append([
            InlineKeyboardButton(
                f"{product['button_text']} → {price}",
                callback_data=(
                    f"set_price:{currency_id}:"
                    f"{product['id']}"
                ),
            )
        ])

    custom = get_custom_price(currency_id)

    rows.append([
        InlineKeyboardButton(
            f"✏️ Custom Amount → {custom}",
            callback_data=f"set_custom:{currency_id}",
        )
    ])

    rows.append([
        InlineKeyboardButton(
            "↩️ Currencies",
            callback_data="admin_prices",
        )
    ])

    await query.edit_message_text(
        f"💰 <b>{clean(currency['name'])} PRICES</b>\n\n"
        "Tap a price to change it.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ============================================================
# TEXT PANEL
# ============================================================

TEXT_NAMES = {
    "welcome": "👋 Welcome Message",
    "currency": "💱 Currency Selection",
    "product": "💰 Product Selection",
    "custom": "✏️ Custom Amount",
    "username": "👤 Username Request",
    "confirmation": "✅ Order Confirmation",
    "how": "ℹ️ How It Works",
}


async def show_texts(query):

    rows = []

    for key, name in TEXT_NAMES.items():

        rows.append([
            InlineKeyboardButton(
                name,
                callback_data=f"edit_text:{key}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "↩️ Admin Panel",
            callback_data="admin",
        )
    ])

    await query.edit_message_text(
        "📝 <b>TEXT EDITOR</b>\n\n"
        "Choose a message to edit.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ============================================================
# BUTTON PANEL
# ============================================================

BUTTON_NAMES = {
    "exchange": "💱 Exchange",
    "how": "ℹ️ How It Works",
    "custom": "✏️ Custom Amount",
    "back": "↩️ Back",
    "home": "🏠 Main Menu",
    "new_order": "💱 New Order",
    "cancel": "❌ Cancel",
}


async def show_buttons(query):

    rows = []

    for key, name in BUTTON_NAMES.items():

        rows.append([
            InlineKeyboardButton(
                f"{name}: {get_button(key)}",
                callback_data=f"edit_button:{key}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            "↩️ Admin Panel",
            callback_data="admin",
        )
    ])

    await query.edit_message_text(
        "🔘 <b>BUTTON EDITOR</b>\n\n"
        "Tap a button to rename it.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(rows),
    )


# ============================================================
# SETTINGS
# ============================================================

async def show_settings(query):

    await query.edit_message_text(
        "🏪 <b>SHOP SETTINGS</b>\n\n"
        f"🏷️ Shop name:\n"
        f"<b>{clean(get_setting('shop_name'))}</b>\n\n"
        f"👤 Admin username:\n"
        f"<b>{clean(get_setting('admin_username'))}</b>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "🏷️ Change Shop Name",
                    callback_data="change_shop_name",
                )
            ],
            [
                InlineKeyboardButton(
                    "👤 Change Admin Username",
                    callback_data="change_admin",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Admin Panel",
                    callback_data="admin",
                )
            ],
        ]),
    )


# ============================================================
# ORDERS
# ============================================================

async def show_orders(query):

    conn = db()

    orders = conn.execute(
        """
        SELECT *
        FROM orders
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if not orders:

        text = (
            "📋 <b>ORDERS</b>\n\n"
            "No orders yet."
        )

    else:

        lines = [
            "📋 <b>RECENT ORDERS</b>\n"
        ]

        for order in orders:

            lines.append(
                f"<b>{clean(order['order_number'])}</b>\n"
                f"💰 {order['robux_amount']:,} R$\n"
                f"💱 {clean(order['currency'])}\n"
                f"👤 {clean(order['roblox_username'])}\n"
                f"⭐ {clean(order['price'])}\n"
                f"📅 {clean(order['created_at'])}\n"
            )

        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "↩️ Admin Panel",
                    callback_data="admin",
                )
            ]
        ]),
    )


# ============================================================
# CALLBACK HANDLER
# ============================================================

async def callback_handler(update, context):

    query = update.callback_query
    await query.answer()

    data = query.data
    user = query.from_user
    user_id = user.id

    # --------------------------------------------------------
    # CUSTOMER
    # --------------------------------------------------------

    if data == "home":

        sessions.pop(user_id, None)

        await query.edit_message_text(
            shop_text("welcome"),
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return

    if data == "exchange":

        await query.edit_message_text(
            shop_text("currency"),
            parse_mode="HTML",
            reply_markup=currency_keyboard(),
        )
        return

    if data == "how":

        await query.edit_message_text(
            shop_text("how"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        get_button("exchange"),
                        callback_data="exchange",
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_button("back"),
                        callback_data="home",
                    )
                ],
            ]),
        )
        return

    if data.startswith("currency:"):

        currency_id = int(data.split(":")[1])

        currency = get_currency(currency_id)

        if not currency or not currency["enabled"]:
            await query.answer(
                "This currency is unavailable.",
                show_alert=True,
            )
            return

        sessions[user_id] = {
            "currency_id": currency_id,
            "waiting": "product",
        }

        await query.edit_message_text(
            shop_text("product"),
            parse_mode="HTML",
            reply_markup=product_keyboard(),
        )
        return

    if data.startswith("product:"):

        product_id = int(data.split(":")[1])

        product = get_product(product_id)

        session = sessions.get(user_id)

        if not product or not session:
            await query.answer(
                "Please start a new order.",
                show_alert=True,
            )
            return

        price = get_price(
            session["currency_id"],
            product_id,
        )

        session.update({
            "product_id": product_id,
            "amount": product["amount"],
            "product": product["name"],
            "price": price,
            "waiting": "username",
        })

        await query.edit_message_text(
            shop_text("username"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        get_button("cancel"),
                        callback_data="home",
                    )
                ]
            ]),
        )
        return

    if data == "custom":

        session = sessions.get(user_id)

        if not session:
            await query.answer(
                "Please start a new order.",
                show_alert=True,
            )
            return

        session["waiting"] = "custom_amount"

        await query.edit_message_text(
            shop_text("custom"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        get_button("cancel"),
                        callback_data="home",
                    )
                ]
            ]),
        )
        return

    # --------------------------------------------------------
    # ADMIN
    # --------------------------------------------------------

    if data.startswith("admin") or data in [
        "add_product",
        "add_currency",
    ] or any(
        data.startswith(prefix)
        for prefix in [
            "edit_product:",
            "rename_product:",
            "amount_product:",
            "product_prices:",
            "toggle_product:",
            "delete_product:",
            "edit_currency:",
            "rename_currency:",
            "currency_button:",
            "toggle_currency:",
            "delete_currency:",
            "prices_currency:",
            "set_price:",
            "set_custom:",
            "edit_text:",
            "edit_button:",
            "change_shop_name",
            "change_admin",
        ]
    ):

        if not is_admin(user):

            await query.answer(
                "⛔ Access denied.",
                show_alert=True,
            )
            return

    # Admin home
    if data == "admin":

        await query.edit_message_text(
            "⚙️ <b>ADMIN PANEL</b>\n\n"
            "Manage your entire shop from your phone.",
            parse_mode="HTML",
            reply_markup=admin_keyboard(),
        )
        return

    # Products
    if data == "admin_products":

        await show_products(query)
        return

    if data == "add_product":

        await add_product_start(query)
        return

    if data.startswith("edit_product:"):

        product_id = int(data.split(":")[1])

        await show_edit_product(
            query,
            product_id,
        )
        return

    if data.startswith("rename_product:"):

        product_id = int(data.split(":")[1])

        sessions[user_id] = {
            "action": "rename_product",
            "product_id": product_id,
        }

        await query.edit_message_text(
            "🔤 <b>RENAME PRODUCT BUTTON</b>\n\n"
            "Send the new button text.",
            parse_mode="HTML",
        )
        return

    if data.startswith("amount_product:"):

        product_id = int(data.split(":")[1])

        sessions[user_id] = {
            "action": "change_product_amount",
            "product_id": product_id,
        }

        await query.edit_message_text(
            "🔢 <b>CHANGE ROBUX AMOUNT</b>\n\n"
            "Send the new amount.\n\n"
            "Example: <code>2500</code>",
            parse_mode="HTML",
        )
        return

    if data.startswith("toggle_product:"):

        product_id = int(data.split(":")[1])

        conn = db()

        conn.execute(
            """
            UPDATE products
            SET enabled = CASE
                WHEN enabled = 1 THEN 0
                ELSE 1
            END
            WHERE id = ?
            """,
            (product_id,),
        )

        conn.commit()
        conn.close()

        await show_edit_product(
            query,
            product_id,
        )
        return

    if data.startswith("delete_product:"):

        product_id = int(data.split(":")[1])

        product = get_product(product_id)

        if product:

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

        await show_products(query)
        return

    # Product prices
    if data.startswith("product_prices:"):

        product_id = int(data.split(":")[1])

        product = get_product(product_id)

        if not product:
            return

        rows = []

        for currency in get_currencies():

            price = get_price(
                currency["id"],
                product_id,
            )

            rows.append([
                InlineKeyboardButton(
                    f"{currency['name']} → {price}",
                    callback_data=(
                        f"set_price:"
                        f"{currency['id']}:"
                        f"{product_id}"
                    ),
                )
            ])

        rows.append([
            InlineKeyboardButton(
                "↩️ Product",
                callback_data=f"edit_product:{product_id}",
            )
        ])

        await query.edit_message_text(
            f"💰 <b>PRICES — "
            f"{clean(product['button_text'])}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(rows),
        )
        return

    # Currencies
    if data == "admin_currencies":

        await show_currencies(query)
        return

    if data == "add_currency":

        await add_currency_start(query)
        return

    if data.startswith("edit_currency:"):

        currency_id = int(data.split(":")[1])

        await show_edit_currency(
            query,
            currency_id,
        )
        return

    if data.startswith("rename_currency:"):

        currency_id = int(data.split(":")[1])

        sessions[user_id] = {
            "action": "rename_currency",
            "currency_id": currency_id,
        }

        await query.edit_message_text(
            "🔤 <b>RENAME CURRENCY</b>\n\n"
            "Send the new currency name.",
            parse_mode="HTML",
        )
        return

    if data.startswith("currency_button:"):

        currency_id = int(data.split(":")[1])

        sessions[user_id] = {
            "action": "currency_button",
            "currency_id": currency_id,
        }

        await query.edit_message_text(
            "🔘 <b>CURRENCY BUTTON</b>\n\n"
            "Send the new button text.",
            parse_mode="HTML",
        )
        return

    if data.startswith("toggle_currency:"):

        currency_id = int(data.split(":")[1])

        conn = db()

        conn.execute(
            """
            UPDATE currencies
            SET enabled = CASE
                WHEN enabled = 1 THEN 0
                ELSE 1
            END
            WHERE id = ?
            """,
            (currency_id,),
        )

        conn.commit()
        conn.close()

        await show_edit_currency(
            query,
            currency_id,
        )
        return

    if data.startswith("delete_currency:"):

        currency_id = int(data.split(":")[1])

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

        await show_currencies(query)
        return

    # Prices
    if data == "admin_prices":

        await show_prices(query)
        return

    if data.startswith("prices_currency:"):

        currency_id = int(data.split(":")[1])

        await show_currency_prices(
            query,
            currency_id,
        )
        return

    if data.startswith("set_price:"):

        _, currency_id, product_id = data.split(":")

        sessions[user_id] = {
            "action": "set_price",
            "currency_id": int(currency_id),
            "product_id": int(product_id),
        }

        await query.edit_message_text(
            "💰 <b>SET PRICE</b>\n\n"
            "Send the new price.\n\n"
            "Examples:\n"
            "<code>50</code>\n"
            "<code>100 Stars</code>\n"
            "<code>NA</code>",
            parse_mode="HTML",
        )
        return

    if data.startswith("set_custom:"):

        currency_id = int(data.split(":")[1])

        sessions[user_id] = {
            "action": "set_custom_price",
            "currency_id": currency_id,
        }

        await query.edit_message_text(
            "✏️ <b>CUSTOM AMOUNT PRICE</b>\n\n"
            "Send the new price.\n\n"
            "Example:\n"
            "<code>NA</code>",
            parse_mode="HTML",
        )
        return

    # Texts
    if data == "admin_texts":

        await show_texts(query)
        return

    if data.startswith("edit_text:"):

        key = data.split(":", 1)[1]

        sessions[user_id] = {
            "action": "edit_text",
            "key": key,
        }

        await query.edit_message_text(
            "📝 <b>EDIT TEXT</b>\n\n"
            f"Current text:\n\n"
            f"<code>{clean(get_text(key))}</code>\n\n"
            "Send the new text.\n\n"
            "You can use HTML formatting.",
            parse_mode="HTML",
        )
        return

    # Buttons
    if data == "admin_buttons":

        await show_buttons(query)
        return

    if data.startswith("edit_button:"):

        key = data.split(":", 1)[1]

        sessions[user_id] = {
            "action": "edit_button",
            "key": key,
        }

        await query.edit_message_text(
            "🔘 <b>EDIT BUTTON</b>\n\n"
            f"Current:\n<b>{clean(get_button(key))}</b>\n\n"
            "Send the new button text.",
            parse_mode="HTML",
        )
        return

    # Settings
    if data == "admin_settings":

        await show_settings(query)
        return

    if data == "change_shop_name":

        sessions[user_id] = {
            "action": "change_shop_name"
        }

        await query.edit_message_text(
            "🏷️ <b>SHOP NAME</b>\n\n"
            "Send the new shop name.",
            parse_mode="HTML",
        )
        return

    if data == "change_admin":

        sessions[user_id] = {
            "action": "change_admin"
        }

        await query.edit_message_text(
            "👤 <b>ADMIN USERNAME</b>\n\n"
            "Send the username.\n\n"
            "Example:\n"
            "<code>@berizienuhq</code>",
            parse_mode="HTML",
        )
        return

    # Orders
    if data == "admin_orders":

        await show_orders(query)
        return


# ============================================================
# TEXT INPUT
# ============================================================

async def text_handler(update, context):

    if not update.message or not update.message.text:
        return

    user = update.effective_user
    user_id = user.id
    text = update.message.text.strip()

    session = sessions.get(user_id)

    if text.lower() == "/cancel":

        sessions.pop(user_id, None)

        await update.message.reply_text(
            "❌ Cancelled.",
            reply_markup=(
                admin_keyboard()
                if is_admin(user)
                else main_keyboard()
            ),
        )
        return

    # ========================================================
    # ADMIN INPUT
    # ========================================================

    if is_admin(user) and session:

        action = session.get("action")

        # Add product - name
        if action == "add_product_name":

            session["product_name"] = text
            session["action"] = "add_product_amount"

            await update.message.reply_text(
                "🔢 <b>PRODUCT AMOUNT</b>\n\n"
                "How many Robux does this product contain?\n\n"
                "Example:\n"
                "<code>2000</code>",
                parse_mode="HTML",
            )
            return

        # Add product - amount
        if action == "add_product_amount":

            cleaned = text.replace(",", "").replace(" ", "")

            if not cleaned.isdigit():

                await update.message.reply_text(
                    "⚠️ Please enter numbers only."
                )
                return

            amount = int(cleaned)

            if amount <= 0:

                await update.message.reply_text(
                    "⚠️ Amount must be greater than 0."
                )
                return

            conn = db()

            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS n FROM products"
            ).fetchone()["n"]

            cursor = conn.execute(
                """
                INSERT INTO products
                (name, button_text, amount, enabled, sort_order)
                VALUES (?, ?, ?, 1, ?)
                """,
                (
                    text,
                    session["product_name"],
                    amount,
                    max_order + 1,
                ),
            )

            product_id = cursor.lastrowid

            # Give every existing currency a default NA price.
            currencies = conn.execute(
                "SELECT id FROM currencies"
            ).fetchall()

            for currency in currencies:

                conn.execute(
                    """
                    INSERT OR IGNORE INTO prices
                    (currency_id, product_id, price)
                    VALUES (?, ?, 'NA')
                    """,
                    (
                        currency["id"],
                        product_id,
                    ),
                )

            conn.commit()
            conn.close()

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ <b>PRODUCT CREATED</b>\n\n"
                f"🔘 {clean(session['product_name'])}\n"
                f"🔢 {amount:,} R$",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📦 Products",
                            callback_data="admin_products",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "⚙️ Admin Panel",
                            callback_data="admin",
                        )
                    ],
                ]),
            )
            return

        # Rename product
        if action == "rename_product":

            conn = db()

            conn.execute(
                """
                UPDATE products
                SET button_text = ?
                WHERE id = ?
                """,
                (
                    text,
                    session["product_id"],
                ),
            )

            conn.commit()
            conn.close()

            product_id = session["product_id"]

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ Product button updated.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📦 Products",
                            callback_data="admin_products",
                        )
                    ]
                ]),
            )
            return

        # Change product amount
        if action == "change_product_amount":

            cleaned = text.replace(",", "").replace(" ", "")

            if not cleaned.isdigit():

                await update.message.reply_text(
                    "⚠️ Please enter numbers only."
                )
                return

            amount = int(cleaned)

            if amount <= 0:

                await update.message.reply_text(
                    "⚠️ Amount must be greater than 0."
                )
                return

            conn = db()

            conn.execute(
                """
                UPDATE products
                SET amount = ?
                WHERE id = ?
                """,
                (
                    amount,
                    session["product_id"],
                ),
            )

            conn.commit()
            conn.close()

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ <b>Amount updated.</b>\n\n"
                f"New amount: <b>{amount:,} R$</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📦 Products",
                            callback_data="admin_products",
                        )
                    ]
                ]),
            )
            return

        # Add currency
        if action == "add_currency_name":

            name = text

            try:

                conn = db()

                max_order = conn.execute(
                    """
                    SELECT COALESCE(MAX(sort_order), 0) AS n
                    FROM currencies
                    """
                ).fetchone()["n"]

                cursor = conn.execute(
                    """
                    INSERT INTO currencies
                    (name, button_text, enabled, sort_order)
                    VALUES (?, ?, 1, ?)
                    """,
                    (
                        name,
                        name,
                        max_order + 1,
                    ),
                )

                currency_id = cursor.lastrowid

                products = conn.execute(
                    "SELECT id FROM products"
                ).fetchall()

                for product in products:

                    conn.execute(
                        """
                        INSERT OR IGNORE INTO prices
                        (currency_id, product_id, price)
                        VALUES (?, ?, 'NA')
                        """,
                        (
                            currency_id,
                            product["id"],
                        ),
                    )

                conn.commit()
                conn.close()

            except sqlite3.IntegrityError:

                await update.message.reply_text(
                    "⚠️ That currency already exists."
                )
                return

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ <b>CURRENCY CREATED</b>\n\n"
                f"💱 {clean(name)}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💱 Currencies",
                            callback_data="admin_currencies",
                        )
                    ]
                ]),
            )
            return

        # Rename currency
        if action == "rename_currency":

            conn = db()

            conn.execute(
                """
                UPDATE currencies
                SET name = ?
                WHERE id = ?
                """,
                (
                    text,
                    session["currency_id"],
                ),
            )

            conn.commit()
            conn.close()

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ Currency renamed.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💱 Currencies",
                            callback_data="admin_currencies",
                        )
                    ]
                ]),
            )
            return

        # Currency button
        if action == "currency_button":

            conn = db()

            conn.execute(
                """
                UPDATE currencies
                SET button_text = ?
                WHERE id = ?
                """,
                (
                    text,
                    session["currency_id"],
                ),
            )

            conn.commit()
            conn.close()

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ Currency button updated.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💱 Currencies",
                            callback_data="admin_currencies",
                        )
                    ]
                ]),
            )
            return

        # Set price
        if action == "set_price":

            set_price(
                session["currency_id"],
                session["product_id"],
                text,
            )

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ <b>Price updated.</b>\n\n"
                f"New price: <b>{clean(text)}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💰 Prices",
                            callback_data="admin_prices",
                        )
                    ]
                ]),
            )
            return

        # Custom price
        if action == "set_custom_price":

            set_custom_price(
                session["currency_id"],
                text,
            )

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ <b>Custom price updated.</b>\n\n"
                f"New price: <b>{clean(text)}</b>",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💰 Prices",
                            callback_data="admin_prices",
                        )
                    ]
                ]),
            )
            return

        # Edit text
        if action == "edit_text":

            set_text(
                session["key"],
                text,
            )

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ Text updated.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "📝 Texts",
                            callback_data="admin_texts",
                        )
                    ]
                ]),
            )
            return

        # Edit button
        if action == "edit_button":

            set_button(
                session["key"],
                text,
            )

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ Button updated.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🔘 Buttons",
                            callback_data="admin_buttons",
                        )
                    ]
                ]),
            )
            return

        # Shop name
        if action == "change_shop_name":

            set_setting(
                "shop_name",
                text,
            )

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ Shop name updated.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏪 Settings",
                            callback_data="admin_settings",
                        )
                    ]
                ]),
            )
            return

        # Admin username
        if action == "change_admin":

            username = text

            if not username.startswith("@"):
                username = "@" + username

            set_setting(
                "admin_username",
                username,
            )

            sessions.pop(user_id, None)

            await update.message.reply_text(
                "✅ Admin username updated.",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "🏪 Settings",
                            callback_data="admin_settings",
                        )
                    ]
                ]),
            )
            return

    # ========================================================
    # CUSTOMER INPUT
    # ========================================================

    if not session:

        await update.message.reply_text(
            "Please use /start to open the shop.",
            reply_markup=main_keyboard(),
        )
        return

    # Custom amount
    if session.get("waiting") == "custom_amount":

        cleaned = text.replace(",", "").replace(" ", "")

        if not cleaned.isdigit():

            await update.message.reply_text(
                "⚠️ Please enter numbers only."
            )
            return

        amount = int(cleaned)

        if amount <= 0 or amount > 1_000_000:

            await update.message.reply_text(
                "⚠️ Please enter an amount between "
                "1 and 1,000,000."
            )
            return

        session["amount"] = amount
        session["product"] = "Custom"
        session["price"] = get_custom_price(
            session["currency_id"]
        )
        session["waiting"] = "username"

        await update.message.reply_text(
            shop_text("username"),
            parse_mode="HTML",
        )
        return

    # Roblox username
    if session.get("waiting") == "username":

        username = text.lstrip("@")

        if (
            len(username) < 3
            or len(username) > 20
            or not all(
                c.isalnum() or c == "_"
                for c in username
            )
        ):

            await update.message.reply_text(
                "⚠️ Please enter a valid Roblox username."
            )
            return

        currency = get_currency(
            session["currency_id"]
        )

        amount = session["amount"]
        product = session["product"]
        price = session["price"]

        conn = db()

        cursor = conn.execute(
            """
            INSERT INTO orders
            (
                order_number,
                telegram_id,
                telegram_username,
                telegram_name,
                currency,
                product,
                robux_amount,
                price,
                roblox_username,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "TEMP",
                user_id,
                user.username or "",
                user.full_name,
                currency["name"],
                product,
                amount,
                price,
                username,
                datetime.now().strftime(
                    "%d.%m.%Y %H:%M:%S"
                ),
            ),
        )

        order_db_id = cursor.lastrowid
        order_number = f"#{order_db_id:04d}"

        conn.execute(
            """
            UPDATE orders
            SET order_number = ?
            WHERE id = ?
            """,
            (
                order_number,
                order_db_id,
            ),
        )

        conn.commit()
        conn.close()

        # Send order to admin.
        if ADMIN_CHAT_ID:

            customer_username = (
                f"@{user.username}"
                if user.username
                else "No username"
            )

            admin_message = (
                "🔔 <b>NEW ORDER</b>\n\n"
                f"🔢 Order: <b>{order_number}</b>\n"
                f"💰 Robux: <b>{amount:,} R$</b>\n"
                f"💱 Currency: <b>{clean(currency['name'])}</b>\n"
                f"📦 Product: <b>{clean(product)}</b>\n"
                f"👤 Roblox: <b>{clean(username)}</b>\n"
                f"💵 Price: <b>{clean(price)}</b>\n"
                f"📅 Date: <b>"
                f"{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                f"</b>\n\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 Telegram: <b>{clean(customer_username)}</b>\n"
                f"🆔 Chat ID: <code>{user_id}</code>"
            )

            try:

                await context.bot.send_message(
                    chat_id=int(ADMIN_CHAT_ID),
                    text=admin_message,
                    parse_mode="HTML",
                )

            except Exception as error:

                logger.error(
                    "Could not send admin notification: %s",
                    error,
                )

        await update.message.reply_text(
            shop_text(
                "confirmation",
                order_id=order_number,
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        get_button("new_order"),
                        callback_data="exchange",
                    )
                ],
                [
                    InlineKeyboardButton(
                        get_button("home"),
                        callback_data="home",
                    )
                ],
            ]),
        )

        sessions.pop(user_id, None)


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
            "BOT_TOKEN is still set to the placeholder "
            "'BOT_TOKEN'."
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

    logger.info("R$ Exchange bot starting...")

    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    run()