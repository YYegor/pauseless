import os
import requests
import asyncio
import logging
import httpx
import config
import json

logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    logging.error("GEMINI_API_KEY not set")

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


_HTTPX_CLIENT: httpx.AsyncClient | None = None

def get_httpx_client() -> httpx.AsyncClient:
    global _HTTPX_CLIENT
    if _HTTPX_CLIENT is None:
        _HTTPX_CLIENT = httpx.AsyncClient(
            http2=True,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=30.0, pool=5.0),
            headers={"User-Agent": "pauseless/1.0"},
        )
    return _HTTPX_CLIENT

async def aclose_httpx_client():
    global _HTTPX_CLIENT
    if _HTTPX_CLIENT is not None:
        await _HTTPX_CLIENT.aclose()
        _HTTPX_CLIENT = None

class GPTGemini:
    def __init__(self):
        self.api_url = config.GEMINI_URL
        self.headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": GEMINI_API_KEY
        }

    async def get_word_meaning(self, word: str, series_name: str, sentence: str) -> str | None:
        # Build prompt
        request_input = (
            f"In this script line '{sentence}' from '{series_name}' TV series give a contextual definition "
            f"of '{word}' in one short sentence as in a dictionary, use context of the TV show and sentence, with simple words. "
            f"Do not mention the TV show if the word is not a TV show character."
            f"If the word is a TV show character, describe it as the TV show character"
            f"Do not mention the word in the question. Do not ask anything."
        )

        payload = {
            "contents": [{"parts": [{"text": request_input}]}],
            "generationConfig": {"temperature": getattr(config, "GPT_temp", 0.2)},
        }

        client = get_httpx_client()

        # Retry on 429 and 5xx: 3 retries, 1s wait each (total 4 attempts)
        for attempt in range(4):
            try:
                resp = await client.post(self.api_url, headers=self.headers, json=payload)
            except httpx.RequestError as e:
                logging.warning(f"Gemini request error: {e}")
                return None

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt < 3:
                    # Respect JSON retry_after if present
                    retry_after = 1
                    try:
                        retry_after = int(resp.json().get("parameters", {}).get("retry_after", 1))
                    except Exception:
                        pass
                    await asyncio.sleep(max(1, retry_after))
                    continue
                logging.error(f"Gemini failed after retries: {resp.status_code} {resp.text[:200]}")
                return None

            if resp.is_error:
                logging.error(f"Gemini error: {resp.status_code} {resp.text[:200]}")
                return None

            try:
                data = resp.json()
                print(request_input, data)
            except ValueError as e:
                logging.error(f"Gemini JSON error: {e}")
                return None

            return (
                data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text")
            )
        return None

    async def get_collocations_meaning(self, series_name: str, sentence: str) -> dict | None:
        # Build prompt
        request_input = (
            f"Analyze the following script line: '{sentence}' from TV show '{series_name}'."
            f"Find a multi-word expression (phrasal verb, collocation, idiom, or compound noun). "
            f"CRITICAL RULE: The extracted phrase MUST contain at least two words. Single-word verbs or nouns are strictly forbidden. "
            f"If there are no expressions with 2 or more words, you MUST output an empty JSON {{}}. "
            f"If a valid multi-word expression is found, reply ONLY with a JSON object in this format: {{\"phrase in infinitive\": \"simple meaning\"}}. "
            f"Do not mention the TV show in the answer, but use TV show context in explanation, if needed."
            f"Do not add conversational text, and do not ask questions."
        )

        payload = {
            "contents": [{"parts": [{"text": request_input}]}],
            "generationConfig": {"temperature": getattr(config, "GPT_temp", 0.2),
                                 "responseMimeType": "application/json"},

        }

        client = get_httpx_client()

        # Retry on 429 and 5xx: 3 retries, 1s wait each (total 4 attempts)
        for attempt in range(4):
            try:
                resp = await client.post(self.api_url, headers=self.headers, json=payload)
            except httpx.RequestError as e:
                logging.warning(f"Gemini request error: {e}")
                return {}

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt < 3:
                    # Respect JSON retry_after if present
                    retry_after = 1
                    try:
                        retry_after = int(resp.json().get("parameters", {}).get("retry_after", 1))
                    except Exception:
                        pass
                    await asyncio.sleep(max(1, retry_after))
                    continue
                logging.error(f"Gemini failed after retries: {resp.status_code} {resp.text[:200]}")
                return {}

            if resp.is_error:
                logging.error(f"Gemini error: {resp.status_code} {resp.text[:200]}")
                return {}

            try:
                data = resp.json()
                print(request_input, data)
            except ValueError as e:
                logging.error(f"Gemini JSON error: {e}")
                return {}
            try:
                response = json.loads(
                    data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text"))
            except ValueError as e:
                logging.error(f"Gemini JSON error: {e}")
                return {}
            return response
        return {}


async def mainroutine():
    m2 = GPTGemini()
    # print (m.get_word_meaning('larynx', 'Severance', "If you breathe on me, "
    #                                                     "I'll rip your larynx out."))

    res = await m2.get_collocations_meaning('Family guy, 1998', "Rupert, hello, do not exaggerate")
    print(res)

if __name__ == '__main__':
    asyncio.run(mainroutine())
    # m = GPT()
