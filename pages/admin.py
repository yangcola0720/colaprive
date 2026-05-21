"""
🔧 管理後台 - 題庫管理
"""

import streamlit as st
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.sheets import is_configured, load_questions_from_sheets, save_questions_to_sheets

# ── 密碼保護 ──────────────────────────────────────────────
def check_password():
    if st.session_state.get("admin_authed"):
        return True

    st.markdown("## 🔒 管理後台")
    pwd = st.text_input("請輸入管理密碼", type="password", key="admin_pwd_input")
    if st.button("登入", use_container_width=True):
        correct = st.secrets.get("admin", {}).get("password", "admin1234")
        if pwd == correct:
            st.session_state["admin_authed"] = True
            st.rerun()
        else:
            st.error("密碼錯誤！")
    return False

if not check_password():
    st.stop()

# ── 主介面 ────────────────────────────────────────────────
st.markdown("## 🔧 題庫管理後台")

if not is_configured():
    st.error(
        "⚠️ **尚未設定 Google Sheets 連線**\n\n"
        "請先完成 Streamlit Secrets 設定（參考設定說明）。"
    )
    st.stop()

# ── 讀取現有題庫 ──────────────────────────────────────────
with st.spinner("讀取題庫中…"):
    raw = load_questions_from_sheets()

# 轉成 DataFrame 方便編輯
def questions_to_df(questions: list[dict]) -> pd.DataFrame:
    rows = []
    for q in questions:
        opts = q.get("opts", ["", "", "", ""])
        rows.append({
            "題目":   q.get("q", ""),
            "選項 A": opts[0] if len(opts) > 0 else "",
            "選項 B": opts[1] if len(opts) > 1 else "",
            "選項 C": opts[2] if len(opts) > 2 else "",
            "選項 D": opts[3] if len(opts) > 3 else "",
            "正確答案 (0=A 1=B 2=C 3=D)": int(q.get("ans", 0)),
            "中文解析": q.get("exp", ""),
        })
    return pd.DataFrame(rows)

def df_to_questions(df: pd.DataFrame) -> list[dict]:
    questions = []
    for _, row in df.iterrows():
        questions.append({
            "q":    row["題目"],
            "opts": [row["選項 A"], row["選項 B"], row["選項 C"], row["選項 D"]],
            "ans":  int(row["正確答案 (0=A 1=B 2=C 3=D)"]),
            "exp":  row["中文解析"],
        })
    return questions

df = questions_to_df(raw)

st.info(f"📚 目前共有 **{len(df)}** 道題目")

# ── 題目編輯表格 ──────────────────────────────────────────
st.markdown("### ✏️ 編輯題目")
st.caption("可直接在表格內點擊修改。新增一列 = 新增一題。勾選最左側方塊可刪除。")

edited_df = st.data_editor(
    df,
    num_rows="dynamic",         # 允許新增 / 刪除列
    use_container_width=True,
    column_config={
        "題目": st.column_config.TextColumn("題目", width="large"),
        "選項 A": st.column_config.TextColumn("選項 A", width="medium"),
        "選項 B": st.column_config.TextColumn("選項 B", width="medium"),
        "選項 C": st.column_config.TextColumn("選項 C", width="medium"),
        "選項 D": st.column_config.TextColumn("選項 D", width="medium"),
        "正確答案 (0=A 1=B 2=C 3=D)": st.column_config.NumberColumn(
            "正確答案", min_value=0, max_value=3, step=1, width="small"
        ),
        "中文解析": st.column_config.TextColumn("中文解析", width="large"),
    },
    hide_index=True,
    key="question_editor",
)

# ── 儲存按鈕 ─────────────────────────────────────────────
st.divider()
col1, col2 = st.columns([3, 1])
with col1:
    st.caption("修改完成後按「儲存題庫」，變更會立即生效，遊戲頁面下次載入就會用新題目。")
with col2:
    if st.button("💾 儲存題庫", type="primary", use_container_width=True):
        # 過濾掉題目欄位空白的列
        clean = edited_df[edited_df["題目"].str.strip().astype(bool)].copy()
        if clean.empty:
            st.warning("題目不能全部為空！")
        else:
            with st.spinner("儲存中…"):
                save_questions_to_sheets(df_to_questions(clean))
            st.success(f"✅ 已儲存 {len(clean)} 道題目！")
            st.balloons()

# ── 登出 ─────────────────────────────────────────────────
st.divider()
if st.button("🚪 登出", use_container_width=False):
    st.session_state["admin_authed"] = False
    st.rerun()
