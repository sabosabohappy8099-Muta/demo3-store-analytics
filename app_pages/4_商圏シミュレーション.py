"""商圏シミュレーション:出店候補地の半径内にいる会員・既存店・競合店を集計する。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st

from src.charts import stat_card
from src.config import COLOR_TEXT_MUTED, format_count, format_pct, format_yen
from src.data_loader import load_table
from src.filters import persisted, setup_page
from src.geo import circle_polygon, radius_table, trade_area_stats, with_distance
from src.maps import (
    ACCENT_RGB,
    COMPETITOR_RGB,
    MEMBER_ACTIVE_RGB,
    MEMBER_INACTIVE_RGB,
    circle_layer,
    competitor_layer,
    legend_html,
    make_deck,
    point_layer,
    zoom_for_radius,
)
from src.queries import QueryFilter, region_table

METHODS = ("既存店を選ぶ", "緯度経度を入力", "市区町村の中心点")
RADII = [round(0.5 * i, 1) for i in range(1, 11)]  # 0.5km〜5.0km
KANTO_BOUNDS = {"lat": (34.8, 36.6), "lon": (138.8, 140.9)}
DISCLAIMER = "ダミーデータによる簡易シミュレーションであり、実際の出店判断には追加調査が必要です。"

con, state, store_names = setup_page("商圏シミュレーション")
st.caption(f"※{DISCLAIMER}")

stores = load_table("stores")
members = load_table("members")
competitors = load_table("competitors")

# 既存店の売上は、地域の絞り込みに関係なく全店を対象にする(期間・チャネルのみ反映)
sales = region_table(con, QueryFilter(channels=state.query.channels), state.period, state.compare, "store")
stores = stores.merge(sales[["key", "sales"]], left_on="store_id", right_on="key", how="left").drop(columns="key")
stores["sales"] = stores["sales"].fillna(0)

# ---------------------------------------------------------------------------
# 候補地の指定
# ---------------------------------------------------------------------------
left, right = st.columns([1, 1])
with left:
    method = st.radio("候補地の指定方法", METHODS, horizontal=True, **persisted("ta_method", METHODS[0], list(METHODS)))
with right:
    radius = st.slider("商圏の半径(km)", 0.5, 5.0, step=0.5, format="%.1f km", **persisted("ta_radius", 2.0))

exclude_id: str | None = None
store_ids = stores["store_id"].tolist()
if method == "既存店を選ぶ":
    # 地図上の店舗がクリックされていれば、その店舗を候補地にする。
    # 反映後は地図のキーを変えて選択状態を解除する(選択中は他の点が薄く表示されるため)
    picked = st.session_state.get(f"ta_map_{st.session_state.get('ta_map_ver', 0)}")
    objs = picked.selection.get("objects", {}).get("stores", []) if picked and picked.selection else []
    if objs and objs[0].get("key") in store_ids:
        st.session_state["ta_store"] = objs[0]["key"]
        st.session_state["ta_map_ver"] = st.session_state.get("ta_map_ver", 0) + 1
    sid = st.selectbox(
        "既存店(地図上の店舗をクリックしても選べます)",
        store_ids,
        format_func=lambda s: store_names.get(s, s),
        **persisted("ta_store", store_ids[0], store_ids),
    )
    row = stores.set_index("store_id").loc[sid]
    lat, lon, label = float(row["lat"]), float(row["lon"]), row["store_name"]
    exclude_id = sid
elif method == "緯度経度を入力":
    c1, c2 = st.columns(2)
    lat = c1.number_input("緯度", min_value=-90.0, max_value=90.0, step=0.001, format="%.4f",
                          **persisted("ta_lat", 35.5300))
    lon = c2.number_input("経度", min_value=-180.0, max_value=180.0, step=0.001, format="%.4f",
                          **persisted("ta_lon", 139.6000))
    label = f"指定地点({lat:.4f}, {lon:.4f})"
    if not (KANTO_BOUNDS["lat"][0] <= lat <= KANTO_BOUNDS["lat"][1]
            and KANTO_BOUNDS["lon"][0] <= lon <= KANTO_BOUNDS["lon"][1]):
        st.warning("関東の範囲外の座標です。会員・店舗のデータは関東(東京・神奈川・埼玉・千葉)のみです。", icon="⚠️")
else:
    cities = stores.groupby(["prefecture", "city"], as_index=False)[["lat", "lon"]].mean()
    city_labels = [f"{p} {c}" for p, c in zip(cities["prefecture"], cities["city"])]
    choice = st.selectbox("市区町村", city_labels, **persisted("ta_city", city_labels[0], city_labels))
    row = cities.iloc[city_labels.index(choice)]
    lat, lon, label = float(row["lat"]), float(row["lon"]), f"{choice}の中心点"
    st.caption("※境界データを使わないため、その市区町村にある自社店舗の座標の平均を中心点としています。")

# ---------------------------------------------------------------------------
# 指標
# ---------------------------------------------------------------------------
stats = trade_area_stats(lat, lon, radius, members, stores, competitors, exclude_id)
st.subheader(f"{label} から半径 {radius:g}km の商圏")
own_label = "既存店(候補の店舗を除く)" if exclude_id else "既存店(自社)"
cards = st.columns(4)
with cards[0]:
    stat_card("半径内の会員数", format_count(stats["members"], "人"),
              f"うち直近12ヶ月の来店あり:{format_count(stats['active_members'], '人')}")
with cards[1]:
    stat_card(own_label, format_count(stats["stores"], "店"), f"売上合計:{format_yen(stats['store_sales'])}")
with cards[2]:
    stat_card("半径内の競合店", format_count(stats["competitors"], "店"), "")
with cards[3]:
    stat_card("既存店との商圏の重なり", format_pct(stats["overlap_rate"], signed=False),
              f"半径内の会員のうち、メイン店舗が半径内の既存店:{format_count(stats['overlap_members'], '人')}")
st.caption(
    "※「商圏の重なり」が高いほど、出店した場合に既存店と売上を奪い合う可能性が高いことを示します。"
    f"売上合計は {state.period.label()} の実績です。"
)

# ---------------------------------------------------------------------------
# 地図
# ---------------------------------------------------------------------------
m_in = with_distance(members, lat, lon, "home_lat", "home_lon")
m_in = m_in[m_in["distance_km"] <= radius]
active = m_in[m_in["visits_12m"] > 0].assign(tip="会員(直近12ヶ月の来店あり)")
inactive = m_in[m_in["visits_12m"] == 0].assign(tip="会員(直近12ヶ月の来店なし)")
store_pts = stores.assign(
    key=stores["store_id"],
    tip=[f"{n}\n売上:{format_yen(s)}" for n, s in zip(stores["store_name"], stores["sales"])],
)
center = pd.DataFrame({"lat": [lat], "lon": [lon], "tip": [f"候補地\n{label}"]})

layers = [
    circle_layer(circle_polygon(lat, lon, radius)),
    point_layer(inactive.rename(columns={"home_lat": "lat", "home_lon": "lon"}), "members_inactive",
                MEMBER_INACTIVE_RGB, 2.5, alpha=150, outline=False, pickable=False),
    point_layer(active.rename(columns={"home_lat": "lat", "home_lon": "lon"}), "members_active",
                MEMBER_ACTIVE_RGB, 2.5, alpha=170, outline=False, pickable=False),
    competitor_layer(competitors, radius_px=8),
    point_layer(store_pts, "stores", ACCENT_RGB, 9),
    point_layer(center, "candidate", (43, 43, 43), 11),
]
view = pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom_for_radius(radius))
st.pydeck_chart(
    make_deck(layers, view),
    height=560,
    width="stretch",
    on_select="rerun" if method == "既存店を選ぶ" else "ignore",
    selection_mode="single-object",
    key=f"ta_map_{st.session_state.get('ta_map_ver', 0)}",
)
st.markdown(
    legend_html(
        [
            ("rgb(43,43,43)", "候補地"),
            (f"rgb{ACCENT_RGB}", "自社店舗"),
            (f"rgb{COMPETITOR_RGB}", "競合店"),
            (f"rgb{MEMBER_ACTIVE_RGB}", "会員(来店あり)"),
            (f"rgb{MEMBER_INACTIVE_RGB}", "会員(来店なし)"),
        ]
    ),
    unsafe_allow_html=True,
)
st.caption("※会員の位置は居住地の目安(約100m単位)です。背景地図:© OpenStreetMap contributors © CARTO")

# ---------------------------------------------------------------------------
# 半径ごとの比較表
# ---------------------------------------------------------------------------
st.subheader("半径を変えたときの比較")
table = radius_table(lat, lon, RADII, members, stores, competitors, exclude_id)
view_df = pd.DataFrame(
    {
        "半径": [f"{r:g}km" for r in table["radius_km"]],
        "会員数": table["members"].map(lambda v: format_count(v, "人")),
        "うち来店あり": table["active_members"].map(lambda v: format_count(v, "人")),
        "既存店": table["stores"].map(lambda v: format_count(v, "店")),
        "既存店の売上合計": table["store_sales"].map(format_yen),
        "競合店": table["competitors"].map(lambda v: format_count(v, "店")),
        "商圏の重なり": table["overlap_rate"].map(lambda v: format_pct(v, signed=False)),
    }
)
current = int(np.argmin(np.abs(table["radius_km"].to_numpy() - radius)))
st.dataframe(
    view_df.style.apply(
        lambda r: ["background-color: #F3E6CC; font-weight: 700" if r.name == current else ""] * len(r), axis=1
    ),
    hide_index=True,
    width="stretch",
)
st.caption("※色付きの行が、現在スライダーで選んでいる半径です。")

# 重なりの内訳:半径内の会員がどの既存店をメインにしているか
if stats["members"]:
    st.subheader("半径内の会員のメイン店舗(上位5店)")
    breakdown = (
        m_in.groupby("main_store_id").size().rename("会員数").reset_index()
        .merge(stores[["store_id", "store_name", "lat", "lon"]], left_on="main_store_id", right_on="store_id")
        .sort_values("会員数", ascending=False)
        .head(5)
    )
    breakdown = with_distance(breakdown, lat, lon)
    st.dataframe(
        pd.DataFrame(
            {
                "メイン店舗": breakdown["store_name"],
                "会員数": breakdown["会員数"].map(lambda v: format_count(v, "人")),
                "構成比": (breakdown["会員数"] / stats["members"]).map(lambda v: format_pct(v, signed=False)),
                "候補地からの距離": breakdown["distance_km"].map(lambda v: f"{v:.1f}km"),
                "位置": np.where(
                    breakdown["store_id"] == exclude_id,
                    "候補地の店舗",
                    np.where(breakdown["distance_km"] <= radius, "半径内", "半径外"),
                ),
            }
        ),
        hide_index=True,
        width="stretch",
    )

st.markdown(
    f"<div style='margin-top:1rem;padding:10px 14px;border-left:4px solid #B9832A;background:#FAF6EE;"
    f"color:{COLOR_TEXT_MUTED}'>注記:{DISCLAIMER}</div>",
    unsafe_allow_html=True,
)
