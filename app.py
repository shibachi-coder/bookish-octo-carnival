import os, re, json
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

# --- 環境変数設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# 現在の日付取得
current_date_str = datetime.now().strftime("%Y年%m月%d日")

# --- 150点：日本郵便・専属コンシェルジュ プロンプト ---
SYSTEM_INSTRUCTION = f"""
あなたは日本郵便（郵便局）のサービスに精通した「発送コンシェルジュ」です。
本日（{current_date_str}）発送する場合の【日本郵便のサービス内での】最善策を案内してください。

# 厳守事項
1. **日本郵便以外のサービス（ヤマト、佐川、メルカリ便、他社運送会社など）は絶対に提案しないでください。**
2. **（アスタリスク2つ）による太字装飾は禁止です。
3. ユーザーへの返答に「JSON」や「形式」という単語を含めないでください。

# 取扱サービス（日本郵便のみ）
- 手紙（定形・定形外）、通常はがき、往復はがき
- スマートレター(210円)、クリックポスト(185円)
- レターパック（ライト430円、プラス600円）
- ゆうパケット(250円〜360円)、ゆうメール、ゆうパック(60〜170サイズ)
- オプション：速達、書留（一般・簡易）、特定記録

# 配送スピードの計算（本日発送基準）
- 翌日着：ゆうパック、レターパック、速達
- 2-3日後：クリックポスト、ゆうパケット
- 3-4日後：普通郵便（土日祝は配達休止を考慮して計算）

# 最終提案データ（末尾に必ず付与）
{{
  "cheapest": {{"name": "日本郵便のサービス名", "price": "金額", "date": "月/日"}},
  "fastest": {{"name": "日本郵便のサービス名", "price": "金額", "date": "月/日"}},
  "advice": "郵便局のサービスに基づいた一言"
}}
"""

model = genai.GenerativeModel(
    model_name="models/gemini-3-flash-preview", 
    system_instruction=SYSTEM_INSTRUCTION
)

chat_sessions = {}

def create_shipping_flex(data):
    """提案データを元に日本郵便カラーのFlex Messageを作成"""
    return {
      "type": "bubble",
      "header": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "🏣 日本郵便 発送ナビ", "weight": "bold", "color": "#ffffff", "size": "sm"}
        ], "backgroundColor": "#E60012" # 日本郵便の赤
      },
      "body": {
        "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": "最適なプランを郵便サービスから選定しました", "size": "xs", "color": "#888888", "margin": "md"},
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
        
        # 記号のクリーンアップ
        reply_text = reply_text.replace("**", "")
        reply_text = re.sub(r'【.*形式】', '', reply_text)
        
        # JSON抽出
        json_match = re.search(r'\{.*\}', reply_text, re.DOTALL)
        
        if json_match:
            try:
                data = json.loads(json_match.group())
                clean_text = reply_text.replace(json_match.group(), "").strip()
                messages = []
                if clean_text: messages.append(TextSendMessage(text=clean_text))
                
                flex_content = create_shipping_flex(data)
                messages.append(FlexSendMessage(alt_text="郵便発送プランの提案", contents=flex_content))
                line_bot_api.reply_message(event.reply_token, messages)
                return
            except: pass
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=make_quick_reply(reply_text))
        )
    except Exception as e:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="エラーが発生しました。リセットしてください。"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
