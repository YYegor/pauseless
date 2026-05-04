import os
import logging
from random import randint, shuffle
from typing import Literal, cast
from broadcast import command_broadcast, command_test
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
from find_subtitles import get_img_resized, Opnsub, srt_cached
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
        context.user_data[k] = response_dict[k]['caption']

    await update.message.reply_text(f"I'll prep your vocab so you won't need to pause while watching.\n"
                                    f"Are you watching one of these hits?", reply_markup=reply_markup)
    await update.message.reply_text("Or let me help to find other shows. Just type the name.")
    return ConversationHandler.END


async def show_poll(update: Update, context: CallbackContext):
    def truncate_options(text: str, limit: int = 100) -> str:
        return text if len(text) <= limit else text[:limit - 3] + "..."

    index = context.user_data.get("card_index", 0)

    cards = context.user_data.get("cards")

    if not cards:
        return
    key = list(cards.keys())[index]
    l = cards[key][0]

    cards_index_max = len(cards) - 1

    if cards_index_max > config.quiz_limit:
        cards_index_max = 15

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
            question=f"[{index + 1}/{cards_index_max}] {l['word']}{ipa_part} means:",
            options=poll_options,
            is_anonymous=False,
            allows_multiple_answers=False,
            correct_option_id=cast(poll_index_type, correct_id),
            type='quiz'
        )

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
            f" ({l['ipa']})\n" + "-" * 45 + "\n"
                                            f" {l['meaning']} {mark_popular}\n"
                                            f"{index + 1}/{len(cards)}")

    keyboard = [
        [
            InlineKeyboardButton("◀️ Back", callback_data="prev"),
            InlineKeyboardButton("🏆Quiz me", callback_data="quiz"),
            InlineKeyboardButton("Next ▶️", callback_data="next")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # FIX: Catch "Message is not modified" safely
    try:
        await context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                            message_id=last_message_id,
                                            text=text, reply_markup=reply_markup, parse_mode='Markdown')
    except telegram.error.BadRequest as e:
        if "Message is not modified" not in str(e):
            logging.warning(f"Error editing card: {e}")


async def buy(update, context: ContextTypes.DEFAULT_TYPE):
    prices = [LabeledPrice("Pro Access", 1)]
    await update.effective_chat.send_invoice(
        title="Pro Access",
        description="Unlock premium features",
        payload="order-001",
        provider_token="",  # empty for digital goods (Stars)
        currency="XTR",  # Stars currency
        prices=prices,
        start_parameter="multi"  # or single-chat behavior
    )


async def yt(update: Update, context: CallbackContext):
    await update.message.reply_text(f"Youtube transcripts tool is coming soon")
    safe_track(mp, str(update.message.chat_id), 'Youtube menu called', {
        'username': update.message.from_user.username,
        'first_name': update.message.from_user.first_name
    })
    return ConversationHandler.END


async def start(update: Update, context: CallbackContext):
    user_id = update.effective_user
    context.user_data["card_index"] = 0
    context.user_data["regime"] = "learn"
    context.user_data["cards"] = None
    context.user_data["season_n"] = 1
    context.user_data["episodes_list_message_id"] = None

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
    if not context.user_data.get("cards"):
        await update.message.reply_text("Nothing to quiz! Find a series first")
        return ConversationHandler.END

    context.user_data["regime"] = "quiz"
    context.user_data["card_index"] = 0

    user = update.effective_user
    user_first_name = user.first_name or ''
    if user_first_name:
        user_first_name = ', ' + user_first_name

    message_text = f"Let's start the quiz{user_first_name}!"

    if update.message:
        # If it's a message update, reply directly to the message
        await update.message.reply_text(message_text)
    elif update.effective_chat:
        # If it's not a message (e.g., callback query), send a message to the effective chat
        await context.bot.send_message(chat_id=update.effective_chat.id, text=message_text)

    safe_track(mp, str(update.effective_chat.id), 'Quiz menu called', {})
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

    # refresh cards, reset
    context.user_data["regime"] = "learn"
    context.user_data["season_n"] = 1
    context.user_data["episodes_list_message_id"] = None

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

                await update.message.reply_photo(photo=f, reply_markup=reply_markup)
    else:
        await update.message.reply_text("😿 No suggestions. Try again")
        safe_track(mp, str(update.effective_chat.id), 'Warning: No suggestions', {
            'query': user_query,
        })
    return ConversationHandler.END


async def cb_handler_show_id(update: Update, context: CallbackContext):
    try:
        context.user_data["feedback_input_flag"] = False
        query = update.callback_query

        # Determine current target
        target_show_id = query.data.split("show_id:")[1] if "show_id:" in query.data else context.user_data.get(
            "show_id")

        # FIX: Reset stale episode list ID if the user clicked a different show
        if context.user_data.get("show_id") and context.user_data["show_id"] != target_show_id:
            context.user_data["episodes_list_message_id"] = None
            context.user_data["season_n"] = 1

        context.user_data["show_id"] = target_show_id

        safe_track(mp, str(update.effective_chat.id), 'Show requested', {
            'show_id': target_show_id
        })

        season_number = opn.get_seasons_number(target_show_id)
        current_season = context.user_data.get("season_n", 1)

        await query.answer(
            text=f"Looking for episodes for Season {current_season}/{season_number} ...",
            show_alert=False
        )
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        episodes = opn.get_episodes(int(target_show_id), season=current_season)

        if episodes:
            context.user_data["episodes"] = episodes

            keyboard = [
                [
                    InlineKeyboardButton(f"🎥 {episodes[episode]['title']}",
                                         callback_data=f"episode_id:{episodes[episode]['id']}")
                ] for episode in episodes
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if context.user_data.get("episodes_list_message_id"):
                # Safe edit for episode list updates (e.g. season switch)
                try:
                    await context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                                        message_id=context.user_data["episodes_list_message_id"],
                                                        text=f"Season {current_season}:", reply_markup=reply_markup)
                except telegram.error.BadRequest:
                    pass
            else:
                message_episodes_list = await query.message.reply_text(f"Season {current_season}:",
                                                                       reply_markup=reply_markup)
                context.user_data["episodes_list_message_id"] = message_episodes_list.message_id

                # prepare Season list buttons
                keyboard = [
                    [
                        InlineKeyboardButton(f"{i}", callback_data=f"season_n:{i}")
                        for i in range(1, season_number + 1)
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.message.reply_text("Switch seasons:", reply_markup=reply_markup, parse_mode='Markdown')

                tap_vocab_message = await query.message.reply_text("Tap to explore the vocab.", reply_markup=None)
                context.user_data["tap_vocab_message_id"] = tap_vocab_message.message_id

            # Note: We do NOT reset context.user_data["season_n"] here, otherwise it breaks switching seasons
        else:
            await query.message.reply_text(f"Sorry, can't find episodes")
            safe_track(mp, str(update.effective_chat.id), 'Failed: Episodes not found', {
                'show_id': target_show_id
            })
            context.user_data["episodes"] = {}
    finally:
        # Release the lock for show clicking
        context.user_data["is_processing_show"] = False


async def cb_handler_episode_id(update: Update, context: CallbackContext):
    try:
        context.user_data["feedback_input_flag"] = False
        query = update.callback_query

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        episode_id = query.data.split("episode_id:")[1]
        logging.info(f"Episode data = {episode_id}")

        episodes = context.user_data.get("episodes", {})
        series_name = context.user_data.get(context.user_data.get("show_id"), '')

        if not episodes:
            await query.message.reply_text("☁️ Something went wrong. It's not you, it's me.")
            safe_track(mp, str(update.effective_chat.id), 'Warning: no episodes yielded', {
                'episode_id': episode_id,
                'show_id': context.user_data.get("show_id")
            })
            return ConversationHandler.END

        safe_track(mp, str(update.effective_chat.id), 'Episode request success', {
            'episode_id': episode_id
        })

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

            # FIX: Edit the hanging "Processing..." message instead of leaving it there
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=last_message.message_id,
                    text="☁️ Something went wrong while parsing the words. It's not you, it's me."
                )
            except telegram.error.BadRequest:
                pass
            return ConversationHandler.END

        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)

        if res:
            context.user_data["cards"] = res
            context.user_data["card_index"] = 0

            # Safe edit episodes list title
            try:
                await context.bot.edit_message_text(chat_id=update.effective_chat.id,
                                                    message_id=context.user_data["episodes_list_message_id"],
                                                    text=f"Episode '{title}'", parse_mode='Markdown')
            except telegram.error.BadRequest:
                pass

            # FIX: Safe delete to avoid "Message to delete not found" on double-clicks
            msg_id = context.user_data.get("tap_vocab_message_id")
            if msg_id:
                try:
                    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
                    context.user_data["tap_vocab_message_id"] = None
                except telegram.error.BadRequest:
                    pass

            await show_card(update, last_message.message_id, context)
        else:
            safe_track(mp, str(update.effective_chat.id), 'Error: Episode extraction failed', {
                'episode_id': episode_id,
                'title': title,
                'show_id': context.user_data.get("show_id")
            })

            # FIX: Edit the hanging "Processing..." message if no words were found
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=last_message.message_id,
                    text="☁️ Didn't find any useful vocab for this episode."
                )
            except telegram.error.BadRequest:
                pass

    finally:
        # FIX: Release the background task lock
        context.user_data["is_processing_episode"] = False


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logging.info(f"Callback data = {query.data}")
    await query.answer()

    if query.data == "quiz":
        await quiz(update, context)
        return ConversationHandler.END

    cards = context.user_data.get("cards", None)

    # 1. Flashcard Navigation
    if cards and query.data in ["next", "prev"]:
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

    # 2. Show / Season Selection
    if "show_id" in query.data or "season_n" in query.data:
        # FIX: Prevent race conditions if clicked 10 times rapidly
        if context.user_data.get("is_processing_show"):
            return ConversationHandler.END

        context.user_data["is_processing_show"] = True

        if "season_n" in query.data:
            context.user_data["season_n"] = int(query.data.split("season_n:")[1])

        context.application.create_task(cb_handler_show_id(update, context))
        return ConversationHandler.END

    # 3. Episode Selection
    if "episode_id" in query.data:
        # FIX: Prevent race conditions causing 5 parallel subtitle downloads/API queries
        if context.user_data.get("is_processing_episode"):
            return ConversationHandler.END

        context.user_data["is_processing_episode"] = True
        context.application.create_task(cb_handler_episode_id(update, context))
        return ConversationHandler.END


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def on_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sp = update.message.successful_payment
    await update.message.reply_text("✅ Payment received. Thanks! Your premium is unlocked.")


