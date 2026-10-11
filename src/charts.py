"""グラフ・指標カードなどの表示部品。"""

from __future__ import annotations

from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import (
    COLOR_ACCENT,
    COLOR_COMPARE,
    COLOR_DOWN,
    COLOR_GRID,
    COLOR_SURFACE,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    COLOR_UP,
    FONT_FAMILY,
    WEEKDAY_LABELS,
    delta_color,
    format_delta,
    format_pct,
    format_yen,
)

# Plotly の共通設定(ツールバーは会議での誤操作を避けるため非表示)
PLOTLY_CONFIG = {"displayModeBar": False, "locale": "ja"}

BASE_CSS = f"""
<style>
html, body, [class*="css"] {{ font-size: 17px; }}
.block-container {{ padding-top: 2.2rem; max-width: 1400px; }}
h1 {{ font-size: 2.0rem !important; }}
h2, h3 {{ color: {COLOR_TEXT}; }}
.flt-bar {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 0 0 1rem; }}
.flt-chip {{
  background: #FAF6EE; border: 1px solid #EADFC8; border-radius: 999px;
  padding: 3px 12px; font-size: 0.86rem; color: {COLOR_TEXT};
}}
.flt-chip b {{ color: {COLOR_TEXT_MUTED}; font-weight: 600; margin-right: 4px; }}
.kpi-card {{
  background: {COLOR_SURFACE}; border: 1px solid #EADFC8; border-top: 4px solid {COLOR_ACCENT};
  border-radius: 10px; padding: 14px 18px; height: 100%;
}}
.kpi-label {{ font-size: 0.95rem; color: {COLOR_TEXT_MUTED}; margin-bottom: 4px; }}
.kpi-value {{ font-size: 2.1rem; font-weight: 700; color: {COLOR_TEXT}; line-height: 1.2;
  font-variant-numeric: tabular-nums; }}
.kpi-delta {{ font-size: 1.1rem; font-weight: 700; margin-top: 6px; }}
.kpi-sub {{ font-size: 0.85rem; color: {COLOR_TEXT_MUTED}; margin-top: 2px; }}
</style>
"""


def inject_base_css() -> None:
    """投影でも読みやすい文字サイズなど、全ページ共通のスタイルを適用する。"""
    st.markdown(BASE_CSS, unsafe_allow_html=True)


