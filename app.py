import os, re, json, threading, requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
# ... (他のモデルなどはそのまま)

app = Flask(__name__)

# HTTPセッションの最適化
http_session = requests.Session()
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
line_bot_api.http_client.session = http_session

# Gemini設定の最適化
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
generation_config = {
    "temperature": 0.7,
    "max_output_tokens": 600, # 長文エラーを防ぎつつ速度向上
}

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview",
    system_instruction=SYSTEM_INSTRUCTION,
    generation_config=generation_config
)
