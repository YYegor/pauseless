key = '7959966862:AAG6BnLLdA4TSITM10A5BDP3hDF4XUGR2yY'

import logging
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)
from find_subtitles import suggestion_wrapper, resize_image

# Enable logging for debug info
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def f1(button_id: str):
    print(f"f1 called with button_id = {button_id}")
    # Perform any action you want here (DB update, etc.)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text  # The text from the user (not used here, but available)
    response_dict = suggestion_wrapper(user_query)
    for k in response_dict:
        with open(resize_image(response_dict[k]["img"]), "rb") as f:
            keyboard = [
                [
                    InlineKeyboardButton(f"{response_dict[k]['caption']}", callback_data=k)
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_photo(photo=f,

                                             reply_markup=reply_markup)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle presses on our inline buttons.
    """
    query = update.callback_query
    button_id = query.data  # The callback_data we set in the button

    # Call the custom function with this button ID
    f1(button_id)

    # Acknowledge the callback to avoid "stuck" button
    await query.answer("Button pressed!")

    # Optionally send a follow-up message or edit the existing one
    await query.message.reply_text(f"You pressed button ID: {button_id}")


def main():
    # Your Bot API key (token) goes here
    bot_token = key

    application = ApplicationBuilder().token(bot_token).build()

    # Handler for any text message
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    application.add_handler(
        CallbackQueryHandler(handle_callback_query)
    )

    application.run_polling()


if __name__ == "__main__":
    main()
