"""
Google Sheets 連線模組
讀取與寫入英文搶答題庫
"""

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Google Sheets 欄位順序
HEADERS = ["q", "opt_a", "opt_b", "opt_c", "opt_d", "ans", "exp"]


def _get_client():
    """從 Streamlit Secrets 建立 gspread 連線"""
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )
    return gspread.authorize(creds)


def is_configured() -> bool:
    """檢查 Streamlit Secrets 是否已設定 Google Sheets"""
    return (
        "gcp_service_account" in st.secrets
        and "sheets" in st.secrets
        and "spreadsheet_id" in st.secrets.get("sheets", {})
    )


@st.cache_data(ttl=60)  # 每 60 秒重新讀取一次
def load_questions_from_sheets() -> list[dict]:
    """從 Google Sheets 讀取題庫，回傳標準格式的 list"""
    client = _get_client()
    sheet_id = st.secrets["sheets"]["spreadsheet_id"]
    sh = client.open_by_key(sheet_id)
    ws = sh.sheet1

    rows = ws.get_all_records()  # 第一列為 header
    questions = []
    for row in rows:
        try:
            questions.append({
                "q":    row["q"],
                "opts": [row["opt_a"], row["opt_b"], row["opt_c"], row["opt_d"]],
                "ans":  int(row["ans"]),
                "exp":  row["exp"],
            })
        except (KeyError, ValueError):
            continue
    return questions


def save_questions_to_sheets(questions: list[dict]):
    """把題庫（list of dict）寫回 Google Sheets"""
    client = _get_client()
    sheet_id = st.secrets["sheets"]["spreadsheet_id"]
    sh = client.open_by_key(sheet_id)
    ws = sh.sheet1

    # 清空舊資料，重新寫入
    ws.clear()
    ws.append_row(HEADERS)

    rows = []
    for q in questions:
        opts = q.get("opts", ["", "", "", ""])
        rows.append([
            q.get("q", ""),
            opts[0] if len(opts) > 0 else "",
            opts[1] if len(opts) > 1 else "",
            opts[2] if len(opts) > 2 else "",
            opts[3] if len(opts) > 3 else "",
            str(q.get("ans", 0)),
            q.get("exp", ""),
        ])
    if rows:
        ws.append_rows(rows)

    # 清除快取，讓下次讀取拿到最新資料
    load_questions_from_sheets.clear()
