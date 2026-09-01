import os
import sqlite3
import logging
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
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

ADMIN_USERNAME = "berizienuhq"

# SQLite database.
# For Railway, later you can put this on a persistent Volume.
DATABASE_FILE = os.getenv("DATABASE_FILE", "shop.db")


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# DATABASE
# ============================================================

def db_connection():
    connection = sqlite3.connect(DATABASE_FILE)
    connection.row_factory = sqlite3.Row
    return connection


def init_database():
    connection = db_connection()
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS currencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            button_text TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            button_text TEXT NOT NULL,
            amount INTEGER NOT NULL,
            enabled INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            currency_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price TEXT NOT NULL,
            PRIMARY KEY (currency_id, product_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS custom_prices (
            currency_id INTEGER PRIMARY KEY,
            price TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS texts (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS buttons (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
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

    # --------------------------------------------------------
    # DEFAULT SETTINGS
    # --------------------------------------------------------

    defaults = {
        "shop_name": "R$ EXCHANGE",
        "admin_username": "@berizienuhq",
    }

    for key, value in defaults.items():
        cursor.execute(
            """
            INSERT OR IGNORE INTO settings (key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    # --------------------------------------------------------
    # DEFAULT CURRENCIES
    # --------------------------------------------------------

    cursor.execute(
        """
        INSERT OR IGNORE INTO currencies
        (name, button_text, enabled, sort_order)
        VALUES (?, ?, 1, 1)
        """,
        ("GRAM", "💎 GRAM"),
    )

    cursor.execute(
        """
        INSERT OR IGNORE INTO currencies
        (name, button_text, enabled, sort_order)
        VALUES (?, ?, 1, 2)
        """,
        ("STARS", "⭐ Telegram Stars"),
    )

    # --------------------------------------------------------
    # DEFAULT PRODUCTS
    # --------------------------------------------------------

    default_products = [
        ("200", "200 R$", 200, 1),
        ("500", "500 R$", 500, 2),
        ("700", "700 R$", 700, 3),
        ("1000", "1,000 R$", 1000, 4),
    ]

    for name, button_text, amount, sort_order in default_products:
        cursor.execute(
            """
            INSERT OR IGNORE INTO products
            (name, button_text, amount, enabled, sort_order)
            VALUES (?, ?, ?, 1, ?)
            """,
            (
                name,
                button_text,
                amount,
                sort_order,
            ),
        )

    # --------------------------------------------------------
    # DEFAULT TEXTS
    # --------------------------------------------------------

    default_texts = {
        "welcome": (
            "🛍️ <b>{shop_name}</b>\n\n"
            "Welcome!\n\n"
            "Exchange your currency for Robux.\n\n"
            "Choose an option below:"
        ),

        "currency_selection": (
            "💱 <b>SELECT CURRENCY TO EXCHANGE</b>\n\n"
            "Choose the currency you would like to exchange:"
        ),

        "product_selection": (
            "💰 <b>SELECT ROBUX AMOUNT</b>\n\n"
            "Choose the amount of Robux you would like:"
        ),

        "custom_amount": (
            "✏️ <b>CUSTOM AMOUNT</b>\n\n"
            "Enter the amount of Robux you would like.\n\n"
            "Example:\n"
            "<code>2500</code>"
        ),

        "username_request": (
            "👤 <b>ROBLOX USERNAME</b>\n\n"
            "Enter your Roblox username.\n\n"
            "Example:\n"
            "<code>bakawjmi1</code>"
        ),

        "order_received": (
            "✅ <b>Order {order_id}</b>\n\n"
            "We have received your order.\n\n"
            "📩 Please wait for a DM from "
            "<b>{admin_username}</b> "
            "to finalise the exchange.\n\n"
            "Thank you for using <b>{shop_name}</b>."
        ),

        "how_it_works": (
            "ℹ️ <b>HOW IT WORKS</b>\n\n"
            "1️⃣ Select the currency you want to exchange.\n\n"
            "2️⃣ Select the amount of Robux.\n\n"
            "3️⃣ Enter your Roblox username.\n\n"
            "4️⃣ Your order is created automatically.\n\n"
            "5️⃣ Wait for a DM from "
            "<b>{admin_username}</b> "
            "to finalise the exchange."
        ),

        "invalid_amount": (
            "⚠️ <b>Invalid amount</b>\n\n"
            "Please enter numbers only."
        ),

        "invalid_username": (
            "⚠️ <b>Invalid Roblox username</b>\n\n"
            "Please enter your Roblox username again."
        ),
    }

    for key, value in default_texts.items():
        cursor.execute(
            """
            INSERT OR IGNORE INTO texts (key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    # --------------------------------------------------------
    # DEFAULT BUTTONS
    # --------------------------------------------------------

    default_buttons = {
        "exchange": "💱 Exchange",
        "how": "ℹ️ How It Works",
        "back": "↩️ Back",
        "cancel": "❌ Cancel",
        "custom": "✏️ Custom Amount",
        "new_order": "💱 New Order",
        "home": "🏠 Main Menu",
        "admin": "⚙️ Admin Panel",
    }

    for key, value in default_buttons.items():
        cursor.execute(
            """
            INSERT OR IGNORE INTO buttons (key, value)
            VALUES (?, ?)
            """,
            (key, value),
        )

    connection.commit()
    connection.close()


# ============================================================
# DATABASE HELPERS
# ============================================================

def get_setting(key, default=""):
    connection = db_connection()

    row = connection.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,),
    ).fetchone()

    connection.close()

    if row:
        return row["value"]

    return default


def set_setting(key, value):
    connection = db_connection()

    connection.execute(
        """
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )

    connection.commit()
    connection.close()


def get_text(key):
    return get_setting_from_table(
        "texts",
        key,
        ""
    )


def set_text(key, value):
    connection = db_connection()

    connection.execute(
        """
        INSERT INTO texts (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )

    connection.commit()
    connection.close()


def get_button(key):
    connection = db_connection()

    row = connection.execute(
        "SELECT value FROM buttons WHERE key = ?",
        (key,),
    ).fetchone()

    connection.close()

    if row:
        return row["value"]

    return key


def set_button(key, value):
    connection = db_connection()

    connection.execute(
        """
        INSERT INTO buttons (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )

    connection.commit()
    connection.close()


def get_setting_from_table(table, key, default=""):
    connection = db_connection()

    row = connection.execute(
        f"SELECT value FROM {table} WHERE key = ?",
        (key,),
    ).fetchone()

    connection.close()

    if row:
        return row["value"]

    return default


# ============================================================
# ADMIN CHECK
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
        if user.username.lower() == ADMIN_USERNAME.lower():
            return True

    return False


# ============================================================
# SHOP DATA
# ============================================================

def get_currencies():
    connection = db_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM currencies
        WHERE enabled = 1
        ORDER BY sort_order, id
        """
    ).fetchall()

    connection.close()

    return rows


def get_all_currencies():
    connection = db_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM currencies
        ORDER BY sort_order, id
        """
    ).fetchall()

    connection.close()

    return rows


def get_currency(currency_id):
    connection = db_connection()

    row = connection.execute(
        "SELECT * FROM currencies WHERE id = ?",
        (currency_id,),
    ).fetchone()

    connection.close()

    return row


def get_products():
    connection = db_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM products
        WHERE enabled = 1
        ORDER BY sort_order, id
        """
    ).fetchall()

    connection.close()

    return rows


def get_all_products():
    connection = db_connection()

    rows = connection.execute(
        """
        SELECT *
        FROM products
        ORDER BY sort_order, id
        """
    ).fetchall()

    connection.close()

    return rows


def get_product(product_id):
    connection = db_connection()

    row = connection.execute(
        "SELECT * FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()

    connection.close()

    return row


def get_price(currency_id, product_id):
    connection = db_connection()

    row = connection.execute(
        """
        SELECT price
        FROM prices
        WHERE currency_id = ?
        AND product_id = ?
        """,
        (
            currency_id,
            product_id,
        ),
    ).fetchone()

    connection.close()

    if row:
        return row["price"]

    return "NA"


def set_price(currency_id, product_id, price):
    connection = db_connection()

    connection.execute(
        """
        INSERT INTO prices
        (currency_id, product_id, price)
        VALUES (?, ?, ?)
        ON CONFLICT(currency_id, product_id)
        DO UPDATE SET price = excluded.price
        """,
        (
            currency_id,
            product_id,
            price,
        ),
    )

    connection.commit()
    connection.close()


def get_custom_price(currency_id):
    connection = db_connection()

    row = connection.execute(
        """
        SELECT price
        FROM custom_prices
        WHERE currency_id = ?
        """,
        (currency_id,),
    ).fetchone()

    connection.close()

    if row:
        return row["price"]

    return "NA"


def set_custom_price(currency_id, price):
    connection = db_connection()

    connection.execute(
        """
        INSERT INTO custom_prices
        (currency_id, price)
        VALUES (?, ?)
        ON CONFLICT(currency_id)
        DO UPDATE SET price = excluded.price
        """,
        (
            currency_id,
            price,
        ),
    )

    connection.commit()
    connection.close()


# ============================================================
# ORDER CREATION
# ============================================================

def create_order(
    telegram_id,
    telegram_username,
    telegram_name,
    currency,
    product,
    robux_amount,
    price,
    roblox_username,
):
    connection = db_connection()

    cursor = connection.cursor()

    cursor.execute(
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
            telegram_id,
            telegram_username,
            telegram_name,
            currency,
            product,
            robux_amount,
            price,
            roblox_username,
            datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        ),
    )

    database_id = cursor.lastrowid
    order_id = f"#{database_id:04d}"

    cursor.execute(
        """
        UPDATE orders
        SET order_number = ?
        WHERE id = ?
        """,
        (
            order_id,
            database_id,
        ),
    )

    connection.commit()
    connection.close()

    return order_id


# ============================================================
# USER SESSION
# ============================================================

user_sessions = {}


# ============================================================
# FORMAT TEXT
# ============================================================

def format_text(key, **kwargs):
    text = get_text(key)

    default_values = {
        "shop_name": get_setting(
            "shop_name",
            "R$ EXCHANGE"
        ),
        "admin_username": get_setting(
            "admin_username",
            "@berizienuhq"
        ),
    }

    default_values.update(kwargs)

    try:
        return text.format(**default_values)
    except Exception:
        return text


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():
    return InlineKeyboardMarkup(
        [
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
        ]
    )


# ============================================================
# /START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    user_id = update.effective_user.id

    user_sessions.pop(user_id, None)

    await update.message.reply_text(
        format_text("welcome"),
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


# ============================================================
# CURRENCY MENU
# ============================================================

def currency_menu():
    buttons = []

    for currency in get_currencies():
        buttons.append(
            [
                InlineKeyboardButton(
                    currency["button_text"],
                    callback_data=f"currency:{currency['id']}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                get_button("back"),
                callback_data="home",
            )
        ]
    )

    return InlineKeyboardMarkup(buttons)


# ============================================================
# PRODUCT MENU
# ============================================================

def product_menu():
    products = get_products()

    buttons = []

    row = []

    for product in products:

        row.append(
            InlineKeyboardButton(
                product["button_text"],
                callback_data=f"product:{product['id']}",
            )
        )

        if len(row) == 2:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    buttons.append(
        [
            InlineKeyboardButton(
                get_button("custom"),
                callback_data="custom",
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                get_button("back"),
                callback_data="exchange",
            )
        ]
    )

    return InlineKeyboardMarkup(buttons)


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # --------------------------------------------------------
    # HOME
    # --------------------------------------------------------

    if data == "home":

        user_sessions.pop(user_id, None)

        await query.edit_message_text(
            format_text("welcome"),
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # EXCHANGE
    # --------------------------------------------------------

    if data == "exchange":

        await query.edit_message_text(
            format_text("currency_selection"),
            parse_mode="HTML",
            reply_markup=currency_menu(),
        )

        return

    # --------------------------------------------------------
    # HOW IT WORKS
    # --------------------------------------------------------

    if data == "how":

        await query.edit_message_text(
            format_text("how_it_works"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
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
                ]
            ),
        )

        return

    # --------------------------------------------------------
    # CURRENCY SELECTED
    # --------------------------------------------------------

    if data.startswith("currency:"):

        currency_id = int(data.split(":")[1])
        currency = get_currency(currency_id)

        if not currency:
            await query.edit_message_text(
                "⚠️ Currency no longer exists.",
                reply_markup=main_menu(),
            )
            return

        user_sessions[user_id] = {
            "currency_id": currency_id,
            "currency": currency["name"],
            "waiting_for": "product",
        }

        await query.edit_message_text(
            format_text(
                "product_selection"
            ),
            parse_mode="HTML",
            reply_markup=product_menu(),
        )

        return

    # --------------------------------------------------------
    # PRODUCT SELECTED
    # --------------------------------------------------------

    if data.startswith("product:"):

        product_id = int(data.split(":")[1])
        product = get_product(product_id)

        if not product:
            await query.edit_message_text(
                "⚠️ Product no longer exists.",
                reply_markup=main_menu(),
            )
            return

        session = user_sessions.get(user_id)

        if not session:
            await query.edit_message_text(
                "Please start a new order.",
                reply_markup=main_menu(),
            )
            return

        currency_id = session["currency_id"]

        price = get_price(
            currency_id,
            product_id,
        )

        session.update(
            {
                "product_id": product_id,
                "product": product["name"],
                "amount": product["amount"],
                "price": price,
                "waiting_for": "username",
            }
        )

        await query.edit_message_text(
            format_text("username_request"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            get_button("cancel"),
                            callback_data="home",
                        )
                    ]
                ]
            ),
        )

        return

    # --------------------------------------------------------
    # CUSTOM
    # --------------------------------------------------------

    if data == "custom":

        session = user_sessions.get(user_id)

        if not session:
            await query.edit_message_text(
                "Please start a new order.",
                reply_markup=main_menu(),
            )
            return

        currency_id = session["currency_id"]

        session["waiting_for"] = "custom_amount"
        session["custom"] = True
        session["price"] = get_custom_price(currency_id)

        await query.edit_message_text(
            format_text("custom_amount"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            get_button("cancel"),
                            callback_data="home",
                        )
                    ]
                ]
            ),
        )

        return

    # ========================================================
    # ADMIN PANEL
    # ========================================================

    if data == "admin":

        if not is_admin(query.from_user):
            await query.answer(
                "You don't have permission to use this.",
                show_alert=True,
            )
            return

        await show_admin_panel(query)

        return

    # --------------------------------------------------------
    # ADMIN: CURRENCIES
    # --------------------------------------------------------

    if data == "admin:currencies":

        if not is_admin(query.from_user):
            return

        await show_admin_currencies(query)

        return

    # --------------------------------------------------------
    # ADMIN: PRODUCTS
    # --------------------------------------------------------

    if data == "admin:products":

        if not is_admin(query.from_user):
            return

        await show_admin_products(query)

        return

    # --------------------------------------------------------
    # ADMIN: PRICES
    # --------------------------------------------------------

    if data == "admin:prices":

        if not is_admin(query.from_user):
            return

        await show_admin_price_currencies(query)

        return

    # --------------------------------------------------------
    # ADMIN: TEXTS
    # --------------------------------------------------------

    if data == "admin:texts":

        if not is_admin(query.from_user):
            return

        await show_admin_texts(query)

        return

    # --------------------------------------------------------
    # ADMIN: BUTTONS
    # --------------------------------------------------------

    if data == "admin:buttons":

        if not is_admin(query.from_user):
            return

        await show_admin_buttons(query)

        return

    # --------------------------------------------------------
    # ADMIN: ORDERS
    # --------------------------------------------------------

    if data == "admin:orders":

        if not is_admin(query.from_user):
            return

        await show_admin_orders(query)

        return

    # --------------------------------------------------------
    # ADMIN: PRICE CURRENCY
    # --------------------------------------------------------

    if data.startswith("admin:pricecurrency:"):

        if not is_admin(query.from_user):
            return

        currency_id = int(data.split(":")[2])

        await show_admin_currency_prices(
            query,
            currency_id,
        )

        return

    # --------------------------------------------------------
    # ADMIN: EDIT PRICE
    # --------------------------------------------------------

    if data.startswith("admin:editprice:"):

        if not is_admin(query.from_user):
            return

        parts = data.split(":")

        currency_id = int(parts[2])
        product_id = int(parts[3])

        user_sessions[user_id] = {
            "admin_action": "edit_price",
            "currency_id": currency_id,
            "product_id": product_id,
        }

        await query.edit_message_text(
            "💰 <b>EDIT PRICE</b>\n\n"
            "Send the new price.\n\n"
            "Examples:\n"
            "<code>50</code>\n"
            "<code>120 Stars</code>\n"
            "<code>NA</code>\n\n"
            "Send /cancel to cancel.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # ADMIN: CUSTOM PRICE
    # --------------------------------------------------------

    if data.startswith("admin:customprice:"):

        if not is_admin(query.from_user):
            return

        currency_id = int(data.split(":")[2])

        user_sessions[user_id] = {
            "admin_action": "edit_custom_price",
            "currency_id": currency_id,
        }

        await query.edit_message_text(
            "✏️ <b>EDIT CUSTOM PRICE</b>\n\n"
            "Send the new price.\n\n"
            "Example:\n"
            "<code>NA</code>\n"
            "<code>500</code>",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # ADMIN: EDIT TEXT
    # --------------------------------------------------------

    if data.startswith("admin:edittext:"):

        if not is_admin(query.from_user):
            return

        key = data.split(":", 2)[2]

        user_sessions[user_id] = {
            "admin_action": "edit_text",
            "key": key,
        }

        current = get_text(key)

        await query.edit_message_text(
            "📝 <b>EDIT TEXT</b>\n\n"
            f"Key: <code>{key}</code>\n\n"
            "Current text:\n"
            f"<code>{current}</code>\n\n"
            "Send the new text.\n\n"
            "You can use HTML formatting such as "
            "<code>&lt;b&gt;text&lt;/b&gt;</code>.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # ADMIN: EDIT BUTTON
    # --------------------------------------------------------

    if data.startswith("admin:editbutton:"):

        if not is_admin(query.from_user):
            return

        key = data.split(":", 2)[2]

        user_sessions[user_id] = {
            "admin_action": "edit_button",
            "key": key,
        }

        await query.edit_message_text(
            "🔘 <b>EDIT BUTTON</b>\n\n"
            f"Button: <code>{key}</code>\n"
            f"Current: <b>{get_button(key)}</b>\n\n"
            "Send the new button text.",
            parse_mode="HTML",
        )

        return

    # --------------------------------------------------------
    # ADMIN: SHOP NAME
    # --------------------------------------------------------

    if data == "admin:shopname":

        if not is_admin(query.from_user):
            return

        user_sessions[user_id] = {
            "admin_action": "shop_name",
        }

        await query.edit_message_text(
            "🏷️ <b>SHOP NAME</b>\n\n"
            f"Current: <b>{get_setting('shop_name')}</b>\n\n"
            "Send the new shop name.",
            parse_mode="HTML",
        )

        return


# ============================================================
# ADMIN PANEL
# ============================================================

async def show_admin_panel(query):

    keyboard = [
        [
            InlineKeyboardButton(
                "💱 Currencies",
                callback_data="admin:currencies",
            )
        ],
        [
            InlineKeyboardButton(
                "📦 Products",
                callback_data="admin:products",
            )
        ],
        [
            InlineKeyboardButton(
                "💰 Prices",
                callback_data="admin:prices",
            )
        ],
        [
            InlineKeyboardButton(
                "📝 Texts",
                callback_data="admin:texts",
            )
        ],
        [
            InlineKeyboardButton(
                "🔘 Buttons",
                callback_data="admin:buttons",
            )
        ],
        [
            InlineKeyboardButton(
                "📋 Orders",
                callback_data="admin:orders",
            )
        ],
        [
            InlineKeyboardButton(
                "🏷️ Shop Name",
                callback_data="admin:shopname",
            )
        ],
        [
            InlineKeyboardButton(
                "🏠 Shop",
                callback_data="home",
            )
        ],
    ]

    await query.edit_message_text(
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "Manage your shop directly from Telegram.\n\n"
        "Changes are saved automatically.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ============================================================
# ADMIN CURRENCIES
# ============================================================

async def show_admin_currencies(query):

    currencies = get_all_currencies()

    buttons = []

    for currency in currencies:

        status = "🟢" if currency["enabled"] else "🔴"

        buttons.append(
            [
                InlineKeyboardButton(
                    f"{status} {currency['button_text']}",
                    callback_data=f"admin:noop",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "➕ Add Currency",
                callback_data="admin:addcurrency",
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await query.edit_message_text(
        "💱 <b>CURRENCIES</b>\n\n"
        "Currency management is stored in the database.\n\n"
        "The default currencies are GRAM and Telegram Stars.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ADMIN PRODUCTS
# ============================================================

async def show_admin_products(query):

    products = get_all_products()

    buttons = []

    for product in products:

        status = "🟢" if product["enabled"] else "🔴"

        buttons.append(
            [
                InlineKeyboardButton(
                    f"{status} {product['button_text']}",
                    callback_data="admin:noop",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await query.edit_message_text(
        "📦 <b>PRODUCTS</b>\n\n"
        "Your current products:\n\n"
        + "\n".join(
            f"• {product['button_text']} → "
            f"{product['amount']:,} R$"
            for product in products
        ),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ADMIN PRICES
# ============================================================

async def show_admin_price_currencies(query):

    currencies = get_all_currencies()

    buttons = []

    for currency in currencies:

        buttons.append(
            [
                InlineKeyboardButton(
                    f"💰 {currency['name']}",
                    callback_data=f"admin:pricecurrency:{currency['id']}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await query.edit_message_text(
        "💰 <b>PRICES</b>\n\n"
        "Choose a currency to manage its prices:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ADMIN CURRENCY PRICES
# ============================================================

async def show_admin_currency_prices(
    query,
    currency_id,
):

    currency = get_currency(currency_id)

    if not currency:
        return

    products = get_all_products()

    buttons = []

    for product in products:

        price = get_price(
            currency_id,
            product["id"],
        )

        buttons.append(
            [
                InlineKeyboardButton(
                    f"{product['button_text']} = {price}",
                    callback_data=(
                        f"admin:editprice:"
                        f"{currency_id}:"
                        f"{product['id']}"
                    ),
                )
            ]
        )

    custom_price = get_custom_price(currency_id)

    buttons.append(
        [
            InlineKeyboardButton(
                f"✏️ Custom = {custom_price}",
                callback_data=f"admin:customprice:{currency_id}",
            )
        ]
    )

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Back",
                callback_data="admin:prices",
            )
        ]
    )

    await query.edit_message_text(
        f"💰 <b>{currency['name']} PRICES</b>\n\n"
        "Tap a product to change its price.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ADMIN TEXTS
# ============================================================

async def show_admin_texts(query):

    text_names = {
        "welcome": "Welcome Message",
        "currency_selection": "Currency Selection",
        "product_selection": "Product Selection",
        "custom_amount": "Custom Amount",
        "username_request": "Username Request",
        "order_received": "Order Confirmation",
        "how_it_works": "How It Works",
        "invalid_amount": "Invalid Amount",
        "invalid_username": "Invalid Username",
    }

    buttons = []

    for key, name in text_names.items():

        buttons.append(
            [
                InlineKeyboardButton(
                    name,
                    callback_data=f"admin:edittext:{key}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await query.edit_message_text(
        "📝 <b>TEXT EDITOR</b>\n\n"
        "Choose which shop text you want to edit.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ADMIN BUTTONS
# ============================================================

async def show_admin_buttons(query):

    button_names = {
        "exchange": "Exchange",
        "how": "How It Works",
        "back": "Back",
        "cancel": "Cancel",
        "custom": "Custom Amount",
        "new_order": "New Order",
        "home": "Main Menu",
    }

    buttons = []

    for key, name in button_names.items():

        buttons.append(
            [
                InlineKeyboardButton(
                    f"🔘 {name}: {get_button(key)}",
                    callback_data=f"admin:editbutton:{key}",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Admin Panel",
                callback_data="admin",
            )
        ]
    )

    await query.edit_message_text(
        "🔘 <b>BUTTON EDITOR</b>\n\n"
        "Tap a button below to rename it.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


# ============================================================
# ADMIN ORDERS
# ============================================================

async def show_admin_orders(query):

    connection = db_connection()

    orders = connection.execute(
        """
        SELECT *
        FROM orders
        ORDER BY id DESC
        LIMIT 15
        """
    ).fetchall()

    connection.close()

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
                f"<b>{order['order_number']}</b> — "
                f"{order['robux_amount']:,} R$ — "
                f"{order['currency']} — "
                f"<code>{order['roblox_username']}</code>"
            )

        text = "\n".join(lines)

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "↩️ Admin Panel",
                        callback_data="admin",
                    )
                ]
            ]
        ),
    )


# ============================================================
# /ADMIN
# ============================================================

async def admin_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_admin(update.effective_user):

        await update.message.reply_text(
            "⛔ You don't have permission to access the admin panel."
        )

        return

    await update.message.reply_text(
        "⚙️ <b>ADMIN PANEL</b>\n\n"
        "Choose what you want to manage:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💱 Currencies",
                        callback_data="admin:currencies",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📦 Products",
                        callback_data="admin:products",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💰 Prices",
                        callback_data="admin:prices",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📝 Texts",
                        callback_data="admin:texts",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔘 Buttons",
                        callback_data="admin:buttons",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📋 Orders",
                        callback_data="admin:orders",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏷️ Shop Name",
                        callback_data="admin:shopname",
                    )
                ],
            ]
        ),
    )


# ============================================================
# ADMIN TEXT INPUT
# ============================================================

async def handle_admin_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user = update.effective_user

    if not is_admin(user):
        return

    user_id = user.id
    text = update.message.text.strip()

    if text.lower() == "/cancel":

        user_sessions.pop(user_id, None)

        await update.message.reply_text(
            "❌ Cancelled.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⚙️ Admin Panel",
                            callback_data="admin",
                        )
                    ]
                ]
            ),
        )

        return

    session = user_sessions.get(user_id)

    if not session:
        return

    action = session.get("admin_action")

    # --------------------------------------------------------
    # EDIT PRICE
    # --------------------------------------------------------

    if action == "edit_price":

        set_price(
            session["currency_id"],
            session["product_id"],
            text,
        )

        user_sessions.pop(user_id, None)

        await update.message.reply_text(
            "✅ <b>Price updated.</b>\n\n"
            f"New price: <b>{text}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💰 Prices",
                            callback_data="admin:prices",
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

    # --------------------------------------------------------
    # CUSTOM PRICE
    # --------------------------------------------------------

    if action == "edit_custom_price":

        set_custom_price(
            session["currency_id"],
            text,
        )

        user_sessions.pop(user_id, None)

        await update.message.reply_text(
            "✅ <b>Custom price updated.</b>\n\n"
            f"New price: <b>{text}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💰 Prices",
                            callback_data="admin:prices",
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

    # --------------------------------------------------------
    # EDIT TEXT
    # --------------------------------------------------------

    if action == "edit_text":

        set_text(
            session["key"],
            text,
        )

        user_sessions.pop(user_id, None)

        await update.message.reply_text(
            "✅ <b>Text updated.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "📝 Texts",
                            callback_data="admin:texts",
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

    # --------------------------------------------------------
    # EDIT BUTTON
    # --------------------------------------------------------

    if action == "edit_button":

        set_button(
            session["key"],
            text,
        )

        user_sessions.pop(user_id, None)

        await update.message.reply_text(
            "✅ <b>Button updated.</b>\n\n"
            f"New text: <b>{text}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔘 Buttons",
                            callback_data="admin:buttons",
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

    # --------------------------------------------------------
    # SHOP NAME
    # --------------------------------------------------------

    if action == "shop_name":

        set_setting(
            "shop_name",
            text,
        )

        user_sessions.pop(user_id, None)

        await update.message.reply_text(
            "✅ <b>Shop name updated.</b>\n\n"
            f"New name: <b>{text}</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "⚙️ Admin Panel",
                            callback_data="admin",
                        )
                    ]
                ]
            ),
        )

        return


# ============================================================
# CUSTOMER TEXT INPUT
# ============================================================

async def handle_customer_input(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    user_id = update.effective_user.id

    session = user_sessions.get(user_id)

    if not session:
        await update.message.reply_text(
            "Please use /start to open the shop.",
            reply_markup=main_menu(),
        )
        return

    text = update.message.text.strip()

    # --------------------------------------------------------
    # CUSTOM AMOUNT
    # --------------------------------------------------------

    if session.get("waiting_for") == "custom_amount":

        cleaned = text.replace(",", "").replace(" ", "")

        if not cleaned.isdigit():

            await update.message.reply_text(
                format_text("invalid_amount"),
                parse_mode="HTML",
            )

            return

        amount = int(cleaned)

        if amount <= 0 or amount > 1000000:

            await update.message.reply_text(
                "⚠️ Please enter an amount between "
                "1 and 1,000,000.",
            )

            return

        session["amount"] = amount
        session["product"] = "Custom"
        session["waiting_for"] = "username"

        await update.message.reply_text(
            format_text("username_request"),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            get_button("cancel"),
                            callback_data="home",
                        )
                    ]
                ]
            ),
        )

        return

    # --------------------------------------------------------
    # USERNAME
    # --------------------------------------------------------

    if session.get("waiting_for") == "username":

        username = text.lstrip("@")

        if len(username) < 3 or len(username) > 20:

            await update.message.reply_text(
                format_text("invalid_username"),
                parse_mode="HTML",
            )

            return

        if not all(
            character.isalnum() or character == "_"
            for character in username
        ):

            await update.message.reply_text(
                format_text("invalid_username"),
                parse_mode="HTML",
            )

            return

        currency_id = session["currency_id"]
        currency = get_currency(currency_id)

        if not currency:
            await update.message.reply_text(
                "⚠️ Currency unavailable.",
                reply_markup=main_menu(),
            )
            return

        amount = session["amount"]
        product = session["product"]

        if session.get("custom"):
            price = get_custom_price(currency_id)
        else:
            price = session["price"]

        order_id = create_order(
            telegram_id=user_id,
            telegram_username=(
                update.effective_user.username or ""
            ),
            telegram_name=update.effective_user.full_name,
            currency=currency["name"],
            product=product,
            robux_amount=amount,
            price=price,
            roblox_username=username,
        )

        date = datetime.now().strftime("%d.%m.%Y")

        # ----------------------------------------------------
        # SEND ADMIN NOTIFICATION
        # ----------------------------------------------------

        if ADMIN_CHAT_ID:

            telegram_username = (
                f"@{update.effective_user.username}"
                if update.effective_user.username
                else "No username"
            )

            admin_message = (
                "🔔 <b>NEW ORDER</b>\n\n"
                f"🔢 Order ID  >  <b>{order_id}</b>\n"
                f"💰 Robux  >  <b>{amount:,} R$</b>\n"
                f"💱 Currency  >  <b>{currency['name']}</b>\n"
                f"📦 Product  >  <b>{product}</b>\n"
                f"👤 Roblox User  >  <b>{username}</b>\n"
                f"⭐ Price  >  <b>{price}</b>\n"
                f"📅 Date  >  <b>{date}</b>\n\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "👤 <b>Telegram Customer</b>\n"
                f"Name: <b>{update.effective_user.full_name}</b>\n"
                f"Username: <b>{telegram_username}</b>\n"
                f"Chat ID: <code>{user_id}</code>"
            )

            try:

                await context.bot.send_message(
                    chat_id=int(ADMIN_CHAT_ID),
                    text=admin_message,
                    parse_mode="HTML",
                )

                logger.info(
                    "Order %s sent to admin.",
                    order_id,
                )

            except Exception as error:

                logger.error(
                    "Could not send order to admin: %s",
                    error,
                )

        # ----------------------------------------------------
        # CUSTOMER CONFIRMATION
        # ----------------------------------------------------

        await update.message.reply_text(
            format_text(
                "order_received",
                order_id=order_id,
            ),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
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
                ]
            ),
        )

        user_sessions.pop(user_id, None)


