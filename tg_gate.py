import os
import logging
import config

# Enable logging for debug info
logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

from mixpanel import Mixpanel
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler, CallbackContext, ConversationHandler, CommandHandler
)
from telegram.constants import ChatAction

from find_subtitles import get_img_resized, parse_episodes, Opnsub, srt_cached
from srt_processor import extract_words


TG_BOT_KEY = os.environ.get('TG_BOT_KEY')
opn = Opnsub()

MIXPANEL_TOKEN = os.environ.get('MIXPANEL_TOKEN')
mp = Mixpanel(MIXPANEL_TOKEN)
logging.info('Mixpanel initialized')


async def start(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    mp.track(str(user_id), 'Bot Started', {
        'username': update.message.from_user.username,
        'first_name': update.message.from_user.first_name
    })
    await update.message.reply_text("Welcome.")


def suggestion_wrapper(get_opnsub_suggestions_data: list):
    if get_opnsub_suggestions_data:
        resp = {}
        for d in get_opnsub_suggestions_data:
            resp[d['id']] = {"caption": f"{str(d['title']).capitalize()}, {d['year']}  rate:{d['rating']}\n",
                             "img": d['poster']}
        return resp


def get_episodes(show_id: int, season=1) -> None | dict:
    episodes_raw_data = opn.get_srt_names(show_id, season=season)
    if episodes_raw_data:
        return parse_episodes(episodes_raw_data)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text
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
        mp.track(str(update.effective_chat.id), 'Warning: No suggestions', {
            'query': user_query,
        })
    return ConversationHandler.END


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle presses on our inline buttons.
    """
    query = update.callback_query
    logging.info(f"Callback data = {query.data}")

    if "show_id" in query.data:
        show_id = query.data.split("show_id:")[1]

        mp.track(str(update.effective_chat.id), 'Show requested', {
            'show_id': show_id
        })
        context.user_data["show_id"] = show_id

        episodes = get_episodes(int(show_id))
        if episodes:
            context.user_data["episodes"] = episodes
            # await query.message.reply_text(f"Season 1:")

            keyboard = [
                    [
                        InlineKeyboardButton(f"🎥 {episodes[episode]['title']}",
                                             callback_data=f"episode_id:{episodes[episode]['id']}")
                    ] for episode in episodes
                ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("Season 1:", reply_markup=reply_markup)
        else:
            await query.message.reply_text(f"Sorry, can't find episodes")
            mp.track(str(update.effective_chat.id), 'Failed: Episodes not found', {
                'show_id': show_id
            })
            context.user_data["episodes"] = {}  # Reset if no episodes found
        return ConversationHandler.END

    if "episode_id" in query.data:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        episode_id = query.data.split("episode_id:")[1]
        logging.info(f"Episode data = {episode_id}")

        mp.track(str(update.effective_chat.id), 'Episode requested', {
            'episode_id': episode_id
        })

        episodes = context.user_data.get("episodes", {})

        # Ensure episode exists in stored data
        if not episodes:
            await query.message.reply_text("Something went wrong.")
            logging.error(f"Didn't find episodes data when called for episode {episode_id}")
            return ConversationHandler.END

        await query.answer(f"Requesting episode data (id: {episode_id})")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        file_name = ''
        file_id = 0
        title = ''
        for episode in episodes:
            if episode_id == episodes[episode]['id']:
                file_name = episodes[episode]['file_name']
                file_id = int(episodes[episode]['file_id'])
                title = episodes[episode]['title']

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        if not srt_cached(file_name):
            logging.info(f"Srt file is not cached {file_name}")
            await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

            download_info = opn.get_srt_download_info(file_id)
            if download_info:
                logging.info(f"Download data acquired {download_info}")
                if opn.download_file(download_info['link'], download_info['file_name']):
                    await query.answer(f"Episode downloaded successfully.")
        else:
            logging.info(f"Srt file cached! {file_name}")
        await query.message.reply_text(f"⏳ Processing the text of {title}")
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        res = await extract_words(file_name)
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        if res:
            for k in res.keys():
                for l in res[k]:
                    mark_popular = ''
                    try:
                        start_time = l['start'].split(",")[0]
                    except (KeyError, IndexError) as e:
                        start_time = l['start']

                    if l['freq_srt']>2:
                        mark_popular = '(popular in episode)'
                    await query.message.reply_text(f"🕑{start_time} *{l['word']}* – {l['meaning']} {mark_popular}",
                                                   parse_mode='Markdown')
        else:
            mp.track(str(update.effective_chat.id), 'Failed: Episode extraction', {
                'episode_id': episode_id,
                'title': title,
                'show_id': context.user_data["show_id"]
            })
        return ConversationHandler.END


def main():

    application = ApplicationBuilder().token(TG_BOT_KEY).build()

    # Handler for any text message
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    application.add_handler(
        CallbackQueryHandler(handle_callback_query)
    )
    application.add_handler(CommandHandler("start", start))

    application.run_polling()


if __name__ == "__main__":
    main()
