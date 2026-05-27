import nltk
from nltk.corpus import brown
from nltk.stem import WordNetLemmatizer
from nltk.corpus import wordnet
import hashlib
import json
import re
import spacy
import time
from datetime import datetime, timedelta
import os
import logging
import asyncio
import requests_cache

import config
import gpt
import eng_to_ipa as ipa

requests_cache.install_cache(backend='filesystem', expire_after=600 * 3)

# Separate concurrency limits: Network calls vs Local CPU processing
API_CONCURRENT_LIMIT = 3  # Keep low to avoid Gemini 429 errors
IPA_CONCURRENT_LIMIT = 20  # High because it's just local thread processing
BATCH_SIZE = 30  # Number of items to send to Gemini per prompt

logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

gptmodel = gpt.GPTGemini()

nlp = spacy.load("en_core_web_sm")
nltk.download('wordnet', quiet=True)
nltk.download('punkt', quiet=True)
nltk.download('averaged_perceptron_tagger_eng', quiet=True)
lemmatizer = WordNetLemmatizer()

# OPTIMIZATION: Instant lookups for known corpus words
BROWN_WORDS_SET = set(word.lower() for word in brown.words())
CLEAN_SRT_PATTERN = re.compile(r'\{\\[^}]*\}|\{\\an\d\}|[-.!?0123456789:,\"]')


