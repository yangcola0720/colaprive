import queue
import threading
from datetime import date, timedelta, datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

TOKEN_FILE = Path(".garmin_tokens.json")
C = {
    "green": "#1FB954",
    "blue": "#0066CC",
    "red": "#FF4444",
    "purple": "#7B68EE",
    "orange": "#FF8C00",
    "teal": "#20B2AA",
}


def save_tokens(client):
    try:
        TOKEN_FILE.write_text(client.garth.dumps())
    except Exception:
        pass


def load_saved_client(email: str, password: str):
    if not TOKEN_FILE.exists():
        return None
    try:
        import garminconnect
        client = garminconnect.Garmin(email, password)
        client.garth.loads(TOKEN_FILE.read_text())
        return client
    except Exception:
        TOKEN_FILE.unlink(missing_ok=True)
        return None


def page_login():
    st.title("🏃 Garmin Health Dashboard")
    _, col, _ = st.columns([1, 2, 1])

    if "login_step" not in st.session_state:
        st.session_state.login_step = 1

    with col:
        if st.session_state.login_step == 1:
            st.subheader("登入 Garmin Connect")
            with st.form("login_step1"):
                email = st.text_input("Email", placeholder="your@email.com")
                password = st.text_input("密碼", type="password")
                if st.form_submit_button("下一步 →", use_container_width=True):
                    if not email or not password:
                        st.error("請輸入 Email 和密碼")
                        return
                    with st.spinner("連線中，請稍候..."):
                        import garminconnect

                        mfa_q = queue.Queue(maxsize=1)
                        result_q = queue.Queue(maxsize=1)

                        def do_login():
                            try:
                                def prompt_mfa():
                                    result_q.put(("mfa_needed", None))
                                    return mfa_q.get(timeout=300)

                                c = garminconnect.Garmin(email, password, prompt_mfa=prompt_mfa)
                                c.login()
                                result_q.put(("success", c))
                            except Exception as exc:
                                result_q.put(("error", str(exc)))

                        t = threading.Thread(target=do_login, daemon=True)
                        t.start()

                        try:
                            status, payload = result_q.get(timeout=15)
                        except queue.Empty:
                            st.error("連線逾時，請確認網路後重試")
                            return

                        if status == "success":
                            save_tokens(payload)
                            st.session_state.client = payload
                            st.session_state.email = email
                            st.session_state.password = password
                            st.rerun()
                        elif status == "mfa_needed":
                            st.session_state.login_step = 2
                            st.session_state.mfa_q = mfa_q
                            st.session_state.result_q = result_q
                            st.session_state.email = email
                            st.session_state.password = password
                            st.rerun()
                        else:
                            msg = payload.lower()
                            if any(k in msg for k in ("auth", "password", "401", "403", "invalid")):
                                st.error("❌ 帳號或密碼錯誤")
                            else:
                                st.error(f"❌ 登入失敗：{payload}")

        elif st.session_state.login_step == 2:
            st.subheader("雙重驗證")
            st.info("📧 驗證碼已發送至您的 Email，請查收後填入下方")
            with st.form("login_step2"):
                mfa_code = st.text_input("MFA 驗證碼", placeholder="例：123456", max_chars=10)
                c_back, c_submit = st.columns(2)
                back = c_back.form_submit_button("← 返回")
                submit = c_submit.form_submit_button("✅ 確認登入", use_container_width=True)

            if back:
                st.session_state.login_step = 1
                st.rerun()

            if submit:
                if not mfa_code.strip():
                    st.error("請輸入驗證碼")
                    return
                with st.spinner("驗證中..."):
                    st.session_state.mfa_q.put(mfa_code.strip())
                    try:
                        status, payload = st.session_state.result_q.get(timeout=30)
                    except queue.Empty:
                        st.error("驗證逾時，請返回重試")
                        st.session_state.login_step = 1
                        return

                    if status == "success":
                        save_tokens(payload)
                        st.session_state.client = payload
                        st.session_state.login_step = 1
                        st.rerun()
                    else:
                        st.error(f"❌ 驗證失敗：{payload}")
                        st.session_state.login_step = 1


