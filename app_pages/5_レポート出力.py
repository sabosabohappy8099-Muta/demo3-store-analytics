"""レポート出力:対象月を選んで月次レポート(Excel+所見コメント)を作成する。"""

from __future__ import annotations

import json
from datetime import date
from html import escape

import duckdb
import streamlit as st

from src.ai_comment import Comment, current_provider, generate_comment
from src.charts import kpi_card
from src.config import format_count, format_pct, format_yen_short
from src.filters import persisted, setup_page
from src.queries import available_months
from src.report import build_monthly_summary, build_report

PROVIDER_LABELS = {"MOCK": "ルールベース(MOCK・無料)", "CLAUDE": "Claude(Anthropic API)", "GEMINI": "Gemini(Google API)"}

con, state, _ = setup_page("レポート出力")
st.caption("※月次レポートは全社・全チャネルが対象です(サイドバーの絞り込み条件は反映しません)。")


@st.cache_data(show_spinner=False)
def _summary(_con: duckdb.DuckDBPyConnection, month: date) -> dict:
    """要約データ(月ごとにキャッシュ)。"""
    return build_monthly_summary(_con, month)


@st.cache_data(show_spinner=False, ttl=3600)
def _comment(summary_json: str, provider: str) -> Comment:
    """所見文(同じ要約・方式なら API を再度呼ばない)。"""
    return generate_comment(json.loads(summary_json), provider)


months = available_months(con)
if not months:
    st.info("該当データがありません。")
    st.stop()
labels = {m: f"{m.year}年{m.month}月" for m in months}
c1, c2 = st.columns([1, 2])
with c1:
    month = st.selectbox("対象月", months, format_func=labels.get, **persisted("report_month", months[0], months))
with c2:
    provider = current_provider()
    st.markdown(f"**所見コメントの生成方式**<br>{PROVIDER_LABELS[provider]}", unsafe_allow_html=True)
    st.caption("方式は環境変数または secrets の AI_PROVIDER で切り替えます(MOCK / CLAUDE / GEMINI)。")

if st.button("月次レポートを作成", type="primary"):
    with st.spinner("集計と所見コメントを作成しています…"):
        summary = _summary(con, month)
        comment = _comment(json.dumps(summary, ensure_ascii=False, sort_keys=True), provider)
        excel = build_report(con, month, summary, comment)
    st.session_state["report"] = {"month": month, "summary": summary, "comment": comment, "excel": excel}

report = st.session_state.get("report")
if not report:
    st.info("対象月を選んで「月次レポートを作成」を押してください。")
    st.stop()
if report["month"] != month:
    st.warning(f"表示中のレポートは {labels[report['month']]} のものです。{labels[month]} を作るにはボタンを押してください。")

summary: dict = report["summary"]
comment: Comment = report["comment"]
t = summary["total"]

# --- ダウンロード ---
st.download_button(
    f"Excelをダウンロード({summary['month_label']})",
    report["excel"],
    file_name=f"月次実績レポート_{report['month']:%Y%m}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    type="primary",
)
st.caption("シート構成:サマリー/地域別(都道府県・市区町村)/店舗別(前年比の色分け)/日別推移(グラフ付き)")

# --- プレビュー:主要指標 ---
st.subheader(f"{summary['month_label']}の主要指標(前年同月比)")
cols = st.columns(4)
cards = [
    ("売上", format_yen_short(t["sales"]), t["sales_yoy"]),
    ("既存店売上の前年比", format_pct(t["same_store_sales_yoy"]), t["same_store_sales_yoy"]),
    ("客数", format_count(t["customers"], "人"), t["customers_yoy"]),
    ("客単価", format_count(t["unit_price"], "円"), t["unit_price_yoy"]),
]
for col, (label, value, growth) in zip(cols, cards):
    with col:
        kpi_card(label, value, growth, summary["compare_period"], "前年同月")

# --- プレビュー:所見コメント ---
st.subheader("所見コメント")
st.markdown(
    f"<div style='border:1px solid #EADFC8;border-left:6px solid #B9832A;border-radius:8px;padding:16px 20px;"
    f"background:#FFFDF8;font-size:1.05rem;line-height:1.8'>"
    f"<b>{escape(comment.headline)}</b><ul style='margin:8px 0 0'>"
    + "".join(f"<li>{escape(p)}</li>" for p in comment.points)
    + "</ul></div>",
    unsafe_allow_html=True,
)
st.caption(f"生成方式:{PROVIDER_LABELS[comment.provider]}")
if comment.note:
    st.caption(f"⚠️ {comment.note}")

with st.expander("AIに渡す要約データ(集計済みの数値のみ。生データは送信しません)"):
    st.json(summary, expanded=False)
