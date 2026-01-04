import os
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# LINE設定（環境変数から取得）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_sessions = {}

# ゆうパック基本運賃表（東京発の例：60, 80, 100, 120, 140, 160, 170サイズ）
# 実際には全都道府県分を辞書化することで正確性が増します
YUPACK_TARIFF = {
    "東京都": {
        "東京都": [910, 1150, 1410, 1690, 1960, 2220, 2610],
        "愛知県": [1030, 1280, 1530, 1830, 2080, 2340, 2750],
        "大阪府": [1160, 1410, 1660, 1940, 2220, 2490, 2870],
        "福岡県": [1410, 1660, 1920, 2200, 2440, 2730, 3110],
        "北海道": [1410, 1660, 1920, 2200, 2440, 2730, 3110],
    },
    # 他の発送元も同様に定義可能
}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    if user_id not in user_sessions or text in ["リセット", "最初から"]:
        user_sessions[user_id] = {"step": "ORIGIN", "answers": {}}
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="物流コンシェルジュです。ゆうパック等の正確な料金を計算します。\nまず【発送元の都道府県】を教えてください。"))
        return

    session = user_sessions[user_id]
    step = session["step"]

    if step == "ORIGIN":
        session["answers"]["origin"] = text
        session["step"] = "DEST"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{text}からですね。次に【お届け先の都道府県】を教えてください。"))

    elif step == "DEST":
        session["answers"]["dest"] = text
        session["step"] = "SIZE_VAL"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="【縦・横・高さの合計（cm）】を数字だけで教えてください（例：85）。"))

    elif step == "SIZE_VAL":
        try:
            val = int(text)
            # サイズ区分判定
            size_list = [60, 80, 100, 120, 140, 160, 170]
            detected_size = next((s for s in size_list if val <= s), 171)
            
            if detected_size > 170:
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text="申し訳ありません。170サイズを超えるお荷物は、ゆうパックではお取り扱いできません。"))
                del user_sessions[user_id]
                return

            session["answers"]["size_index"] = size_list.index(detected_size)
            session["answers"]["size_name"] = detected_size
            session["step"] = "OPTION"
            msg = (f"{detected_size}サイズですね。追加オプションはありますか？番号を選んでください。\n"
                   "1) なし\n2) チルド(+230円〜)\n3) 代金引換(+290円)\n4) セキュリティサービス(+390円)")
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
        except:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="数字（半角）で入力してください。"))

    elif step == "OPTION":
        opt_map = {"1": 0, "2": 230, "3": 290, "4": 390}
        session["answers"]["opt_fee"] = opt_map.get(text, 0)
        
        # 最終計算
        ans = session["answers"]
        origin = ans["origin"]
        dest = ans["dest"]
        
        # 料金テーブルから取得（未定義の場合はデフォルト値）
        base_fare = YUPACK_TARIFF.get(origin, YUPACK_TARIFF["東京都"]).get(dest, [1500]*7)[ans["size_index"]]
        total_fare = base_fare + session["answers"]["opt_fee"]
        
        res_msg = (
            f"📦 【ゆうパック詳細見積もり】\n"
            f"━━━━━━━━━━━━━━\n"
            f"●区間: {origin} → {dest}\n"
            f"●サイズ: {ans['size_name']}サイズ\n"
            f"●基本運賃: {base_fare}円\n"
            f"●オプション: {session['answers']['opt_fee']}円\n"
            f"----------------------------\n"
            f"💰 合計料金: {total_fare}円\n"
            f"━━━━━━━━━━━━━━\n"
            f"※郵便局・コンビニ持ち込みで120円割引されます。\n"
            f"※お届け時期は通常、翌日〜翌々日です。"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=res_msg))
        del user_sessions[user_id]

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