async def handle_poll_vote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cards = context.user_data.get("cards", None)

    if cards:
        await asyncio.sleep(1.0)
        chat_id = context.user_data.get("chat_id")
        old_poll_message_id = context.user_data.get("current_poll_message_id")

        if chat_id and old_poll_message_id:
            try:
                await context.bot.delete_message(chat_id=chat_id, message_id=old_poll_message_id)
            except telegram.error.BadRequest as e:
                logging.warning(f"Could not delete old poll: {e}")

        index = context.user_data.get("card_index", 0)
        index += 1
        if index >= config.quiz_limit or index == len(cards):
            # end of the poll
            context.user_data["regime"] = "learn"
            logging.info(f"Poll is over")
            await context.bot.send_message(chat_id, "Thanks for playing!")
            return ConversationHandler.END

        context.user_data["card_index"] = index

        await show_poll(update, context=context)

    return ConversationHandler.END


async def set_bot_commands(application):
    commands = [
        BotCommand("feedback", "Send feedback"),
        BotCommand("start", "Restart the bot"),
        #BotCommand("yt", "Read from Youtube"),
    ]
    await application.bot.set_my_commands(commands)


def main():
    application = ApplicationBuilder().token(TG_BOT_KEY).build()

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message),
    )
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_handler(PreCheckoutQueryHandler(precheckout))
    application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("feedback", feedback))
    application.add_handler(CommandHandler("premium", buy))
    application.add_handler(CommandHandler("youtube", yt))
    application.add_handler(CommandHandler("quiz", quiz))

    application.add_handler(CommandHandler("test", command_test))
    application.add_handler(CommandHandler("broadcast", command_broadcast))
    application.add_handler(PollAnswerHandler(handle_poll_vote))

    application.post_init = set_bot_commands
    application.run_polling()


if __name__ == "__main__":
    main()
