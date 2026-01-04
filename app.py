import os
import sys
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# Renderの環境変数からトークンを取得
channel_secret = os.getenv('LINE_CHANNEL_SECRET')
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')

if channel_secret is None or channel_access_token is None:
    print('Specify LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN as environment variables.')
    sys.exit(1)

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

# ユーザーごとの進捗を保存（メモリ保存のためサーバー再起動でリセットされます）
user_state = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['x-line-signature']
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

    # ユーザー状態の取得（なければ初期化）
    if user_id not in user_state:
        user_state[user_id] = {"step": 1, "data": {}}
    
    state = user_state[user_id]

    # --- 対話フローロジック ---
    if state["step"] == 1:
        reply = ("こんにちは！郵便物流ナビです。\n送りたいものの種類を番号で選んでください。\n\n"
                 "1) はがき\n2) 手紙\n3) 小さな荷物\n4) 大きな荷物\n5) 海外発送\n6) その他")
        state["step"] = 2

    elif state["step"] == 2:
        state["data"]["type"] = text
        reply = f"【{text}】ですね。次に、荷物の「縦」の長さをcmで教えてください。"
        state["step"] = 3

    elif state["step"] == 3:
        state["data"]["length"] = text
        reply = "ありがとうございます。次に「横」の長さをcmで教えてください。"
        state["step"] = 4

    elif state["step"] == 4:
        state["data"]["width"] = text
        reply = "ありがとうございます。次に「厚さ（高さ）」をcmで教えてください。"
        state["step"] = 5

    elif state["step"] == 5:
        state["data"]["height"] = text
        reply = "ありがとうございます。次に「重さ」を教えてください（例: 200g）。"
        state["step"] = 6

    elif state["step"] == 6:
        state["data"]["weight"] = text
        reply = "ありがとうございます。お届け先の「郵便番号」または「都道府県」を教えてください。"
        state["step"] = 7

    elif state["step"] == 7:
        state["data"]["dest"] = text
        reply = "最後に、追跡希望などはありますか？（なければ「なし」）"
        state["step"] = 8

    elif state["step"] == 8:
        # 本来はここで判定ロジックを走らせます
        res = state["data"]
        reply = (f"【診断結果】\n種類:{res['type']}\nサイズ:{res['length']}x{res['width']}x{res['height']}\n"
                 f"重さ:{res['weight']}\n宛先:{res['dest']}\n\n"
                 "この条件では「クリックポスト(185円)」が最安です！")
        # 状態をリセット
        user_state[user_id] = {"step": 1, "data": {}}

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
