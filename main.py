```python
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
# SETTINGS
# ============================================================

# Railway:
# Create a variable called BOT_TOKEN and put your actual
# Telegram BotFather token as its VALUE.
BOT_TOKEN = os.getenv("BOT_TOKEN")

CONTACT_USERNAME = "@berizienuhq"
PRICE = "NA"

PRESET_AMOUNTS = [200, 500, 700, 1000]

# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)

# Temporary order information.
# It resets if the bot restarts.
orders = {}


# ============================================================
# MENUS
# ============================================================

def main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Buy Robux", callback_data="buy")],
        [InlineKeyboardButton("ℹ️ How It Works", callback_data="how")],
    ]

    return InlineKeyboardMarkup(keyboard)


def amount_menu():
    keyboard = [
        [
            InlineKeyboardButton("200 R$", callback_data="amount:200"),
            InlineKeyboardButton("500 R$", callback_data="amount:500"),
        ],
        [
            InlineKeyboardButton("700 R$", callback_data="amount:700"),
            InlineKeyboardButton("1,000 R$", callback_data="amount:1000"),
        ],
        [
            InlineKeyboardButton(
                "✏️ Custom Amount",
                callback_data="custom"
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

    orders.pop(user_id, None)

    text = (
        "🛍️ <b>R$ SHOP</b>\n\n"
        "Welcome!\n"
        "Choose the amount of Robux you'd like to order.\n\n"
        "Select an option below:"
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

    # ----------------------------
    # HOME
    # ----------------------------

    if data == "home":

        orders.pop(user_id, None)

        await query.edit_message_text(
            "🛍️ <b>R$ SHOP</b>\n\n"
            "Welcome!\n"
            "Choose an option below:",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

        return

    # ----------------------------
    # BUY
    # ----------------------------

    if data == "buy":

        await query.edit_message_text(
            "💰 <b>Select Robux Amount</b>\n\n"
            "Choose one of the available amounts:",
            parse_mode="HTML",
            reply_markup=amount_menu(),
        )

        return

    # ----------------------------
    # HOW IT WORKS
    # ----------------------------

    if data == "how":

        await query.edit_message_text(
            "ℹ️ <b>HOW IT WORKS</b>\n\n"
            "1️⃣ Select your Robux amount.\n\n"
            "2️⃣ Enter your Roblox username.\n\n"
            "3️⃣ The bot creates your order message.\n\n"
            "4️⃣ Send the generated message to "
            f"<b>{CONTACT_USERNAME}</b>.\n\n"
            "5️⃣ Wait for your payment notification.\n\n"
            "⭐ Current price: <b>NA</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💰 Buy Robux",
                            callback_data="buy"
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

    # ----------------------------
    # PRESET AMOUNT
    # ----------------------------

    if data.startswith("amount:"):

        amount = int(data.split(":")[1])

        orders[user_id] = {
            "amount": amount,
            "waiting_for": "username",
        }

        await query.edit_message_text(
            f"💰 <b>{amount:,} R$ Selected</b>\n\n"
            "Please enter your <b>Roblox username</b>.\n\n"
            "Example:\n"
            "<code>bakawjmi1</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )

        return

    # ----------------------------
    # CUSTOM AMOUNT
    # ----------------------------

    if data == "custom":

        orders[user_id] = {
            "waiting_for": "custom_amount",
        }

        await query.edit_message_text(
            "✏️ <b>CUSTOM AMOUNT</b>\n\n"
            "Enter the amount of Robux you'd like.\n\n"
            "Example:\n"
            "<code>2500</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )

        return


# ============================================================
# MESSAGE HANDLER
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

    # ----------------------------
    # CANCEL
    # ----------------------------

    if text.lower() == "/cancel":

        orders.pop(user_id, None)

        await update.message.reply_text(
            "❌ <b>Order cancelled.</b>\n\n"
            "You can start a new order whenever you're ready.",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )

        return

    # ----------------------------
    # NO ACTIVE ORDER
    # ----------------------------

    order = orders.get(user_id)

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

        if amount > 1000000:

            await update.message.reply_text(
                "⚠️ Please enter an amount of "
                "1,000,000 R$ or less.",
                reply_markup=cancel_menu(),
            )

            return

        orders[user_id] = {
            "amount": amount,
            "waiting_for": "username",
        }

        await update.message.reply_text(
            f"💰 <b>{amount:,} R$ Selected</b>\n\n"
            "Please enter your <b>Roblox username</b>.\n\n"
            "Example:\n"
            "<code>bakawjmi1</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )

        return

    # ========================================================
    # USERNAME
    # ========================================================

    if order["waiting_for"] == "username":

        username = text.lstrip("@")

        # Basic Roblox username validation
        if len(username) < 3 or len(username) > 20:

            await update.message.reply_text(
                "⚠️ <b>Invalid username</b>\n\n"
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
                "⚠️ <b>Invalid username</b>\n\n"
                "Roblox usernames can contain letters, "
                "numbers and underscores.\n\n"
                "Please try again.",
                parse_mode="HTML",
                reply_markup=cancel_menu(),
            )

            return

        amount = order["amount"]

        date = datetime.now().strftime("%d.%m.%Y")

        # ====================================================
        # FINAL ORDER TEMPLATE
        # ====================================================

        order_message = (
            "🧾 <b>R$ ORDER</b>\n\n"
            f"💰 Amount  >  <b>{amount:,} R$</b>\n"
            f"👤 R$ User  >  <b>{username}</b>\n"
            f"⭐ Price    >  <b>{PRICE}</b>\n"
            f"📅 Date     >  <b>{date}</b>"
        )

        # ====================================================
        # INSTRUCTIONS
        # ====================================================

        instructions = (
            "📩 <b>ORDER READY</b>\n\n"
            "Your order information is ready.\n\n"
            f"➡️ Send the message above to "
            f"<b>{CONTACT_USERNAME}</b>.\n\n"
            "Once your order has been received, "
            "please wait for your payment notification.\n\n"
            "Thank you for using the R$ Shop! 🛍️"
        )

        await update.message.reply_text(
            order_message,
            parse_mode="HTML",
        )

        await update.message.reply_text(
            instructions,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "💰 New Order",
                            callback_data="buy"
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

        # Clear temporary order
        orders.pop(user_id, None)


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.error(
        "Exception while handling an update:",
        exc_info=context.error,
    )


# ============================================================
# RUN BOT
# ============================================================

def run():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN is missing. "
            "Add a Railway environment variable named "
            "BOT_TOKEN containing your Telegram BotFather token."
        )

    # IMPORTANT:
    # The token is loaded from the Railway environment variable.
    # It is NOT written anywhere in this source code.

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

    print("===================================")
    print("       R$ SHOP BOT IS RUNNING")
    print("===================================")

    application.run_polling()


if __name__ == "__main__":
    run()