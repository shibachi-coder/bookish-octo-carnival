import streamlit as st

# アプリのタイトル
st.title("郵便物流ナビ 📮")
st.caption("日本郵便・発送最適化エージェント")

# セッション状態（会話の進捗）の初期化
if "step" not in st.session_state:
    st.session_state.step = 1
    st.session_state.data = {}

def next_step():
    st.session_state.step += 1

# 1発言1質問の徹底ロジック
if st.session_state.step == 1:
    st.write("こんにちは！発送の最適化をお手伝いします。")
    option = st.selectbox(
        "送りたいものの種類を選んでください：",
        ["選択してください", "はがき", "手紙", "小さな荷物（3辺90cm以内）", "大きな荷物", "海外への送付", "その他"],
        key="type"
    )
    if option != "選択してください":
        if st.button("次へ"):
            st.session_state.data["type"] = option
            next_step()
            st.rerun()

elif st.session_state.step == 2:
    st.write(f"【{st.session_state.data['type']}】ですね。承知いたしました。")
    size = st.text_input("荷物のサイズ（縦・横・高さの合計/cm）を教えてください：")
    if size:
        if st.button("次へ"):
            st.session_state.data["size"] = size
            next_step()
            st.rerun()

elif st.session_state.step == 3:
    weight = st.text_input("荷物の重さ（gまたはkg）を教えてください：")
    if weight:
        if st.button("次へ"):
            st.session_state.data["weight"] = weight
            next_step()
            st.rerun()

elif st.session_state.step == 4:
    origin = st.text_input("発送元の郵便番号または都道府県を教えてください：")
    if origin:
        if st.button("次へ"):
            st.session_state.data["origin"] = origin
            next_step()
            st.rerun()

elif st.session_state.step == 5:
    dest = st.text_input("お届け先の郵便番号または都道府県を教えてください：")
    if dest:
        if st.button("次へ"):
            st.session_state.data["dest"] = dest
            next_step()
            st.rerun()

elif st.session_state.step == 6:
    condition = st.text_input("その他、追跡の有無や速達希望など条件はありますか？（なければ「なし」）")
    if condition:
        if st.button("診断結果を表示する"):
            st.session_state.data["condition"] = condition
            next_step()
            st.rerun()

elif st.session_state.step == 7:
    st.success("全ての情報を確認しました。最適な配送方法をご案内します。")
    st.json(st.session_state.data)
    
    # ここにロジックに基づいた提案内容を表示
    st.write("### 提案：クリックポスト（最安） / レターパック（最速）")
    
    if st.button("最初からやり直す"):
        st.session_state.step = 1
        st.session_state.data = {}
        st.rerun()
