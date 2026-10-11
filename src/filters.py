"""サイドバーの共通フィルターと、「現在の絞り込み条件」の表示。

Streamlit はページを移動するとウィジェットの値を破棄するため、
値は別のキー(flt_*)に保存しておき、各ページで描画する前にウィジェットへ書き戻す。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape

import duckdb
import streamlit as st

from src.charts import inject_base_css
from src.config import APP_TITLE, CHANNELS, COMPARE_MODES, FORMATS, PERIOD_PRESETS, PREFECTURES
from src.data_loader import get_cursor
from src.queries import Period, QueryFilter, comparison_period, data_date_range, filter_options, resolve_period

# 保存用キーと初期値
DEFAULTS: dict[str, object] = {
    "flt_preset": "直近3ヶ月",
    "flt_custom": None,
    "flt_compare": "前年同期間",
    "flt_prefs": [],
    "flt_cities": [],
    "flt_formats": [],
    "flt_channels": [],
    "flt_stores": [],
}


@dataclass(frozen=True)
class FilterState:
    """画面で選ばれている絞り込み条件一式。"""

    query: QueryFilter
    period: Period
    compare: Period
    preset: str
    compare_mode: str
    data_start: date
    data_end: date

    @property
    def compare_is_partial(self) -> bool:
        """比較期間の一部がデータの範囲外かどうか。"""
        return self.compare.start < self.data_start


def _widget_key(key: str) -> str:
    """保存用キーに対応するウィジェットのキー。"""
    return f"w_{key}"


def _sync(key: str) -> None:
    """ウィジェットの値を保存用キーへコピーする(on_change 用)。"""
    st.session_state[key] = st.session_state[_widget_key(key)]


def _prepare(key: str, valid: list | None = None) -> str:
    """保存値をウィジェットへ書き戻し、ウィジェットのキーを返す。

    valid を渡すと、選択肢に存在しない値(上位の条件変更で無効になったもの)を取り除く。
    """
    if key not in st.session_state:
        st.session_state[key] = DEFAULTS[key]
    value = st.session_state[key]
    if valid is not None and isinstance(value, list):
        value = [v for v in value if v in valid]
        st.session_state[key] = value
    st.session_state[_widget_key(key)] = value
    return _widget_key(key)


def reset_filters() -> None:
    """すべての絞り込み条件を初期値に戻す。"""
    for key, default in DEFAULTS.items():
        st.session_state[key] = default


def render_sidebar(con: duckdb.DuckDBPyConnection) -> FilterState:
    """サイドバーに共通フィルターを描画し、選択された条件を返す。"""
    data_start, data_end = data_date_range(con)
    sb = st.sidebar
    sb.header("絞り込み条件")

    # --- 期間 ---
    preset = sb.selectbox(
        "期間", PERIOD_PRESETS, key=_prepare("flt_preset"), on_change=_sync, args=("flt_preset",)
    )
    custom: tuple[date, date] | None = None
    if preset == "カスタム":
        if st.session_state.get("flt_custom") is None:
            st.session_state["flt_custom"] = (data_end.replace(day=1), data_end)
        picked = sb.date_input(
            "開始日〜終了日",
            min_value=data_start,
            max_value=data_end,
            key=_prepare("flt_custom"),
            on_change=_sync,
            args=("flt_custom",),
            format="YYYY/MM/DD",
        )
        # 開始日だけ選んだ途中の状態では、その1日を期間とみなす
        if isinstance(picked, (tuple, list)):
            custom = (picked[0], picked[-1]) if picked else (data_end, data_end)
        else:
            custom = (picked, picked)
    period = resolve_period(preset, data_end, custom)

    compare_mode = sb.radio(
        "比較対象", COMPARE_MODES, key=_prepare("flt_compare"), on_change=_sync, args=("flt_compare",),
        horizontal=True,
    )
    compare = comparison_period(period, compare_mode)

    sb.divider()

    # --- エリア・業態・チャネル・店舗 ---
    prefs = sb.multiselect(
        "都道府県", PREFECTURES, key=_prepare("flt_prefs", list(PREFECTURES)), on_change=_sync,
        args=("flt_prefs",), placeholder="すべて",
    )
    opts = filter_options(con, tuple(prefs))
    cities = sb.multiselect(
        "市区町村", opts["cities"], key=_prepare("flt_cities", opts["cities"]), on_change=_sync,
        args=("flt_cities",), placeholder="すべて",
    )
    formats = sb.multiselect(
        "業態", FORMATS, key=_prepare("flt_formats", list(FORMATS)), on_change=_sync,
        args=("flt_formats",), placeholder="すべて",
    )
    channels = sb.multiselect(
        "チャネル", CHANNELS, key=_prepare("flt_channels", list(CHANNELS)), on_change=_sync,
        args=("flt_channels",), placeholder="すべて",
    )
    store_opts = filter_options(con, tuple(prefs), tuple(cities), tuple(formats))["stores"]
    store_names = dict(store_opts)
    stores = sb.multiselect(
        "店舗", list(store_names), key=_prepare("flt_stores", list(store_names)), on_change=_sync,
        args=("flt_stores",), placeholder="すべて", format_func=lambda sid: store_names.get(sid, sid),
    )

    sb.button("条件をリセット", on_click=reset_filters, width="stretch")
    sb.caption(f"データ期間:{data_start:%Y/%m/%d}〜{data_end:%Y/%m/%d}")

    query = QueryFilter(
        prefectures=tuple(prefs),
        cities=tuple(cities),
        formats=tuple(formats),
        channels=tuple(channels),
        store_ids=tuple(stores),
    )
    return FilterState(query, period, compare, preset, compare_mode, data_start, data_end)


def _describe(values: tuple[str, ...], limit: int = 3) -> str:
    """選択値を短い文字列にまとめる(多い場合は「ほかN件」)。"""
    if not values:
        return "すべて"
    if len(values) <= limit:
        return "・".join(values)
    return "・".join(values[:limit]) + f" ほか{len(values) - limit}件"


def render_filter_summary(state: FilterState, store_names: dict[str, str] | None = None) -> None:
    """ページ上部に「現在の絞り込み条件」を表示する。"""
    q = state.query
    store_labels = tuple((store_names or {}).get(s, s) for s in q.store_ids)
    items = [
        ("期間", f"{state.preset}({state.period.label()})"),
        ("比較", f"{state.compare_mode}({state.compare.label()})"),
        ("都道府県", _describe(q.prefectures)),
        ("市区町村", _describe(q.cities)),
        ("業態", _describe(q.formats)),
        ("チャネル", _describe(q.channels)),
        ("店舗", _describe(store_labels)),
    ]
    chips = "".join(
        f'<span class="flt-chip"><b>{escape(k)}</b> {escape(v)}</span>' for k, v in items
    )
    st.markdown(f'<div class="flt-bar">{chips}</div>', unsafe_allow_html=True)
    if state.compare_is_partial:
        st.warning(
            f"比較期間({state.compare.label()})の一部が、データの開始日({state.data_start:%Y/%m/%d})より前です。"
            "比較値・増減率は参考値としてご覧ください。",
            icon="⚠️",
        )


def setup_page(title: str) -> tuple[duckdb.DuckDBPyConnection, FilterState, dict[str, str]]:
    """各ページ共通の初期化(ページ設定・共通スタイル・サイドバー・見出し・絞り込み条件の表示)。

    返り値:(DuckDB カーソル, 絞り込み条件, 店舗ID→店舗名の辞書)
    """
    st.set_page_config(page_title=f"{title}|{APP_TITLE}", page_icon="🥐", layout="wide")
    inject_base_css()
    try:
        con = get_cursor()
    except FileNotFoundError as e:
        st.title(title)
        st.error(f"データを読み込めませんでした。{e}", icon="🚫")
        st.stop()
    except Exception as e:  # Parquet の破損など想定外のエラー
        st.title(title)
        st.error(f"データの読み込み中にエラーが発生しました({type(e).__name__})。管理者にお問い合わせください。", icon="🚫")
        st.stop()
    state = render_sidebar(con)
    store_names = dict(con.execute("SELECT store_id, store_name FROM stores").fetchall())
    st.title(title)
    st.caption(f"{APP_TITLE} ※架空の会社・ダミーデータによるデモです")
    render_filter_summary(state, store_names)
    return con, state, store_names


def persisted(key: str, default: object, valid: list | None = None) -> dict[str, object]:
    """ページを移動しても値を保持したいウィジェット用の引数(key / on_change / args)を返す。

    使い方:st.slider("半径", 0.5, 5.0, **persisted("ta_radius", 2.0))
    valid を渡すと、保存値が選択肢にない場合は初期値に戻す。
    """
    if key not in st.session_state:
        st.session_state[key] = default
    if valid is not None:
        value = st.session_state[key]
        if isinstance(value, list):
            st.session_state[key] = [v for v in value if v in valid]
        elif value not in valid:
            st.session_state[key] = default
    st.session_state[_widget_key(key)] = st.session_state[key]
    return {"key": _widget_key(key), "on_change": _sync, "args": (key,)}
