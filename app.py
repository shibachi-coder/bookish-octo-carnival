import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 1. 環境変数設定 ---
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# --- 2. システムプロンプト ---
SYSTEM_INSTRUCTION = """
あなたは「日本郵便・発送最適化エージェント」です。
2024年10月1日改定後の最新料金体系に基づき、オプション（速達・書留等）を含めた最安・最適な発送方法を提案します。

# 2024年10月〜の主要料金データ
- 定形郵便: 50gまで一律 110円
- 通常はがき: 85円
- 定形外郵便（規格内）: 50g 140円 / 100g 180円 / 150g 270円 / 250g 320円 / 500g 510円 / 1kg 750円
- スマートレター: 210円
- レターパックライト: 430円
- レターパックプラス: 600円
- クリックポスト: 185円（要事前決済・ラベル印刷）
- ゆうパケット: 厚さにより変動（1cm 250円 / 2cm 310円 / 3cm 360円）

# 厳守ルール
1. **1発言1質問の徹底**: いかなる理由があっても、一度に複数の情報を求めてはいけません。
2. **逐次承認**: ユーザーの回答に対し「承知いたしました。〇〇ですね」と受け止めてから次の質問をします。
3. **オプションの確認**: サイズ・重さの確認後、必ず「速達や書留（補償）、追跡などのオプション希望」があるかを確認します。

# 質問フロー
1. 内容物 [1]〜[9]
2. 縦
3. 横
4. 厚さ
5. 重さ
6. オプション確認
7. 発送元・先（必要な場合）
8. 最終提案
"""

# --- 3. モデルの初期化と診断 ---
try:
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash", 
        system_instruction=SYSTEM_INSTRUCTION
    )
    # 診断用：利用可能なモデルをログに出力
    print("--- 利用可能なモデルの確認を開始 ---")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"利用可能モデル: {m.name}")
except Exception as e:
    print(f"初期設定エラー: {e}")

# 会話履歴の保持
chat_sessions = {}

# --- 4. ルーティング ---

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

# --- 5. メッセージ処理 ---

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    user_text = event.message.text
    print(f"ユーザーからのメッセージ: {user_text}")
    
    # セッションの開始/取得
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        # Geminiに送信
        response = chat.send_message(user_text)
        
        if not response.text:
            reply_text = "AIから回答が得られませんでした。もう一度試してください。"
        else:
            reply_text = response.text.strip()
        
        print(f"Geminiの回答: {reply_text}")

        # LINEへ返信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        print(f"通信エラー詳細: {e}")
        # LINE側へエラーを通知
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="現在AIと通信できません。時間を置いてから再度お試しください。")
        )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
