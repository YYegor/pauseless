import os
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler, ConversationHandler
)
from find_subtitles import get_img_resized, parse_episodes, Opnsub

TG_BOT_KEY = os.environ.get('TG_BOT_KEY')
opn = Opnsub()

# Enable logging for debug info
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename="/Users/egor/app.log"
)


def suggestion_wrapper(get_opnsub_suggestions_data: list):
    if get_opnsub_suggestions_data:
        resp = {}
        for d in get_opnsub_suggestions_data:
            resp[d['id']] = {"caption": f"{str(d['title']).capitalize()}, {d['year']}  rate:{d['rating']}\n",
                             "img": d['poster']}
        return resp


def show_episodes(show_id: int, season=1) -> list:
    episodes_data = opn.get_srt_names(show_id, season=season)
    if episodes_data:
        res_dict = parse_episodes(episodes_data)
        if res_dict:
            formatted_lines = []
            for res in res_dict:
                formatted_lines.append(f'{res_dict[res]["title"]}')
            return formatted_lines
    else:
        return []


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text  # The text from the user (not used here, but available)
    suggestions = opn.get_suggestions(user_query)
    response_dict = suggestion_wrapper(suggestions)

    if response_dict:

        for k in response_dict:
            with open(get_img_resized(response_dict[k]["img"]), "rb") as f:
                keyboard = [
                    [
                        InlineKeyboardButton(f"{response_dict[k]['caption']}",
                                             callback_data=f"show_id:{k}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_photo(photo=f,
                                                 reply_markup=reply_markup)

    else:
        await update.message.reply_text("No suggestions. Try again")


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle presses on our inline buttons.
    """
    query = update.callback_query
    logging.info(f"Callback data = {query.data}")

    if "show_id" in query.data:
        show_id = query.data.split("show_id:")[1]

        episodes = show_episodes(int(show_id))
        if episodes:
            await query.message.reply_text(f"Season 1:")
            for episode in episodes:
                keyboard = [
                    [
                        InlineKeyboardButton(f"Watch",
                                             callback_data=f"episode_id:{1}")
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text(f"{episode}",reply_markup=reply_markup)
        else:
            await query.message.reply_text(f"Sorry, can't find episodes")
        return ConversationHandler.END

    if "episode_id" in query.data:
        episode_id = query.data
        await query.answer(f"Episode {episode_id} will be requested")


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
