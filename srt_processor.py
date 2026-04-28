import nltk
from nltk.corpus import brown
from nltk.stem import WordNetLemmatizer
from nltk.corpus import wordnet
from nltk.probability import FreqDist
import hashlib
import json
import re
import requests
import spacy
import time
from datetime import datetime, timedelta
import os
import logging

import config
import asyncio
import requests_cache
import gpt
import eng_to_ipa as ipa

requests_cache.install_cache(backend='filesystem', expire_after=600 * 3)

SIMULT_LIMIT = 15

logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

gptmodel = gpt.GPTGemini()

nlp = spacy.load("en_core_web_sm")
nltk.download('wordnet')
nltk.download('punkt')
nltk.download('averaged_perceptron_tagger_eng')
lemmatizer = WordNetLemmatizer()

words = brown.words()
WORDS_FREQ_DIST = FreqDist(word.lower() for word in words)


def hash_srt_file(file_path, hash_algorithm="sha256"):
    """Calculate hash of an SRT file based on its content."""
    hasher = hashlib.new(hash_algorithm)

    with open(os.path.join(config.srt_cache_folder_name, file_path), "rb") as f:
        while chunk := f.read(8192):  # Read in chunks for efficiency
            hasher.update(chunk)

    return hasher.hexdigest()


async def check_if_name(word) -> bool:
    doc = nlp(word)
    first_names = [ent.text.split()[0] for ent in doc.ents if ent.label_ == "PERSON"]
    if first_names:
        return True
    else:
        return False


async def escape_for_telegram_markup(text):
    data = text.replace('[', '')
    data = data.replace(']', '')
    data = data.replace('\n', '')
    data = data.replace('\r\r', ' ')
    data = data.replace('"', '')
    data = data.replace('`', """'""")
    data = data.replace('*', "")

    return data


async def get_urbandictionary_meaning_async(word):
    url = f"https://api.urbandictionary.com/v0/define?term={word}"
    data = ''
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        try:
            data = data['list'][0]['definition'].replace(']', '')
        except IndexError:
            logging.warning(f"UD: Can't find with {word}, {data}")
            return 'unknown meaning'

        data = await escape_for_telegram_markup(data)

    if len(data) > 80:
        data = data[:80] + '...'
    return data


async def get_meaning_wordnet_async(word):
    synsets = wordnet.synsets(word)
    meanings = [syn.definition() for syn in synsets]
    return meanings


# def get_wordnet_pos(word):
#     tag = nltk.pos_tag([word])[0][1][0].upper()  # Get POS tag
#     tag_dict = {"J": wordnet.ADJ, "N": wordnet.NOUN, "V": wordnet.VERB, "R": wordnet.ADV}
#     return tag_dict.get(tag, wordnet.NOUN)  # Default to NOUN if not found


def get_words_by_timedelta(srt_timestamp: timedelta, resulting_dict: dict):
    for i in resulting_dict:
        start_dt = datetime.strptime(resulting_dict[i][0]['start'], "%H:%M:%S,%f")
        start_delta = timedelta(
            hours=start_dt.hour,
            minutes=start_dt.minute,
            seconds=start_dt.second,
            microseconds=start_dt.microsecond)

        end_dt = datetime.strptime(resulting_dict[i][0]['end'], "%H:%M:%S,%f")
        end_delta = timedelta(
            hours=end_dt.hour,
            minutes=end_dt.minute,
            seconds=end_dt.second,
            microseconds=end_dt.microsecond)

        if start_delta <= srt_timestamp <= end_delta:
            return {i: resulting_dict[i]}
    return None

def remove_srt_inclusions(text):
    '''like inclusions like {\pos(982.5219)}'''
    return re.sub(r"\{\\[^}]*\}", "", text)

def get_cleaned_srt_line(line: str) -> str:
    replacements = [
        "<i>", "</i>", "- ", " -", "'s", "'d", "'ve", "'ll", "[", "]", "…", "♪", '"', "$", "%", "—", "(", ")",
        "#", "##", "''", ">>",
        "II", "III", "IV",
        "Mr.", "Dr."
    ]

    cleaned_text = line
    for char in replacements:
        cleaned_text = cleaned_text.replace(char, " ")

    cleaned_text = remove_srt_inclusions(cleaned_text)

    cleaned_text = re.sub(r'\{\\an\d\}', '', cleaned_text)

    cleaned_text = re.sub(r"[-.!?0123456789:,\"]", ' ', cleaned_text)
    return cleaned_text


