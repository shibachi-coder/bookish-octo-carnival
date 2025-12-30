import os, re, json, threading  # threadingを追加
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    QuickReply, QuickReplyButton, MessageAction,
    FlexSendMessage
)
import google.generativeai as genai
from datetime import datetime

app = Flask(__name__)

# --- 環境変数等はそのまま ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# --- プロンプトなどは前回と同様 ---
SYSTEM_INSTRUCTION = f"あなたは日本郵便コンシェルジュです..." # (省略)

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    system_instruction=SYSTEM_INSTRUCTION
)

chat_sessions = {}

# --- 重い処理を別スレッドで実行する関数 ---
def process_gemini_and_reply(user_id, user_text, reply_token):
    try:
        if user_id not in chat_sessions:
            chat_sessions[user_id] = model.start_chat(history=[])
        
        response = chat_sessions[user_id].send_message(user_text)
        reply_text = response.text.strip()
        
        # 記号の掃除
        reply_text = reply_text.replace("**", "")
        reply_text = re.sub(r'【.*形式】', '', reply_text)
        
        # JSON抽出とFlex Messageの処理 (前回のロジックをここに移動)
        json_match = re.search(r'\{.*\}', reply_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                clean_text = reply_text.replace(json_match.group(), "").strip()
                messages = []
                if clean_text: messages.append(TextSendMessage(text=clean_text))
                
                # Flexメッセージ作成関数（前回定義したもの）を呼び出す
                flex_content = create_shipping_flex(data) 
                messages.append(FlexSendMessage(alt_text="郵便発送プランの提案", contents=flex_content))
                line_bot_api.reply_message(reply_token, messages)
                return
            except: pass
        
        # 通常返信
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=reply_text, quick_reply=make_quick_reply(reply_text))
        )
    except Exception as e:
        print(f"Async Error: {e}")

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK' # ここで即座にLINEにOKを返す

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text
    
    # リセット処理
    if user_text in ["最初から", "リセット"]:
        if user_id in chat_sessions: del chat_sessions[user_id]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="リセットしました。"))
        return

    # 重い処理を別スレッドで開始
    thread = threading.Thread(target=process_gemini_and_reply, args=(user_id, user_text, event.reply_token))
    thread.start()

# (create_shipping_flex, make_quick_reply関数は前回と同じものを下に配置)
