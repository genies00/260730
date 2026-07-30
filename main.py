import re
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

st.set_page_config(page_title="전국 생산가능인구 지도", layout="wide")
st.title("👷 전국 생산가능인구 비율 지도")
st.caption("시군구별 15~64세 인구 비율 (행정안전부 주민등록 인구)")

POP_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/population_yearly.csv.gz"
GEO_URL = "https://raw.githubusercontent.com/greatsong/modudata/main/data/boundaries/sigungu_kr.geojson"


@st.cache_data(show_spinner="인구 데이터를 불러오는 중입니다...")
def load_population():
    # '코드' 열은 앞자리 0이 사라지지 않게 글자로 읽습니다
    return pd.read_csv(POP_URL, dtype={"코드": str})


@st.cache_data(show_spinner="지도 경계를 불러오는 중입니다...")
def load_geojson():
    return requests.get(GEO_URL, timeout=30).json()


df = load_population()
geojson = load_geojson()

# ------------------------------------------------------------
# 1. '계_'로 시작하는 나이 열 중, 15~64세(생산가능인구)만 뽑기
#    (남_·여_ 열까지 더하면 인구가 두 배로 잡히므로 '계_'만 사용)
# ------------------------------------------------------------
total_cols = [c for c in df.columns if c.startswith("계_")]


def age_of(col):
    m = re.match(r"계_(\d+)세", col)
    return int(m.group(1)) if m else None


working_age_cols = [
    c for c in total_cols if age_of(c) is not None and 15 <= age_of(c) <= 64
]

# ------------------------------------------------------------
# 2. 옛 행정구역 코드를 요즘 경계 파일 코드로 바꾸는 함수
#    - 42로 시작하던 강원도 코드 → 51로 시작하는 코드
#    - 45로 시작하던 전북 코드 → 52로 시작하는 코드
#    - 군위군: 47720(옛 경북 소속) → 27720(현재 대구 소속)
# ------------------------------------------------------------
def remap_code(code: str) -> str:
    if code == "47720":
        return "27720"
    if code.startswith("42"):
        return "51" + code[2:]
    if code.startswith("45"):
        return "52" + code[2:]
    return code


# ------------------------------------------------------------
# 3. 경계 파일(geojson)에서 코드 → 시군구·시도 이름 짝 만들기
#    이 255개 코드가 '지도에 실제로 그릴 수 있는' 기준 목록입니다.
# ------------------------------------------------------------
names = pd.DataFrame(
    [
        {
            "코드": str(f["properties"]["코드"]),
            "시군구": f["properties"]["시군구"],
            "시도": f["properties"]["시도"],
        }
        for f in geojson["features"]
    ]
)
geo_code_set = set(names["코드"])


# ------------------------------------------------------------
# 4. 특정 연도의 시군구별 생산가능인구 비율을 계산하는 함수
#    (연도 슬라이더용, 애니메이션용 모두 이 함수를 재사용합니다)
# ------------------------------------------------------------
def compute_ratio(year: int) -> pd.DataFrame:
    d = df[df["연도"] == year].copy()
    d["전체인구"] = d[total_cols].sum(axis=1)
    d["생산가능인구"] = d[working_age_cols].sum(axis=1)

    d["시군구코드"] = d["코드"].str[:5]
    d["시군구코드_보정"] = d["시군구코드"].apply(remap_code)

    g = d.groupby("시군구코드_보정")[["전체인구", "생산가능인구"]].sum().reset_index()
    g["생산가능인구비율"] = (g["생산가능인구"] / g["전체인구"] * 100).round(2)

    merged = names.merge(g, left_on="코드", right_on="시군구코드_보정", how="left")
    merged["연도"] = year
    return merged


year_list = sorted(df["연도"].unique())

# ------------------------------------------------------------
# 5. 전체 연도를 다 모아서 20/40/60/80% 분위수로 고정 구간 계산
#    → 어떤 연도를 보든, 애니메이션 어느 프레임이든 같은 기준으로 색 비교 가능
# ------------------------------------------------------------
@st.cache_data(show_spinner="전체 연도 데이터로 색 구간을 계산하는 중입니다...")
def compute_fixed_bins():
    all_years_ratio = pd.concat(
        [compute_ratio(y)["생산가능인구비율"] for y in year_list]
    ).dropna()
    q20, q40, q60, q80 = all_years_ratio.quantile([0.2, 0.4, 0.6, 0.8]).round(1)
    return q20, q40, q60, q80


Q20, Q40, Q60, Q80 = compute_fixed_bins()

BINS = [0, Q20, Q40, Q60, Q80, 100]
LABELS = [f"{Q20}% 미만", f"{Q20}~{Q40}%", f"{Q40}~{Q60}%", f"{Q60}~{Q80}%", f"{Q80}% 이상"]
NO_DATA_LABEL = "데이터 없음"
ALL_LABELS = LABELS + [NO_DATA_LABEL]

