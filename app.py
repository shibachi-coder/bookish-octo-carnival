import os
import re
import json
import threading
import requests
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

# --- 1. 初期化とパフォーマンス最適化 ---
# HTTPセッションを再利用して高速化
http_session = requests.Session()
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
line_bot_api.http_client.session = http_session
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

# Geminiの設定
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
generation_config = {
    "temperature": 0.7,
    "max_output_tokens": 800,
}

# 2025年12月31日の日付を基準に設定
current_date_str = datetime.now().strftime("%Y年%m月%d日")

SYSTEM_INSTRUCTION = f"""
あなたは日本郵便の「発送コンシェルジュ」です。
本日（{current_date_str}）発送する場合の【日本郵便のサービス内】での最適解を出します。

# 厳守ルール
- 日本郵便以外のサービスは絶対に提案しない。
- **（太字記号）は使用禁止。
- メッセージに「JSON」や「形式」という言葉を出さない。
- 選択肢は「1:項目名」の形式で1行ずつ縦に並べる。

# 提案データ（末尾に必ず付与）
{{
  "cheapest": {{"name": "サービス名", "price": "金額", "date": "月/日"}},
  "fastest": {{"name": "サービス名", "price": "金額", "date": "月/日"}},
  "advice": "コンシェルジュのアドバイス"
}}
"""

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview",
    system_instruction=SYSTEM_INSTRUCTION,
    generation_config=generation_config
)

chat_sessions = {}

# --- 2. ヘルパー関数 ---

def create_shipping_flex(data):
    """日本郵便ブランドカラーの提案カードを作成"""
    return {
      "type": "bubble",
      "header": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "🏣 日本郵便 発送ナビ", "weight": "bold", "color": "#ffffff", "size": "sm"}
        ], "backgroundColor": "#E60012"
      },
      "body": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "最適な郵便プランを選定しました", "size": "xs", "color": "#888888", "margin": "md"},
          {"type": "separator", "margin": "md"},
          {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
            {"type": "text", "text": "💰 最安プラン", "weight": "bold", "size": "md", "color": "#f1c40f"},
            {"type": "box", "layout": "horizontal", "contents": [
              {"type": "text", "text": data['cheapest']['name'], "flex": 4, "size": "sm", "weight": "bold"},
              {"type": "text", "text": f"¥{data['cheapest']['price']}", "flex": 2, "size": "sm", "align": "end"}
            ]},
            {"type": "text", "text": f"到着予定: {data['cheapest']['date']} 頃", "size": "xs", "color": "#555555"}
          ]},
          {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
            {"type": "text", "text": "🚀 最短プラン", "weight": "bold", "size": "md", "color": "#3498db"},
            {"type": "box", "layout": "horizontal", "contents": [
              {"type": "text", "text": data['fastest']['name'], "flex": 4, "size": "sm", "weight": "bold"},
              {"type": "text", "text": f"¥{data['fastest']['price']}", "flex": 2, "size": "sm", "align": "end"}
            ]},
            {"type": "text", "text": f"到着予定: {data['fastest']['date']} 頃", "size": "xs", "color": "#555555"}
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
    """テキストから選択肢を抽出してボタン化"""
    options = re.findall(r'([1-9一二三四五][:：️⃣][^\n]+)', text)
    if not options: return None
    items = [QuickReplyButton(action=MessageAction(label=opt[:20], text=opt)) for opt in options[:13]]
    return QuickReply(items=items)

# --- 3. 非同期処理ロジック ---

def process_and_reply(user_id, user_text, reply_token):
    try:
        if user_id not in chat_sessions:
            chat_sessions[user_id] = model.start_chat(history=[])
        
        response = chat_sessions[user_id].send_message(user_text)
        reply_text = response.text.strip().replace("**", "")
        reply_text = re.sub(r'【.*形式】', '', reply_text)
        
        json_match = re.search(r'\{.*\}', reply_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                clean_text = reply_text.replace(json_match.group(), "").strip()
                messages = []
                if clean_text: messages.append(TextSendMessage(text=clean_text))
                
                flex_content = create_shipping_flex(data)
                messages.append(FlexSendMessage(alt_text="郵便発送プランの提案", contents=flex_content))
                line_bot_api.reply_message(reply_token, messages)
                return
            except: pass
        
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=reply_text, quick_reply=make_quick_reply(reply_text))
        )
    except Exception as e:
        print(f"Error in thread: {e}")

# --- 4. Webhookハンドラー ---

@app.route("/")
def hello(): return "発送コンシェルジュ稼働中"

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
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="リセットしました。送るものはどれですか？\n1:書類\n2:小物\n3:大型"))
        return

    # タイムアウト回避のため別スレッドで実行
    thread = threading.Thread(target=process_and_reply, args=(user_id, user_text, event.reply_token))
    thread.start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
