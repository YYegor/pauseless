
logs_filename='./app.log'
logs_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

img_cache_folder_name = 'cache_img'
srt_cache_folder_name = 'cache_srt'

chat_preview_height = 100

collect_collocations = False

GPT_model_name = 'mistral-7b-instruct-v0.1.Q4_0.gguf'
GPT_model_path = '/Users/egor/Library/Application Support/nomic.ai/GPT4All/'
GPT_n_threads = 8
GPT_temp = 0
GEMINI_model = 'gemini-2.5-flash'
#GEMINI_model = 'gemini-2.5-flash'
GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_model}:generateContent"