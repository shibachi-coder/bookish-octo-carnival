import os, re, json, threading, requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, FollowEvent, TextMessage, TextSendMessage, 
    QuickReply, QuickReplyButton, MessageAction, FlexSendMessage
)
import google.generativeai as genai
from datetime import datetime

app = Flask(__name__)

# --- 初期設定 ---
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
line_bot_api.http_client.session = requests.Session()
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    generation_config={"temperature": 0.2, "max_output_tokens": 900}
)

# --- 1. ウェルカムカード（スタートボタン）のデザイン ---
def create_welcome_flex():
    return {
      "type": "bubble",
      "hero": {
        "type": "image",
        "url": "https://images.unsplash.com/photo-1566121316354-91b3563b2218?q=80&w=1000&auto=format&fit=crop", # 郵便をイメージしたお洒落な画像
        "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"
      },
      "body": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "発送コンシェルジュ 🏣", "weight": "bold", "size": "xl", "color": "#E60012"},
          {"type": "text", "text": "日本郵便のサービスから、あなたに最適な最短・最安プランを秒速で診断します。", "wrap": True, "size": "sm", "margin": "md", "color": "#555555"}
        ]
      },
      "footer": {
        "type": "box", "layout": "vertical", "spacing": "sm", "contents": [
          {
            "type": "button",
            "style": "primary",
            "color": "#E60012",
            "action": {"type": "message", "label": "診断をスタート", "text": "スタート"}
          }
        ]
      }
    }

# --- 2. 友だち追加（フォロー）時のイベント ---
@handler.add(FollowEvent)
def handle_follow(event):
    uid = event.source.user_id
    if uid in chat_sessions: del chat_sessions[uid]
    
    # ウェルカムカードを送信
    line_bot_api.reply_message(
        event.reply_token,
        FlexSendMessage(alt_text="発送ナビへようこそ！", contents=create_welcome_flex())
    )

# --- 3. メイン処理（メッセージ受信） ---
def process_async(user_id, user_text, reply_token):
    try:
        # 「スタート」と打たれたら最初の質問を促す
        if user_text == "スタート":
            msg = "承知いたしました！まず、送るものはどれですか？\n\n1:書類・手紙\n2:小物\n3:箱・大型\n4:はがき\n5:その他"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=msg, quick_reply=make_quick_reply(msg)))
            return

        # AI処理（Gemini 3.0）
        if user_id not in chat_sessions:
            chat_sessions[user_id] = model.start_chat(history=[])
        
        raw_res = chat_sessions[user_id].send_message(user_text).text.replace("**", "")
        parts = raw_res.split("###")
        user_msg = parts[0].strip()
        
        messages = []
        if user_msg:
            user_msg = re.sub(r'【.*】', '', user_msg)
            messages.append(TextSendMessage(text=user_msg, quick_reply=make_quick_reply(user_msg)))
            
        # (以前のFlexメッセージ提案ロジック等は継続)
        # ... 

        line_bot_api.reply_message(reply_token, messages)
    except: pass

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    uid, txt = event.source.user_id, event.message.text
    if txt in ["最初から", "リセット", "やり直し"]:
        if uid in chat_sessions: del chat_sessions[uid]
        txt = "スタート" # 内部的にスタートとして処理

    threading.Thread(target=process_async, args=(uid, txt, event.reply_token)).start()

# --- ヘルパー関数 ---
def make_quick_reply(text):
    options = re.findall(r'([1-9一二三四五][:：️⃣][^\n]+)', text)
    if not options: return None
    return QuickReply(items=[QuickReplyButton(action=MessageAction(label=o[:20], text=o)) for o in options[:13]])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
