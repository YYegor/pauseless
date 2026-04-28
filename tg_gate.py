import os
import logging
from random import randint, shuffle
from typing import Literal, cast

import telegram

import config
import asyncio
from telegram import BotCommand
from telegram import LabeledPrice
from mixpanel import Mixpanel, Consumer
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    ContextTypes,
    filters,
    PollAnswerHandler,
    CallbackQueryHandler, CallbackContext, ConversationHandler, CommandHandler
)
from telegram.constants import ChatAction
from telegram.ext import PreCheckoutQueryHandler
from find_subtitles import get_img_resized, parse_episodes, Opnsub, srt_cached
from srt_processor import extract_words

logging.getLogger("httpx").setLevel(logging.WARNING)
poll_index_type = Literal[0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
TG_BOT_KEY = os.environ.get('TG_BOT_KEY')

# Enable logging for debug info
logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

class VerboseConsumer(Consumer):
    def send(self, endpoint, json_message):
        print(f"[Mixpanel track] endpoint={endpoint}")
        print(f"[Mixpanel track] payload={json_message}")
        resp = super().send(endpoint, json_message)
        print(f"[Mixpanel track] response={resp}")
        return resp

opn = Opnsub()

MIXPANEL_TOKEN = os.environ.get('MIXPANEL_TOKEN')
mp = Mixpanel(MIXPANEL_TOKEN, consumer=VerboseConsumer())
logging.info('Mixpanel initialized')


def safe_track(mixpanel, *args, **kwargs):
    try:
        mixpanel.track(*args, **kwargs)
    except Exception as e:
        # Optional: log the error
        logging.warning(f"Mixpanel tracking failed: {e}")

async def get_top_series(update: Update, context: CallbackContext):
    response_dict = {"1340460": {'caption': 'Severance (2022)'},
                     "8882": {'caption': 'Breaking Bad (2008)'},
                     "1299348": {'caption': 'Squid Game (2021)'},
                     "1434916": {'caption': 'Shrinking (2023)'},
                     "7160": {'caption': 'South Park (1997)'}
                     }

    keyboard = [
        [
            InlineKeyboardButton(f"⭐ {response_dict[k]['caption']}",
                                 callback_data=f"show_id:{k}")
        ] for k in response_dict
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    for k in response_dict:
        context.user_data[k]=response_dict[k]['caption']

    await update.message.reply_text(f"I'll prep your vocab so you won't need to pause while watching.\n"
                                    f"Are you watching one of these hits?", reply_markup=reply_markup)
    await update.message.reply_text("Or let me help to find other shows. Just type the name.")
    return ConversationHandler.END


async def show_poll(update: Update, context: CallbackContext):
    index = context.user_data.get("card_index", 0)
    cards = context.user_data.get("cards")

    if not cards:
        return

    key = list(cards.keys())[index]
    l = cards[key][0]
    cards_index_max = len(cards) - 1

    def truncate_options(text: str, limit: int = 100) -> str:
        return text if len(text) <= limit else text[:limit - 3] + "..."

    # 1. Define the correct answer
    correct_answer = truncate_options(l['meaning'])

    # 2. Collect 3 unique distractors
    distractors = set()
    while len(distractors) < 3:
        key_ = list(cards.keys())[randint(0, cards_index_max)]
        candidate = truncate_options(cards[key_][0]['meaning'])
        if candidate != correct_answer:
            distractors.add(candidate)

    # 3. Create the final list and shuffle it
    poll_options = [correct_answer] + list(distractors)
    shuffle(poll_options)

    # 4. Find the new index of the correct answer
    correct_id = poll_options.index(correct_answer)

    # 5. Determine chat_id (Fallback to user_data if called from PollAnswerHandler)
    chat_id = update.effective_chat.id if update.effective_chat else context.user_data.get("chat_id")

    # 6. Send the poll and save its message ID so we can delete it later
    try:
        ipa_part = f" ({l['ipa']})" if l['ipa'] else ""
        poll_message = await context.bot.send_poll(
            chat_id=chat_id,
            question=f"[{index+1}/{len(cards)}] {l['word']}{ipa_part} means:",
            options=poll_options,
            is_anonymous=False,
            allows_multiple_answers=False,
            correct_option_id=cast(poll_index_type, correct_id),
            type='quiz'
        )

        # Save tracking data for the next step
        context.user_data["chat_id"] = chat_id
        context.user_data["current_poll_message_id"] = poll_message.message_id

    except (telegram.error.BadRequest, IndexError) as e:
        logging.warning(f": {e}; {poll_options}")


async def show_card(update: Update, last_message_id, context: CallbackContext):

    index = context.user_data.get("card_index", 0)

    cards = context.user_data.get("cards")
    key = list(cards.keys())[index]
    l = cards[key][0]
    mark_popular = ''
    try:
        start_time = l['start'].split(",")[0]
    except (KeyError, IndexError):
        start_time = l['start']

    if l['freq_srt'] > 2:
        mark_popular = '(popular in episode)'

    text = (f"🕑{start_time} *{l['word']}*"
            f" ({l['ipa']})\n"+"-"*45+"\n"
            f" {l['meaning']} {mark_popular}\n"
            f"{index+1}/{len(cards)}")

    keyboard = [
        [
            InlineKeyboardButton("◀️ Back", callback_data="prev"),
            InlineKeyboardButton("Next ▶️", callback_data="next")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                        message_id=last_message_id,
                                        text=text, reply_markup=reply_markup, parse_mode='Markdown')

async def buy(update, context: ContextTypes.DEFAULT_TYPE):
    prices = [LabeledPrice("Pro Access", 1)]
    await update.effective_chat.send_invoice(
        title="Pro Access",
        description="Unlock premium features",
        payload="order-001",
        provider_token="",          # empty for digital goods (Stars)
        currency="XTR",             # Stars currency
        prices=prices,
        start_parameter="multi"     # or single-chat behavior
    )

async def yt(update: Update, context: CallbackContext):
    await update.message.reply_text(
        f"Youtube transcripts tool is coming soon")

    safe_track(mp, str(update.message.chat_id), 'Youtube menu called', {
        'username': update.message.from_user.username,
        'first_name': update.message.from_user.first_name
    })

    return ConversationHandler.END

async def start(update: Update, context: CallbackContext):
    user_id = update.message.chat_id
    context.user_data["card_index"] = 0
    context.user_data["regime"] = "learn"
    context.user_data["cards"] = None
    args = context.args
    param = ""
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
    await get_top_series(update, context)

    return ConversationHandler.END

async def quiz(update: Update, context: CallbackContext):

    context.user_data["regime"] = "quiz"
    context.user_data["card_index"] = 0

    user_first_name = update.message.from_user.first_name or ''
    if user_first_name:
        user_first_name = ', ' + user_first_name

    await update.message.reply_text(
        f"Let's start the quiz{user_first_name}!")

    safe_track(mp, str(update.message.chat_id), 'Quiz menu called', {})
    await show_poll(update, context=context)

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

    # refresh cards
    context.user_data["cards"] = None

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
                context.user_data[k] = response_dict[k]['caption']

                await update.message.reply_photo(photo=f,
                                                 reply_markup=reply_markup)

    else:
        await update.message.reply_text("😿 No suggestions. Try again")
        safe_track(mp, str(update.effective_chat.id), 'Warning: No suggestions', {
            'query': user_query,
        })
    return ConversationHandler.END


async def cb_handler_show_id(update: Update, context: CallbackContext):
    print(context.user_data)
    context.user_data["feedback_input_flag"] = False
    query = update.callback_query
    print(query.data)
    show_id = query.data.split("show_id:")[1]

    safe_track(mp, str(update.effective_chat.id), 'Show requested', {
        'show_id': show_id
    })
    context.user_data["show_id"] = show_id
    print(context.user_data)
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
        message_episodes_list = await query.message.reply_text("Season 1:", reply_markup=reply_markup)
        context.user_data["episodes_list_message_id"] = message_episodes_list.message_id
        tap_vocab_message = await query.message.reply_text("Tap to explore the vocab.", reply_markup=None)
        context.user_data["tap_vocab_message_id"] = tap_vocab_message.message_id

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
    series_name = context.user_data[context.user_data["show_id"]] or ''
    print(context.user_data[context.user_data["show_id"]], context.user_data["show_id"])

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

    last_message = await query.message.reply_text(f"⏳ Processing the text of {title}. It may take a while...")
    context.user_data["card_last_message_id"] = last_message.message_id
    try:
        res = await extract_words(file_name, series_name=series_name)

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
        #await print_words_to_chat(query, res)
        context.user_data["cards"] = res
        context.user_data["card_index"] = 0

        #edit episodes list
        await context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                        message_id=context.user_data["episodes_list_message_id"],
                                        text=f"Episode '{title}'", parse_mode='Markdown')
        # remove unnecessary message
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data["tap_vocab_message_id"])
        # await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=context.user_data["card_last_message_id"])

        await show_card(update, last_message.message_id, context)
        # await show_poll(update, context)
        # await query.message.reply_text("⭐ Rate the words set with /feedback or search for another episode.")
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
            await query.message.reply_text(f"🕑{start_time} *{l['word']}* ({l['ipa']}) – {l['meaning']} {mark_popular}",
                                           parse_mode='Markdown')
            await asyncio.sleep(0.3)

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle presses on our inline buttons.
    """
    query = update.callback_query
    logging.info(f"Callback data = {query.data}")
    await query.answer()
    cards = context.user_data.get("cards", None)

    if cards:
        index = context.user_data.get("card_index", 0)
        if query.data == "next":
            index = (index + 1) % len(cards)
        elif query.data == "prev":
            index = (index - 1) % len(cards)

        context.user_data["card_index"] = index
        if context.user_data["regime"] == "quiz":
            await show_poll(update, context=context)
        else:
            await show_card(update, context.user_data["card_last_message_id"], context=context)

        return ConversationHandler.END

    if "show_id" in query.data:
        context.application.create_task(cb_handler_show_id(update, context))

        # await cb_handler_show_id(update, context)
        return ConversationHandler.END

    if "episode_id" in query.data:
        context.application.create_task(cb_handler_episode_id(update, context))

        # await cb_handler_episode_id(update, context)
        return ConversationHandler.END

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    await update.message.reply_text("✅ Payment received. Thanks! Your premium is unlocked.")
    # TODO: grant user's premium features here (e.g., set a flag in DB)


async def handle_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ When voted in the poll, move to the next poll"""
    cards = context.user_data.get("cards", None)

    if cards:
        # 1. Wait 1.5 seconds so the user sees the right/wrong animation
        await asyncio.sleep(1.0)

        chat_id = context.user_data.get("chat_id")
        old_poll_message_id = context.user_data.get("current_poll_message_id")

        # 2. Delete the old poll to create the "replacement" illusion
        if chat_id and old_poll_message_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_poll_message_id)
            except telegram.error.BadRequest as e:
                logging.warning(f"Could not delete old poll: {e}")

        # 3. Move to the next card
        index = context.user_data.get("card_index", 0)
        index = (index + 1) % len(cards)
        context.user_data["card_index"] = index

        # 4. Show the new poll
        await show_poll(update, context=context)

    return ConversationHandler.END

async def set_bot_commands(application):
    commands = [
        BotCommand("feedback", "Send feedback"),
        BotCommand("start", "Restart the bot"),
        BotCommand("yt", "Read from Youtube"),

        # Add more commands here
    ]
    await application.bot.set_my_commands(commands)



def main():
    application = ApplicationBuilder().token(TG_BOT_KEY).build()

    # Handler for any text message
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
    )

    application.add_handler(
        CallbackQueryHandler(handle_callback_query)
    )
    application.add_handler(PreCheckoutQueryHandler(precheckout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("feedback", feedback))
    application.add_handler(CommandHandler("premium", buy))
    application.add_handler(CommandHandler("youtube", yt))
    application.add_handler(CommandHandler("quiz", quiz))

    application.add_handler(PollAnswerHandler(handle_vote))

    application.post_init = set_bot_commands

    application.run_polling()


if __name__ == "__main__":
    main()