# ============================================================
# GENERAL MESSAGE ROUTER
# ============================================================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    if not update.message.text:
        return

    user_id = update.effective_user.id

    # Admin input takes priority.
    session = user_sessions.get(user_id)

    if (
        is_admin(update.effective_user)
        and session
        and session.get("admin_action")
    ):
        await handle_admin_input(
            update,
            context,
        )
        return

    await handle_customer_input(
        update,
        context,
    )


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# ============================================================
# RUN
# ============================================================

def run():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is missing. "
            "Add BOT_TOKEN to Railway Variables."
        )

    if BOT_TOKEN == "BOT_TOKEN":

        raise RuntimeError(
            "BOT_TOKEN is configured incorrectly. "
            "The value cannot literally be BOT_TOKEN."
        )

    init_database()

    logger.info("Database initialized.")

    if ADMIN_CHAT_ID:
        logger.info("Admin Chat ID configured.")
    else:
        logger.warning(
            "ADMIN_CHAT_ID is not configured."
        )

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # Commands
    application.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command,
        )
    )

    # Buttons
    application.add_handler(
        CallbackQueryHandler(
            button_handler,
        )
    )

    # Text
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler,
        )
    )

    application.add_error_handler(
        error_handler
    )

    print("==========================================")
    print("            R$ EXCHANGE BOT")
    print("            BOT IS RUNNING")
    print("==========================================")

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    run()