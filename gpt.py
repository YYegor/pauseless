import os
import config
import requests
import logging

logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

class GPT:
    def __init__(self):
        # self.api_url = "http://localhost:1234/v1/chat/completions"
        self.api_url = "http://localhost:1234/v1/chat/completions"

        self.model = "local-model"  # Replace with the model name if needed, or leave as placeholder
        self.headers = {
            "Content-Type": "application/json"
        }

    def get_word_meaning(self, word, series_name, sentence):
        print(series_name)
        request_input = (
            f"In this script line '{sentence}' from '{series_name}' TV series give a contextual definition "
            f" of '{word}' in one short sentence as in a dictionary, use context of the TV show, with simple words. "
            f"Do not mention the TV show. Do not ask anything."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": request_input}
            ],
            "temperature": config.GPT_temp
        }

        try:
            response = requests.post(self.api_url, headers=self.headers, json=payload)
            response.raise_for_status()
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            logging.error(f"Failed to get response from LL Studio: {e}")
            return None

# Expect your Gemini API key in env, or set it directly.


class GPTGemini:
    def __init__(self):
        self.api_url = config.GEMINI_URL
        self.headers = {"Content-Type": "application/json",
                        "X-goog-api-key": GEMINI_API_KEY}


    def get_word_meaning(self, word, series_name, sentence):

        # Build the user prompt
        request_input = (
            f"In this script line '{sentence}' from '{series_name}' TV series give a contextual definition "
            f"of '{word}' in one short sentence as in a dictionary, use context of the TV show, with simple words. "
            f"Do not mention the TV show. Do not ask anything."
        )

        payload = {
            "contents": [
                {
                    "parts": [{"text": request_input}]
                }
            ],
            "generationConfig": {
                "temperature": getattr(config, "GPT_temp", 0.7)
            }
        }

        try:
            resp = requests.post(self.api_url, headers=self.headers, json=payload, timeout=60)

            resp.raise_for_status()
            data = resp.json()
            # Extract first candidate text (Gemini/Gemma response shape)
            return (
                data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", None)
            )
        except Exception as e:
            logging.error(f"Failed to get response from Gemini API: {e}")
            return None

# class GPT:
#     def __init__(self):
#         try:
#             self.model = GPT4All(model_path=config.GPT_model_path,
#                         model_name=config.GPT_model_name,
#                         n_threads=config.GPT_n_threads)
#         except Exception as e:
#             logging.error(f"GPT can't initialise, {e}")
#             self.model = None
#
#     def get_word_meaning(self, word, series_name, sentence):
#         request_input = (f"In this script line '{sentence}' from '{series_name}' TV series give a contextual definition"
#                          f" of '{word}' in one short sentence as in a dictionary, use context of the TV show, with simple words. Do not mention the TV show. Use template 'word (transcription, if not a name) – meaning'")
#         print(request_input)
#         with self.model.chat_session():
#                 response2 = self.model.generate(
#                 prompt=f"{request_input}",
#                 temp=config.GPT_temp)
#                 # print(f"{model.current_chat_session[-1]['content']} \n\n")
#                 return response2

if __name__ == '__main__':
    # m = GPT()
    m2 = GPTGemini()
    # print (m.get_word_meaning('larynx', 'Severance', "If you breathe on me, "
    #                                                     "I'll rip your larynx out."))

    print(m2.get_word_meaning('larynx', 'Severance', "If you breathe on me, "
                                                    "I'll rip your larynx out."))