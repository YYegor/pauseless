import requests
from io import BytesIO
from PIL import Image
import os
import logging

img_cache_folder_name = 'cache'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)


class Opnsub:
    def __init__(self):
        self.opnsub_api_key = os.environ.get("OPNSUB_API_KEY")
        self.opnsub_api_name = os.environ.get("OPNSUB_API_NAME")
        self.opnsub_api_token = os.environ.get("OPNSUB_TOKEN")
        self.api_url_base = 'https://api.opensubtitles.com/api/v1'
        self.headers = {
            "Content-Type": "application/json; charset=utf-8"
        }

    def get_opnsub_suggestions(self, query, showtype="Tvshow") -> list:
        query = query.replace(' ', '+')

        response = requests.get(f"https://www.opensubtitles.com/en/en/search/autocomplete/{query}.json",
                                headers=self.headers)

        if response.status_code == 200:
            data = response.json()
            result = []
            for show in data:
                if show["type"] == showtype:
                    result.append(show)
            return result
        else:
            logging.error(f"Error: {response.status_code}")
            return []

    def get_opnsub_subtitles_names(self, parent_feature_id:int, season=1, year=0, lang="en") -> dict:
        api_url = self.api_url_base + '/subtitles'
        headers = dict(self.headers)
        headers["Api-Key"] = self.opnsub_api_key
        params = {
            "parent_feature_id": parent_feature_id,
            "languages": lang,
            "season_number": season,
            **({"year": year} if year != 0 else {})

        }
        logging.info(f"Subtitles call with p:{params}")
        response = requests.get(api_url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            return data
        else:
            logging.error(f"Error: {response.status_code}, {response.text}, {parent_feature_id}, {season}")
            return {}


def img_is_cached(filename_full) -> bool:
    if os.path.exists(filename_full):
        return True
    else:
        return False


def get_img_resized(input_path, new_height=100):
    filename = input_path.split('/')[-1].split('.')[0]
    filename_end = '_.jpg'
    if img_is_cached(os.path.join(img_cache_folder_name, filename + filename_end)):
        pass
    else:
        response = requests.get(input_path)
        img_data = response.content
        img_bytes_io = BytesIO(img_data)
        img = Image.open(img_bytes_io)
        width, height = img.size

        # convert png to jpg
        if img.mode in ("P", "RGBA"):
            img = img.convert("RGB")
        target_width = int((new_height / height) * width)
        new_image = Image.new("RGB", (200, new_height), (0, 0, 0))

        img = img.resize((target_width, new_height), resample=Image.Resampling.BICUBIC)
        new_image.paste(img, (0, 0))
        new_image.save(os.path.join(img_cache_folder_name, filename + filename_end), format="JPEG")
    return os.path.join(img_cache_folder_name, filename + filename_end)


def parse_episodes(opn_data: dict) -> dict:
    sorted_data = sorted(opn_data['data'], key=lambda item: item['attributes']['feature_details']['episode_number'],
                         reverse=False)
    res_dict = {}
    for data in sorted_data:
        attrs = data['attributes']
        feature_details = attrs['feature_details']
        if not attrs['hearing_impaired']:
            res_dict[feature_details['episode_number']] = {'id': data['id'], 'title': feature_details['title']}
            # print(f"{feature_details['episode_number']} {feature_details['title']} {data['id']}")
    return res_dict


def opnsub_fix_poster_url(url):
    if 'http' not in url:
        return 'https://opensubtitles.com' + url
    else:
        return url


def suggestion_wrapper(get_opnsub_suggestions_data:list):
    if get_opnsub_suggestions_data:
        resp = {}
        for d in get_opnsub_suggestions_data:
            resp[d['id']] = {"caption": f"{str(d['title']).capitalize()}, {d['year']}  rate:{d['rating']}\n",
                             "img": opnsub_fix_poster_url(d['poster'])}
        return resp


if __name__ == '__main__':
    opn = Opnsub()
    # print(opn.get_opnsub_suggestions("house of cards"))


    series_data = opn.get_opnsub_subtitles_names(parent_feature_id=8780)
    print(parse_episodes(series_data))

    # print(get_opnsub_subtitles_names('Shrinking')['data'])
