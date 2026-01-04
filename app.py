import os
import sys
import logging # 追加
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)
# ログ出力を有効にする
app.logger.setLevel(logging.DEBUG)

channel_secret = os.getenv('LINE_CHANNEL_SECRET')
channel_access_token = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')

# 起動時に環境変数が読み込めているかログに出す（トークン自体は伏せる）
if not channel_secret or not channel_access_token:
    app.logger.error("環境変数が設定されていません！")
else:
    app.logger.info("環境変数の読み込みに成功しました。")

line_bot_api = LineBotApi(channel_access_token)
handler = WebhookHandler(channel_secret)

user_state = {}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('x-line-signature')
    body = request.get_data(as_text=True)
    
    app.logger.debug(f"Request body: {body}") # 届いた内容をログに出す

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("署名検証に失敗しました。Channel Secretが正しいか確認してください。")
        abort(400)
    except Exception as e:
        app.logger.error(f"予期せぬエラー: {e}")
        abort(500)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    # (中身は以前のコードと同じ)
    user_id = event.source.user_id
    text = event.message.text
    
    if user_id not in user_state:
        user_state[user_id] = {"step": 1, "data": {}}
    
    state = user_state[user_id]
    
    # 応答メッセージ作成
    if state["step"] == 1:
        reply = "こんにちは！郵便物流ナビです。\n番号を選んでください。"
        state["step"] = 2
    else:
        reply = f"「{text}」を受け取りました。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