def chunk_list(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def hash_srt_file(file_path, hash_algorithm="sha256"):
    hasher = hashlib.new(hash_algorithm)
    with open(os.path.join(config.srt_cache_folder_name, file_path), "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()


async def escape_for_telegram_markup(text):
    return text.translate(str.maketrans({
        '[': '', ']': '', '\n': '', '\r': ' ', '"': '', '`': "'", '*': ''
    }))


def get_cleaned_srt_line(line: str) -> str:
    replacements = [
        "<i>", "</i>", "- ", " -", "'s", "'d", "'ve", "'ll", "…", "♪", "$", "%", "—", "(", ")",
        "#", "##", "''", ">>", "II", "III", "IV", "Mr.", "Dr."
    ]
    cleaned_text = line
    for char in replacements:
        cleaned_text = cleaned_text.replace(char, " ")

    cleaned_text = CLEAN_SRT_PATTERN.sub(' ', cleaned_text)
    return cleaned_text


def srt_parse_from_file(filename) -> dict:
    with open(os.path.join(config.srt_cache_folder_name, filename), 'r', encoding='utf-8-sig') as file:
        content = file.read().strip()

    subtitles = {}
    blocks = content.split('\n\n')

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) >= 3:
            try:
                index = int(lines[0].strip())
            except ValueError:
                continue

            time_range = lines[1]
            text = ' '.join(lines[2:])
            subtitles[index] = {"time": time_range, "text": text}

    return subtitles


# --- API Fetching Wrappers ---
async def fetch_word_chunk(chunk, series_name, sem):
    async with sem:
        return await gptmodel.get_word_meanings_batch(chunk, series_name)


async def fetch_colloc_chunk(chunk, series_name, sem):
    async with sem:
        return await gptmodel.get_collocations_meaning_batch(chunk, series_name)


# --- Finalizing Tasks ---
async def finalize_word_data(context, meaning, freq, sem):
    """Processes IPA and formatting locally after AI definition is retrieved."""
    async with sem:
        # Offload synchronous IPA processing to a thread
        ipa_text = await asyncio.to_thread(ipa.convert, context['word'])
        return {
            'start': context['start'],
            'end': context['end'],
            'word': context['word'],
            'meaning': meaning,
            'freq_srt': freq,
            'dict': 'AI',
            'sentence': context['sentence'],
            'ipa': await escape_for_telegram_markup(ipa_text)
        }


async def extract_words(srt_filename: str, series_name='') -> dict:
    try:
        hash_from_content = hash_srt_file(srt_filename)
    except FileNotFoundError:
        logging.error(f"No srt file found {srt_filename}. Can't extract words")
        return {}

    fn = hash_from_content + '.json'
    if os.path.exists(fn):
        with open(fn, "r", encoding="utf-8") as f:
            logging.info(f"Cached data found for {srt_filename}")
            return json.load(f)

    srt_dict = srt_parse_from_file(srt_filename)

    # Context trackers
    rare_words_context = {}
    word_frequencies = {}
    sentence_times = {}  # Used for collocations

    # 1. Parse lines and collect targets
    for i in srt_dict.values():
        clean_text = get_cleaned_srt_line(i['text'])
        time_start, _, time_end = i['time'].partition(" --> ")
        original_sentence = i['text']

        # Track sentence times for collocations
        if len(original_sentence) > 10:
            sentence_times[original_sentence] = (time_start, time_end)

        for word in clean_text.split():
            word_lower = word.lower()
            word_frequencies[word_lower] = word_frequencies.get(word_lower, 0) + 1

            if word_lower not in BROWN_WORDS_SET and word_lower not in rare_words_context:
                rare_words_context[word_lower] = {
                    'word': word,  # Preserves Original Casing
                    'start': time_start,
                    'end': time_end,
                    'sentence': original_sentence
                }

    print(f"Total unique words in SRT: {len(word_frequencies)}, Rare words to process: {len(rare_words_context)}")

    api_sem = asyncio.Semaphore(API_CONCURRENT_LIMIT)

    # ==========================================
    # 2. PROCESS WORDS IN BATCHES
    # ==========================================
    global_word_meanings = {}
    if gptmodel and rare_words_context:
        # Prepare payloads
        word_payloads = [
            {"word": ctx["word"], "sentence": ctx["sentence"]}
            for ctx in rare_words_context.values()
        ]

        # Create chunked tasks
        word_tasks = [
            fetch_word_chunk(chunk, series_name, api_sem)
            for chunk in chunk_list(word_payloads, BATCH_SIZE)
        ]

        # Await all API calls
        print(f"Sending {len(word_tasks)} batches to Gemini for words...")
        chunk_results = await asyncio.gather(*word_tasks)

        # Merge dictionary results (Fallback to case-insensitive merging just in case Gemini changed cases)
        for res in chunk_results:
            for w, m in res.items():
                global_word_meanings[w.lower()] = m

    # ==========================================
    # 3. PROCESS COLLOCATIONS IN BATCHES
    # ==========================================
    global_collocations = {}
    if config.collect_collocations and gptmodel and sentence_times:
        sentence_payloads = list(sentence_times.keys())
        colloc_tasks = [
            fetch_colloc_chunk(chunk, series_name, api_sem)
            for chunk in chunk_list(sentence_payloads, BATCH_SIZE)
        ]

        print(f"Sending {len(colloc_tasks)} batches to Gemini for collocations...")
        c_chunk_results = await asyncio.gather(*colloc_tasks)

        for res in c_chunk_results:
            global_collocations.update(res)

    # ==========================================
    # 4. LOCALLY COMPILE DATA (IPA & Formatting)
    # ==========================================
    ipa_sem = asyncio.Semaphore(IPA_CONCURRENT_LIMIT)
    compile_tasks = []
    resulting_dict = {}

    # Queue Word Tasks
    for word_lower, context in rare_words_context.items():
        original_word = context['word']
        # Try finding meaning by original case or lowercase fallback
        meaning = global_word_meanings.get(original_word.lower())

        if meaning:
            freq = word_frequencies.get(word_lower, 0)
            compile_tasks.append(finalize_word_data(context, meaning, freq, ipa_sem))

    # Process all IPA/formatting concurrently
    compiled_words = await asyncio.gather(*compile_tasks)

    for item in compiled_words:
        if item:
            resulting_dict.setdefault(item['start'], []).append(item)

    # Add Collocations manually (no IPA needed)
    for sentence, col_data in global_collocations.items():
        times = sentence_times.get(sentence)
        if not times:
            continue

        time_start, time_end = times
        for phrase, meaning in col_data.items():
            if "phrase in infinitive" in phrase.lower():
                continue  # Skip dummy returns

            c_item = {
                'start': time_start,
                'end': time_end,
                'word': phrase,
                'meaning': meaning,
                'freq_srt': 0,
                'dict': 'Collocations',
                'sentence': sentence,
                'ipa': ''
            }
            resulting_dict.setdefault(time_start, []).append(c_item)

    # ==========================================
    # 5. SORT & SAVE
    # ==========================================
    # Sort purely alphabetically by string time (Fastest method)
    resulting_dict = dict(sorted(resulting_dict.items(), key=lambda x: x[0]))

    try:
        with open(fn, "w", encoding="utf-8") as f:
            json.dump(resulting_dict, f, ensure_ascii=False, indent=4)
    except IOError as e:
        logging.error(f"Error saving cache: {e}")

    return resulting_dict


# --- Existing Helpers Maintained ---
def get_words_by_timedelta(srt_timestamp: timedelta, resulting_dict: dict):
    for i in resulting_dict:
        start_dt = datetime.strptime(resulting_dict[i][0]['start'], "%H:%M:%S,%f")
        start_delta = timedelta(
            hours=start_dt.hour, minutes=start_dt.minute,
            seconds=start_dt.second, microseconds=start_dt.microsecond)

        end_dt = datetime.strptime(resulting_dict[i][0]['end'], "%H:%M:%S,%f")
        end_delta = timedelta(
            hours=end_dt.hour, minutes=end_dt.minute,
            seconds=end_dt.second, microseconds=end_dt.microsecond)

        if start_delta <= srt_timestamp <= end_delta:
            return {i: resulting_dict[i]}
    return None


def filter_dicts_by_name(srt_dict: dict, filter_dict_name="AI") -> dict:
    return {
        k: filtered_list
        for k, v in srt_dict.items()
        if (filtered_list := [item for item in v if item.get("dict") != filter_dict_name])
    }


def console_play_srt(resulting_dict: dict):
    loop_start_time = datetime.now()
    if not resulting_dict:
        return

    last_key = list(resulting_dict.keys())[-1]
    full_end_dt = datetime.strptime(resulting_dict[last_key][0]['end'], "%H:%M:%S,%f")
    full_end_delta = timedelta(
        hours=full_end_dt.hour, minutes=full_end_dt.minute,
        seconds=full_end_dt.second, microseconds=full_end_dt.microsecond)

    print()
    index_shown = None
    while True:
        current_time = datetime.now() - loop_start_time
        words_item = get_words_by_timedelta(current_time, resulting_dict)

        if words_item and index_shown != next(iter(words_item.keys())):
            for item in words_item[next(iter(words_item.keys()))]:
                print(f"{item['word']:15} - {item['meaning']}")
            index_shown = next(iter(words_item.keys()))

        if current_time > full_end_delta:
            print("Time range ended. Exiting loop.")
            break
        time.sleep(0.2)


async def mainroutine():
    srt_filename = "5MuIMqhT8DM.en-orig.srt"
    print(hash_srt_file(srt_filename))
    result = await extract_words(srt_filename, series_name="Sleep Is Your Superpower | Matt Walker | TED")
    print(result)
    # Uncomment to test playback:
    # console_play_srt(result)


if __name__ == '__main__':
    asyncio.run(mainroutine())