# def get_time_index(word: str, parsed_srt):
#     for i in parsed_srt:
#         if word.lower() in parsed_srt[i]['text'].lower():
#             return parsed_srt[i]['time'].split(" ")[0], parsed_srt[i]['time'].split(" ")[2]


def get_time_index(word: str, parsed_srt):
    pattern = re.compile(rf"(?<![a-z]){re.escape(word)}(?![a-z])", re.IGNORECASE)

    for i in parsed_srt:
        if pattern.search(parsed_srt[i]['text']):
            return parsed_srt[i]['time'].split(" ")[0], parsed_srt[i]['time'].split(" ")[2]

    return None, None

def srt_parse_from_file(filename) -> dict:
    with open(os.path.join(config.srt_cache_folder_name, filename), 'r', encoding='utf-8-sig') as file:
        content = file.read().strip()

    subtitles = {}
    blocks = re.split(r'\n\n+', content)  # Split by empty lines (blocks)

    for block in blocks:
        lines = block.strip().split('\n')

        if len(lines) >= 3:
            try:
                index = int(lines[0].strip())  # Subtitle index
            except ValueError as e:
                logging.error(f"Error while parsing {lines[0]}, {e}")
                return {}

            time_range = lines[1]  # Time range (e.g., 00:00:01,500 --> 00:00:04,000)
            text = ' '.join(lines[2:])  # Combine text lines

            subtitles[index] = {"time": time_range, "text": text}

    return subtitles


def words_dump_as_json_by_hash(res_dict: dict, content_hash: str):
    with open(content_hash + '.json', "w", encoding="utf-8") as f:
        json.dump(res_dict, f, ensure_ascii=False, indent=4)


def words_load_from_json_by_hash(content_hash: str) -> dict:
    fn = content_hash + '.json'
    if os.path.exists(fn):  # Check if file exists
        with open(fn, "r", encoding="utf-8") as f:
            return json.load(f)  # Load JSON into dictionary
    else:
        return {}  # Return None if file doesn't exist


async def process_words(w: str, srt_freq, srt_dict: dict, sem, series_name=''):
    async with sem:
        line_dict = {}
        dictionary_type = 'default'

        # Only process rare or unknown words

        # Fallback to GPT or Urban Dictionary
        sentence = ""
        meaning = ""
        period = get_time_index(w, srt_dict)

        if period[0] is not None:
            print(w, period)
            for i in srt_dict:
                if srt_dict[i]["time"].startswith(period[0]):
                    sentence = srt_dict[i]["text"]
                    break
            if sentence:
                if gptmodel:
                    meaning = await gptmodel.get_word_meaning(w, series_name, sentence)
                    dictionary_type = 'AI'

                if not meaning:
                    logging.warning(f"No meaning found for {w}")
                    return {}

                # Frequency of word in subtitle
                srt_freq_w = srt_freq.get(w, 0)

                line_dict = {
                        'start': period[0],
                        'end': period[1],
                        'word': w,
                        'meaning': meaning,
                        'freq_srt': srt_freq_w,
                        'dict': dictionary_type,
                        'sentence': sentence,
                        'ipa': await escape_for_telegram_markup(ipa.convert(w))
                    }

    return line_dict

async def process_sentences(sentence: str, time_start, time_end, sem, series_name=''):

    async with sem:
        line_dict = {}
        # skip short sentences, use only  len(sentence)>5
        if len(sentence)>10 and gptmodel:
            phrase_definition = await gptmodel.get_collocations_meaning(series_name, sentence)
            if phrase_definition:

                try:
                    if "phrase in infinitive" in list(phrase_definition.keys())[0]:
                        return line_dict
                    line_dict = {
                    'start': time_start,
                    'end': time_end,
                    'word': list(phrase_definition.keys())[0],
                    'meaning': list(phrase_definition.values())[0],
                    'freq_srt': 0,
                    'dict': 'Collocations',
                    'sentence': sentence,
                    'ipa': ''
                    }
                except Exception as e:
                    logging.error(f"Collocation failed {phrase_definition}")
                    return line_dict

    return line_dict


def extract_words_sync(srt_filename: str, series_name: str = "") -> dict:
    return asyncio.run(extract_words(srt_filename, series_name))

