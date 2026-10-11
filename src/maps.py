"""地図部品(pydeck)。背景地図は CARTO の無料ベースマップを使い、APIキーは不要。"""

from __future__ import annotations

from html import escape

import numpy as np
import pandas as pd
import pydeck as pdk

from src.config import COLOR_ACCENT, COLOR_DOWN, COLOR_UP, format_count, format_delta, format_yen

# 関東4都県が収まる初期表示
KANTO_VIEW = pdk.ViewState(latitude=35.76, longitude=139.70, zoom=8.45, pitch=0)

# 増減率の色:赤(減少)〜グレー(横ばい)〜緑(増加)。±15%で色が飽和する
GROWTH_CLIP = 0.15
_NEUTRAL_RGB = (184, 182, 174)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """'#RRGGBB' を (R, G, B) に変換する。"""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


ACCENT_RGB = _hex_to_rgb(COLOR_ACCENT)
UP_RGB = _hex_to_rgb(COLOR_UP)
DOWN_RGB = _hex_to_rgb(COLOR_DOWN)
COMPETITOR_RGB = (74, 58, 167)  # 競合店(紫)
MEMBER_ACTIVE_RGB = (42, 120, 214)  # 来店ありの会員(青)
MEMBER_INACTIVE_RGB = (150, 150, 150)
# 会員密度の色(小麦色の濃淡:薄い→濃い)
HEX_RAMP = [(246, 236, 214), (236, 214, 166), (222, 186, 116), (196, 150, 72), (160, 112, 40), (112, 74, 22)]

TOOLTIP_STYLE = {
    "backgroundColor": "white",
    "color": "#2B2B2B",
    "fontSize": "14px",
    "border": "1px solid #EADFC8",
    "borderRadius": "6px",
    "padding": "8px 10px",
    "whiteSpace": "pre-line",  # Streamlit はツールチップの HTML をエスケープするため、改行で区切る
}


def growth_color(growth: float | None, alpha: int = 210) -> list[int]:
    """増減率を赤〜グレー〜緑の色に変換する。比較できない(新店など)場合は小麦色。"""
    if growth is None or pd.isna(growth):
        return [*ACCENT_RGB, alpha]
    t = float(np.clip(growth / GROWTH_CLIP, -1, 1))
    target = UP_RGB if t > 0 else DOWN_RGB
    w = abs(t)
    rgb = [round(n + (c - n) * w) for n, c in zip(_NEUTRAL_RGB, target)]
    return [*rgb, alpha]


def bubble_radius_m(sales: pd.Series, max_radius_m: float = 3200, min_radius_m: float = 500) -> pd.Series:
    """売上に応じたバブルの半径(m)。面積が売上に比例するよう平方根で変換する。"""
    top = sales.max()
    if not top or pd.isna(top):
        return pd.Series(min_radius_m, index=sales.index)
    return min_radius_m + np.sqrt(sales.clip(lower=0) / top) * (max_radius_m - min_radius_m)


def store_bubble_layer(df: pd.DataFrame, growth_label: str) -> pdk.Layer:
    """店舗バブル(大きさ=売上、色=増減率)。df:key, lat, lon, name, sales, growth, customers"""
    data = df.copy()
    data["radius"] = bubble_radius_m(data["sales"])
    data["color"] = [growth_color(g) for g in data["growth"]]
    data["tip"] = [
        f"{n}\n売上:{format_yen(s)}\n{growth_label}:{format_delta(g)}\n客数:{format_count(c, '人')}"
        for n, s, g, c in zip(data["name"], data["sales"], data["growth"], data["customers"])
    ]
    data = data.sort_values("sales", ascending=False)  # 小さいバブルを上に描く
    return pdk.Layer(
        "ScatterplotLayer",
        id="stores",
        data=data[["lat", "lon", "radius", "color", "tip", "key"]],
        get_position=["lon", "lat"],
        get_radius="radius",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 255],
        line_width_min_pixels=1.5,
        stroked=True,
        pickable=True,
        auto_highlight=True,
    )


def member_hex_layer(hex_df: pd.DataFrame, size_km: float) -> pdk.Layer:
    """会員分布の六角形マス(色の濃さ=会員数)。hex_df は geo.hex_bin の結果(active 列あり)。"""
    data = hex_df.copy()
    # 会員数の大きい少数のマスに色が引っ張られないよう、順位(パーセンタイル)で6段階に分ける
    pct = data["count"].rank(pct=True, method="max").to_numpy() if len(data) else np.array([])
    level = np.minimum((pct * len(HEX_RAMP)).astype(int), len(HEX_RAMP) - 1)
    data["color"] = [[*HEX_RAMP[i], 200] for i in level]
    data["tip"] = [
        f"会員 {format_count(c, '人')}\nうち直近12ヶ月の来店あり:{format_count(a, '人')}\n"
        f"(1マス=半径{size_km:g}kmの六角形)"
        for c, a in zip(data["count"], data["active"])
    ]
    return pdk.Layer(
        "PolygonLayer",
        id="member_hex",
        data=data[["polygon", "color", "tip"]],
        get_polygon="polygon",
        get_fill_color="color",
        get_line_color=[255, 255, 255, 160],
        line_width_min_pixels=0.5,
        stroked=True,
        pickable=True,
        auto_highlight=True,
    )


