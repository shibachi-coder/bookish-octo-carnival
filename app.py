import os, re
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    QuickReply, QuickReplyButton, MessageAction
)
import google.generativeai as genai
from datetime import datetime

app = Flask(__name__)

# --- 環境変数 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# --- プロンプト（ボタン化しやすいように1行1項目を徹底） ---
SYSTEM_INSTRUCTION = f"""
あなたは発送コンシェルジュです。本日（{datetime.now().strftime("%m/%d")}）の最適解を出します。

# ルール
- 選択肢は必ず「1:項目名」の形式で、1行に1つ書くこと。
- 余計な挨拶は省き、すぐ質問に入る。
- 最後に「最安」と「最短」を比較。

# 質問フロー
1. 分類選択（書類/小物/大型/はがき/その他）
2. 厚さ・重さ・サイズの確認
3. 送り先の都道府県
4. 最終提案
"""

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    system_instruction=SYSTEM_INSTRUCTION
)

chat_sessions = {}

def make_quick_reply(text):
    """テキストから『1:〇〇』のような行を探してボタンにする"""
    # 「数字:」または「数字：」または「数字️⃣」で始まる行を抽出
    options = re.findall(r'([1-9一二三四五][:：️⃣][^\n]+)', text)
    if not options:
        return None
    
    items = []
    for opt in options[:13]: # LINEの仕様で最大13個まで
        # ボタンのラベル用に「1:」などを削る（任意）
        label = opt[:20] # 20文字制限
        items.append(QuickReplyButton(action=MessageAction(label=label, text=opt)))
    
    return QuickReply(items=items)

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
    
    if user_text in ["最初から", "リセット"]:
        if user_id in chat_sessions: del chat_sessions[user_id]
        user_text = "最初から"

    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    try:
        response = chat_sessions[user_id].send_message(user_text)
        reply_text = response.text.strip()
        
        # ボタンを自動生成
        q_reply = make_quick_reply(reply_text)
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=q_reply)
        )
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="エラーです。リセットして下さい"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
