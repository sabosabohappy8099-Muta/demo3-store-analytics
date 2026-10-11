"""店舗詳細:1店舗の推移・曜日別・チャネル構成と、同業態との比較。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.charts import PLOTLY_CONFIG, composition_chart, kpi_card, trend_chart, weekday_chart
from src.config import (
    CHANNEL_COLORS,
    COLOR_DOWN,
    COLOR_NEUTRAL,
    COLOR_UP,
    format_count,
    format_delta,
    format_pct,
    format_yen,
    format_yen_short,
)
from src.filters import setup_page
from src.queries import (
    QueryFilter,
    composition,
    filter_options,
    format_peer_stats,
    growth,
    kpi_with_comparison,
    sales_trend,
    store_info,
    weekday_profile,
)

con, state, store_names = setup_page("店舗詳細")
q = state.query
cmp_label = state.compare_mode

# ---------------------------------------------------------------------------
# 店舗の選択(サイドバーの地域・業態・店舗の条件で候補を絞る)
# ---------------------------------------------------------------------------
options = [sid for sid, _ in filter_options(con, q.prefectures, q.cities, q.formats)["stores"]]
if q.store_ids:
    options = [sid for sid in options if sid in q.store_ids]
if not options:
    st.info("該当データがありません。絞り込み条件を見直してください。")
    st.stop()

# ページを移動しても選択を保持するため、保存用キーからウィジェットへ書き戻す
if st.session_state.get("detail_store") not in options:
    st.session_state["detail_store"] = options[0]
st.session_state["w_detail_store"] = st.session_state["detail_store"]


def _sync_store() -> None:
    """選択された店舗を保存用キーへコピーする。"""
    st.session_state["detail_store"] = st.session_state["w_detail_store"]


store_id = st.selectbox(
    "店舗を選択",
    options,
    key="w_detail_store",
    on_change=_sync_store,
    format_func=lambda sid: f"{store_names.get(sid, sid)}({sid})",
)
info = store_info(con, store_id)
fmt = info["format"]
store_name = info["store_name"]

f_store = QueryFilter(store_ids=(store_id,), channels=q.channels)
f_peer = QueryFilter(formats=(fmt,), channels=q.channels)

# ---------------------------------------------------------------------------
# 基本情報と順位
# ---------------------------------------------------------------------------
peers = format_peer_stats(con, store_id, q.channels, state.period, state.compare)
me = peers[peers["store_id"] == store_id]

c1, c2, c3, c4 = st.columns(4)
c1.markdown(f"**業態**<br>{fmt}", unsafe_allow_html=True)
c2.markdown(f"**所在地**<br>{info['prefecture']} {info['city']}", unsafe_allow_html=True)
c3.markdown(f"**開店日**<br>{pd.Timestamp(info['open_date']):%Y年%m月%d日}", unsafe_allow_html=True)
c4.markdown(f"**席数**<br>{info['seats']}席", unsafe_allow_html=True)
st.write("")

kpi = kpi_with_comparison(con, f_store, state.period, state.compare)
if not kpi["sales"]["current"]:
    st.info(f"選択した期間に {store_name} の売上データがありません(開店前・休業中など)。期間を変更してください。")
    st.stop()

cards = [
    ("売上", format_yen_short, "sales"),
    ("客数", lambda v: format_count(v, "人"), "customers"),
    ("客単価", lambda v: format_count(v, "円"), "unit_price"),
]
cols = st.columns(4)
for col, (label, fmt_fn, key) in zip(cols, cards):
    with col:
        k = kpi[key]
        kpi_card(label, fmt_fn(k["current"]), k["growth"], fmt_fn(k["compare"]), cmp_label)

# 同業態の中での順位カード
with cols[3]:
    n_sales = len(peers)
    n_growth = int(peers["growth"].notna().sum())
    sales_rank = int(me["sales_rank"].iloc[0]) if not me.empty else None
    growth_rank = me["growth_rank"].iloc[0] if not me.empty else None
    growth_text = (
        f"伸び率:{int(growth_rank)}位 / {n_growth}店" if pd.notna(growth_rank) else "伸び率:比較データなし"
    )
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">同業態({fmt})の中での順位</div>
          <div class="kpi-value">{sales_rank}位<span style="font-size:1.1rem;font-weight:500"> / {n_sales}店</span></div>
          <div class="kpi-delta" style="color:{COLOR_NEUTRAL}">売上の順位</div>
          <div class="kpi-sub">{growth_text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# 推移
# ---------------------------------------------------------------------------
st.subheader("売上の推移")
tabs = st.tabs(["日別", "週別", "月別"])
for tab, grain in zip(tabs, ("day", "week", "month")):
    with tab:
        trend = sales_trend(con, f_store, state.period, state.compare, grain)
        st.plotly_chart(trend_chart(trend, "当期", cmp_label), width="stretch", config=PLOTLY_CONFIG,
                        key=f"trend_{grain}")
        if grain == "week":
            st.caption("※週は期間の開始日から7日ごとに区切っています(最終週は7日未満の場合があります)。")

# ---------------------------------------------------------------------------
# 曜日別・チャネル構成
# ---------------------------------------------------------------------------
left, right = st.columns(2)
with left:
    st.subheader("曜日別の平均日販")
    st.plotly_chart(
        weekday_chart(
            weekday_profile(con, f_store, state.period),
            weekday_profile(con, f_peer, state.period),
            store_name.removeprefix("こむぎ堂 "),
            f"{fmt}の平均",
        ),
        width="stretch", config=PLOTLY_CONFIG,
    )
    st.caption("※1営業日あたりの平均売上。休業日(売上ゼロ)は除いています。")
with right:
    st.subheader("チャネル構成")
    st.markdown(f"**{store_name.removeprefix('こむぎ堂 ')}**")
    st.plotly_chart(
        composition_chart(composition(con, f_store, state.period, "channel"), CHANNEL_COLORS),
        width="stretch", config=PLOTLY_CONFIG, key="comp_store",
    )
    st.markdown(f"**{fmt}の平均**")
    st.plotly_chart(
        composition_chart(composition(con, f_peer, state.period, "channel"), CHANNEL_COLORS),
        width="stretch", config=PLOTLY_CONFIG, key="comp_peer",
    )

# ---------------------------------------------------------------------------
# 同業態平均との比較
# ---------------------------------------------------------------------------
st.subheader(f"同業態({fmt}・{len(peers)}店)の平均との比較")
peer_avg = {
    "sales": peers["sales"].mean(),
    "customers": peers["customers"].mean(),
    "unit_price": peers["sales"].sum() / peers["customers"].sum() if peers["customers"].sum() else None,
    "mobile_share": (peers["sales"] * peers["mobile_share"]).sum() / peers["sales"].sum(),
    "growth": peers["growth"].mean(),
}
mine = me.iloc[0]
rows = [
    ("売上", format_yen(mine["sales"]), format_yen(peer_avg["sales"]), growth(mine["sales"], peer_avg["sales"])),
    ("客数", format_count(mine["customers"], "人"), format_count(peer_avg["customers"], "人"),
     growth(mine["customers"], peer_avg["customers"])),
    ("客単価", format_count(mine["unit_price"], "円"), format_count(peer_avg["unit_price"], "円"),
     growth(mine["unit_price"], peer_avg["unit_price"])),
    ("モバイルオーダー比率", format_pct(mine["mobile_share"], signed=False),
     format_pct(peer_avg["mobile_share"], signed=False), None),
    (f"{cmp_label}比", format_delta(mine["growth"]), format_delta(peer_avg["growth"]), None),
]
diffs = [r[3] for r in rows]
compare_df = pd.DataFrame(rows, columns=["指標", "この店舗", "同業態の平均", "平均との差"])


def _diff_text(v: float | None) -> str:
    """平均との差を「平均より +12.3%」の形で表示する。"""
    return "—" if v is None or pd.isna(v) else f"平均より {format_delta(v)}"


def _diff_style(v: float | None) -> str:
    """平均との差の文字色。"""
    if v is None or pd.isna(v) or v == 0:
        return f"color: {COLOR_NEUTRAL}"
    return f"color: {COLOR_UP if v > 0 else COLOR_DOWN}; font-weight: 700"


st.dataframe(
    # 欠損値が「None」と表示されないよう、文字列に変換してから色だけ元の数値で付ける
    compare_df.assign(平均との差=[_diff_text(v) for v in diffs]).style.apply(
        lambda _: [_diff_style(v) for v in diffs], subset=["平均との差"]
    ),
    hide_index=True,
    width="stretch",
)

with st.expander(f"{fmt}の全店舗の順位を見る"):
    rank_df = pd.DataFrame(
        {
            "売上順位": peers["sales_rank"].astype(int),
            "店舗": peers["store_name"],
            "売上": peers["sales"].map(format_yen),
            f"{cmp_label}比": peers["growth"].map(format_delta),
            "伸び率順位": peers["growth_rank"].map(lambda v: "—" if pd.isna(v) else f"{int(v)}位"),
        }
    )
    st.dataframe(
        rank_df.style.apply(
            lambda r: ["background-color: #F3E6CC" if peers.iloc[r.name]["store_id"] == store_id else ""] * len(r),
            axis=1,
        ),
        hide_index=True,
        width="stretch",
    )
