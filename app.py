import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from datetime import datetime

app = Flask(__name__)

# --- 1. 環境変数設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# 現在の日付を取得（到着予定日の計算用）
current_date = datetime.now().strftime("%Y年%m月%d日")

# --- 2. 究極の比較提案システムプロンプト ---
SYSTEM_INSTRUCTION = f"""
あなたは「郵便・発送ナビ」です。
本日（{current_date}）発送した場合の、最安と最短のプランを比較提案してください。

# 基本方針
- 挨拶や余計な説明は一切不要。
- 選択肢は必ず縦に並べ、数字で選ばせる。
- 住所、重さ、厚さから、日本郵便の全サービスから最適なものを選定。

# 配送スピードの目安（本日発送の場合）
- 普通郵便（定形・定形外）：3〜4日後（土日祝の配達なし）
- 速達・レターパック・ゆうパック：翌日〜翌々日
- クリックポスト・ゆうパケット：2〜3日後

# 進行フロー
1. 【内容物の確認】（1〜5の選択肢を縦に提示）
2. 【サイズ・重さの確認】（1つずつ簡潔に聞く）
3. 【住所の確認】（県名や郵便番号を聞く）
4. 【オプション確認】（補償の要否など。急ぎかどうかはここで聞かずに最終提案で比較する）

# 最終提案フォーマット（厳守）
「最安」と「最短」が異なる場合、必ず2パターン提示してください。

---
【最安プラン】
・サービス：[サービス名]
・料金：[金額]円
・到着予定：[○月○日]頃

【最短プラン】
・サービス：[サービス名]
・料金：[金額]円
・到着予定：[○月○日]頃
（※最安と同じ場合は「最安と同じ」と記載）

【アドバイス】
[例：補償が必要なら＋350円で簡易書留にできます]
---
"""

# Gemini 3.0 Flash Preview を採用
model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    system_instruction=SYSTEM_INSTRUCTION
)

chat_sessions = {}

@app.route("/")
def hello():
    return "郵便・発送ナビ稼働中"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text
    
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        response = chat.send_message(user_text)
        reply_text = response.text.strip()
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        print(f"Error: {e}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="すみません、もう一度入力してください。")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
