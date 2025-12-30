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

# 現在の日付を取得（配送日数の計算基準）
current_date_str = datetime.now().strftime("%Y年%m月%d日")

# --- 2. 120点：究極の配送コンシェルジュプロンプト ---
SYSTEM_INSTRUCTION = f"""
あなたは日本一親切な「郵便・発送コンシェルジュ」です。
本日（{current_date_str}）発送する場合の【最安】と【最短】を比較提案します。

# UX指針
- 言葉を極限まで削り、視覚的（縦並び・絵文字）に伝える。
- ユーザーに文字を打たせず、「番号」だけで進めるよう誘導する。
- 住所、重さ、厚さから日本郵便の全サービス（ゆうパック、レターパック、手紙、はがき等）を網羅。

# 到着予定の計算
- 翌日着：ゆうパック、レターパック、速達
- 2-3日後：クリックポスト、ゆうパケット
- 3-4日後：普通郵便（土日祝は配達なしとして計算）

# 進行フロー
1. 【何を送る？】（1️⃣〜5️⃣の選択肢を提示）
2. 【サイズ確認】（1つずつ簡潔に聞く）
3. 【どこへ送る？】（都道府県や郵便番号を聞く）
4. 【最終提案】
   ---
   💰【最安】[サービス名]
   └ 料金：[金額]円
   └ 到着：[月/日]頃

   🚀【最短】[サービス名]
   └ 料金：[金額]円
   └ 到着：[月/日]頃
   （※同じ場合は「最安と同じ」）

   💡【一言アドバイス】
   [例：壊れやすいならゆうパック一択です]
   ---
"""

# Gemini 3.0 Flash Preview を採用（診断ログは削除しました）
model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    system_instruction=SYSTEM_INSTRUCTION
)

chat_sessions = {}

# --- 3. ルーティング ---

@app.route("/")
def hello():
    return "郵便・発送コンシェルジュ稼働中"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 4. メッセージ処理 ---

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text
    
    # リセット機能
    if user_text in ["最初から", "リセット", "やり直し", "0"]:
        if user_id in chat_sessions:
            del chat_sessions[user_id]
        reply_text = "リセットしました。送るものはどれですか？\n\n1️⃣ 書類・手紙\n2️⃣ 小物\n3️⃣ 箱・大型\n4️⃣ はがき\n5️⃣ その他"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

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
            TextSendMessage(text="すみません、うまく聞き取れませんでした。もう一度入力してください。")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
