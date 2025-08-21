import os
import requests
import asyncio
import logging
import httpx
import config

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
            f"Do not mention the TV show. Do not ask anything."
        )

        payload = {
            "contents": [{"parts": [{"text": request_input}]}],
            "generationConfig": {"temperature": getattr(config, "GPT_temp", 0.7)},
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


async def mainroutine():
    m2 = GPTGemini()
    # print (m.get_word_meaning('larynx', 'Severance', "If you breathe on me, "
    #                                                     "I'll rip your larynx out."))

    print(await m2.get_word_meaning('RUPERT', 'Family guy, 1998', "RUPERT, DID YOU CALL THAT ENGINEER AT LOCKHEED YET?"))

if __name__ == '__main__':
    asyncio.run(mainroutine())
    # m = GPT()
