from PIL import Image, UnidentifiedImageError, ImageFilter
import requests as regular_requests
from json import JSONDecodeError
from curl_cffi import requests
from io import BytesIO
import requests_cache
import logging
import config
import yt_dlp
import os

logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

class Youtube:
    def __init__(self):
        pass

    def download_srt(self, url, subtitle_lang='en'):
        ydl_opts = {
            'writesub': True,  # Download subtitles (if available)
            'subtitleslangs': [subtitle_lang],  # Specify the subtitle language
            'subtitlesformat': 'srt',  # Download subtitles in .srt format
            'skip_download': True,  # Skip video download, only download subtitles
            'quiet': False,  # Show output for debugging
            'outtmpl': os.path.join(config.srt_cache_folder_name,'%(id)s.%(ext)s'),  # Save the file with the video title
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

class Opnsub:
    def __init__(self):
        self.opnsub_api_key = os.environ.get("OPNSUB_API_KEY")
        self.opnsub_api_name = os.environ.get("OPNSUB_API_NAME")
        self.opnsub_api_token = os.environ.get("OPNSUB_TOKEN")
        self.api_url_base = 'https://api.opensubtitles.com/api/v1'
        self.headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "pauseless1 v1.1",
            "Accept" : "application/json",
            "Api-Key": self.opnsub_api_key
        }

        requests_cache.install_cache(backend='filesystem', expire_after=600 * 3)
    def get_seasons_number(self, feature_id:int):
        count = 0
        raw_data = self.get_features(None, feature_id=feature_id, show_type="feature")
        #print(raw_data)
        if raw_data:
            for season in raw_data[0]['attributes']['seasons']:
                if len(season['episodes'])>0:
                    count += 1

            return count
        return 0

    def download_file(self, url: str, save_path: str) -> bool:
        """
        Downloads a file from the given URL and saves it to disk.

        :param url: The URL of the file to download.
        :param save_path: The local file path where the file should be saved.
        """
        try:
            response = regular_requests.get(url, stream=True)
            response.raise_for_status()  # Raise an error for bad responses (4xx, 5xx)

            with open(os.path.join(config.srt_cache_folder_name, save_path), "wb") as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)

            logging.info(f"File downloaded successfully: {save_path}")
            return True
        except regular_requests.exceptions.RequestException as e:
            logging.error(f"Download of {url} failed: {e}")
            return False

    def get_srt_download_info(self, file_id: int) -> dict:
        api_url = self.api_url_base + '/download'

        params = {
            "file_id": int(file_id)
        }

        logging.info(f"get_srt_download_url: {params}")
        response = regular_requests.post(api_url, headers=self.headers, params=params)

        if response.status_code == 200:
            data = response.json()
            return data
        else:
            logging.error(f"Error: {response.status_code}, {response.text}")
            return {}

    def fix_poster_url(self, url):
        if 'http' not in url:
            return 'https://opensubtitles.com' + url
        else:
            return url

    def get_suggestions_old(self, query, show_type="tv"):
        query = query.replace('"', ' ')
        query = query.replace("'", ' ')
        query = query.replace("&", ' ')
        query = query.replace(' ', '%20')

        response = regular_requests.get(f"https://www.opensubtitles.org/libs/suggest.php?format=json3&MovieName={query}"
                                f"&SubLanguageID=null",
                                headers=self.headers)
        if response.status_code == 200:
            data = response.json()
            result = []
            for show in data:
                if show["type"] == show_type:
                    show["poster"] = self.fix_poster_url(show["poster"])
                    result.append(show)
            return result
        else:
            logging.error(f"{response.status_code}")
            return []

    def suggestion_wrapper(self, get_opnsub_suggestions_data: list):
        if get_opnsub_suggestions_data:
            resp = {}
            for d in get_opnsub_suggestions_data:
                resp[d['id']] = {"caption": f"{str(d['attributes']['original_title']).capitalize()}, {d['attributes']['year']}\n",
                                 "img": d["attributes"]['img_url']}
            return resp

    def get_suggestions_discnt(self, query, show_type="Tvshow") -> list:

        query = query.replace('"', ' ')
        query = query.replace("'", ' ')
        query = query.replace("&", ' ')
        query = query.replace(' ', '%20')

        response = regular_requests.get(f"https://www.opensubtitles.com/en/en/search/autocomplete/{query}.json",
                                headers=self.headers)

        if response.status_code == 200:
            data = response.json()

            result = []
            for show in data:
                if show["type"] == show_type:
                    show["poster"] = self.fix_poster_url(show["poster"])
                    result.append(show)
            return result
        else:
            logging.error(f"Error: {response.status_code}")
            return []

    def get_features(self, query, show_type="tvshow", lang="en", feature_id=None) -> list[dict]:
        if query:
            query = query.replace('"', ' ')
            query = query.replace("'", ' ')
            query = query.replace("&", ' ')

        #api_url = f"{self.api_url_base}/features/{feature_id}?query={query}&type={show_type}"
        api_url = f"{self.api_url_base}/features"
        params = {
            "languages": lang,
            "type": show_type,
            "feature_id": feature_id,
            "query": query
        }
        logging.info(f"Features call with p:{params}")
        response = regular_requests.get(api_url, headers=self.headers, params=params)

        if response.status_code == 200:
            data = response.json()['data']
            print(data)
            result = []
            for show in data:
                if show["type"] == show_type:
                    show["attributes"]["img_url"] = self.fix_poster_url(show["attributes"]["img_url"])
                    result.append(show)
            return result
        else:
            logging.error(f"Error: {response.status_code}, {response.text}")
            return []


    def get_suggestions(self, query:str, parent_feature_id=0, season=1, year=0, lang="en", order_by="download_count", type="episode") -> list:
        api_url = self.api_url_base + '/subtitles'
        params = {
            "query": query,
            type: type,
            **({"parent_feature_id": parent_feature_id} if parent_feature_id != 0 else {}),
            "languages": lang,
            "season_number": season,
            "order_by": order_by,
            **({"year": year} if year != 0 else {})

        }
        logging.info(f"Subtitles call with p:{params}")
        response = regular_requests.get(api_url, headers=self.headers, params=params)

        if response.status_code == 200:
            try:
                data = response.json()
            except JSONDecodeError:
                logging.error(f"Error: {response.status_code}, {response.text}, {parent_feature_id}, {season}")
                data = None

            return data["data"]
        else:
            logging.error(f"Error: {response.status_code}, {response.text}, {parent_feature_id}, {season}")
            return []

    def get_episodes(self, show_id: int, season=1) -> None | dict:
        episodes_raw_data = self.get_srt_names(show_id, season=season)
        if episodes_raw_data:
            return parse_episodes(episodes_raw_data)

    def get_srt_names(self, parent_feature_id: int, season=1, year=0, lang="en") -> dict:
        api_url = self.api_url_base + '/subtitles'
        params = {
            "parent_feature_id": parent_feature_id,
            "languages": lang,
            "season_number": season,
            **({"year": year} if year != 0 else {})

        }
        logging.info(f"Subtitles call with p:{params}")
        response = regular_requests.get(api_url, headers=self.headers, params=params)

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


