import os
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
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")

ADMIN_USERNAME = "@berizienuhq"

# Prices for each currency.
# Change "NA" to your actual prices whenever you are ready.

PRICES = {
    "GRAM": {
        200: "NA",
        500: "NA",
        700: "NA",
        1000: "NA",
    },
    "STARS": {
        200: "NA",
        500: "NA",
        700: "NA",
        1000: "NA",
    },
}

# Price shown for custom orders.
CUSTOM_PRICE = {
    "GRAM": "NA",
    "STARS": "NA",
}


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# USER ORDER STORAGE
# ============================================================

user_orders = {}

# Order number.
# Note: this resets if the bot restarts.
order_number = 0


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def next_order_number():
    global order_number

    order_number += 1

    return f"#{order_number:04d}"


def get_currency_name(currency):
    if currency == "STARS":
        return "Telegram Stars"

    return "GRAM"


def get_price(currency, amount, custom=False):
    if custom:
        return CUSTOM_PRICE.get(currency, "NA")

    return PRICES.get(currency, {}).get(amount, "NA")


# ============================================================
# MAIN MENU
# ============================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "💱 Exchange",
                callback_data="exchange"
            )
        ],
        [
            InlineKeyboardButton(
                "ℹ️ How It Works",
                callback_data="how"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# CURRENCY MENU
# ============================================================

def currency_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "💎 GRAM",
                callback_data="currency:GRAM"
            )
        ],
        [
            InlineKeyboardButton(
                "⭐ Telegram Stars",
                callback_data="currency:STARS"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Back",
                callback_data="home"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# AMOUNT MENU
# ============================================================

def amount_menu(currency):
    keyboard = [
        [
            InlineKeyboardButton(
                "200 R$",
                callback_data=f"amount:{currency}:200"
            ),
            InlineKeyboardButton(
                "500 R$",
                callback_data=f"amount:{currency}:500"
            ),
        ],
        [
            InlineKeyboardButton(
                "700 R$",
                callback_data=f"amount:{currency}:700"
            ),
            InlineKeyboardButton(
                "1,000 R$",
                callback_data=f"amount:{currency}:1000"
            ),
        ],
        [
            InlineKeyboardButton(
                "✏️ Custom Amount",
                callback_data=f"custom:{currency}"
            )
        ],
        [
            InlineKeyboardButton(
                "↩️ Back",
                callback_data="exchange"
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# ============================================================
# CANCEL BUTTON
# ============================================================

def cancel_menu():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Cancel",
                    callback_data="home"
                )
            ]
        ]
    )


# ============================================================
# /START
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Clear any unfinished order.
    user_orders.pop(user_id, None)

    text = (
        "🛍️ <b>R$ EXCHANGE</b>\n\n"
        "Welcome!\n\n"
        "Exchange your GRAM or Telegram Stars "
        "for Robux.\n\n"
        "Choose an option below:"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


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
        user_orders.pop(user_id, None)

        await query.edit_message_text(
            "🛍️ <b>R$ EXCHANGE</b>\n\n"
            "Welcome!\n\n"
            "Choose an option below:",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # EXCHANGE
    # --------------------------------------------------------

    if data == "exchange":

        await query.edit_message_text(
            "💱 <b>SELECT CURRENCY TO EXCHANGE</b>\n\n"
            "Choose the currency you would like to exchange:",
            parse_mode="HTML",
            reply_markup=currency_menu(),
        )

        return

    # --------------------------------------------------------
    # HOW IT WORKS
    # --------------------------------------------------------

    if data == "how":

        await query.edit_message_text(
            "ℹ️ <b>HOW IT WORKS</b>\n\n"
            "1️⃣ Select the currency you want to exchange.\n\n"
            "2️⃣ Select the amount of Robux.\n\n"
            "3️⃣ Enter your Roblox username.\n\n"
            "4️⃣ Your order is created automatically.\n\n"
            f"5️⃣ We receive your order and "
            f"you will receive a DM from <b>{ADMIN_USERNAME}</b> "
            "to finalise the exchange.\n\n"
            "⭐ Prices currently show as <b>NA</b>.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💱 Exchange",
                            callback_data="exchange"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "↩️ Back",
                            callback_data="home"
                        )
                    ],
                ]
            ),
        )

        return

    # --------------------------------------------------------
    # CURRENCY
    # --------------------------------------------------------

    if data.startswith("currency:"):

        currency = data.split(":")[1]

        user_orders[user_id] = {
            "currency": currency,
            "waiting_for": "amount",
        }

        currency_name = get_currency_name(currency)

        await query.edit_message_text(
            f"💱 <b>{currency_name}</b>\n\n"
            "Select how much Robux you would like:",
            parse_mode="HTML",
            reply_markup=amount_menu(currency),
        )

        return

    # --------------------------------------------------------
    # PRESET AMOUNT
    # --------------------------------------------------------

    if data.startswith("amount:"):

        parts = data.split(":")

        currency = parts[1]
        amount = int(parts[2])

        price = get_price(
            currency,
            amount
        )

        user_orders[user_id] = {
            "currency": currency,
            "amount": amount,
            "price": price,
            "custom": False,
            "waiting_for": "username",
        }

        currency_name = get_currency_name(currency)

        await query.edit_message_text(
            f"💰 <b>{amount:,} R$ selected</b>\n\n"
            f"💱 Currency: <b>{currency_name}</b>\n"
            f"⭐ Price: <b>{price}</b>\n\n"
            "👤 Enter your <b>Roblox username</b>.\n\n"
            "Example:\n"
            "<code>bakawjmi1</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )

        return

    # --------------------------------------------------------
    # CUSTOM AMOUNT
    # --------------------------------------------------------

    if data.startswith("custom:"):

        currency = data.split(":")[1]

        user_orders[user_id] = {
            "currency": currency,
            "custom": True,
            "waiting_for": "custom_amount",
        }

        currency_name = get_currency_name(currency)
        price = get_price(
            currency,
            0,
            custom=True
        )

        await query.edit_message_text(
            "✏️ <b>CUSTOM AMOUNT</b>\n\n"
            f"💱 Currency: <b>{currency_name}</b>\n"
            f"⭐ Price: <b>{price}</b>\n\n"
            "Enter the amount of Robux you would like.\n\n"
            "Example:\n"
            "<code>2500</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )

        return


# ============================================================
# TEXT MESSAGE HANDLER
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
    text = update.message.text.strip()

    # --------------------------------------------------------
    # CANCEL
    # --------------------------------------------------------

    if text.lower() == "/cancel":

        user_orders.pop(user_id, None)

        await update.message.reply_text(
            "❌ <b>Order cancelled.</b>\n\n"
            "You can start a new order whenever you're ready.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

        return

    # --------------------------------------------------------
    # CHECK ACTIVE ORDER
    # --------------------------------------------------------

    order = user_orders.get(user_id)

    if not order:

        await update.message.reply_text(
            "Please use /start to open the shop.",
            reply_markup=main_menu(),
        )

        return

    # ========================================================
    # CUSTOM AMOUNT
    # ========================================================

    if order["waiting_for"] == "custom_amount":

        cleaned = (
            text
            .replace(",", "")
            .replace(" ", "")
        )

        if not cleaned.isdigit():

            await update.message.reply_text(
                "⚠️ <b>Invalid amount</b>\n\n"
                "Please enter numbers only.\n\n"
                "Example:\n"
                "<code>2500</code>",
                parse_mode="HTML",
                reply_markup=cancel_menu(),
            )

            return

        amount = int(cleaned)

        if amount <= 0:

            await update.message.reply_text(
                "⚠️ The amount must be greater than 0.",
                reply_markup=cancel_menu(),
            )

            return

        if amount > 1_000_000:

            await update.message.reply_text(
                "⚠️ Please enter an amount of "
                "1,000,000 R$ or less.",
                reply_markup=cancel_menu(),
            )

            return

        currency = order["currency"]

        order["amount"] = amount
        order["price"] = get_price(
            currency,
            amount,
            custom=True
        )

        order["waiting_for"] = "username"

        currency_name = get_currency_name(currency)

        await update.message.reply_text(
            f"💰 <b>{amount:,} R$ selected</b>\n\n"
            f"💱 Currency: <b>{currency_name}</b>\n"
            f"⭐ Price: <b>{order['price']}</b>\n\n"
            "👤 Enter your <b>Roblox username</b>.\n\n"
            "Example:\n"
            "<code>bakawjmi1</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )

        return

    # ========================================================
    # ROBLOX USERNAME
    # ========================================================

    if order["waiting_for"] == "username":

        username = text.lstrip("@")

        # Basic username validation.

        if len(username) < 3 or len(username) > 20:

            await update.message.reply_text(
                "⚠️ <b>Invalid Roblox username</b>\n\n"
                "Please enter your Roblox username again.",
                parse_mode="HTML",
                reply_markup=cancel_menu(),
            )

            return

        if not all(
            character.isalnum() or character == "_"
            for character in username
        ):

            await update.message.reply_text(
                "⚠️ <b>Invalid Roblox username</b>\n\n"
                "Roblox usernames can contain letters, "
                "numbers and underscores.\n\n"
                "Please try again.",
                parse_mode="HTML",
                reply_markup=cancel_menu(),
            )

            return

        # ----------------------------------------------------
        # ORDER DATA
        # ----------------------------------------------------

        amount = order["amount"]
        currency = order["currency"]
        price = order["price"]

        currency_name = get_currency_name(currency)

        date = datetime.now().strftime("%d.%m.%Y")
        order_id = next_order_number()

        # ----------------------------------------------------
        # CUSTOMER ORDER
        # ----------------------------------------------------

        customer_order = (
            "🧾 <b>ORDER CREATED</b>\n\n"
            f"🔢 Order ID  >  <b>{order_id}</b>\n"
            f"💰 Robux  >  <b>{amount:,} R$</b>\n"
            f"💱 Currency  >  <b>{currency_name}</b>\n"
            f"👤 Roblox User  >  <b>{username}</b>\n"
            f"⭐ Price  >  <b>{price}</b>\n"
            f"📅 Date  >  <b>{date}</b>"
        )

        # ----------------------------------------------------
        # CUSTOMER CONFIRMATION
        # ----------------------------------------------------

        customer_confirmation = (
            f"✅ <b>Order {order_id}</b>\n\n"
            "We have received your order.\n\n"
            f"📩 Please wait for a DM from "
            f"<b>{ADMIN_USERNAME}</b> "
            "to finalise the exchange.\n\n"
            "Thank you for using <b>R$ Exchange</b>."
        )

        # ----------------------------------------------------
        # SEND ORDER TO CUSTOMER
        # ----------------------------------------------------

        await update.message.reply_text(
            customer_order,
            parse_mode="HTML",
        )

        await update.message.reply_text(
            customer_confirmation,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💱 New Order",
                            callback_data="exchange"
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🏠 Main Menu",
                            callback_data="home"
                        )
                    ],
                ]
            ),
        )

        # ====================================================
        # SEND ORDER TO ADMIN
        # ====================================================

        if ADMIN_CHAT_ID:

            admin_order = (
                "🔔 <b>NEW ORDER</b>\n\n"
                f"🔢 Order ID  >  <b>{order_id}</b>\n"
                f"💰 Robux  >  <b>{amount:,} R$</b>\n"
                f"💱 Currency  >  <b>{currency_name}</b>\n"
                f"👤 Roblox User  >  <b>{username}</b>\n"
                f"⭐ Price  >  <b>{price}</b>\n"
                f"📅 Date  >  <b>{date}</b>\n\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "👤 <b>Telegram Customer</b>\n"
                f"Name: <b>{update.effective_user.full_name}</b>\n"
                f"Username: "
                f"<b>@{update.effective_user.username}</b>\n"
                f"Chat ID: <code>{user_id}</code>"
                if update.effective_user.username
                else
                (
                    "🔔 <b>NEW ORDER</b>\n\n"
                    f"🔢 Order ID  >  <b>{order_id}</b>\n"
                    f"💰 Robux  >  <b>{amount:,} R$</b>\n"
                    f"💱 Currency  >  <b>{currency_name}</b>\n"
                    f"👤 Roblox User  >  <b>{username}</b>\n"
                    f"⭐ Price  >  <b>{price}</b>\n"
                    f"📅 Date  >  <b>{date}</b>\n\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "👤 <b>Telegram Customer</b>\n"
                    f"Name: <b>{update.effective_user.full_name}</b>\n"
                    f"Chat ID: <code>{user_id}</code>"
                )
            )

            try:

                await context.bot.send_message(
                    chat_id=int(ADMIN_CHAT_ID),
                    text=admin_order,
                    parse_mode="HTML",
                )

                logger.info(
                    "Order %s successfully sent to admin.",
                    order_id
                )

            except Exception as error:

                logger.error(
                    "Failed to send order %s to admin: %s",
                    order_id,
                    error,
                )

        else:

            logger.warning(
                "ADMIN_CHAT_ID is not configured. "
                "Order %s was not sent to admin.",
                order_id,
            )

        # Remove finished order.
        user_orders.pop(user_id, None)


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Exception while handling update:",
        exc_info=context.error,
    )


