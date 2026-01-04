import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# LINE公式アカウントの設定 (環境変数や直接入力)
LINE_CHANNEL_ACCESS_TOKEN = 'YOUR_CHANNEL_ACCESS_TOKEN'
LINE_CHANNEL_SECRET = 'YOUR_CHANNEL_SECRET'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ユーザーの状態を一時的に保存する辞書
# 実際の実装ではRedisやDBを推奨
user_sessions = {}

# 質問の定義
QUESTIONS = [
    "こんにちは！発送の最適化をお手伝いします。\nまずは送りたいものの種類を番号で選んでください。\n1) はがき\n2) 手紙\n3) 小さな荷物（3辺90cm、4kg以内）\n4) 大きな荷物\n5) 日本以外への送付\n6) その他",
    "承知いたしました。次に、荷物の【縦、横、高さの合計（cm）】を教えてください。",
    "ありがとうございます。次に、【重さ】を教えてください。",
    "承知いたしました。次に、【発送元の住所（または郵便番号）】を教えてください。",
    "ありがとうございます。次に、【お届け先の住所（または郵便番号）】を教えてください。",
    "最後に、追跡の有無や速達希望など、その他条件はありますか？（なければ「なし」）"
]

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
    text = event.message.text

    # セッションの初期化
    if user_id not in user_sessions:
        user_sessions[user_id] = {"step": 0, "answers": []}
        reply_text = QUESTIONS[0]
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        return

    session = user_sessions[user_id]
    current_step = session["step"]

    # 回答を保存
    session["answers"].append(text)
    
    # 次のステップへ
    next_step = current_step + 1
    session["step"] = next_step

    if next_step < len(QUESTIONS):
        # 次の質問を送信
        reply_text = f"承知いたしました。\n\n{QUESTIONS[next_step]}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
    else:
        # すべての回答が揃ったので診断結果を表示
        ans = session["answers"]
        # ここで簡易的なロジック判定
        result = (
            "全ての情報を確認いたしました！最適な方法をご案内します。\n\n"
            "💰 【最安】クリックポスト（185円）\n"
            "⚡ 【最速】レターパックプラス（600円）\n\n"
            "※実際の料金はサイズにより変動する場合があります。詳細は窓口でご確認ください。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=result))
        # セッションをリセット
        del user_sessions[user_id]

if __name__ == "__main__":
    app.run(port=5000)
