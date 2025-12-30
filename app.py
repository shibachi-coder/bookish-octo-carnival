import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# --- 1. 環境変数設定 ---
# RenderのDashboard > Environmentで設定した値を取得します
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
genai.configure(api_key=GOOGLE_API_KEY)

# --- 2. 最新の料金体系を組み込んだシステムプロンプト ---
SYSTEM_INSTRUCTION = """
あなたは「日本郵便・発送最適化エージェント」です。
2024年10月1日改定後の最新料金体系に基づき、オプション（速達・書留等）を含めた最安・最適な発送方法を提案します。

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
1. **1発言1質問の徹底**: いかなる理由があっても、一度に複数の情報を求めてはいけません。
2. **逐次承認**: ユーザーの回答に対し「承知いたしました。〇〇ですね」と受け止めてから次の質問をします。
3. **オプションの確認**: サイズ・重さの確認後、必ず「速達や書留（補償）、追跡などのオプション希望」があるかを確認します。

# 質問フロー (1つずつ質問すること)
1. 内容物の確認 ([1]〜[9]の選択肢を提示)
2. サイズ（縦）
3. サイズ（横）
4. サイズ（厚さ）
5. 重さ
6. オプション希望の確認（急ぎ、補償、追跡の有無）
7. 発送元・先の都道府県（ゆうパックが必要な場合のみ）
8. 最終提案
"""

# 修正：モデルの初期化をより詳細に設定します
try:
    # 2025年現在の標準的な安定版モデル名を指定
    model = genai.GenerativeModel(
        model_name="gemini-1.5-flash", 
        system_instruction=SYSTEM_INSTRUCTION
    )
    # 診断用：起動時に利用可能なモデルをログに出力する（任意）
    print("--- 利用可能なモデルの確認を開始 ---")
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"利用可能モデル: {m.name}")
except Exception as e:
    print(f"モデル初期化エラー: {e}")

# --- (中略：hello, callback関数はそのまま) ---

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # (中略：user_id取得などはそのまま)
    
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        # 修正：最新のSDKに合わせて明示的にコンテンツを生成
        response = chat.send_message(user_text)
        
        # エラーチェック（responseが空でないか）
        if not response.text:
            reply_text = "AIから有効な回答が得られませんでした。もう一度試してください。"
        else:
            reply_text = response.text.strip()
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        print(f"Gemini通信エラー: {e}")
        # LINE側へエラーを通知
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="現在、AIとの通信に問題が発生しています。しばらく時間を置いてから再度お試しください。")
        )

# --- 3. ルーティング設定 ---

# Renderの稼働確認用
@app.route("/")
def hello():
    return "郵便物流ナビ：サーバー稼働中です！"

# LINE Webhook用
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# --- 4. メッセージ処理ロジック ---

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # (中略：user_id取得などはそのまま)
    
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        # 修正：最新のSDKに合わせて明示的にコンテンツを生成
        response = chat.send_message(user_text)
        
        # エラーチェック（responseが空でないか）
        if not response.text:
            reply_text = "AIから有効な回答が得られませんでした。もう一度試してください。"
        else:
            reply_text = response.text.strip()
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    except Exception as e:
        print(f"Gemini通信エラー: {e}")
        # LINE側へエラーを通知
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="現在、AIとの通信に問題が発生しています。しばらく時間を置いてから再度お試しください。")
        )
    
    # セッションの開始
    if user_id not in chat_sessions:
        chat_sessions[user_id] = model.start_chat(history=[])
    
    chat = chat_sessions[user_id]

    try:
        # Geminiにメッセージを送信
        response = chat.send_message(user_text)
        reply_text = response.text.strip()
        print(f"Geminiの回答: {reply_text}")
        
        # LINEに返信
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
        print("LINEへの返信に成功しました")

    except Exception as e:
        print(f"エラーが発生しました: {e}")
        # エラー発生時のみ、ユーザーへ通知する
        try:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="申し訳ありません、処理中にエラーが起きました。もう一度入力してください。")
            )
        except:
            print("エラーメッセージの送信にも失敗しました")

if __name__ == "__main__":
    # RenderなどのPaaSでは環境変数のPORTを使用するため8000はローカル用
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)

