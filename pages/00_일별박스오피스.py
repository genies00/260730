import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

st.set_page_config(page_title="박스오피스 대시보드", layout="wide")
st.title("🎬 박스오피스 대시보드")

# 비밀 금고에서 인증키 꺼내기 (코드에는 키를 적지 않는다)
KOBIS_KEY = st.secrets["KOBIS_KEY"]

now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
yesterday = now_kst - timedelta(days=1)

DAILY_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"
WEEKLY_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchWeeklyBoxOfficeList.json"

# ── 조회 구분 & 날짜 선택 ──────────────────────────
mode = st.radio("조회 구분", ["일별", "주간", "주말"], horizontal=True)

if mode == "일별":
    selected_date = st.date_input(
        "조회 날짜", value=yesterday.date(), max_value=yesterday.date()
    )
    target_dt = selected_date.strftime("%Y%m%d")
    week_gb = None
    st.caption(f"조회 기준일: {selected_date.strftime('%Y-%m-%d')}")
else:
    # 주간/주말 API는 해당 주의 '월요일' 날짜를 기준으로 조회한다
    default_monday = (yesterday - timedelta(days=yesterday.weekday())).date()
    picked = st.date_input(
        "조회할 주에 포함된 아무 날짜나 선택하세요",
        value=default_monday,
        max_value=yesterday.date(),
    )
    monday_of_week = picked - timedelta(days=picked.weekday())
    target_dt = monday_of_week.strftime("%Y%m%d")
    week_gb = "1" if mode == "주말" else "0"
    st.caption(f"조회 기준 주: {monday_of_week.strftime('%Y-%m-%d')} 포함 주 ({mode})")

# ── API 호출 (캐싱) ──────────────────────────────
@st.cache_data(ttl=3600)
def fetch_daily(target_dt: str, key: str):
    res = requests.get(DAILY_URL, params={"key": key, "targetDt": target_dt}, timeout=10)
    return res.status_code, res.json()

@st.cache_data(ttl=3600)
def fetch_weekly(target_dt: str, week_gb: str, key: str):
    res = requests.get(
        WEEKLY_URL,
        params={"key": key, "targetDt": target_dt, "weekGb": week_gb},
        timeout=10,
    )
    return res.status_code, res.json()

try:
    with st.spinner("박스오피스 정보를 불러오는 중..."):
        if mode == "일별":
            status, data = fetch_daily(target_dt, KOBIS_KEY)
        else:
            status, data = fetch_weekly(target_dt, week_gb, KOBIS_KEY)
except requests.exceptions.RequestException as e:
    st.error(f"요청 중 오류가 발생했습니다: {e}")
    st.stop()

if status != 200:
    st.error(f"요청이 실패했습니다 (상태코드: {status})")
    st.stop()

# KOBIS는 키가 틀려도 상태코드 200을 준다. 대신 faultInfo 상자가 온다.
if "faultInfo" in data:
    st.error("인증키가 올바르지 않습니다. 금고(Secrets)의 KOBIS_KEY를 확인해 주세요.")
    st.stop()

result = data.get("boxOfficeResult", {})
box_list = result.get("dailyBoxOfficeList") or result.get("weeklyBoxOfficeList") or []

if not box_list:
    st.warning("해당 기간 자료가 없습니다. 날짜를 조정해 보세요.")
    st.stop()

df = pd.DataFrame(box_list)

# 글자로 온 숫자들을 진짜 숫자로 바꾸기
for col in ["rank", "audiCnt", "audiAcc", "scrnCnt", "showCnt", "rankInten"]:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col])

TEN_MILLION = 10_000_000
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

# ── 전일(또는 전주) 대비 순위 변동 ──────────────────
def rank_change(row):
    tag = row.get("rankOldAndNew", "")
    if tag == "NEW":
        return "🆕 NEW"
    if tag == "RE":
        return "↩️ RE"
    inten = int(row["rankInten"])
    if inten > 0:
        return f"▲{inten}"
    elif inten < 0:
        return f"▼{abs(inten)}"
    return "-"

df["증감"] = df.apply(rank_change, axis=1)

# ── 순위 메달 + 영화명 + 천만 트로피 ─────────────────
def format_title(row):
    medal = MEDALS.get(int(row["rank"]), "")
    trophy = " 🏆" if row["audiAcc"] >= TEN_MILLION else ""
    prefix = f"{medal} " if medal else ""
    return f"{prefix}{row['movieNm']}{trophy}"

df["영화명_표시"] = df.apply(format_title, axis=1)

# 1위 영화 지표 카드 세 장
top = df.sort_values("rank").iloc[0]
c1, c2, c3 = st.columns(3)
c1.metric("1위", top["movieNm"])
c2.metric("관객수", f"{int(top['audiCnt']):,}명")
c3.metric("누적 관객", f"{int(top['audiAcc']):,}명")

# 표를 한국어 열 이름으로 정리
table = df[["rank", "증감", "영화명_표시", "openDt", "audiCnt", "audiAcc", "scrnCnt"]].copy()
table.columns = ["순위", "증감", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]
table = table.sort_values("순위").reset_index(drop=True)

# ── 증감 컬럼 색상: 상승=빨강, 하락=파랑 ─────────────
def color_change(val):
    if isinstance(val, str) and val.startswith("▲"):
        return "color: red; font-weight: bold;"
    if isinstance(val, str) and val.startswith("▼"):
        return "color: blue; font-weight: bold;"
    return ""

styled_table = table.style.applymap(color_change, subset=["증감"])

st.subheader("📋 박스오피스 TOP 10")
st.caption("🏆 누적관객 1,000만 이상 · 🥇🥈🥉 현재 순위 1·2·3위")
st.dataframe(styled_table, use_container_width=True)

st.subheader("📈 관객수 상위 5편")
top5 = table.sort_values("관객수", ascending=False).head(5)
st.bar_chart(top5.set_index("영화명")["관객수"])
