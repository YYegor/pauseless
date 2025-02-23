import requests
from io import BytesIO
from PIL import Image
import os
import logging
import requests_cache

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
        requests_cache.install_cache(backend='filesystem', expire_after=600*3)

    import requests

    def download_file(self, url: str, save_path: str):
        """
        Downloads a file from the given URL and saves it to disk.

        :param url: The URL of the file to download.
        :param save_path: The local file path where the file should be saved.
        """
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()  # Raise an error for bad responses (4xx, 5xx)

            with open(save_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

            print(f"File downloaded successfully: {save_path}")
        except requests.exceptions.RequestException as e:
            print(f"Download failed: {e}")


    def get_srt_download_url(self, file_id)->dict:
        api_url = self.api_url_base + '/download'
        headers = dict(self.headers)
        headers["Api-Key"] = self.opnsub_api_key
        headers["Accept"] = "application/json"

        params = {
        "file_id": file_id}

        logging.info(f"Subtitles call with p:{params}")
        response = requests.post(api_url, headers=headers, params=params)

        if response.status_code == 200:
            data = response.json()
            return data
        else:
            logging.error(f"Error: {response.status_code}, {response.text}")
            return {}

    def get_suggestions(self, query, showtype="Tvshow") -> list:
        query = query.replace(' ', '+')

        response = requests.get(f"https://www.opensubtitles.com/en/en/search/autocomplete/{query}.json",
                                headers=self.headers)

        if response.status_code == 200:
            data = response.json()
            result = []
            for show in data:
                if show["type"] == showtype:
                    show["poster"] = opnsub_fix_poster_url(show["poster"])
                    result.append(show)
            return result
        else:
            logging.error(f"Error: {response.status_code}")
            return []

    def get_srt_names(self, parent_feature_id: int, season=1, year=0, lang="en") -> dict:
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
    res_dict = {}
    try:
        sorted_data = sorted(opn_data['data'], key=lambda item: item['attributes']['feature_details']['episode_number'],
                             reverse=False)
    except KeyError:
        logging.error(f"Error: {opn_data['data']}")
        return res_dict
    print(sorted_data)
    for data in sorted_data:
        attrs = data['attributes']
        feature_details = attrs['feature_details']
        files = attrs['files'][0] # TODO: detect right index
        if not attrs['hearing_impaired']:
            res_dict[feature_details['episode_number']] = {'id': data['id'],
                                                           'title': feature_details['title'],
                                                           'file_id':files['file_id'],
                                                           'file_name': files['file_name']+'.srt',}
            # print(f"{feature_details['episode_number']} {feature_details['title']} {data['id']}")
    return res_dict


def opnsub_fix_poster_url(url):
    if 'http' not in url:
        return 'https://opensubtitles.com' + url
    else:
        return url


if __name__ == '__main__':
    opn = Opnsub()
    # print(opn.get_opnsub_suggestions("house of cards"))

    series_data = opn.get_srt_names(parent_feature_id=12809)
    print(parse_episodes(series_data))
    # download_info = (opn.get_srt_download_url(9022929))
    # if download_info:
    #     opn.download_file(download_info['link'], download_info['file_name'])
    # print(get_opnsub_subtitles_names('Shrinking')['data'])