def kpi_card(label: str, value: str, growth: float | None, compare_text: str, compare_label: str) -> None:
    """指標カード(大きな数値+増減率)を表示する。"""
    color = delta_color(growth)
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{escape(label)}</div>
          <div class="kpi-value">{escape(value)}</div>
          <div class="kpi-delta" style="color:{color}">{escape(format_delta(growth))}</div>
          <div class="kpi-sub">{escape(compare_label)}:{escape(compare_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def stat_card(label: str, value: str, sub: str = "") -> None:
    """増減率を持たない指標のカード(大きな数値+補足)。"""
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{escape(label)}</div>
          <div class="kpi-value">{escape(value)}</div>
          <div class="kpi-sub">{escape(sub)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _base_layout(fig: go.Figure, height: int = 360) -> go.Figure:
    """全グラフ共通の見た目(白背景・控えめな罫線・大きめの文字)を設定する。"""
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=20, t=30, b=10),
        paper_bgcolor=COLOR_SURFACE,
        plot_bgcolor=COLOR_SURFACE,
        font=dict(family=FONT_FAMILY, size=15, color=COLOR_TEXT),
        hoverlabel=dict(font=dict(family=FONT_FAMILY, size=15), bgcolor="white"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
    )
    fig.update_xaxes(showgrid=False, linecolor=COLOR_GRID, tickfont=dict(color=COLOR_TEXT_MUTED))
    fig.update_yaxes(gridcolor=COLOR_GRID, zeroline=False, tickfont=dict(color=COLOR_TEXT_MUTED))
    return fig


def _yen_axis_ticks(max_value: float) -> tuple[list[float], list[str]]:
    """金額軸の目盛りを「万円/億円」表記で作る。"""
    if max_value <= 0:
        return [0], ["0"]
    raw = max_value / 4
    magnitude = 10 ** (len(str(int(raw))) - 1)
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    ticks = [i * step for i in range(int(max_value // step) + 2)]
    return ticks, [format_yen(t) if t else "0" for t in ticks]


def trend_chart(df: pd.DataFrame, current_label: str, compare_label: str) -> go.Figure:
    """当期と比較期間の売上推移を重ねた折れ線グラフ。df は queries.sales_trend の結果。"""
    fig = go.Figure()
    hover_cmp = [format_yen(v) if pd.notna(v) else "—" for v in df["compare"]]
    hover_cur = [format_yen(v) if pd.notna(v) else "—" for v in df["current"]]
    fig.add_trace(
        go.Scatter(
            x=df["label"], y=df["compare"], name=compare_label, mode="lines+markers",
            line=dict(color=COLOR_COMPARE, width=2, dash="dot"), marker=dict(size=8),
            customdata=hover_cmp, hovertemplate=f"{compare_label}:%{{customdata}}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["label"], y=df["current"], name=current_label, mode="lines+markers",
            line=dict(color=COLOR_ACCENT, width=3), marker=dict(size=9, line=dict(color="white", width=2)),
            customdata=hover_cur, hovertemplate=f"{current_label}:%{{customdata}}<extra></extra>",
        )
    )
    ymax = float(pd.concat([df["current"], df["compare"]]).max(skipna=True) or 0)
    tickvals, ticktext = _yen_axis_ticks(ymax)
    fig.update_yaxes(tickvals=tickvals, ticktext=ticktext, rangemode="tozero")
    fig.update_layout(hovermode="x unified")
    # 点が多いときはマーカーを省き、目盛りの数も間引いて読みやすくする
    if len(df) > 40:
        fig.update_traces(mode="lines")
    fig.update_xaxes(nticks=14, tickangle=0)
    return _base_layout(fig, height=380)


def composition_chart(df: pd.DataFrame, colors: dict[str, str]) -> go.Figure:
    """構成比を1本の100%積み上げ横棒で表示する。df は queries.composition の結果。"""
    fig = go.Figure()
    for row in df.itertuples(index=False):
        fig.add_trace(
            go.Bar(
                y=[""], x=[row.share], name=row.key, orientation="h",
                marker=dict(color=colors.get(row.key, COLOR_COMPARE), line=dict(color="white", width=2)),
                # 細すぎる区分は文字が収まらないため、凡例とホバーで確認してもらう
                text=[f"{row.key}<br>{format_pct(row.share, signed=False)}" if row.share >= 0.12 else ""],
                textposition="inside", insidetextanchor="middle", textangle=0,
                textfont=dict(color="white", size=15),
                customdata=[format_yen(row.sales)],
                hovertemplate=f"{row.key}:%{{customdata}}(%{{x:.1%}})<extra></extra>",
            )
        )
    fig.update_layout(barmode="stack", showlegend=True, bargap=0.25, legend_traceorder="normal")
    fig.update_xaxes(visible=False, range=[0, 1])
    fig.update_yaxes(visible=False)
    fig = _base_layout(fig, height=150)
    fig.update_layout(margin=dict(l=0, r=0, t=36, b=0), legend_traceorder="normal")
    return fig


def ranking_chart(df: pd.DataFrame, label_col: str = "store_name") -> go.Figure:
    """増減率の横棒グラフ(増加=緑・減少=赤、数値と▲▼を併記)。

    df には label_col・current・compare・growth の列が必要。上の行から順に上から並べる。
    """
    df = df.iloc[::-1]  # 上から順位順に並べるため反転
    colors = [COLOR_UP if g >= 0 else COLOR_DOWN for g in df["growth"]]
    labels = [format_delta(g) for g in df["growth"]]
    fig = go.Figure(
        go.Bar(
            x=df["growth"], y=df[label_col], orientation="h",
            marker=dict(color=colors), text=labels, textposition="outside", cliponaxis=False,
            textfont=dict(size=15, color=COLOR_TEXT),
            customdata=list(zip([format_yen(v) for v in df["current"]], [format_yen(v) for v in df["compare"]])),
            hovertemplate="%{y}<br>当期:%{customdata[0]}<br>比較:%{customdata[1]}<extra></extra>",
        )
    )
    span = max(abs(df["growth"]).max() if len(df) else 0.1, 0.05)
    fig.update_xaxes(range=[min(0, df["growth"].min()) - span * 0.45, max(0, df["growth"].max()) + span * 0.45],
                     tickformat="+.0%", zeroline=True, zerolinecolor=COLOR_TEXT_MUTED)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0)")
    return _base_layout(fig, height=60 + 44 * len(df))


def weekday_chart(store: pd.DataFrame, peer: pd.DataFrame, store_label: str, peer_label: str) -> go.Figure:
    """曜日別の平均日販を、対象店舗と同業態平均で並べた棒グラフ。

    store・peer は queries.weekday_profile の結果。
    """
    fig = go.Figure()
    for df, label, color in ((peer, peer_label, COLOR_COMPARE), (store, store_label, COLOR_ACCENT)):
        fig.add_trace(
            go.Bar(
                x=list(WEEKDAY_LABELS), y=df["avg_sales"], name=label, marker=dict(color=color),
                customdata=[format_yen(v) if pd.notna(v) else "—" for v in df["avg_sales"]],
                hovertemplate=f"{label}:%{{customdata}}<extra></extra>",
            )
        )
    ymax = float(pd.concat([store["avg_sales"], peer["avg_sales"]]).max(skipna=True) or 0)
    tickvals, ticktext = _yen_axis_ticks(ymax)
    fig.update_yaxes(tickvals=tickvals, ticktext=ticktext)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08, hovermode="x unified")
    return _base_layout(fig, height=340)