# 생산가능인구 비율은 "높을수록 좋은 상태"라 낮은 구간을 진한 경고색으로 칠했습니다
COLORS = {
    LABELS[0]: "#a63603",  # 가장 진함 (비율 낮음 → 주의)
    LABELS[1]: "#e8590c",
    LABELS[2]: "#fdc086",
    LABELS[3]: "#fee6ce",
    LABELS[4]: "#ffffe5",  # 가장 옅음 (비율 높음 → 양호)
    NO_DATA_LABEL: "#cccccc",
}


def add_stage(merged: pd.DataFrame) -> pd.DataFrame:
    merged = merged.copy()
    merged["단계"] = pd.cut(merged["생산가능인구비율"], bins=BINS, labels=LABELS, right=False)
    merged["단계"] = merged["단계"].astype("object")
    merged.loc[merged["생산가능인구비율"].isna(), "단계"] = NO_DATA_LABEL
    return merged


# ==============================================================
# [화면 1] 연도 슬라이더 지도
# ==============================================================
st.markdown("## 📌 특정 연도 살펴보기")

selected_year = st.slider(
    "연도 선택",
    min_value=int(min(year_list)),
    max_value=int(max(year_list)),
    value=int(max(year_list)),
    step=1,
)

merged_selected = add_stage(compute_ratio(selected_year))

fig_static = px.choropleth(
    merged_selected,
    geojson=geojson,
    locations="코드",
    featureidkey="properties.코드",
    color="단계",
    category_orders={"단계": ALL_LABELS},
    color_discrete_map=COLORS,
    hover_name="시군구",
    hover_data={"생산가능인구비율": True, "시도": True, "코드": False, "단계": False},
    labels={"생산가능인구비율": "15~64세 비율(%)"},
)
fig_static.update_geos(fitbounds="locations", visible=False)
fig_static.update_layout(
    margin=dict(l=0, r=0, t=10, b=0),
    height=700,
    legend_title_text=f"생산가능인구 비율 ({selected_year}년)",
)
st.plotly_chart(fig_static, width="stretch")

# 매칭 안 된 지역 안내
missing_rows = merged_selected[merged_selected["생산가능인구비율"].isna()]
if not missing_rows.empty:
    missing_names = ", ".join(
        f"{row['시도']} {row['시군구']}" for _, row in missing_rows.iterrows()
    )
    st.warning(
        f"⚠️ {selected_year}년 데이터에서 다음 지역은 행정구역 코드가 "
        f"경계 파일과 맞지 않아 회색으로 표시되며 순위표에서도 제외됩니다: "
        f"{missing_names}"
    )

# 순위표
valid = merged_selected.dropna(subset=["생산가능인구비율"])
c1, c2 = st.columns(2)
cols = ["시도", "시군구", "생산가능인구비율"]
with c1:
    st.subheader("🟢 생산가능인구 비율 높은 곳 10")
    st.dataframe(valid.nlargest(10, "생산가능인구비율")[cols].reset_index(drop=True))
with c2:
    st.subheader("🔴 생산가능인구 비율 낮은 곳 10")
    st.dataframe(valid.nsmallest(10, "생산가능인구비율")[cols].reset_index(drop=True))

# ==============================================================
# [화면 2] 10년 단위 변화 애니메이션
# ==============================================================
st.markdown("---")
st.markdown("## 🎞️ 10년 단위 변화 보기 (애니메이션)")
st.caption("재생 버튼을 누르면 10년 간격으로 지도 색이 바뀌는 모습을 볼 수 있어요.")

# 데이터가 있는 첫 해부터 10년 간격으로 연도 뽑기 (마지막 해는 항상 포함)
min_year, max_year = int(min(year_list)), int(max(year_list))
decade_years = list(range(min_year, max_year + 1, 10))
if decade_years[-1] != max_year:
    decade_years.append(max_year)

st.caption(f"비교 연도: {', '.join(str(y) for y in decade_years)}년")

anim_df = pd.concat([add_stage(compute_ratio(y)) for y in decade_years], ignore_index=True)

fig_anim = px.choropleth(
    anim_df,
    geojson=geojson,
    locations="코드",
    featureidkey="properties.코드",
    color="단계",
    animation_frame="연도",
    category_orders={"단계": ALL_LABELS, "연도": decade_years},
    color_discrete_map=COLORS,
    hover_name="시군구",
    hover_data={"생산가능인구비율": True, "시도": True, "코드": False, "단계": False},
    labels={"생산가능인구비율": "15~64세 비율(%)"},
)
fig_anim.update_geos(fitbounds="locations", visible=False)
fig_anim.update_layout(
    margin=dict(l=0, r=0, t=10, b=0),
    height=700,
    legend_title_text="생산가능인구 비율 (10년 단위 고정 구간)",
)
st.plotly_chart(fig_anim, width="stretch")
