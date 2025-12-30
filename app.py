import os, re, json
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    QuickReply, QuickReplyButton, MessageAction,
    FlexSendMessage, BubbleContainer
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

# --- 150点のためのシステムプロンプト ---
SYSTEM_INSTRUCTION = f"""
あなたは発送コンシェルジュです。本日（{datetime.now().strftime("%m/%d")}）の最適解を出します。

# 進行ルール
- 選択肢は必ず「1:項目名」形式で縦に並べる（クイックリプライ用）。
- 最終提案の時だけ、必ず以下の【JSON形式】で回答を締めくくってください。

【JSON形式】
{{
  "cheapest": {{"name": "サービス名", "price": "金額", "date": "月/日"}},
  "fastest": {{"name": "サービス名", "price": "金額", "date": "月/日"}},
  "advice": "一言アドバイス"
}}
"""

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    system_instruction=SYSTEM_INSTRUCTION
)

chat_sessions = {}

def create_shipping_flex(data):
    """提案データを元に美しいFlex Messageを作成する"""
    return {
      "type": "bubble",
      "header": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "📦 発送ナビ 最終提案", "weight": "bold", "color": "#ffffff", "size": "sm"}
        ], "backgroundColor": "#E60012"
      },
      "body": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "あなたに最適なプランは以下の通りです", "size": "xs", "color": "#888888", "margin": "md"},
          {"type": "separator", "margin": "md"},
          # 最安セクション
          {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
            {"type": "text", "text": "💰 最安プラン", "weight": "bold", "size": "md", "color": "#f1c40f"},
            {"type": "box", "layout": "horizontal", "contents": [
              {"type": "text", "text": data['cheapest']['name'], "flex": 4, "size": "sm", "weight": "bold"},
              {"type": "text", "text": f"¥{data['cheapest']['price']}", "flex": 2, "size": "sm", "align": "end"}
            ]},
            {"type": "text", "text": f"到着予定: {data['cheapest']['date']} 頃", "size": "xs", "color": "#555555"}
          ]},
          # 最速セクション
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
          {"type": "button", "action": {"type": "message", "label": "最初からやり直す", "text": "最初から"}, "style": "link", "height": "sm"}
        ]
      }
    }

def make_quick_reply(text):
    options = re.findall(r'([1-9一二三四五][:：️⃣][^\n]+)', text)
    if not options: return None
    items = [QuickReplyButton(action=MessageAction(label=opt[:20], text=opt)) for opt in options[:13]]
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
        
        # JSONが含まれているかチェック
        json_match = re.search(r'\{.*\}', reply_text, re.DOTALL)
        
        if json_match:
            # JSON部分を解析してFlex Messageを送信
            try:
                data = json.loads(json_match.group())
                # JSON以外のテキスト部分があればそれも送る
                clean_text = reply_text.replace(json_match.group(), "").strip()
                messages = []
                if clean_text: messages.append(TextSendMessage(text=clean_text))
                
                flex_content = create_shipping_flex(data)
                messages.append(FlexSendMessage(alt_text="発送プランの提案", contents=flex_content))
                line_bot_api.reply_message(event.reply_token, messages)
                return
            except:
                pass # 解析失敗時は通常のテキスト送信へ
        
        # 通常のテキスト＋クイックリプライ送信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=make_quick_reply(reply_text))
        )
    except Exception as e:
        print(f"Error: {e}")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="エラーです。リセットして下さい"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