def point_layer(
    df: pd.DataFrame,
    layer_id: str,
    rgb: tuple[int, int, int],
    radius_px: float,
    tip_col: str = "tip",
    alpha: int = 230,
    outline: bool = True,
    pickable: bool = True,
) -> pdk.Layer:
    """一定サイズ(画面上のピクセル)の点を描く。df:lat, lon, tip"""
    cols = ["lat", "lon", tip_col] + (["key"] if "key" in df.columns else [])
    return pdk.Layer(
        "ScatterplotLayer",
        id=layer_id,
        data=df[cols].rename(columns={tip_col: "tip"}),
        get_position=["lon", "lat"],
        get_radius=1,
        radius_units="pixels",
        radius_min_pixels=radius_px,
        radius_max_pixels=radius_px,
        get_fill_color=[*rgb, alpha],
        get_line_color=[255, 255, 255, 255],
        line_width_min_pixels=1.5 if outline else 0,
        stroked=outline,
        pickable=pickable,
        auto_highlight=pickable,
    )


def competitor_layer(df: pd.DataFrame, radius_px: float = 7) -> pdk.Layer:
    """競合店の点。df:lat, lon, name"""
    data = df.assign(tip=[f"{n}\n競合店" for n in df["name"]])
    return point_layer(data, "competitors", COMPETITOR_RGB, radius_px)


def circle_layer(polygon: list[list[float]]) -> pdk.Layer:
    """商圏の円(半透明の塗り+枠線)。"""
    return pdk.Layer(
        "PolygonLayer",
        id="circle",
        data=[{"polygon": polygon}],
        get_polygon="polygon",
        get_fill_color=[*ACCENT_RGB, 28],
        get_line_color=[*ACCENT_RGB, 255],
        line_width_min_pixels=2.5,
        stroked=True,
        pickable=False,
    )


def make_deck(layers: list[pdk.Layer], view: pdk.ViewState = KANTO_VIEW) -> pdk.Deck:
    """背景地図・ツールチップの設定をそろえた Deck を作る。"""
    return pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_provider="carto",
        map_style=pdk.map_styles.CARTO_LIGHT,
        tooltip={"text": "{tip}", "style": TOOLTIP_STYLE},
    )


def zoom_for_radius(radius_km: float) -> float:
    """商圏の円が画面に収まるズームレベルの目安。"""
    return float(np.clip(13.6 - np.log2(max(radius_km, 0.25)), 9.0, 14.5))


def legend_html(items: list[tuple[str, str]]) -> str:
    """地図の下に置く凡例(色見本+説明)を HTML で作る。items:[(CSSの色, 説明), ...]"""
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:18px">'
        f'<span style="width:14px;height:14px;border-radius:50%;background:{c};'
        f'border:1px solid #fff;box-shadow:0 0 0 1px #ccc"></span>{escape(t)}</span>'
        for c, t in items
    )
    return f'<div style="font-size:0.9rem;color:#2B2B2B;margin:6px 0 2px">{chips}</div>'


def growth_legend_html(growth_label: str) -> str:
    """増減率のグラデーション凡例を HTML で作る。"""
    stops = ", ".join(
        f"rgb({c[0]},{c[1]},{c[2]})" for c in (growth_color(-GROWTH_CLIP), growth_color(0), growth_color(GROWTH_CLIP))
    )
    pct = round(GROWTH_CLIP * 100)
    return (
        '<div style="display:flex;align-items:center;gap:10px;font-size:0.9rem;margin:6px 0">'
        f"<span>色={growth_label}</span><span>▼ -{pct}%以下</span>"
        f'<span style="width:180px;height:12px;border-radius:6px;background:linear-gradient(90deg,{stops})"></span>'
        f"<span>▲ +{pct}%以上</span>"
        f'<span style="margin-left:14px;display:inline-flex;align-items:center;gap:6px">'
        f'<span style="width:12px;height:12px;border-radius:50%;background:{COLOR_ACCENT}"></span>比較データなし(新店)</span>'
        "<span style='margin-left:14px;color:#6B6A65'>大きさ=売上</span></div>"
    )
