"""
英文搶答計分系統 - 整合自 yangcola0720/english-quiz
題庫優先從 Google Sheets 讀取，若未設定則讀本地 questions.json
"""

import streamlit as st
import streamlit.components.v1 as components
import json
import sys
import os
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from utils.sheets import is_configured, load_questions_from_sheets

ASSETS = Path("assets/english_quiz")

# ── 讀取題庫（Google Sheets 優先） ───────────────────────
def load_questions() -> list:
    if is_configured():
        try:
            return load_questions_from_sheets()
        except Exception as e:
            st.warning(f"Google Sheets 讀取失敗，改用本地題庫：{e}")

    # Fallback：讀本地 JSON
    path = ASSETS / "questions.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            st.warning(f"讀取 questions.json 失敗：{e}")
    return []

questions = load_questions()

if not questions:
    st.error("⚠️ 找不到題庫，請先在管理後台設定 Google Sheets 或確認 questions.json 存在。")
    st.stop()

# ── 讀取遊戲 HTML 並注入題庫 ─────────────────────────────
@st.cache_data
def load_game_html() -> str:
    path = ASSETS / "game_streamlit.html"
    if not path.exists():
        st.error("找不到 assets/english_quiz/game_streamlit.html！")
        st.stop()
    return path.read_text(encoding="utf-8")

game_html_raw = load_game_html()
questions_json = json.dumps(questions, ensure_ascii=False)
game_html = game_html_raw.replace("__QUESTIONS_JSON__", questions_json)

# ── 隱藏 Streamlit 預設 header/footer ───────────────────
st.markdown("""
<style>
#MainMenu { visibility: hidden; }
header { visibility: hidden; }
footer { visibility: hidden; }
.block-container {
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    max-width: 100% !important;
}
</style>
""", unsafe_allow_html=True)

# ── 渲染遊戲 ─────────────────────────────────────────────
components.html(game_html, height=820, scrolling=False)
