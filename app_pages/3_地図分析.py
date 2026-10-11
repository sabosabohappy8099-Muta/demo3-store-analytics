"""地図分析:店舗バブル・会員分布(六角形で集計)・競合店を地図に表示する。"""

from __future__ import annotations

import streamlit as st

from src.data_loader import load_table
from src.filters import persisted, setup_page
from src.geo import hex_bin
from src.maps import (
    COMPETITOR_RGB,
    competitor_layer,
    growth_legend_html,
    legend_html,
    make_deck,
    member_hex_layer,
    store_bubble_layer,
)
from src.queries import region_table

LAYER_OPTIONS = ("店舗バブル", "会員の分布", "競合店")
HEX_SIZE_KM = 1.0

con, state, store_names = setup_page("地図分析")
growth_label = "前年比" if state.compare_mode == "前年同期間" else "前期比"

# 表示するレイヤーの切り替え(ページを移動しても保持する)
shown = st.pills(
    "表示する内容(複数選択できます)",
    LAYER_OPTIONS,
    selection_mode="multi",
    **persisted("map_layers", ["店舗バブル"], list(LAYER_OPTIONS)),
)

# --- データ準備(サイドバーの条件を反映) ---
stores_master = load_table("stores")
store_df = region_table(con, state.query, state.period, state.compare, "store")
store_df = store_df.merge(stores_master[["store_id", "lat", "lon"]], left_on="key", right_on="store_id")

layers = []
if "会員の分布" in shown:
    members = load_table("members")
    # 絞り込み後の店舗をメイン店舗にしている会員だけを集計する
    members = members[members["main_store_id"].isin(store_df["key"])]
    if not members.empty:
        hexes = hex_bin(
            members["home_lat"], members["home_lon"], HEX_SIZE_KM,
            weights={"active": (members["visits_12m"] > 0).astype(int)},
        )
        layers.append(member_hex_layer(hexes, HEX_SIZE_KM))
if "競合店" in shown:
    layers.append(competitor_layer(load_table("competitors")))
if "店舗バブル" in shown and not store_df.empty:
    layers.append(store_bubble_layer(store_df, growth_label))

if not shown:
    st.info("表示する内容を1つ以上選んでください。")
elif store_df.empty and "競合店" not in shown:
    st.info("該当データがありません。絞り込み条件を見直してください。")
else:
    st.pydeck_chart(make_deck(layers), height=620, width="stretch")

    # 凡例
    if "店舗バブル" in shown:
        st.markdown(growth_legend_html(growth_label), unsafe_allow_html=True)
    extra = []
    if "会員の分布" in shown:
        extra.append(("#C49648", f"会員の分布(1マス=半径{HEX_SIZE_KM:g}kmの六角形。色が濃いほど会員が多い)"))
    if "競合店" in shown:
        extra.append((f"rgb{COMPETITOR_RGB}", "競合店"))
    if extra:
        st.markdown(legend_html(extra), unsafe_allow_html=True)
    st.caption("※地図にマウスを乗せると詳細が表示されます。背景地図:© OpenStreetMap contributors © CARTO")

# --- 地図の下に要約 ---
if not store_df.empty:
    c1, c2, c3 = st.columns(3)
    c1.metric("表示中の店舗数", f"{len(store_df)}店")
    with_growth = store_df.dropna(subset=["growth"])
    c2.metric(f"{growth_label}プラスの店舗", f"{int((with_growth['growth'] > 0).sum())}店")
    c3.metric(f"{growth_label}マイナスの店舗", f"{int((with_growth['growth'] < 0).sum())}店")
