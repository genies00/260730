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

COLORS = {
    LABELS[0]: "#a63603",
    LABELS[1]: "#e8590c",
    LABELS[2]: "#fdc086",
    LABELS[3]: "#fee6ce",
    LABELS[4]: "#ffffe5",
    NO_DATA_LABEL: "#cccccc",
}


def add_stage(merged: pd.DataFrame) -> pd.DataFrame:
    merged = merged.copy()
    merged["단계"] = pd.cut(merged["생산가능인구비율"], bins=BINS, labels=LABELS, right=False)
    merged["단계"] = merged["단계"].astype("object")
    merged.loc[merged["생산가능인구비율"].isna(), "단계"] = NO_DATA_LABEL
    return merged


def show_missing_warning(merged: pd.DataFrame, year_label: str):
    missing_rows = merged[merged["생산가능인구비율"].isna()]
    if not missing_rows.empty:
        missing_names = ", ".join(
            f"{row['시도']} {row['시군구']}" for _, row in missing_rows.iterrows()
        )
        st.warning(
            f"⚠️ {year_label} 데이터에서 다음 지역은 행정구역 코드가 "
            f"경계 파일과 맞지 않아 회색으로 표시되며 계산에서도 제외됩니다: "
            f"{missing_names}"
        )


# ------------------------------------------------------------
# 탭 4개로 화면 정리
# ------------------------------------------------------------
tab1, tab2, tab3, tab4 = st.tabs(
    ["📌 연도별 지도", "🎞️ 10년 변화 애니메이션", "📈 두 시점 비교", "🔍 읍면동 드릴다운"]
)

