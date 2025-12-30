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

# --- 1. 初期設定と変数定義 ---
# ここで確実に辞書を定義します
chat_sessions = {}

line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
line_bot_api.http_client.session = requests.Session()
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    generation_config={"temperature": 0.2, "max_output_tokens": 1000}
)

# 日本郵便専属システムプロンプト
SYSTEM_INSTRUCTION = f"""
本日は{datetime.now().strftime("%Y/%m/%d")}。日本郵便の専門家として即答せよ。
他社サービスは禁止。** (太字)は禁止。JSON等のシステム用語は出すな。
必ず返答の末尾に ### と以下のJSONデータを付与せよ。
{{
  "cheapest": {{"name": "名称", "price": "金額", "date": "月/日"}},
  "fastest": {{"name": "名称", "price": "金額", "date": "月/日"}},
  "advice": "助言"
}}
"""

# --- 2. 各種デザイン・ヘルパー関数 ---

def create_welcome_flex():
    """スタートボタン付きウェルカムカード"""
    return {
      "type": "bubble",
      "hero": {
        "type": "image", "url": "https://images.unsplash.com/photo-1566121316354-91b3563b2218?q=80&w=1000&auto=format&fit=crop",
        "size": "full", "aspectRatio": "20:13", "aspectMode": "cover"
      },
      "body": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "発送コンシェルジュ 🏣", "weight": "bold", "size": "xl", "color": "#E60012"},
          {"type": "text", "text": "日本郵便の最短・最安プランを秒速で診断します。", "wrap": True, "size": "sm", "margin": "md"}
        ]
      },
      "footer": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "button", "style": "primary", "color": "#E60012", "action": {"type": "message", "label": "診断をスタート", "text": "スタート"}}
        ]
      }
    }

def create_shipping_flex(data):
    """提案結果カード"""
    return {
      "type": "bubble", "header": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "🏣 日本郵便 最適解", "weight": "bold", "color": "#ffffff", "size": "sm"}
        ], "backgroundColor": "#E60012"
      },
      "body": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "box", "layout": "vertical", "margin": "md", "contents": [
            {"type": "text", "text": "💰 最安", "weight": "bold", "size": "md", "color": "#f1c40f"},
            {"type": "box", "layout": "horizontal", "contents": [
              {"type": "text", "text": data['cheapest']['name'], "flex": 4, "size": "sm", "weight": "bold"},
              {"type": "text", "text": f"¥{data['cheapest']['price']}", "flex": 2, "size": "sm", "align": "end"}
            ]},
            {"type": "text", "text": f"到着予定: {data['cheapest']['date']}", "size": "xs", "color": "#888888"}
          ]},
          {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
            {"type": "text", "text": "🚀 最短", "weight": "bold", "size": "md", "color": "#3498db"},
            {"type": "box", "layout": "horizontal", "contents": [
              {"type": "text", "text": data['fastest']['name'], "flex": 4, "size": "sm", "weight": "bold"},
              {"type": "text", "text": f"¥{data['fastest']['price']}", "flex": 2, "size": "sm", "align": "end"}
            ]},
            {"type": "text", "text": f"到着予定: {data['fastest']['date']}", "size": "xs", "color": "#888888"}
          ]}
        ]
      },
      "footer": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": f"💡 {data['advice']}", "size": "xs", "color": "#666666", "wrap": True},
          {"type": "button", "action": {"type": "message", "label": "最初から", "text": "最初から"}, "style": "link", "height": "sm"}
        ]
      }
    }

def make_quick_reply(text):
    options = re.findall(r'([1-9一二三四五][:：️⃣][^\n]+)', text)
    if not options: return None
    return QuickReply(items=[QuickReplyButton(action=MessageAction(label=o[:20], text=o)) for o in options[:13]])

# --- 3. 非同期処理 ---

def process_async(user_id, user_text, reply_token):
    try:
        if user_text == "スタート":
            msg = "送るものはどれですか？\n1:書類・手紙\n2:小物\n3:箱・大型\n4:はがき\n5:その他"
            line_bot_api.reply_message(reply_token, TextSendMessage(text=msg, quick_reply=make_quick_reply(msg)))
            return

        if user_id not in chat_sessions:
            chat_sessions[user_id] = model.start_chat(history=[], system_instruction=SYSTEM_INSTRUCTION)
        
        raw_res = chat_sessions[user_id].send_message(user_text).text.replace("**", "")
        parts = raw_res.split("###")
        user_msg = re.sub(r'【.*】', '', parts[0].strip())
        
        messages = [TextSendMessage(text=user_msg, quick_reply=make_quick_reply(user_msg))]
        
        if len(parts) > 1:
            try:
                data = json.loads(re.search(r'\{.*\}', parts[1], re.DOTALL).group())
                messages.append(FlexSendMessage(alt_text="提案カード", contents=create_shipping_flex(data)))
            except: pass
            
        line_bot_api.reply_message(reply_token, messages)
    except: pass

# --- 4. Webhookイベント ---

@app.route("/")
def hello(): return "発送ナビ稼働中"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try: handler.handle(body, signature)
    except InvalidSignatureError: abort(400)
    return 'OK'

@handler.add(FollowEvent)
def handle_follow(event):
    line_bot_api.reply_message(event.reply_token, FlexSendMessage(alt_text="ようこそ！", contents=create_welcome_flex()))

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    uid, txt = event.source.user_id, event.message.text
    if txt in ["最初から", "リセット", "やり直し"]:
        if uid in chat_sessions: del chat_sessions[uid]
        txt = "スタート"
    threading.Thread(target=process_async, args=(uid, txt, event.reply_token)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
