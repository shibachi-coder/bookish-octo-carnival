import os
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, 
    QuickReply, QuickReplyButton, MessageAction
)

app = Flask(__name__)

# LINE設定
LINE_CHANNEL_ACCESS_TOKEN = 'YOUR_CHANNEL_ACCESS_TOKEN'
LINE_CHANNEL_SECRET = 'YOUR_CHANNEL_SECRET'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_sessions = {}

# --- 配送リードタイム・マトリックス (簡易版) ---
# 0: 同一・近隣県, 1: 翌日/翌々日圏, 2: 遠隔地(九州・北海道等), 3: 離島
LEAD_TIME_MATRIX = {
    "東京都": {"愛知県": 1, "大阪府": 1, "福岡県": 2, "北海道": 2, "東京都": 0},
    "愛知県": {"東京都": 1, "大阪府": 0, "福岡県": 1, "北海道": 2, "愛知県": 0},
    # 必要に応じて全47都道府県の距離区分を定義可能
}

def get_yn_menu():
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="はい", text="はい")),
        QuickReplyButton(action=MessageAction(label="いいえ", text="いいえ"))
    ])

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

    if user_id not in user_sessions or text in ["リセット", "最初から"]:
        user_sessions[user_id] = {"step": "KIND", "answers": {}}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="発送コンシェルジュです。まずは種類を教えてください。\n1)はがき 2)手紙 3)小さな荷物 4)大きな荷物"))
        return

    session = user_sessions[user_id]
    step = session["step"]

    # 1. 種類、2. サイズ、3. 重さ、4. 発送元、5. お届け先 の順に取得（逐次確認）
    if step == "KIND":
        session["answers"]["kind"] = text
        session["step"] = "SIZE"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="承知いたしました。3辺の合計サイズ(cm)を教えてください。"))

    elif step == "SIZE":
        session["answers"]["size"] = text
        session["step"] = "WEIGHT"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="重さを教えてください。"))

    elif step == "WEIGHT":
        session["answers"]["weight"] = text
        session["step"] = "ORIGIN"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="【発送元】の都道府県を教えてください。"))

    elif step == "ORIGIN":
        session["answers"]["origin"] = text
        session["step"] = "DEST"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="【お届け先】の都道府県を教えてください。"))

    elif step == "DEST":
        session["answers"]["dest"] = text
        session["step"] = "Q_SPEED"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="急ぎ（速達・ゆうパック等）を希望しますか？", quick_reply=get_yn_menu()))

    elif step == "Q_SPEED":
        session["answers"]["is_fast"] = (text == "はい")
        session["step"] = "Q_TODAY"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="本日中に発送（ポスト投函または窓口持込）されますか？", quick_reply=get_yn_menu()))

    elif step == "Q_TODAY":
        session["answers"]["is_today"] = (text == "はい")
        ans = session["answers"]

        # --- マトリックスを使用した日数計算 ---
        dist_level = LEAD_TIME_MATRIX.get(ans["origin"], {}).get(ans["dest"], 1)
        
        # 基本日数の設定
        if ans["is_fast"]:
            # 速達/ゆうパック系
            min_days = 1 if dist_level <= 1 else 2
            comment = "速達優先ルートで配送されます。"
        else:
            # 普通郵便/クリックポスト系（土日祝の配達休止を考慮）
            min_days = 2 + dist_level
            comment = "普通郵便は土日祝の配達がないため、週末を挟む場合はさらに日数を要します。"

        base_date = datetime.now() if ans["is_today"] else datetime.now() + timedelta(days=1)
        arrival_date = base_date + timedelta(days=min_days)

        res = (
            f"【診断結果】\n"
            f"📍 {ans['origin']} → {ans['dest']}\n"
            f"🗓 最速到着目安：{arrival_date.strftime('%m月%d日')} 頃\n\n"
            f"💡 補足：{comment}\n"
            f"※夕方以降の発送や窓口の受付時間を過ぎた場合、翌日受付扱いとなります。"
        )
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res))
        del user_sessions[user_id]

if __name__ == "__main__":
    app.run(port=5000)
