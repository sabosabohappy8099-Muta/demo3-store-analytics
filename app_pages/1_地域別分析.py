"""地域別分析:都道府県 → 市区町村 → 店舗 のドリルダウン。"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import streamlit as st

from src.charts import PLOTLY_CONFIG, ranking_chart
from src.config import COLOR_DOWN, COLOR_NEUTRAL, COLOR_UP, format_count, format_delta, format_pct, format_yen
from src.filters import setup_page
from src.queries import region_table

LEVEL_LABELS = {"prefecture": "都道府県", "city": "市区町村", "store": "店舗"}

con, state, store_names = setup_page("地域別分析")
growth_label = "前年比" if state.compare_mode == "前年同期間" else "前期比"


# ---------------------------------------------------------------------------
# ドリルダウンの状態
# ---------------------------------------------------------------------------
def go_to(pref: str | None, city: str | None) -> None:
    """表示する階層を切り替える(パンくずリストのボタン用)。"""
    st.session_state["drill_pref"] = pref
    st.session_state["drill_city"] = city


drill_pref: str | None = st.session_state.get("drill_pref")
drill_city: str | None = st.session_state.get("drill_city")

# サイドバーの条件変更で、選んでいた地域が対象外になった場合は上の階層に戻す
q = state.query
if drill_pref and q.prefectures and drill_pref not in q.prefectures:
    drill_pref, drill_city = None, None
if drill_city and q.cities and drill_city not in q.cities:
    drill_city = None
go_to(drill_pref, drill_city)

if drill_city:
    level, f = "store", replace(q, prefectures=(drill_pref,), cities=(drill_city,))
elif drill_pref:
    level, f = "city", replace(q, prefectures=(drill_pref,))
else:
    level, f = "prefecture", q

# パンくずリスト
crumbs: list[tuple[str, str | None, str | None]] = [("関東全体", None, None)]
if drill_pref:
    crumbs.append((drill_pref, drill_pref, None))
if drill_city:
    crumbs.append((drill_city, drill_pref, drill_city))
cols = st.columns([1.3] * len(crumbs) + [8 - 1.3 * len(crumbs)])
for i, (label, pref, city) in enumerate(crumbs):
    is_current = i == len(crumbs) - 1
    cols[i].button(
        ("📍 " if is_current else "") + label + ("" if is_current else " ›"),
        key=f"crumb_{i}",
        on_click=go_to,
        args=(pref, city),
        disabled=is_current,
        width="stretch",
    )

# ---------------------------------------------------------------------------
# 表
# ---------------------------------------------------------------------------
df = region_table(con, f, state.period, state.compare, level)
if df.empty:
    st.info("該当データがありません。絞り込み条件を見直してください。")
    st.stop()

level_label = LEVEL_LABELS[level]
st.subheader(f"{level_label}別の実績")
if level != "store":
    st.caption(f"行を選ぶと、その{level_label}の内訳に移動します。")
else:
    st.caption("行を選ぶと、その店舗の詳細ページへ移動できます。")

table = pd.DataFrame(
    {
        level_label: df["name"],
        "売上": df["sales"],
        growth_label: df["growth"],
        "客数": df["customers"],
        "客単価": df["unit_price"],
        "店舗数": df["stores"],
        "構成比": df["share"],
    }
)


def _growth_style(v: float) -> str:
    """増減率の文字色(増加=緑、減少=赤)。"""
    if pd.isna(v) or v == 0:
        return f"color: {COLOR_NEUTRAL}"
    return f"color: {COLOR_UP if v > 0 else COLOR_DOWN}; font-weight: 700"


styled = table.style.format(
    {
        "売上": format_yen,
        growth_label: format_delta,
        "客数": lambda v: format_count(v, "人"),
        "客単価": lambda v: format_count(v, "円"),
        "店舗数": lambda v: format_count(v, "店"),
        "構成比": lambda v: format_pct(v, signed=False),
    }
).map(_growth_style, subset=[growth_label])

event = st.dataframe(
    styled,
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
    key=f"region_table_{level}_{drill_pref}_{drill_city}",
)

selected = event.selection.rows if event else []
if selected:
    row = df.iloc[selected[0]]
    if level == "prefecture":
        go_to(row["key"], None)
        st.rerun()
    elif level == "city":
        go_to(drill_pref, row["key"])
        st.rerun()
    else:
        if st.button(f"「{row['name']}」の詳細を見る →", type="primary"):
            st.session_state["detail_store"] = row["key"]
            st.switch_page("app_pages/2_店舗詳細.py")

# CSV ダウンロード(Excel で文字化けしないよう BOM 付き UTF-8)
csv_df = table.copy()
csv_df[growth_label] = (csv_df[growth_label] * 100).round(1)
csv_df["構成比"] = (csv_df["構成比"] * 100).round(1)
csv_df["客単価"] = csv_df["客単価"].round(0)
csv_df = csv_df.rename(columns={"売上": "売上(円)", growth_label: f"{growth_label}(%)", "構成比": "構成比(%)",
                                "客数": "客数(人)", "客単価": "客単価(円)"})
area = "_".join(x for x in ("関東全体", drill_pref, drill_city) if x)
st.download_button(
    "表をCSVでダウンロード",
    csv_df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"地域別実績_{area}_{state.period.start:%Y%m%d}-{state.period.end:%Y%m%d}.csv",
    mime="text/csv",
)

# ---------------------------------------------------------------------------
# 増減率の棒グラフ
# ---------------------------------------------------------------------------
st.subheader(f"{level_label}別の{growth_label}")
chart_df = df.dropna(subset=["growth"]).sort_values("growth", ascending=False)
chart_df = chart_df.rename(columns={"sales": "current"})
if chart_df.empty:
    st.info("比較期間のデータがないため、グラフを表示できません。")
else:
    st.plotly_chart(ranking_chart(chart_df, label_col="name"), width="stretch", config=PLOTLY_CONFIG)
    missing = df[df["growth"].isna()]["name"].tolist()
    if missing:
        st.caption(f"※比較期間に売上がないため対象外:{'、'.join(missing)}")
