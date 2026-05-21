import streamlit as st

st.set_page_config(
    page_title="COLA Hub",
    page_icon="🏠",
    layout="wide",
)

# ─────────────────────────────────────────────
# 導覽結構定義（新增 app 只需在這裡加一行）
# ─────────────────────────────────────────────
pg = st.navigation(
    {
        "📱 應用程式": [
            st.Page("pages/english_quiz.py",    title="English Quiz",     icon="📚"),
            st.Page("pages/garmin_dashboard.py", title="Garmin Dashboard", icon="🏃"),
        ],
        "⚙️ 系統": [
            st.Page("pages/admin.py", title="管理後台", icon="🔧"),
        ],
        # 未來新增分類，照這個格式往下加：
        # "🔧 工具": [
        #     st.Page("pages/xxx.py", title="工具名稱", icon="⚙️"),
        # ],
    }
)

pg.run()
