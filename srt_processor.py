import nltk
from nltk.corpus import brown
from nltk.probability import FreqDist
from nltk.stem import WordNetLemmatizer
from nltk.corpus import wordnet
from nltk.tokenize import word_tokenize
from nltk.probability import FreqDist
from datetime import datetime
import hashlib
import json
import string
import re
import requests
import spacy
import time
from datetime import datetime, timedelta
import os
nlp = spacy.load("en_core_web_sm")
nltk.download('wordnet')
nltk.download('punkt')
nltk.download('averaged_perceptron_tagger_eng')
lemmatizer = WordNetLemmatizer()
srt_filename = "Shrinking.S02E12.The.Last.Thanksgiving.720p.ATVP.WEB-DL.DDP5.1.H.264-NTb.srt"
# srt_filename = "01 The One After I Do.srt"

words = brown.words()
freq_dist = FreqDist(word.lower() for word in words)


def hash_srt_file(file_path, hash_algorithm="sha256"):
    """Calculate hash of an SRT file based on its content."""
    hasher = hashlib.new(hash_algorithm)

    with open(file_path, "rb") as f:
        while chunk := f.read(8192):  # Read in chunks for efficiency
            hasher.update(chunk)

    return hasher.hexdigest()


# Example usage:


def check_if_name(word) -> bool:
    doc = nlp(word)
    first_names = [ent.text.split()[0] for ent in doc.ents if ent.label_ == "PERSON"]
    if first_names:
        return True
    else:
        return False


def get_urbandictionaty_meaning(word):
    url = f"https://api.urbandictionary.com/v0/define?term={word}"
    data = ''
    response = requests.get(url)

    if response.status_code == 200:
        data = response.json()
        try:
            data = data['list'][0]['definition'].replace(']', '')
        except IndexError as e:
            print(f"Error with {word}, {data}")
            return 'None'
        data = data.replace('[', '')
        data = data.replace('\n', '')
        data = data.replace('\r\r', ' ')
    if len(data) > 80:
        data = data[:80] + '...'
    return data


def get_meaning(word):
    synsets = wordnet.synsets(word)
    meanings = [syn.definition() for syn in synsets]
    return meanings


def get_wordnet_pos(word):
    tag = nltk.pos_tag([word])[0][1][0].upper()  # Get POS tag
    tag_dict = {"J": wordnet.ADJ, "N": wordnet.NOUN, "V": wordnet.VERB, "R": wordnet.ADV}
    return tag_dict.get(tag, wordnet.NOUN)  # Default to NOUN if not found


def get_words_by_timedelta(srt_timestamp: timedelta, resulting_dict:dict):
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


def get_cleaned_srt_line(line:str)->str:
    cleaned_text = line.replace("<i>", "")
    cleaned_text = cleaned_text.replace("</i>", "")
    cleaned_text = cleaned_text.replace("- ", "")
    cleaned_text = cleaned_text.replace(" -", "")
    cleaned_text = cleaned_text.replace("'s", "")
    cleaned_text = cleaned_text.replace("'d", "")
    cleaned_text = cleaned_text.replace("'ve", "")
    cleaned_text = re.sub(r'\{\\an\d\}', '', cleaned_text)

    cleaned_text = re.sub(r"[-.!?0123456789:,\"]", ' ', cleaned_text)
    return cleaned_text


def get_time_index(word: str, parsed_srt):
    for i in parsed_srt:
        if word.lower() in parsed_srt[i]['text'].lower():
            return parsed_srt[i]['time'].split(" ")[0], parsed_srt[i]['time'].split(" ")[2]


def srt_parse_from_file(filename)->dict:
    with open(filename, 'r', encoding='utf-8-sig') as file:
        content = file.read().strip()

    subtitles = {}
    blocks = re.split(r'\n\n+', content)  # Split by empty lines (blocks)

    for block in blocks:
        lines = block.strip().split('\n')

        if len(lines) >= 3:
            try:
                index = int(lines[0].strip())  # Subtitle index
            except ValueError as e:
                print(f"Error while parsing {lines[0]}, {e}")
                return {}

            time_range = lines[1]  # Time range (e.g., 00:00:01,500 --> 00:00:04,000)
            text = ' '.join(lines[2:])  # Combine text lines

            subtitles[index] = {"time": time_range, "text": text}

    return subtitles


def words_dump_as_json_by_hash(res_dict: dict, content_hash: str):
    with open(content_hash + '.json', "w", encoding="utf-8") as f:
        json.dump(res_dict, f, ensure_ascii=False, indent=4)


def words_load_from_json_by_hash(content_hash: str)->dict:
    fn = content_hash + '.json'
    if os.path.exists(fn):  # Check if file exists
        with open(fn, "r", encoding="utf-8") as f:
            return json.load(f)  # Load JSON into dictionary
    else:
        return {}  # Return None if file doesn't exist


if __name__ == '__main__':
    hash_from_content = hash_srt_file(srt_filename)
    resulting_dict = words_load_from_json_by_hash(hash_from_content)

    if not resulting_dict:
        srt_dict = srt_parse_from_file(srt_filename)
        words = []
        for i in range(1, len(srt_dict)):
            clean_text = get_cleaned_srt_line(srt_dict[i]['text'])
            for word in clean_text.split():
                words.append(word)
                # singularize

                # print (word, get_wordnet_pos(word), lemmatizer.lemmatize(word, get_wordnet_pos(word)))

        # calc words stat from subtitle
        srt_freq_dist = FreqDist(words)

        words_unique = set(words)
        words_freq = {}

        for word in words:
            try:
                words_freq[word] = freq_dist[word.lower()]
            except KeyError:
                words_freq[word] = -1


        index = 1

        for w in words_freq:
            if words_freq[w] < 1:
                if check_if_name(w):
                    meaning = 'a name'
                else:
                    meaning = get_meaning(w)
                    if meaning:
                        meaning = meaning[0]
                    else:
                        meaning = get_urbandictionaty_meaning(w) + ' [UD]'
                try:
                    srt_freq_w = srt_freq_dist[w]
                except KeyError:
                    srt_freq_w = 0
                period = get_time_index(w, srt_dict)
                resulting_dict.setdefault(period[0], []).append({'start': period[0],
                                                                 'end': period[1],
                                                                 'word': w,
                                                                 'meaning': meaning,
                                                                 'freq_srt': srt_freq_w})

                # print(f"{times[0]} {times[1]} {w:15} ({srt_freq_w}) – {meaning}")
                meaning = None
                index += 1

        words_dump_as_json_by_hash(resulting_dict, hash_from_content)

    print(resulting_dict)
    input('Press Enter to continue')

    loop_start_time = datetime.now()
    once_index = ''

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
