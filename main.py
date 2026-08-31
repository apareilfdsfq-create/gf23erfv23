import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# SETTINGS
# =========================
BOT_TOKEN = "8989730014:AAGq4Ppq3YKlzukOSTkEr-BUZ_mrjn0RPWs"
CONTACT_USERNAME = "@berizienuhq"
PRICE = "NA"

PRESET_AMOUNTS = [200, 500, 700, 1000]

# =========================
# BOT
# =========================
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Temporary order data for each Telegram user.
# This is enough for a simple bot. Nothing is stored permanently.
orders = {}


def main_menu():
    keyboard = [
        [InlineKeyboardButton("💰 Buy Robux", callback_data="buy")],
        [InlineKeyboardButton("ℹ️ How it works", callback_data="how")],
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
        [InlineKeyboardButton("✏️ Custom Amount", callback_data="custom")],
        [InlineKeyboardButton("↩️ Back", callback_data="home")],
    ]
    return InlineKeyboardMarkup(keyboard)


def cancel_menu():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("❌ Cancel", callback_data="home")]]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders.pop(update.effective_user.id, None)

    text = (
        "🛍️ <b>R$ SHOP</b>\n\n"
        "Welcome! Choose the amount of Robux you'd like to order.\n\n"
        "Select an option below:"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "home":
        orders.pop(user_id, None)

        await query.edit_message_text(
            "🛍️ <b>R$ SHOP</b>\n\n"
            "Welcome! Choose an option below:",
            parse_mode="HTML",
            reply_markup=main_menu(),
        )
        return

    if data == "buy":
        await query.edit_message_text(
            "💰 <b>Select your Robux amount</b>\n\n"
            "Choose a preset amount or enter a custom amount.",
            parse_mode="HTML",
            reply_markup=amount_menu(),
        )
        return

    if data == "how":
        await query.edit_message_text(
            "ℹ️ <b>How it works</b>\n\n"
            "1. Select your Robux amount.\n"
            "2. Enter your Roblox username.\n"
            "3. The bot generates your order message.\n"
            "4. Send that message to our contact.\n"
            "5. Wait for your payment notification.\n\n"
            "⭐ Price: <b>NA</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Back", callback_data="home")]]
            ),
        )
        return

    if data.startswith("amount:"):
        amount = int(data.split(":")[1])
        orders[user_id] = {"amount": amount, "waiting_for": "username"}

        await query.edit_message_text(
            f"💰 <b>{amount:,} R$ selected</b>\n\n"
            "Now send your <b>Roblox username</b>.\n\n"
            "Example: <code>bakawjmi1</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )
        return

    if data == "custom":
        orders[user_id] = {"waiting_for": "custom_amount"}

        await query.edit_message_text(
            "✏️ <b>Custom Amount</b>\n\n"
            "Enter the amount of Robux you want.\n\n"
            "Example: <code>2500</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )
        return


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text.lower() == "/cancel":
        orders.pop(user_id, None)
        await update.message.reply_text(
            "❌ Order cancelled.",
            reply_markup=main_menu(),
        )
        return

    order = orders.get(user_id)

    if not order:
        await update.message.reply_text(
            "Please use /start to begin an order.",
            reply_markup=main_menu(),
        )
        return

    if order["waiting_for"] == "custom_amount":
        # Accept whole positive numbers only.
        cleaned = text.replace(",", "").replace(" ", "")

        if not cleaned.isdigit() or int(cleaned) <= 0:
            await update.message.reply_text(
                "⚠️ Please enter a valid positive number.\n\n"
                "Example: <code>2500</code>",
                parse_mode="HTML",
                reply_markup=cancel_menu(),
            )
            return

        amount = int(cleaned)

        # Basic safety/abuse limit. Change or remove if you want.
        if amount > 1000000:
            await update.message.reply_text(
                "⚠️ Please enter an amount of 1,000,000 R$ or less.",
                reply_markup=cancel_menu(),
            )
            return

        order["amount"] = amount
        order["waiting_for"] = "username"

        await update.message.reply_text(
            f"💰 <b>{amount:,} R$ selected</b>\n\n"
            "Now send your <b>Roblox username</b>.\n\n"
            "Example: <code>bakawjmi1</code>",
            parse_mode="HTML",
            reply_markup=cancel_menu(),
        )
        return

    if order["waiting_for"] == "username":
        username = text.lstrip("@")

        # Basic username validation.
        if not (3 <= len(username) <= 20):
            await update.message.reply_text(
                "⚠️ That doesn't look like a valid Roblox username.\n"
                "Please enter your username again.",
                reply_markup=cancel_menu(),
            )
            return

        if not all(c.isalnum() or c == "_" for c in username):
            await update.message.reply_text(
                "⚠️ Roblox usernames can only contain letters, numbers, "
                "and underscores.\n\nPlease try again.",
                reply_markup=cancel_menu(),
            )
            return

        amount = order["amount"]
        date = datetime.now().strftime("%d.%m.%Y")

        # This is the clean template sent to the customer.
        template = (
            "🧾 <b>R$ ORDER</b>\n\n"
            f"💰 Amount  >  <b>{amount:,} R$</b>\n"
            f"👤 R$ User  >  <b>{username}</b>\n"
            f"⭐ Price    >  <b>{PRICE}</b>\n"
            f"📅 Date     >  <b>{date}</b>"
        )

        instruction = (
            f"📩 <b>Next step</b>\n\n"
            f"Send the order above to <b>{CONTACT_USERNAME}</b>.\n"
            "Once your order is received, please wait for a "
            "payment notification.\n\n"
            "⚠️ Do not send payment until you receive the appropriate "
            "confirmation."
        )

        await update.message.reply_text(
            template,
            parse_mode="HTML",
        )

        await update.message.reply_text(
            instruction,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("🛍️ New Order", callback_data="buy")],
                    [InlineKeyboardButton("🏠 Main Menu", callback_data="home")],
                ]
            ),
        )

        orders.pop(user_id, None)


def run():
    if BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Put your Telegram bot token in BOT_TOKEN before running the bot."
        )

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", message_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

    print("R$ Shop bot is running...")
    app.run_polling()


if __name__ == "__main__":
    run()
