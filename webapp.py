import os
import hmac
import hashlib
import urllib.parse
import json
from flask import Flask, render_template, request, jsonify
import logging
import config

logging.basicConfig(
    format=config.logs_format,
    level=logging.INFO,
    filename=config.logs_filename
)

logging.getLogger("httpx").setLevel(logging.WARNING)

app = Flask(__name__)
TG_BOT_KEY = os.environ.get('TG_BOT_KEY')

def validate_telegram_data(init_data: str):
    """Проверка криптографической подписи Telegram"""
    try:
        parsed_data = dict(urllib.parse.parse_qsl(init_data))
        if "hash" not in parsed_data:
            return None

        hash_from_telegram = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))
        secret_key = hmac.new(b"WebAppData", TG_BOT_KEY.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if calculated_hash == hash_from_telegram:
            return json.loads(parsed_data.get("user", "{}"))
    except Exception:
        pass
    return None


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/get_file', methods=['POST'])
def get_file():
    data = request.json
    init_data = data.get('initData', '')

    # 1. Проверяем, что запрос реально из Telegram
    user = validate_telegram_data(init_data)
    if not user:
        return jsonify({"error": "Доступ запрещен. Неверная подпись."}), 403

    user_id = user.get('id')

    # 2. Ищем файл этого пользователя (для теста ищем sample.txt)
    # В реальном проекте: file_path = os.path.join(DATA_DIR, f"{user_id}.txt")
    file_path = os.path.join(DATA_DIR, "sample.txt")

    if not os.path.exists(file_path):
        return jsonify({"error": "Файл не найден на сервере."}), 404

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({"content": content, "user_id": user_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)