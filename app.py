"""トップページ(全体サマリー)と、ページ一覧(ナビゲーション)の定義。"""

from __future__ import annotations

import streamlit as st

from src.charts import (
    PLOTLY_CONFIG,
    composition_chart,
    kpi_card,
    ranking_chart,
    trend_chart,
)
from src.config import CHANNEL_COLORS, FORMAT_COLORS, format_count, format_yen_short
from src.filters import setup_page
from src.queries import composition, kpi_with_comparison, sales_trend, store_growth_ranking


def render_summary() -> None:
    """全体サマリーページを描画する。"""
    con, state, _ = setup_page("全体サマリー")

    kpi = kpi_with_comparison(con, state.query, state.period, state.compare)
    if not kpi["sales"]["current"]:
        st.info("該当データがありません。絞り込み条件を見直してください。")
        st.stop()

    # --- 指標カード ---
    cmp_label = state.compare_mode
    cards = [
        ("売上", format_yen_short, "sales"),
        ("客数", lambda v: format_count(v, "人"), "customers"),
        ("客単価", lambda v: format_count(v, "円"), "unit_price"),
        ("店舗あたり売上", format_yen_short, "sales_per_store"),
    ]
    for col, (label, fmt, key) in zip(st.columns(4), cards):
        with col:
            k = kpi[key]
            kpi_card(label, fmt(k["current"]), k["growth"], fmt(k["compare"]), cmp_label)
    st.caption(f"営業店舗数:{kpi['stores']['current']}店(期間中に売上のあった店舗)")

    # --- 売上推移 ---
    grain = "day" if state.period.days <= 62 else "month"
    st.subheader("日別の売上推移" if grain == "day" else "月別の売上推移")
    trend = sales_trend(con, state.query, state.period, state.compare, grain)
    st.plotly_chart(trend_chart(trend, "当期", cmp_label), width="stretch", config=PLOTLY_CONFIG)

    # --- 構成比 ---
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("業態別の構成比")
        st.plotly_chart(
            composition_chart(composition(con, state.query, state.period, "format"), FORMAT_COLORS),
            width="stretch", config=PLOTLY_CONFIG,
        )
    with c2:
        st.subheader("チャネル別の構成比")
        st.plotly_chart(
            composition_chart(composition(con, state.query, state.period, "channel"), CHANNEL_COLORS),
            width="stretch", config=PLOTLY_CONFIG,
        )

    # --- 伸び率ランキング ---
    st.subheader(f"店舗の伸び率ランキング({cmp_label}比)")
    ranking = store_growth_ranking(con, state.query, state.period, state.compare)
    if ranking.empty:
        st.info("比較期間のデータがないため、ランキングを表示できません。")
    else:
        top = ranking.head(5)
        bottom = ranking[~ranking["store_id"].isin(top["store_id"])].tail(5).iloc[::-1]
        r1, r2 = st.columns(2)
        with r1:
            st.markdown("**上位5店**")
            st.plotly_chart(ranking_chart(top), width="stretch", config=PLOTLY_CONFIG)
        with r2:
            st.markdown("**下位5店**")
            if bottom.empty:
                st.caption("該当する店舗がありません")
            else:
                st.plotly_chart(ranking_chart(bottom), width="stretch", config=PLOTLY_CONFIG)
        st.caption("※比較期間に売上がない店舗(新店など)はランキングの対象外です。")


# ページ一覧(サイドバーのメニュー表示名を日本語にするため st.navigation を使う)
navigation = st.navigation(
    [
        st.Page(render_summary, title="全体サマリー", icon="📊", default=True),
        st.Page("app_pages/1_地域別分析.py", title="地域別分析", icon="🗾", url_path="region"),
        st.Page("app_pages/2_店舗詳細.py", title="店舗詳細", icon="🏪", url_path="store"),
        st.Page("app_pages/3_地図分析.py", title="地図分析", icon="🗺️", url_path="map"),
        st.Page("app_pages/4_商圏シミュレーション.py", title="商圏シミュレーション", icon="📍", url_path="trade-area"),
        st.Page("app_pages/5_レポート出力.py", title="レポート出力", icon="📄", url_path="report"),
    ]
)
navigation.run()
