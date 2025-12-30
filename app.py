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

# --- 初期設定 ---
http_session = requests.Session()
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
line_bot_api.http_client.session = http_session
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))

# AIが途中で切れないよう、かつ端的に答える設定
generation_config = {
    "temperature": 0.4,       # 回答のブレを抑える
    "max_output_tokens": 1024, # 余裕を持って設定
}

# 本日の日付
current_date_str = datetime.now().strftime("%Y年%m月%d日")

SYSTEM_INSTRUCTION = f"""
あなたは日本郵便の専属コンシェルジュです。
本日（{current_date_str}）発送の最適解を【最短・端的な言葉】で提示します。

# 鉄則
- 1つの回答は「3行以内」を目標にし、極限まで短く。
- 文章は絶対に途中で切らず、最後まで完結させる。
- **（太字）は一切使用禁止。
- 選択肢は「1:項目」の形式で1行1つ書く。

# 最終提案の出力形式
提案時は必ず最後に以下のJSONデータだけを付与。

{{
  "cheapest": {{"name": "サービス名", "price": "金額", "date": "月/日"}},
  "fastest": {{"name": "サービス名", "price": "金額", "date": "月/日"}},
  "advice": "短い一言"
}}
"""

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview",
    system_instruction=SYSTEM_INSTRUCTION,
    generation_config=generation_config
)

chat_sessions = {}

def create_shipping_flex(data):
    """日本郵便ブランドのFlex Message"""
    return {
      "type": "bubble",
      "header": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "🏣 日本郵便 発送ナビ", "weight": "bold", "color": "#ffffff", "size": "sm"}
        ], "backgroundColor": "#E60012"
      },
      "body": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "最適なプランを選定しました", "size": "xs", "color": "#888888"},
          {"type": "separator", "margin": "md"},
          {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
            {"type": "text", "text": "💰 最安", "weight": "bold", "size": "md", "color": "#f1c40f"},
            {"type": "box", "layout": "horizontal", "contents": [
              {"type": "text", "text": data['cheapest']['name'], "flex": 4, "size": "sm", "weight": "bold"},
              {"type": "text", "text": f"¥{data['cheapest']['price']}", "flex": 2, "size": "sm", "align": "end"}
            ]},
            {"type": "text", "text": f"到着: {data['cheapest']['date']}頃", "size": "xs", "color": "#555555"}
          ]},
          {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
            {"type": "text", "text": "🚀 最短", "weight": "bold", "size": "md", "color": "#3498db"},
            {"type": "box", "layout": "horizontal", "contents": [
              {"type": "text", "text": data['fastest']['name'], "flex": 4, "size": "sm", "weight": "bold"},
              {"type": "text", "text": f"¥{data['fastest']['price']}", "flex": 2, "size": "sm", "align": "end"}
            ]},
            {"type": "text", "text": f"到着: {data['fastest']['date']}頃", "size": "xs", "color": "#555555"}
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
    """テキストから選択肢を抽出"""
    options = re.findall(r'([1-9一二三四五][:：️⃣][^\n]+)', text)
    if not options: return None
    items = [QuickReplyButton(action=MessageAction(label=opt[:20], text=opt)) for opt in options[:13]]
    return QuickReply(items=items)

def process_and_reply(user_id, user_text, reply_token):
    try:
        if user_id not in chat_sessions:
            chat_sessions[user_id] = model.start_chat(history=[])
        
        response = chat_sessions[user_id].send_message(user_text)
        reply_text = response.text.strip().replace("**", "")
        
        # 不要な「【JSON】」などの文字列を除去
        reply_text = re.sub(r'【.*】', '', reply_text)
        
        # JSONの抽出ロジック（後方一致で確実に取得）
        json_match = re.search(r'\{.*\}', reply_text, re.DOTALL)
        
        if json_match:
            try:
                data = json.loads(json_match.group())
                clean_text = reply_text.replace(json_match.group(), "").strip()
                
                messages = []
                if clean_text: 
                    messages.append(TextSendMessage(text=clean_text))
                
                flex_content = create_shipping_flex(data)
                messages.append(FlexSendMessage(alt_text="郵便発送の提案", contents=flex_content))
                line_bot_api.reply_message(reply_token, messages)
                return
            except: pass
        
        # 通常の返信（クイックリプライ付き）
        line_bot_api.reply_message(
            reply_token,
            TextSendMessage(text=reply_text, quick_reply=make_quick_reply(reply_text))
        )
    except Exception as e:
        print(f"Error: {e}")

@app.route("/")
def hello(): return "コンシェルジュ稼働中"

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
    
    if user_text in ["最初から", "リセット", "やり直し"]:
        if user_id in chat_sessions: del chat_sessions[user_id]
        reply_text = "リセットしました。\n送るものはどれですか？\n\n1:書類\n2:小物\n3:大型\n4:はがき"
        line_bot_api.reply_message(
            event.reply_token, 
            TextSendMessage(text=reply_text, quick_reply=make_quick_reply(reply_text))
        )
        return

    # 非同期処理でタイムアウトを回避
    threading.Thread(target=process_and_reply, args=(user_id, user_text, event.reply_token)).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
