import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai
from datetime import datetime, timedelta

app = Flask(__name__)

# --- 1. 環境変数設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# 現在の日付を取得（配送日数の計算基準）
now = datetime.now()
current_date_str = now.strftime("%Y年%m月%d日")

# --- 2. 120点のためのシステムプロンプト ---
SYSTEM_INSTRUCTION = f"""
あなたは日本一親切な「郵便・発送コンシェルジュ」です。
本日（{current_date_str}）発送する場合の【最安】と【最短】をズバリ回答します。

# 120点のためのUX指針
1. 言葉を極限まで削り、視覚的（縦並び・絵文字）に伝える。
2. ユーザーに文字を打たせない。「番号」だけで進めるよう誘導する。
3. 住所は「154-0001」「世田谷区」「東京都」など、断片的な情報から送料を即断する。
4. 「リセット」や「最初から」と言われたら、すべて忘れて最初の質問に戻る。

# 知識ベース（日本郵便 全サービス対応）
- 手紙/はがき/スマートレター(210円)/クリックポスト(185円)
- レターパック(ライト430円/プラス600円)
- ゆうパケット(250円〜360円)/ゆうパック(サイズ・地域別)
- オプション：速達(+300円〜)、簡易書留(+350円)、特定記録(+210円)

# 到着日の計算ロジック
- 翌日着：ゆうパック、レターパック、速達
- 2-3日後：クリックポスト、ゆうパケット
- 3-4日後：普通郵便（土日祝はカウント外とする）

# 進行フロー
1. 【何を送る？】
   1️⃣ 書類・手紙
   2️⃣ 小物(本・服など)
   3️⃣ 箱・大型(ゆうパック)
   4️⃣ はがき
   5️⃣ その他(自由入力)

2. 【サイズ確認】
   選んだ番号に合わせて「厚さは3cm以内？」「重さは？」と1つずつ聞く。

3. 【どこへ送る？】
   「送り先の【都道府県】か【郵便番号】は？」と聞く。

4. 【最終提案フォーマット】
   ---
   💰【最安】[サービス名]
   └ 料金：[金額]円
   └ 到着：[月/日]頃

   🚀【最短】[サービス名]
   └ 料金：[金額]円
   └ 到着：[月/日]頃
   （※同じ場合は「最安と同じ」）

   💡【一言アドバイス】
   [例：対面受取がいいならプラス170円でレターパックプラスが安心です]
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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text
    
    # 「最初から」や「リセット」で会話をクリア
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
            TextSendMessage(text="すみません、うまく聞き取れませんでした。もう一度だけ入力してください。")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
