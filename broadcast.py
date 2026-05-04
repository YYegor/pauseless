import os
import logging
import asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.error import TelegramError, Forbidden, BadRequest, RetryAfter
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

ADMIN_ID = int(os.environ.get('ADMIN_ID'))
USERS_FILE = "user_list.txt"
MESSAGE_FILE = "message.md"

logging.getLogger("httpx").setLevel(logging.WARNING)

def get_message_content() -> str:
    """Reads the markdown message from the file."""
    if not os.path.exists(MESSAGE_FILE):
        return ""
    with open(MESSAGE_FILE, 'r', encoding='utf-8') as f:
        return f.read()

def get_user_ids() -> list[int]:
    """Reads user IDs from the txt file."""
    if not os.path.exists(USERS_FILE):
        return []
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        # Read lines, strip whitespace, and keep only valid numbers
        return [int(line.strip()) for line in f if line.strip().isdigit()]


async def send_message_safely(bot, chat_id: int, text: str, reply_md=None) -> bool:
    """
    Sends a message to a specific user and handles Telegram errors gracefully.
    """
    try:

        await bot.send_message(chat_id=chat_id, text=text, parse_mode='Markdown', reply_markup=reply_md)
        return True

    except Forbidden:
        logging.warning(f"Skipped {chat_id}: User blocked the bot.")
        # Optional: You could add code here to remove this ID from users.txt
    except BadRequest as e:
        logging.warning(f"Skipped {chat_id}: Bad Request ({e}) - Chat might not exist.")
    except RetryAfter as e:
        logging.warning(f"Rate limited by Telegram. Sleeping for {e.retry_after} seconds.")
        await asyncio.sleep(e.retry_after)
        # Retry sending after sleeping
        return await send_message_safely(bot, chat_id, text)
    except TelegramError as e:
        logging.error(f"Failed to send to {chat_id}: Telegram Error ({e})")
    except Exception as e:
        logging.error(f"Unexpected error for {chat_id}: {e}")

    return False


async def command_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command 1: Sends the message only to the ADMIN_ID."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return  # Ignore unauthorized users

    text = get_message_content()
    if not text:
        await update.message.reply_text("❌ Error: `message.md` is missing or empty.")
        return

    await update.message.reply_text("🔄 Sending test message...")

    # button = InlineKeyboardButton("Restart", callback_data="start")
    # keyboard = InlineKeyboardMarkup([[button]])

    # Send the message with the keyboard

    success = await send_message_safely(context.bot, ADMIN_ID, text)


    if success:
        await update.message.reply_text("✅ Test message delivered successfully.")
    else:
        await update.message.reply_text("❌ Failed to deliver test message. Check terminal logs.")


async def command_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command 2: Sends the message to all IDs in users.txt."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return  # Ignore unauthorized users

    text = get_message_content()
    target_users = get_user_ids()

    if not text:
        await update.message.reply_text("❌ Error: `message.md` is missing or empty.")
        return
    if not target_users:
        await update.message.reply_text("❌ Error: `users.txt` is missing or empty.")
        return

    await update.message.reply_text(f"🚀 Starting broadcast to {len(target_users)} users...")

    success_count = 0
    for target_id in target_users:
        success = await send_message_safely(context.bot, target_id, text)
        if success:
            success_count += 1

        # VERY IMPORTANT: Sleep to respect Telegram's rate limits
        # Telegram allows max ~30 messages per second for broadcasts.
        await asyncio.sleep(0.05)

    await update.message.reply_text(
        f"🏁 **Broadcast Complete!**\n"
        f"Successfully sent: {success_count}/{len(target_users)}",
        parse_mode="Markdown"
    )