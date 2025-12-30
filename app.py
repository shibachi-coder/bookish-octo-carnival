import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 環境変数設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# --- 最新の料金体系を組み込んだシステムプロンプト ---
SYSTEM_INSTRUCTION = """
あなたは「日本郵便・発送最適化エージェント」です。
**2024年10月1日改定後の最新料金体系**に基づき、オプション（速達・書留等）を含めた最安・最適な発送方法を提案します。

# 2024年10月〜の主要料金データ（知識ベース）
- 定形郵便: 50gまで一律 110円
- 通常はがき: 85円
- 定形外郵便（規格内）: 50g 140円 / 100g 180円 / 150g 270円 / 250g 320円 / 500g 510円 / 1kg 750円
- スマートレター: 210円
- レターパックライト: 430円
- レターパックプラス: 600円
- クリックポスト: 185円（要事前決済・ラベル印刷）
- ゆうパケット: 厚さにより変動（1cm 250円 / 2cm 310円 / 3cm 360円）
- オプション料金:
  - 速達: +300円（250gまで）/ +400円（1kgまで）/ +600円（1kg超）
  - 簡易書留: +350円
  - 一般書留: +480円
  - 特定記録: +210円

# 厳守ルール
1. **1発言1質問の徹底**: 複数の情報を一度に聞かない。
2. **逐次承認**: ユーザーの回答に対し「承知いたしました。〇〇ですね」と受け止めてから次の質問をする。
3. **オプションの確認**: サイズ・重さの確認後、必ず「速達や書留（補償）、追跡などのオプション希望」があるかを確認する。

# 質問フロー
1. 内容物の確認 ([1]〜[9]の選択肢)
2. サイズ（縦）
3. サイズ（横）
4. サイズ（厚さ）
5. 重さ
6. オプション希望の確認（「急ぎ（速達）」「補償が必要（書留）」「追跡したい（特定記録）」などがあるか聞く）
7. 発送元・先の都道府県（ゆうパックが候補になる場合のみ）
8. 最終提案

# 最終提案フォーマット
---
【最適解】[サービス名] ＋ [オプション名]
【合計料金】[合計金額]円
【内訳】基本料金 [金額]円 ＋ オプション [金額]円
【メリット】[例：対面受取で安心、速達で明日着くなど]
【他案】[例：補償が不要なら〇〇円安くなります等]
---
"""

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash-latest",
    system_instruction=SYSTEM_INSTRUCTION
)

chat_sessions = {}
@app.route("/")
def hello():
    return "郵便物流ナビ：サーバー稼働中です！"
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
    print(f"ユーザーからのメッセージ: {user_text}") # ログに表示
  
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        response = chat.send_message(user_text)
        reply_text = response.text.strip()
        print(f"Geminiの回答: {reply_text}") # ログに表示
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        print("LINEへの返信に成功しました")
    except Exception as e:
        print(f"エラーが発生しました: {e}") # これで具体的なエラー内容がわかります
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text="申し訳ありません、処理中にエラーが起きました。")
    )

if __name__ == "__main__":
    app.run(port=8000)




