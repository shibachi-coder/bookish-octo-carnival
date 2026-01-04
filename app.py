import os
import sys
import logging
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)
app.logger.setLevel(logging.INFO)

# --- 環境変数の読み込み ---
# 直接書き込む場合は 'YOUR_...' を消して実際の文字列を入れてください
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', 'YOUR_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET', 'YOUR_CHANNEL_SECRET')

# 起動時にログを出力（app定義の後に移動）
app.logger.info(f"Access Token Length: {len(LINE_CHANNEL_ACCESS_TOKEN) if LINE_CHANNEL_ACCESS_TOKEN else 'EMPTY'}")
app.logger.info(f"Channel Secret Length: {len(LINE_CHANNEL_SECRET) if LINE_CHANNEL_SECRET else 'EMPTY'}")

if LINE_CHANNEL_ACCESS_TOKEN == 'YOUR_CHANNEL_ACCESS_TOKEN':
    app.logger.warning("警告: LINEのトークンがデフォルト値のままです。")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_sessions = {}

# 配送距離マトリックス
LEAD_TIME_MATRIX = {
    "東京都": {"愛知県": 1, "大阪府": 1, "福岡県": 2, "北海道": 2},
    "愛知県": {"東京都": 1, "大阪府": 0, "福岡県": 1, "北海道": 2},
}

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.error("署名検証に失敗しました。")
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text.strip()

    # --- セッション開始：ご挨拶 ---
    if user_id not in user_sessions or text in ["リセット", "最初から"]:
        user_sessions[user_id] = {"step": "KIND", "answers": {}}
        msg = ("こんにちは。日本郵便の物流コンシェルジュでございます。\n"
               "お客様の大切なお荷物に、最も適した発送方法をご提案させていただきます。\n\n"
               "まずは、お送りいただくものの種類を教えていただけますでしょうか？\n\n"
               "1) はがき\n2) 手紙\n3) 小さな荷物\n4) 大きな荷物\n5) 海外発送\n6) その他")
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
        return

    session = user_sessions[user_id]
    step = session["step"]

    # --- 逐次確認と次の質問 ---
    if step == "KIND":
        mapping = {"1": "はがき", "2": "手紙", "3": "小さな荷物", "4": "大きな荷物", "5": "海外"}
        kind = mapping.get(text)
        
        if text == "6" or kind is None:
            session["answers"]["kind"] = text if kind is None else "その他"
            msg = f"「{text}」でございますね。承知いたしました。\nそれでは、梱包を含めた【縦・横・高さの合計（cm）】を教えていただけますか？"
        else:
            session["answers"]["kind"] = kind
            msg = f"「{kind}」をお送りになるのですね。ありがとうございます。\nそれでは、お荷物の【縦・横・高さの合計（cm）】を教えていただけますでしょうか。"
        
        session["step"] = "SIZE"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))

    elif step == "SIZE":
        session["answers"]["size"] = text
        session["step"] = "WEIGHT"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"サイズは {text}cm ですね。ありがとうございます。\n続きまして、おおよその【重さ】を教えていただけますでしょうか。"))

    elif step == "WEIGHT":
        session["answers"]["weight"] = text
        session["step"] = "ORIGIN"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="重さを確認いたしました。\n次に、お荷物を差し出される【発送元の都道府県】を教えていただけますか？"))

    elif step == "ORIGIN":
        session["answers"]["origin"] = text
        session["step"] = "DEST"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"{text}から発送されるのですね。承知いたしました。\nそれでは、【お届け先の都道府県】を教えていただけますでしょうか。"))

    elif step == "DEST":
        session["answers"]["dest"] = text
        session["step"] = "Q_SPEED"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=f"お届け先は {text} でございますね。\nお急ぎの配送（速達や翌日配達など）をご希望されますでしょうか？\n「はい」か「いいえ」でお答えください。"))

    elif step == "Q_SPEED":
        session["answers"]["is_fast"] = (text == "はい")
        session["step"] = "Q_TODAY"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="承知いたしました。最後に、お荷物は【本日中】に発送（投函または窓口へのお持ち込み）をご予定でしょうか？"))

    elif step == "Q_TODAY":
        is_today = (text == "はい")
        ans = session["answers"]
        
        # 到着予測ロジック
        dist = LEAD_TIME_MATRIX.get(ans["origin"], {}).get(ans["dest"], 1)
        base_days = 1 if ans["is_fast"] else (2 + dist)
        send_date = datetime.now() if is_today else datetime.now() + timedelta(days=1)
        arrival_date = send_date + timedelta(days=base_days)
        
        proposal = (
            f"お客様のご要望に合わせて、最適なプランをご案内いたします。\n\n"
            f"📦 【おすすめの発送方法】\n"
        )
        
        if ans["is_fast"]:
            proposal += "「ゆうパック」または「レターパックプラス」が最適でございます。速達並みのスピードで、追跡・対面受取も可能でございます。"
        else:
            proposal += "「クリックポスト」や「定形外郵便」がお安くお送りいただけます。追跡が必要であればクリックポストをご検討ください。"

        proposal += (
            f"\n\n🗓 【お届け時期の目安】\n"
            f"{arrival_date.strftime('%m月%d日')} 頃の到着を見込んでおります。\n\n"
            f"💡 【コンシェルジュより補足】\n"
        )
        
        if not ans["is_fast"]:
            proposal += "普通郵便の場合、土・日・休日の配達が行われませんため、週末を挟む場合はお届けまでにお時間をいただくことがございます。"
        else:
            proposal += "速達扱いのサービスは、土日祝日も休まずお届けいたしますのでご安心ください。"

        proposal += "\n\nまた何かお手伝いできることがあれば、いつでも「最初から」とお声がけくださいませ。"
        
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=proposal))
        del user_sessions[user_id]

if __name__ == "__main__":
    # Renderの環境に合わせたポート指定
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