from PIL import Image, UnidentifiedImageError, ImageFilter, ImageOps, ImageEnhance


def get_img_resized(input_path, new_height=config.chat_preview_height):
    filename = input_path.split('/')[-1].split('.')[0]
    filename_end = '_.jpg'
    save_path = os.path.join(config.img_cache_folder_name, filename + filename_end)

    if img_is_cached(save_path):
        return save_path

    try:
        response = requests.get(input_path, impersonate="chrome120")
        img_data = response.content
        img_bytes_io = BytesIO(img_data)

        img = Image.open(img_bytes_io)
    except UnidentifiedImageError as e:
        logging.warning(f"Warning, no image: {response.status_code}, {filename}, {input_path}, {e}")
        return os.path.join(config.img_cache_folder_name, "no_image" + filename_end)
    except Exception as e:
        logging.error(f"Download error: {e}")
        return os.path.join(config.img_cache_folder_name, "no_image" + filename_end)

    width, height = img.size
    canvas_size = (200, new_height)

    # Convert transparent PNGs to RGB properly before processing
    if img.mode in ("P", "RGBA"):
        background = Image.new("RGB", img.size, (0, 0, 0))
        if img.mode == "RGBA":
            background.paste(img, mask=img.split()[3])
        else:
            background.paste(img)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # --- 1. CREATE THE BLURRED BACKGROUND ---
    # ImageOps.fit crops and zooms the image to perfectly fill the 200xNewHeight canvas
    bg_img = ImageOps.fit(img, canvas_size, method=Image.Resampling.LANCZOS)

    # Apply a strong blur (radius 15 usually looks best for UI backgrounds)
    bg_img = bg_img.filter(ImageFilter.GaussianBlur(radius=15))

    # Optional but highly recommended: Darken the blurred background by 40%
    # so the sharp foreground poster stands out more.
    enhancer = ImageEnhance.Brightness(bg_img)
    bg_img = enhancer.enhance(0.6)

    # --- 2. CREATE THE SHARP, CENTERED FOREGROUND ---
    # Calculate scale ratio so the poster perfectly fits *inside* the canvas without being cut off
    ratio = min(canvas_size[0] / width, canvas_size[1] / height)
    fg_width = int(width * ratio)
    fg_height = int(height * ratio)

    # Resize with LANCZOS and apply UnsharpMask to remove downscaling blur ("soapy" look)
    fg_img = img.resize((fg_width, fg_height), resample=Image.Resampling.LANCZOS)
    fg_img = fg_img.filter(ImageFilter.UnsharpMask(radius=1, percent=75, threshold=3))

    # --- 3. COMPOSE THE IMAGE ---
    # Calculate exactly where to paste the foreground so it sits perfectly in the center
    x_offset = (canvas_size[0] - fg_width) // 2
    y_offset = (canvas_size[1] - fg_height) // 2

    # Paste the sharp foreground onto the blurred background
    bg_img.paste(fg_img, (x_offset, y_offset))

    # --- 4. SAVE ---
    try:
        # subsampling=0 stops JPEG compression from muddying the colors
        bg_img.save(save_path, format="JPEG", quality=100, subsampling=0)
    except IOError as e:
        logging.error(f"Error: {e} while saving {filename}")

    return save_path

