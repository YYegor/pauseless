import os
import logging
from webbrowser import Opera

from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler
)
from find_subtitles import suggestion_wrapper, get_img_resized, parse_episodes, Opnsub

TG_BOT_KEY = os.environ.get('TG_BOT_KEY')
opn = Opnsub()

# Enable logging for debug info
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


def show_episodes(show_id:int, season=1)->list:
    episodes_data = opn.get_opnsub_subtitles_names(show_id, season=season)
    if episodes_data:
        res_dict = parse_episodes(episodes_data)
        formatted_lines = []
        for res in res_dict:
            formatted_lines.append(f'{res_dict[res]["title"]}')
        return formatted_lines
    else:
        return []


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text  # The text from the user (not used here, but available)
    suggestions = opn.get_opnsub_suggestions(user_query)
    response_dict = suggestion_wrapper(suggestions)

    if response_dict:

        for k in response_dict:
            with open(get_img_resized(response_dict[k]["img"]), "rb") as f:
                keyboard = [
                    [
                        InlineKeyboardButton(f"{response_dict[k]['caption']}", callback_data=k)
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_photo(photo=f,
                                                 reply_markup=reply_markup)

    else:
        await update.message.reply_text("Can't find any suggestions. Try again")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle presses on our inline buttons.
    """
    query = update.callback_query
    show_id = query.data  # The callback_data we set in the button

    # Call the custom function with this button ID

    episodes = show_episodes(int(show_id))

    for episode in episodes:
        await query.message.reply_text(f"{episode}")

    # Acknowledge the callback to avoid "stuck" button
    # await query.answer("Button pressed!")

    # Optionally send a follow-up message or edit the existing one


def main():
    # Your Bot API key (token) goes here
    bot_token = TG_BOT_KEY

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
