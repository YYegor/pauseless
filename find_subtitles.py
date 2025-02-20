import requests
from io import BytesIO
from PIL import Image
import os
opnsub_api_key = os.environ.get("OPNSUB_API_KEY")
opn_api_name = os.environ.get("OPNSUB_API_KEY")
opnsub_api_token = os.environ.get("OPNSUB_TOKEN")

api_url_base = 'https://api.opensubtitles.com/api/v1'
img_cache_folder_name = 'cache'

def resize_image(input_path, new_width=100, new_height=30):

    filename = input_path.split('/')[-1].split('.')[0]
    filename_end = '_.jpg'
    if os.path.exists(os.path.join(img_cache_folder_name, filename+filename_end)):
        pass
    else:
        response = requests.get(input_path)
        img_data = response.content
        img_bytes_io = BytesIO(img_data)
        img = Image.open(img_bytes_io)

        # convert png to jpg
        if img.mode in ("P", "RGBA"):
            img = img.convert("RGB")
        img = img.resize((new_width, new_height))
        img.save(os.path.join(img_cache_folder_name, filename+filename_end), format="JPEG")
    return os.path.join(img_cache_folder_name,filename+filename_end)

def get_opnsub_suggestions(query):
    query = query.replace(' ', '+')
    headers = {
        "Content-Type": "application/json; charset=utf-8"
    }
    response = requests.get(f"https://www.opensubtitles.com/en/en/search/autocomplete/{query}.json", headers=headers)

    if response.status_code == 200:
        data = response.json()
        return data
    else:
        print(f"Error: {response.status_code}")
        return None

def get_opnsub_subtitles_names(title, season =1, year=0, lang="en"):
    api_url = api_url_base + '/subtitles'
    headers = {
        "Api-Key": opnsub_api_key,
        "Content-Type": "application/json"
    }
    params = {
        "parent_feature_id": 1434916,
        "languages": lang,
        "season_number": season
    }
    response = requests.get(api_url, headers=headers, params=params)

    if response.status_code == 200:
        data = response.json()
        return data
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return None

def opnsub_fix_poster_url(url):
    if 'http' not in url:
        return 'https://opensubtitles.com'+url
    else:
        return url

def suggestion_wrapper(query):
    data = get_opnsub_suggestions(query)
    if data:
        resp = {}
        for d in data:
            resp[d['id']] ={"caption": f"{d['title']} {d['year']}  rate:{d['rating']}\n", "img":opnsub_fix_poster_url(d['poster'])}
        return resp

if __name__ == '__main__':
    print(get_opnsub_subtitles_names('Shrinkin'))
    # print(get_opnsub_subtitles_names('Shrinking')['data'])