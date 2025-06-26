import os
import logging
import config
import asyncio
from telegram import BotCommand

# Enable logging for debug info
logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)
logging.getLogger("httpx").setLevel(logging.WARNING)

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


def safe_track(mixpanel, *args, **kwargs):
    try:
        mixpanel.track(*args, **kwargs)
    except Exception as e:
        # Optional: log the error
        logging.warning(f"Mixpanel tracking failed: {e}")


async def get_top_series(update: Update):
    response_dict = {"1340460": {'caption': 'Severance (2022)'},
                     "8882": {'caption': 'Breaking Bad (2008)'},
                     "1299348": {'caption': 'Squid Game (2021)'},
                     "1434916": {'caption': 'Shrinking (2023)'},
                     "7160": {'caption': 'South Park (1997)'},
                     }

    keyboard = [
        [
            InlineKeyboardButton(f"⭐ {response_dict[k]['caption']}",
                                 callback_data=f"show_id:{k}")
        ] for k in response_dict
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(f"I'll prep your vocab so you won't need to pause while watching.\n"
                                    f"Are you watching one of these hits?", reply_markup=reply_markup)
    await update.message.reply_text("Or let me help to find other shows. Just type the name.")
    return ConversationHandler.END


async def start(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    args = context.args
    param = ''
    if args:
        param = args[0]

    safe_track(mp, str(user_id), 'Bot Started', {
        'username': update.message.from_user.username,
        'first_name': update.message.from_user.first_name,
        'start_parameter': param
    })
    context.user_data["feedback_input_flag"] = False
    user_first_name = update.message.from_user.first_name or ''
    if user_first_name:
        user_first_name = ', ' + user_first_name
    await update.message.reply_text(f"Hi{user_first_name}!")
    await get_top_series(update)

    return ConversationHandler.END


async def feedback(update: Update, context: CallbackContext):
    context.user_data["feedback_input_flag"] = True

    user_first_name = update.message.from_user.first_name or ''
    if user_first_name:
        user_first_name = ', ' + user_first_name
    await update.message.reply_text(
        f"Your feedback is very valuable{user_first_name}! Please type in your feedback here:")

    return ConversationHandler.END


def get_episodes(show_id: int, season=1) -> None | dict:
    episodes_raw_data = opn.get_srt_names(show_id, season=season)
    if episodes_raw_data:
        return parse_episodes(episodes_raw_data)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_query = update.message.text
    if context.user_data.get("feedback_input_flag"):
        safe_track(mp, str(update.message.chat_id), 'Feedback', {
            'username': update.message.from_user.username,
            'first_name': update.message.from_user.first_name,
            'feedback_text': str(user_query),
            'last_show_id': context.user_data.get("show_id") or '',
            'last_episode_id': context.user_data.get("episode_id") or ''

        })
        context.user_data["feedback_input_flag"] = False
        await update.message.reply_text("Sent! 🙏", reply_markup=None)
        return ConversationHandler.END

    await update.message.reply_text("Looking...", reply_markup=None)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    suggestions = opn.get_features(user_query)
    response_dict = opn.suggestion_wrapper(suggestions)

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
        await update.message.reply_text("😿 No suggestions. Try again")
        safe_track(mp, str(update.effective_chat.id), 'Warning: No suggestions', {
            'query': user_query,
        })
    return ConversationHandler.END


async def cb_handler_show_id(update: Update, context: CallbackContext):
    context.user_data["feedback_input_flag"] = False
    query = update.callback_query
    show_id = query.data.split("show_id:")[1]

    safe_track(mp, str(update.effective_chat.id), 'Show requested', {
        'show_id': show_id
    })
    context.user_data["show_id"] = show_id

    await query.message.reply_text("Great choice! Looking for episodes...", reply_markup=None)

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

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
        await query.message.reply_text("Tap to explore the vocab.", reply_markup=None)
    else:
        await query.message.reply_text(f"Sorry, can't find episodes")
        safe_track(mp, str(update.effective_chat.id), 'Failed: Episodes not found', {
            'show_id': show_id
        })
        context.user_data["episodes"] = {}  # Reset if no episodes found
    return


async def cb_handler_episode_id(update: Update, context: CallbackContext):
    context.user_data["feedback_input_flag"] = False
    query = update.callback_query

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    episode_id = query.data.split("episode_id:")[1]
    logging.info(f"Episode data = {episode_id}")

    episodes = context.user_data.get("episodes", {})

    if not episodes:
        await query.message.reply_text("☁️ Something went wrong. It's not you, it's me.")

        safe_track(mp, str(update.effective_chat.id), 'Warning: no episodes yielded', {
            'episode_id': episode_id,
            'show_id': context.user_data["show_id"]
        })

        logging.error(f"Didn't find episodes data when called for episode {episode_id}")
        return ConversationHandler.END

    safe_track(mp, str(update.effective_chat.id), 'Episode request success', {
        'episode_id': episode_id
    })

    # await query.answer(f"Requesting episode data (id: {episode_id})")
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

    await query.message.reply_text(f"⏳ Processing the text of {title}. It may take a while...")
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    try:
        res = await extract_words(file_name)
    except Exception as e:
        logging.error(f"Error {e} while extracting  {file_name}")
        safe_track(mp, str(update.effective_chat.id), 'Error', {
            'filename': file_name,
            'action': 'extract_words'
        })
        await query.message.reply_text("☁️ Something went wrong. It's not you, it's me.")
        return ConversationHandler.END

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

    if res:
        await print_words_to_chat(query, res)
        await query.message.reply_text("⭐ Rate the words set with /feedback or search for another episode.")
        # TODO: show the button for the next episode
    else:
        safe_track(mp, str(update.effective_chat.id), 'Error: Episode extraction failed', {
            'episode_id': episode_id,
            'title': title,
            'show_id': context.user_data["show_id"]
        })
    return

async def print_words_to_chat(query, res: dict):
    for k in res.keys():
        for l in res[k]:
            mark_popular = ''
            try:
                start_time = l['start'].split(",")[0]
            except (KeyError, IndexError):
                start_time = l['start']

            if l['freq_srt'] > 2:
                mark_popular = '(popular in episode)'
            await query.message.reply_text(f"🕑{start_time} *{l['word']}* – {l['meaning']} {mark_popular}",
                                           parse_mode='Markdown')
            await asyncio.sleep(0.3)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle presses on our inline buttons.
    """
    query = update.callback_query
    logging.info(f"Callback data = {query.data}")

    if "show_id" in query.data:
        context.application.create_task(cb_handler_show_id(update, context))

        # await cb_handler_show_id(update, context)
        return ConversationHandler.END

    if "episode_id" in query.data:
        context.application.create_task(cb_handler_episode_id(update, context))

        # await cb_handler_episode_id(update, context)
        return ConversationHandler.END


async def set_bot_commands(application):
    commands = [
        BotCommand("feedback", "Send feedback"),
        BotCommand("start", "Restart the bot"),
        # Add more commands here
    ]
    await application.bot.set_my_commands(commands)


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
    application.add_handler(CommandHandler("feedback", feedback))
    application.post_init = set_bot_commands

    application.run_polling()


if __name__ == "__main__":
    main()