# ==============================================================
# 탭 1. 연도 슬라이더 지도
# ==============================================================
with tab1:
    selected_year = st.slider(
        "연도 선택",
        min_value=int(min(year_list)),
        max_value=int(max(year_list)),
        value=int(max(year_list)),
        step=1,
        key="year_slider_tab1",
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

    show_missing_warning(merged_selected, f"{selected_year}년")

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
# 탭 2. 10년 단위 변화 애니메이션
# ==============================================================
with tab2:
    st.caption("재생 버튼을 누르면 10년 간격으로 지도 색이 바뀌는 모습을 볼 수 있어요.")

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

# ==============================================================
# 탭 3. 두 시점 비교 (증감 지도) — 새로 추가
# ==============================================================
with tab3:
    st.caption("두 연도를 골라서, 그 사이 생산가능인구 비율이 얼마나 늘거나 줄었는지 봅니다.")

    col_a, col_b = st.columns(2)
    with col_a:
        start_year = st.selectbox(
            "시작 연도", year_list, index=0, key="start_year_tab3"
        )
    with col_b:
        end_year = st.selectbox(
            "끝 연도", year_list, index=len(year_list) - 1, key="end_year_tab3"
        )

    if start_year == end_year:
        st.info("서로 다른 두 연도를 골라주세요.")
    else:
        ratio_start = compute_ratio(start_year)[["코드", "시군구", "시도", "생산가능인구비율"]]
        ratio_end = compute_ratio(end_year)[["코드", "생산가능인구비율"]]

        diff_df = ratio_start.merge(
            ratio_end, on="코드", how="left", suffixes=("_시작", "_끝")
        )
        # 두 연도 모두 값이 있는 지역만 증감 계산 (하나라도 없으면 비교 불가능)
        diff_df["증감"] = (
            diff_df["생산가능인구비율_끝"] - diff_df["생산가능인구비율_시작"]
        ).round(2)

        # 증감 지도는 "늘었다/줄었다"의 방향과 크기가 핵심이라
        # 5단계 대신 이어지는 그라데이션(발산형 컬러스케일)을 씁니다.
        fig_diff = px.choropleth(
            diff_df,
            geojson=geojson,
            locations="코드",
            featureidkey="properties.코드",
            color="증감",
            color_continuous_scale="RdBu",
            color_continuous_midpoint=0,  # 0을 기준으로 파랑(증가)/빨강(감소) 나뉨
            hover_name="시군구",
            hover_data={"시도": True, "증감": True, "코드": False},
            labels={"증감": "비율 변화(%p)"},
        )
        fig_diff.update_geos(fitbounds="locations", visible=False)
        fig_diff.update_layout(
            margin=dict(l=0, r=0, t=10, b=0),
            height=700,
            coloraxis_colorbar_title="변화(%p)",
        )
        st.plotly_chart(fig_diff, width="stretch")

        show_missing_warning(
            diff_df.rename(columns={"생산가능인구비율_시작": "생산가능인구비율"}),
            f"{start_year}년",
        )

        valid_diff = diff_df.dropna(subset=["증감"])
        c1, c2 = st.columns(2)
        cols = ["시도", "시군구", "증감"]
        with c1:
            st.subheader(f"📈 {start_year}→{end_year}년 가장 많이 늘어난 곳 10")
            st.dataframe(valid_diff.nlargest(10, "증감")[cols].reset_index(drop=True))
        with c2:
            st.subheader(f"📉 {start_year}→{end_year}년 가장 많이 줄어든 곳 10")
            st.dataframe(valid_diff.nsmallest(10, "증감")[cols].reset_index(drop=True))

# ==============================================================
# 탭 4. 읍면동 드릴다운 — 새로 추가
#   (경계 파일에는 읍면동 경계가 없어서 지도 대신 막대그래프로 보여줍니다)
# ==============================================================
with tab4:
    st.caption("시군구 하나를 골라서, 그 안의 읍·면·동별 생산가능인구 비율을 봅니다.")

    col_a, col_b = st.columns(2)
    with col_a:
        drill_year = st.selectbox(
            "연도 선택", year_list, index=len(year_list) - 1, key="drill_year_tab4"
        )
    with col_b:
        # 시도 - 시군구 순서로 고르기 쉽게 표시 문자열 만들기
        names_sorted = names.sort_values(["시도", "시군구"])
        display_options = (names_sorted["시도"] + " " + names_sorted["시군구"]).tolist()
        code_by_display = dict(zip(display_options, names_sorted["코드"]))
        selected_display = st.selectbox("시군구 선택", display_options, key="sigungu_tab4")
        selected_code = code_by_display[selected_display]

    # 선택한 연도의 원본(읍면동 단위) 데이터에서
    # 코드 보정 후 선택한 시군구 코드와 일치하는 행만 골라내기
    d = df[df["연도"] == drill_year].copy()
    d["시군구코드"] = d["코드"].str[:5]
    d["시군구코드_보정"] = d["시군구코드"].apply(remap_code)
    dong_df = d[d["시군구코드_보정"] == selected_code].copy()

    if dong_df.empty:
        st.warning("이 시군구·연도 조합에는 데이터가 없습니다. 다른 연도를 선택해보세요.")
    else:
        dong_df["전체인구"] = dong_df[total_cols].sum(axis=1)
        dong_df["생산가능인구"] = dong_df[working_age_cols].sum(axis=1)

        dong_grouped = (
            dong_df.groupby("동")[["전체인구", "생산가능인구"]].sum().reset_index()
        )
        dong_grouped["생산가능인구비율"] = (
            dong_grouped["생산가능인구"] / dong_grouped["전체인구"] * 100
        ).round(2)
        dong_grouped = dong_grouped.sort_values("생산가능인구비율", ascending=True)

        fig_bar = px.bar(
            dong_grouped,
            x="생산가능인구비율",
            y="동",
            orientation="h",
            labels={"생산가능인구비율": "15~64세 비율(%)", "동": "읍·면·동"},
            title=f"{selected_display} · {drill_year}년 읍·면·동별 생산가능인구 비율",
        )
        fig_bar.update_layout(height=max(400, len(dong_grouped) * 25), margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_bar, width="stretch")

        st.dataframe(
            dong_grouped[["동", "생산가능인구비율"]].reset_index(drop=True)
        )