async def extract_words(srt_filename: str, series_name='') -> dict:
    try:
        hash_from_content = hash_srt_file(srt_filename)
    except FileNotFoundError:
        logging.error(f"No srt file found {srt_filename}. Can't extract words")
        return {}

    resulting_dict = words_load_from_json_by_hash(hash_from_content)
    if resulting_dict:
        logging.info(f"Cached data found for {srt_filename} of {len(resulting_dict)} words")

    else: # no cache
        srt_dict = srt_parse_from_file(srt_filename)
        words = []
        for i in range(1, len(srt_dict)):
            try:
                clean_text = get_cleaned_srt_line(srt_dict[i]['text'])
            except KeyError:
                logging.error(f"{srt_filename} doesnt have {i} line")
                continue

            for word in clean_text.split():
                words.append(word)

        # calc words stat from subtitle
        srt_freq_dist = FreqDist(words)

        words_freq = {}
        print(f"Frequency of words {len(words)}, {len(set(words))}")
        words = list(set(words))
        for word in words:
            try:
                words_freq[word] = WORDS_FREQ_DIST[word.lower()]
            except KeyError:
                words_freq[word] = -1

        sem = asyncio.Semaphore(SIMULT_LIMIT)
        tasks = []
        for w in words_freq:
            if words_freq[w] < 1:
                tasks.append(process_words(w, srt_freq_dist, srt_dict, sem, series_name=series_name))

        if config.collect_collocations:
            # find collocations with AI:
            for i in srt_dict:
                time_start = srt_dict[i]['time'].split(" ")[0]
                time_end = srt_dict[i]['time'].split(" ")[2]
                tasks.append(process_sentences(srt_dict[i]['text'], time_start, time_end, sem, series_name=series_name))

        results = await asyncio.gather(*tasks)  # Process words asynchronously
        resulting_dict = {}

        for res in results:
            if res:
                resulting_dict.setdefault(res['start'], []).append(res)

        resulting_dict = dict(
            sorted(
                resulting_dict.items(),
                key=lambda x: datetime.strptime(x[0].replace(",", "."), "%H:%M:%S.%f")
            )
        )

        try:
            words_dump_as_json_by_hash(resulting_dict, hash_from_content)
        except IOError as e:
            logging.error(f"Error while writing to cache words json file: {e}. No cache saved.")
        return resulting_dict

    # TODO skip sorting if all cached data is sorted
    resulting_dict = dict(
        sorted(
            resulting_dict.items(),
            key=lambda x: datetime.strptime(x[0].replace(",", "."), "%H:%M:%S.%f")
        )
    )
    resulting_dict = filter_dicts_by_name(resulting_dict, "Collocations")
    return resulting_dict

def filter_dicts_by_name (srt_dict: dict, filter_dict_name="AI") -> dict:
    filtered_data = {k: [item for item in v if item.get("dict") != filter_dict_name] for k, v in srt_dict.items()}
    return filtered_data

def console_play_srt(resulting_dict: dict):
    loop_start_time = datetime.now()

    last_key = list(resulting_dict.keys())[-1]
    full_end_dt = datetime.strptime(resulting_dict[last_key][0]['end'], "%H:%M:%S,%f")
    full_end_delta = timedelta(
        hours=full_end_dt.hour,
        minutes=full_end_dt.minute,
        seconds=full_end_dt.second,
        microseconds=full_end_dt.microsecond)

    print()
    index_shown = None
    while True:
        # Get elapsed time
        current_time = datetime.now() - loop_start_time
        # print(current_time)

        words_item = get_words_by_timedelta(current_time, resulting_dict)
        # print(words_item)
        if words_item and index_shown != next(iter(words_item.keys())):
            for item in words_item[next(iter(words_item.keys()))]:
                print(f"{item['word']:15} - {item['meaning']}")
            index_shown = next(iter(words_item.keys()))

        # Exit loop after end_time has passed
        if current_time > full_end_delta:
            print("Time range ended. Exiting loop.")
            break

        time.sleep(0.2)  # Sleep to reduce CPU usage


async def mainroutine():
    # srt_filename = "Severance.S01E01.Good.News.About.Hell.1080p.ATVP.WEB-DL.DDP5.1.Atmos.H.264-TEPES.srt"
    srt_filename = "For.All.Mankind.S01E01.1080p.WEB-DL.DD5.1.H.264-Tars.srt"
    print(hash_srt_file("For.All.Mankind.S01E01.1080p.WEB-DL.DD5.1.H.264-Tars.srt"))

    print(await extract_words(srt_filename, series_name="For All Mankind"))


if __name__ == '__main__':
    #print (hash_srt_file('Severance.S01E01.Good.News.About.Hell.1080p.ATVP.WEB-DL.DDP5.1.Atmos.H.264-TEPES.srt'))
    asyncio.run(mainroutine())