@st.cache_data(ttl=3600, show_spinner=False)
def load_daily(_client, email: str, days: int) -> pd.DataFrame:
    rows = []
    today = date.today()
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        try:
            s = _client.get_user_summary(d)
            rows.append({
                "date": d,
                "steps": s.get("totalSteps") or 0,
                "calories": s.get("totalKilocalories") or 0,
                "dist_km": ((s.get("totalDistanceMeters") or 0) / 1000),
                "active_min": s.get("moderateIntensityMinutes") or 0,
                "floors": s.get("floorsAscended") or 0,
                "rhr": s.get("restingHeartRate") or None,
                "avg_stress": s.get("averageStressLevel") if (s.get("averageStressLevel") or 0) > 0 else None,
                "bb_high": s.get("bodyBatteryHighestValue"),
                "bb_low": s.get("bodyBatteryLowestValue"),
            })
        except Exception:
            pass
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_hr_day(_client, email: str, d: str) -> pd.DataFrame:
    try:
        data = _client.get_heart_rates(d)
        vals = data.get("heartRateValues") or []
        rows = [
            {"time": datetime.fromtimestamp(v[0] / 1000), "bpm": v[1]}
            for v in vals if v and v[1]
        ]
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame(columns=["time", "bpm"])


@st.cache_data(ttl=3600, show_spinner=False)
def load_sleep(_client, email: str, days: int) -> pd.DataFrame:
    rows = []
    today = date.today()
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        try:
            data = _client.get_sleep_data(d)
            dto = data.get("dailySleepDTO") or {}
            if not dto:
                continue
            overall = ((dto.get("sleepScores") or {}).get("overall") or {})
            rows.append({
                "date": d,
                "total_h": (dto.get("sleepTimeSeconds") or 0) / 3600,
                "deep_h": (dto.get("deepSleepSeconds") or 0) / 3600,
                "light_h": (dto.get("lightSleepSeconds") or 0) / 3600,
                "rem_h": (dto.get("remSleepSeconds") or 0) / 3600,
                "awake_h": (dto.get("awakeSleepSeconds") or 0) / 3600,
                "score": overall.get("value"),
            })
        except Exception:
            pass
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def load_activities(_client, email: str, limit: int = 100) -> pd.DataFrame:
    try:
        acts = _client.get_activities(0, limit)
        rows = []
        for a in acts:
            t = a.get("activityType") or {}
            dist = (a.get("distance") or 0) / 1000
            dur = (a.get("duration") or 0) / 60
            rows.append({
                "date": (a.get("startTimeLocal") or "")[:10],
                "name": a.get("activityName", ""),
                "type": t.get("typeKey", "") if isinstance(t, dict) else "",
                "dur_min": round(dur, 1),
                "dist_km": round(dist, 2),
                "calories": a.get("calories") or 0,
                "avg_hr": a.get("averageHR"),
                "max_hr": a.get("maxHR"),
                "elev_m": a.get("elevationGain") or 0,
                "pace": round(dur / dist, 2) if dist > 0.1 else None,
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df.sort_values("date", ascending=False, inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_body(_client, email: str, days: int) -> pd.DataFrame:
    today = date.today()
    start = (today - timedelta(days=days)).isoformat()
    end = today.isoformat()
    try:
        data = _client.get_weight_based_on_start_and_end_date(start, end)
        rows = []
        for item in (data.get("dateWeightList") or []):
            rows.append({
                "date": item.get("calendarDate", ""),
                "weight_kg": round((item.get("weight") or 0) / 1000, 1),
                "bmi": item.get("bmi"),
                "fat_pct": item.get("bodyFat"),
                "muscle_kg": round((item.get("muscleMass") or 0) / 1000, 1)
                if item.get("muscleMass") else None,
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            df.sort_values("date", inplace=True)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_spo2(_client, email: str, days: int) -> pd.DataFrame:
    rows = []
    today = date.today()
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        try:
            data = _client.get_spo2_data(d)
            avg = data.get("averageSpO2")
            if avg:
                rows.append({"date": d, "spo2": avg})
        except Exception:
            pass
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df.sort_values("date", inplace=True)
    return df


def tab_overview(df: pd.DataFrame, days: int):
    if df.empty:
        st.info("暫無資料，請確認 Garmin 設備已同步至 Garmin Connect")
        return

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else None

    def delta(col):
        if prev is None:
            return None
        v, p = latest[col], prev[col]
        if pd.isna(v) or pd.isna(p):
            return None
        return round(float(v) - float(p), 1)

    st.subheader("今日概覽")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🚶 步數", f"{int(latest.steps):,}", delta("steps"))
    c2.metric("🔥 消耗卡路里", f"{int(latest.calories):,} kcal", delta("calories"))
    c3.metric("📏 移動距離", f"{latest.dist_km:.2f} km", delta("dist_km"))
    c4.metric("❤️ 靜息心率", f"{int(latest.rhr)} bpm" if pd.notna(latest.rhr) else "N/A")
    c5.metric("⚡ Body Battery", f"{int(latest.bb_high)}" if pd.notna(latest.bb_high) else "N/A")

    st.markdown("---")
    st.subheader(f"近期趨勢（近 {days} 天）")

    r1l, r1r = st.columns(2)

    with r1l:
        fig = px.bar(
            df,
            x="date",
            y="steps",
            title=f"每日步數（近 {days} 天）",
            color_discrete_sequence=[C["green"]],
            labels={"date": "日期", "steps": "步數"},
        )
        fig.add_hline(y=10000, line_dash="dash", line_color="gray", annotation_text="目標 10,000 步")
        st.plotly_chart(fig, use_container_width=True)

    with r1r:
        fig = px.area(
            df,
            x="date",
            y="calories",
            title=f"每日消耗卡路里（近 {days} 天）",
            color_discrete_sequence=[C["blue"]],
            labels={"date": "日期", "calories": "kcal"},
        )
        st.plotly_chart(fig, use_container_width=True)

    r2l, r2r = st.columns(2)

    with r2l:
        rhr_df = df[df["rhr"].notna()]
        if not rhr_df.empty:
            fig = px.line(
                rhr_df,
                x="date",
                y="rhr",
                markers=True,
                title=f"靜息心率趨勢（近 {days} 天）",
                color_discrete_sequence=[C["red"]],
                labels={"date": "日期", "rhr": "bpm"},
            )
            st.plotly_chart(fig, use_container_width=True)

    with r2r:
        s_df = df[df["avg_stress"].notna()]
        if not s_df.empty:
            fig = px.bar(
                s_df,
                x="date",
                y="avg_stress",
                title=f"每日平均壓力指數（近 {days} 天）",
                color="avg_stress",
                color_continuous_scale=["#00CC44", "#FFCC00", "#FF0000"],
                range_color=[0, 100],
                labels={"date": "日期", "avg_stress": "壓力指數（0-100）"},
            )
            st.plotly_chart(fig, use_container_width=True)

    dist_df = df[df["dist_km"] > 0]
    if not dist_df.empty:
        fig = px.area(
            dist_df,
            x="date",
            y="dist_km",
            title=f"每日移動距離（近 {days} 天）",
            color_discrete_sequence=[C["teal"]],
            labels={"date": "日期", "dist_km": "距離 (km)"},
        )
        st.plotly_chart(fig, use_container_width=True)


def tab_activities(df: pd.DataFrame):
    if df.empty:
        st.info("暫無活動資料")
        return

    types = ["全部"] + sorted(df["type"].dropna().unique().tolist())
    sel = st.selectbox("篩選活動類型", types)
    flt = df if sel == "全部" else df[df["type"] == sel]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("活動總數", len(flt))
    c2.metric("總距離", f"{flt['dist_km'].sum():.1f} km")
    c3.metric("總消耗", f"{int(flt['calories'].sum()):,} kcal")
    c4.metric("總時間", f"{flt['dur_min'].sum():.0f} 分鐘")

    st.markdown("---")
    l, r = st.columns(2)

    with l:
        tc = df["type"].value_counts().reset_index()
        tc.columns = ["type", "n"]
        fig = px.pie(tc, values="n", names="type", title="活動類型分布", hole=0.4)
        st.plotly_chart(fig, use_container_width=True)

    with r:
        if flt["dist_km"].sum() > 0:
            m = flt.copy()
            m["month"] = m["date"].dt.to_period("M").astype(str)
            agg = m.groupby("month")["dist_km"].sum().reset_index()
            fig = px.bar(
                agg,
                x="month",
                y="dist_km",
                title="月累積距離",
                color_discrete_sequence=[C["green"]],
                labels={"month": "月份", "dist_km": "距離 (km)"},
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            m = flt.copy()
            m["month"] = m["date"].dt.to_period("M").astype(str)
            agg = m.groupby("month")["dur_min"].sum().reset_index()
            fig = px.bar(
                agg,
                x="month",
                y="dur_min",
                title="月累積運動時間",
                color_discrete_sequence=[C["blue"]],
                labels={"month": "月份", "dur_min": "時間 (分鐘)"},
            )
            st.plotly_chart(fig, use_container_width=True)

    hr_df = flt[flt["avg_hr"].notna()]
    if not hr_df.empty:
        fig = px.histogram(
            hr_df,
            x="avg_hr",
            nbins=20,
            title="活動平均心率分布",
            color_discrete_sequence=[C["red"]],
            labels={"avg_hr": "平均心率 (bpm)", "count": "次數"},
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("活動列表")
    show = flt[["date", "name", "type", "dur_min", "dist_km", "calories", "avg_hr", "max_hr", "elev_m"]].copy()
    show.columns = ["日期", "名稱", "類型", "時間(分)", "距離(km)", "卡路里", "平均心率", "最高心率", "爬升(m)"]
    show["日期"] = show["日期"].dt.strftime("%Y-%m-%d")
    st.dataframe(show, use_container_width=True, hide_index=True)


def tab_heart_rate(df_daily: pd.DataFrame, _client, email: str, d: str, days: int):
    df_hr = load_hr_day(_client, email, d)

    left, right = st.columns([3, 1])
    with left:
        if not df_hr.empty:
            fig = px.area(
                df_hr,
                x="time",
                y="bpm",
                title=f"心率曲線（{d}）",
                color_discrete_sequence=[C["red"]],
                labels={"time": "時間", "bpm": "心率 (bpm)"},
            )
            fig.update_traces(fillcolor="rgba(255,68,68,0.12)")
            for y0, y1, color, label in [
                (0, 100, "#00CC44", "緩和"),
                (100, 120, "#FFCC00", "有氧"),
                (120, 140, "#FF8800", "有氧強化"),
                (140, 160, "#FF4400", "無氧"),
                (160, 220, "#CC0000", "最大強度"),
            ]:
                fig.add_hrect(y0=y0, y1=y1, fillcolor=color, opacity=0.05, annotation_text=label, annotation_position="right")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info(f"⚠️ {d} 的心率資料尚未同步，請嘗試選擇其他日期")

    with right:
        today_row = df_daily[df_daily["date"].dt.date == date.today()]
        if not today_row.empty:
            rhr = today_row.iloc[-1]["rhr"]
            if pd.notna(rhr):
                st.metric("今日靜息心率", f"{int(rhr)} bpm")
                zone = "優秀 🏆" if rhr < 60 else "良好 ✅" if rhr < 70 else "正常 📊" if rhr < 80 else "偏高 ⚠️"
                st.info(f"心率狀態：{zone}")
        if not df_hr.empty:
            st.metric("最高心率", f"{int(df_hr['bpm'].max())} bpm")
            st.metric("最低心率", f"{int(df_hr['bpm'].min())} bpm")
            st.metric("平均心率", f"{int(df_hr['bpm'].mean())} bpm")

    st.markdown("---")
    st.subheader(f"靜息心率趨勢（近 {days} 天）")
    rhr_df = df_daily[df_daily["rhr"].notna()]
    if not rhr_df.empty:
        fig = px.line(
            rhr_df,
            x="date",
            y="rhr",
            markers=True,
            color_discrete_sequence=[C["red"]],
            labels={"date": "日期", "rhr": "bpm"},
        )
        fig.add_hrect(y0=0, y1=60, fillcolor="green", opacity=0.06, annotation_text="優秀 <60")
        fig.add_hrect(y0=60, y1=70, fillcolor="blue", opacity=0.06, annotation_text="良好 60-70")
        fig.add_hrect(y0=70, y1=80, fillcolor="yellow", opacity=0.06, annotation_text="正常 70-80")
        fig.add_hrect(y0=80, y1=120, fillcolor="red", opacity=0.06, annotation_text="偏高 >80")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暫無靜息心率資料")


def tab_sleep(df: pd.DataFrame, days: int):
    if df.empty:
        st.info("暫無睡眠資料")
        return

    latest = df.iloc[-1]
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("總睡眠", f"{latest.total_h:.1f} 小時")
    c2.metric("深度睡眠", f"{latest.deep_h:.1f} 小時")
    c3.metric("淺度睡眠", f"{latest.light_h:.1f} 小時")
    c4.metric("REM 睡眠", f"{latest.rem_h:.1f} 小時")
    c5.metric("睡眠評分", f"{int(latest.score)}" if pd.notna(latest.score) else "N/A")

    st.markdown("---")
    left, right = st.columns(2)

    with left:
        fig = go.Figure()
        for col, name, color in [
            ("deep_h", "深度睡眠", "#1a0050"),
            ("light_h", "淺度睡眠", C["purple"]),
            ("rem_h", "REM", "#9370DB"),
            ("awake_h", "清醒", "#D3D3D3"),
        ]:
            fig.add_trace(go.Bar(name=name, x=df["date"], y=df[col], marker_color=color))
        fig.update_layout(
            barmode="stack",
            title=f"睡眠階段分布（近 {days} 天）",
            xaxis_title="日期",
            yaxis_title="小時",
            legend=dict(orientation="h", y=1.08),
        )
        st.plotly_chart(fig, use_container_width=True)

    with right:
        fig = px.line(
            df,
            x="date",
            y="total_h",
            markers=True,
            title=f"睡眠時長趨勢（近 {days} 天）",
            color_discrete_sequence=[C["purple"]],
            labels={"date": "日期", "total_h": "小時"},
        )
        fig.add_hline(y=8, line_dash="dash", line_color="green", annotation_text="建議 8 小時", annotation_position="top right")
        fig.add_hline(y=7, line_dash="dash", line_color="orange", annotation_text="最低 7 小時", annotation_position="bottom right")
        st.plotly_chart(fig, use_container_width=True)

    score_df = df[df["score"].notna()]
    if not score_df.empty:
        fig = px.bar(
            score_df,
            x="date",
            y="score",
            title=f"睡眠評分趨勢（近 {days} 天）",
            color="score",
            color_continuous_scale=["#FF4444", "#FFCC00", "#00CC44"],
            range_color=[0, 100],
            labels={"date": "日期", "score": "評分"},
        )
        st.plotly_chart(fig, use_container_width=True)


def tab_stress(df: pd.DataFrame, days: int):
    s_df = df[df["avg_stress"].notna()]
    if s_df.empty:
        st.info("暫無壓力資料（需支援壓力偵測的 Garmin 裝置）")
        return

    latest = s_df.iloc[-1]
    avg = float(latest["avg_stress"])
    c1, c2, c3 = st.columns(3)
    c1.metric("今日平均壓力", f"{int(avg)}")
    level = "低壓 😌" if avg < 25 else "輕微 🙂" if avg < 50 else "中等 😐" if avg < 75 else "高壓 😫"
    c2.metric("壓力狀態", level)
    if pd.notna(latest["bb_high"]):
        c3.metric("今日 Body Battery", f"{int(latest['bb_high'])} / 100")

    st.markdown("---")

    fig = go.Figure(go.Bar(
        x=s_df["date"],
        y=s_df["avg_stress"],
        marker=dict(
            color=s_df["avg_stress"],
            colorscale=[[0, "#00CC44"], [0.25, "#FFCC00"], [0.5, "#FF8800"], [1, "#FF0000"]],
            cmin=0,
            cmax=100,
        ),
    ))
    fig.update_layout(
        title=f"每日平均壓力指數（近 {days} 天）",
        xaxis_title="日期",
        yaxis_title="壓力（0-100）",
        yaxis_range=[0, 100],
    )
    for y, color, label in [(25, "green", "低壓"), (50, "orange", "中壓"), (75, "red", "高壓")]:
        fig.add_hline(y=y, line_dash="dot", line_color=color, annotation_text=label, annotation_position="top right")
    st.plotly_chart(fig, use_container_width=True)

    bb_df = df[df["bb_high"].notna() & df["bb_low"].notna()]
    if not bb_df.empty:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=bb_df["date"], y=bb_df["bb_high"], name="最高電量", fill="tonexty", line_color=C["green"]))
        fig2.add_trace(
            go.Scatter(
                x=bb_df["date"],
                y=bb_df["bb_low"],
                name="最低電量",
                fill="tozeroy",
                line_color=C["red"],
                fillcolor="rgba(255,68,68,0.18)",
            )
        )
        fig2.update_layout(
            title=f"Body Battery 電量（近 {days} 天）",
            yaxis_range=[0, 100],
            xaxis_title="日期",
            yaxis_title="電量 (%)",
        )
        st.plotly_chart(fig2, use_container_width=True)


def tab_body(df: pd.DataFrame, df_spo2: pd.DataFrame):
    has_weight = not df.empty and (df["weight_kg"] > 0).any()

    if has_weight:
        valid = df[df["weight_kg"] > 0]
        latest = valid.iloc[-1]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最新體重", f"{latest.weight_kg:.1f} kg")
        c2.metric("BMI", f"{latest.bmi:.1f}" if pd.notna(latest.bmi) else "N/A")
        c3.metric("體脂率", f"{latest.fat_pct:.1f}%" if pd.notna(latest.fat_pct) else "N/A")
        c4.metric("肌肉量", f"{latest.muscle_kg:.1f} kg" if pd.notna(latest.muscle_kg) else "N/A")

        st.markdown("---")
        left, right = st.columns(2)

        with left:
            fig = px.line(
                valid,
                x="date",
                y="weight_kg",
                markers=True,
                title="體重趨勢",
                color_discrete_sequence=[C["teal"]],
                labels={"date": "日期", "weight_kg": "體重 (kg)"},
            )
            st.plotly_chart(fig, use_container_width=True)

        with right:
            fat_df = df[df["fat_pct"].notna()]
            if not fat_df.empty:
                fig = px.line(
                    fat_df,
                    x="date",
                    y="fat_pct",
                    markers=True,
                    title="體脂率趨勢",
                    color_discrete_sequence=[C["orange"]],
                    labels={"date": "日期", "fat_pct": "體脂率 (%)"},
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("暫無體脂率資料（需 Garmin 智慧體重計）")
    else:
        st.info("暫無體重資料（需 Garmin 智慧體重計或手動在 App 記錄）")

    st.markdown("---")
    st.subheader("血氧 SpO₂")
    if not df_spo2.empty:
        c1, c2 = st.columns(2)
        with c1:
            latest_spo2 = df_spo2.iloc[-1]["spo2"]
            st.metric("最新血氧", f"{latest_spo2:.1f}%")
            status = "正常 ✅" if latest_spo2 >= 95 else "偏低 ⚠️" if latest_spo2 >= 90 else "過低 🚨"
            st.info(f"狀態：{status}（正常範圍 ≥ 95%）")
        with c2:
            st.metric("平均血氧", f"{df_spo2['spo2'].mean():.1f}%")

        fig = px.line(
            df_spo2,
            x="date",
            y="spo2",
            markers=True,
            title="血氧 SpO₂ 趨勢",
            color_discrete_sequence=["#4169E1"],
            labels={"date": "日期", "spo2": "SpO₂ (%)"},
        )
        fig.add_hline(y=95, line_dash="dash", line_color="green", annotation_text="正常下限 95%", annotation_position="top right")
        fig.update_yaxes(range=[85, 100])
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暫無血氧資料（需支援 SpO₂ 偵測的 Garmin 裝置）")


def _build_health_context(df_daily, df_sleep, df_acts, df_body, df_spo2, days):
    lines = [f"以下是使用者最近 {days} 天的 Garmin 健康資料摘要：\n"]

    if not df_daily.empty:
        latest = df_daily.iloc[-1]
        lines.append("【每日活動（Daily Activity）】")
        lines.append(f"- 最新步數：{int(latest.steps):,} 步　平均：{int(df_daily['steps'].mean()):,} 步")
        lines.append(f"- 最新卡路里：{int(latest.calories):,} kcal　平均：{int(df_daily['calories'].mean()):,} kcal")
        lines.append(f"- 最新移動距離：{latest.dist_km:.2f} km")
        rhr_s = df_daily["rhr"].dropna()
        if not rhr_s.empty:
            lines.append(f"- 靜息心率：{int(latest.rhr) if pd.notna(latest.rhr) else 'N/A'} bpm　近期平均：{int(rhr_s.mean())} bpm")
        stress_s = df_daily["avg_stress"].dropna()
        if not stress_s.empty:
            lines.append(f"- 近期平均壓力指數：{stress_s.mean():.1f}（0-100，越高壓力越大）")
        if pd.notna(latest.get("bb_high")) and pd.notna(latest.get("bb_low")):
            lines.append(f"- 最新 Body Battery：最高 {int(latest.bb_high)}　最低 {int(latest.bb_low)}")
        lines.append("")

    if not df_sleep.empty:
        sl = df_sleep.iloc[-1]
        lines.append("【睡眠資料（Sleep）】")
        lines.append(f"- 最新睡眠時長：{sl.total_h:.1f} 小時　近期平均：{df_sleep['total_h'].mean():.1f} 小時")
        lines.append(f"- 深度睡眠：{sl.deep_h:.1f} 小時　REM：{sl.rem_h:.1f} 小時　淺度：{sl.light_h:.1f} 小時")
        if pd.notna(sl.score):
            lines.append(f"- 睡眠評分：{int(sl.score)}")
        lines.append("")

    if not df_acts.empty:
        top = df_acts["type"].value_counts().head(3)
        lines.append("【活動記錄（Activities）】")
        lines.append(f"- 總活動筆數：{len(df_acts)}")
        lines.append(f"- 主要類型：{', '.join(f'{t}({n}次)' for t, n in top.items())}")
        lines.append(f"- 累積距離：{df_acts['dist_km'].sum():.1f} km　累積卡路里：{int(df_acts['calories'].sum()):,} kcal")
        lines.append("")

    if not df_body.empty and (df_body["weight_kg"] > 0).any():
        bv = df_body[df_body["weight_kg"] > 0].iloc[-1]
        lines.append("【身體組成（Body Composition）】")
        lines.append(f"- 最新體重：{bv.weight_kg:.1f} kg")
        if pd.notna(bv.bmi):
            lines.append(f"- BMI：{bv.bmi:.1f}")
        if pd.notna(bv.fat_pct):
            lines.append(f"- 體脂率：{bv.fat_pct:.1f}%")
        if pd.notna(bv.muscle_kg):
            lines.append(f"- 肌肉量：{bv.muscle_kg:.1f} kg")
        lines.append("")

    if not df_spo2.empty:
        lines.append("【血氧 SpO₂】")
        lines.append(f"- 最新血氧：{df_spo2.iloc[-1]['spo2']:.1f}%　近期平均：{df_spo2['spo2'].mean():.1f}%")
        lines.append("")

    return "\n".join(lines)


def tab_ai_chat(df_daily, df_sleep, df_acts, df_body, df_spo2, days):
    st.subheader("🤖 AI 健康分析師")
    st.caption("根據您的 Garmin 資料，與 AI 進行健康諮詢")

    api_key = st.session_state.get("anthropic_api_key", "")
    if not api_key:
        st.warning("請先在左側側邊欄「🤖 AI 設定」欄位輸入您的 Anthropic API Key")
        return

    try:
        import anthropic as _anthropic
    except ImportError:
        st.error("請執行 pip install anthropic 安裝套件後重新啟動")
        return

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if prompt := st.chat_input("詢問關於您的健康資料，例如：我的睡眠品質怎麼樣？"):
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        health_ctx = _build_health_context(df_daily, df_sleep, df_acts, df_body, df_spo2, days)
        system_text = (
            "你是一位專業的健康顧問，擅長解讀 Garmin 穿戴裝置的健康與運動資料。"
            "請以繁體中文回答，語氣友善專業，並給出具體可行的建議。"
            "遇到可能的醫療問題，請建議使用者諮詢醫療專業人員。\n\n"
            + health_ctx
        )

        ai_client = _anthropic.Anthropic(api_key=api_key)
        api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat_messages]

        with st.chat_message("assistant"):
            placeholder = st.empty()
            full = ""
            try:
                with ai_client.messages.stream(
                    model="claude-opus-4-7",
                    max_tokens=2048,
                    system=[{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}],
                    messages=api_messages,
                    thinking={"type": "adaptive"},
                ) as stream:
                    for chunk in stream.text_stream:
                        full += chunk
                        placeholder.markdown(full + "▌")
                placeholder.markdown(full)
                st.session_state.chat_messages.append({"role": "assistant", "content": full})
            except Exception as exc:
                placeholder.error(f"AI 回應失敗：{exc}")

    if st.session_state.get("chat_messages"):
        if st.button("🗑️ 清除對話記錄"):
            st.session_state.chat_messages = []
            st.rerun()


def main():
    st.markdown(
        """
    <style>
    [data-testid="metric-container"] {
        background: #f4f6f8;
        border-radius: 10px;
        padding: 14px 18px;
        border: 1px solid #e0e4ea;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    if "client" not in st.session_state:
        st.session_state.client = None

    if st.session_state.client is None and "email" in st.session_state:
        restored = load_saved_client(st.session_state.email, st.session_state.get("password", ""))
        if restored:
            st.session_state.client = restored

    if st.session_state.client is None:
        page_login()
        return

    client = st.session_state.client
    email = st.session_state.email

    with st.sidebar:
        st.title("⚙️ 控制面板")
        try:
            name = client.get_full_name()
            st.success(f"✅ {name}")
        except Exception:
            st.success("✅ 已登入")

        st.markdown("---")
        days = st.slider("歷史天數", 7, 90, 30, 7, help="載入過去幾天的資料（天數越多載入越慢）")
        sel_d = st.date_input("心率查詢日期", date.today()).isoformat()

        st.markdown("---")
        if st.button("🔄 重新載入資料"):
            st.cache_data.clear()
            st.rerun()
        if st.button("🚪 登出"):
            st.session_state.clear()
            TOKEN_FILE.unlink(missing_ok=True)
            st.rerun()

        st.markdown("---")
        st.caption("資料每小時自動快取。\n點擊「重新載入」可強制更新。")

        st.markdown("---")
        st.subheader("🤖 AI 設定")
        ak = st.text_input(
            "Anthropic API Key",
            type="password",
            value=st.session_state.get("anthropic_api_key", ""),
            placeholder="sk-ant-...",
            help="前往 console.anthropic.com 取得 API Key",
        )
        if ak:
            st.session_state.anthropic_api_key = ak

    st.title("🏃 Garmin Health Dashboard")

    with st.spinner("載入 Garmin 健康資料中，請稍候..."):
        df_daily = load_daily(client, email, days)
        df_sleep = load_sleep(client, email, days)
        df_acts = load_activities(client, email, 100)
        df_body = load_body(client, email, 365)
        df_spo2 = load_spo2(client, email, days)

    if df_daily.empty and df_acts.empty:
        st.warning("⚠️ 無法取得資料。請確認網路連線正常，並確認 Garmin 設備已同步。")

    t1, t2, t3, t4, t5, t6, t7 = st.tabs([
        "📊 總覽",
        "🏃 活動紀錄",
        "❤️ 心率",
        "😴 睡眠",
        "🧘 壓力 & Battery",
        "⚖️ 身體組成",
        "🤖 AI 健康分析",
    ])

    with t1:
        tab_overview(df_daily, days)
    with t2:
        tab_activities(df_acts)
    with t3:
        tab_heart_rate(df_daily, client, email, sel_d, days)
    with t4:
        tab_sleep(df_sleep, days)
    with t5:
        tab_stress(df_daily, days)
    with t6:
        tab_body(df_body, df_spo2)
    with t7:
        tab_ai_chat(df_daily, df_sleep, df_acts, df_body, df_spo2, days)


main()