# def get_img_resized(input_path, new_height=config.chat_preview_height):
#     filename = input_path.split('/')[-1].split('.')[0]
#     filename_end = '_.jpg'
#     if img_is_cached(os.path.join(config.img_cache_folder_name, filename + filename_end)):
#         pass
#     else:
#         response = requests.get(input_path, impersonate="chrome120")
#         img_data = response.content
#         img_bytes_io = BytesIO(img_data)
#         try:
#             img = Image.open(img_bytes_io)
#         except UnidentifiedImageError as e:
#             logging.warning(f"Warning, no image: {response.status_code}, {filename}, {input_path}, {e}")
#             return os.path.join(config.img_cache_folder_name, "no_image" + filename_end)
#         width, height = img.size
#
#         # convert png to jpg
#         if img.mode in ("P", "RGBA"):
#             img = img.convert("RGB")
#         target_width = int((new_height / height) * width)
#         new_image = Image.new("RGB", (200, new_height), (0, 0, 0))
#
#         img = img.resize((target_width, new_height), resample=Image.Resampling.HAMMING)
#         new_image.paste(img, (0, 0))
#         try:
#             new_image.save(os.path.join(config.img_cache_folder_name, filename + filename_end), format="JPEG",
#                            quality=100)
#         except IOError as e:
#             logging.error(f"Error: {e} while saving {filename}")
#
#     return os.path.join(config.img_cache_folder_name, filename + filename_end)


def parse_episodes(opn_data: dict) -> dict:
    res_dict = {}
    try:
        sorted_data = sorted(opn_data['data'], key=lambda item: item['attributes']['feature_details']['episode_number'],
                             reverse=False)
    except KeyError:
        logging.error(f"Error: {opn_data['data']}")
        return res_dict
    # logging.debug(f"parse_episodes: {sorted_data}")
    for data in sorted_data:
        attrs = data['attributes']
        feature_details = attrs['feature_details']
        files = attrs['files'][0]  # TODO: detect right index
        if not attrs['hearing_impaired']:
            res_dict[feature_details['episode_number']] = {'id': data['id'],
                                                           'title': feature_details['title'],
                                                           'file_id': files['file_id'],
                                                           'file_name': files['file_name'] + '.srt', }

    return res_dict


def srt_cached(file_name: str) -> bool:
    """
    Checks if a .srt file with the given file_name exists in the current directory.

    :param file_name: Name of the file (including or excluding .srt extension)
    :return: True if the file exists, False otherwise
    """
    if not file_name.endswith(".srt"):
        file_name += ".srt"

    return os.path.isfile(os.path.exists(os.path.join(config.srt_cache_folder_name, file_name)))


if __name__ == '__main__':
    opn = Opnsub()
    #print(opn.suggestion_wrapper(opn.get_features("better call")))
    #resp = opn.get_features('Emily in Paris')
    #print(resp)
    print (opn.get_seasons_number("1110654"))
    # suggestions = opn.get_suggestions('South Park')
    # # 'https://www.opensubtitles.org/gfx/thumbs/4/9/0/6/13406094-t.jpg'
    # print(suggestions)
    # y = Youtube()
    # y.download_srt('https://www.youtube.com/watch?v=4muxFVZ4XfM&ab_channel=Lenny%27sPodcast')
    # "https://www.opensubtitles.com/nocache/search/en?current_languages=all&episode_number=all&hearing_impaired=hearing_impaired-1&machine_translated=machine_translated-1&q=osdb%3A1180031&search_in=tvshows&season_number=all&trusted_sources=trusted_sources-1"
    # series_data = opn.get_srt_names(parent_feature_id=7160, season=None, lang="en")
    # print (series_data)
    # download_info = (opn.get_srt_download_url(9022929))
    # if download_info:
    #     opn.download_file(download_info['link'], download_info['file_name'])
    # print(get_opnsub_subtitles_names('Shrinking')['data'])