# ============================================================
# START BOT
# ============================================================

def run():

    # --------------------------------------------------------
    # CHECK BOT TOKEN
    # --------------------------------------------------------

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is missing. "
            "Add BOT_TOKEN to Railway Variables."
        )

    if BOT_TOKEN == "BOT_TOKEN":

        raise RuntimeError(
            "BOT_TOKEN is configured incorrectly. "
            "The value cannot literally be 'BOT_TOKEN'."
        )

    # --------------------------------------------------------
    # ADMIN CHAT ID WARNING
    # --------------------------------------------------------

    if not ADMIN_CHAT_ID:

        logger.warning(
            "ADMIN_CHAT_ID is not configured. "
            "The shop will work, but orders cannot be "
            "sent to the admin."
        )

    # --------------------------------------------------------
    # CREATE BOT
    # --------------------------------------------------------

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # --------------------------------------------------------
    # HANDLERS
    # --------------------------------------------------------

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("cancel", message_handler)
    )

    application.add_handler(
        CallbackQueryHandler(button_handler)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    application.add_error_handler(error_handler)

    # --------------------------------------------------------
    # START POLLING
    # --------------------------------------------------------

    print("==========================================")
    print("           R$ EXCHANGE BOT")
    print("           BOT IS RUNNING")
    print("==========================================")

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    run()