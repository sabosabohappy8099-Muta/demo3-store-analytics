"""DuckDB による集計関数と、期間計算のユーティリティ。

Streamlit に依存しない純粋な関数だけを置き、pytest から直接テストできるようにしている。
集計対象のテーブル:
    sales  … 日次売上に店舗属性(店舗名・業態・都道府県・市区町村)を結合したもの
    stores … 店舗マスタ
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb
import pandas as pd


# ---------------------------------------------------------------------------
# 期間
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Period:
    """集計期間(両端を含む)。"""

    start: date
    end: date

    @property
    def days(self) -> int:
        """期間の日数。"""
        return (self.end - self.start).days + 1

    def label(self) -> str:
        """画面表示用のラベル。"""
        return f"{self.start:%Y/%m/%d}〜{self.end:%Y/%m/%d}"


def _month_end(d: date) -> date:
    """その月の末日を返す。"""
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def _add_months(d: date, months: int) -> date:
    """月を加算する(日が存在しない場合は月末に丸める)。"""
    total = d.year * 12 + (d.month - 1) + months
    y, m = divmod(total, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def resolve_period(preset: str, latest: date, custom: tuple[date, date] | None = None) -> Period:
    """期間プリセットを具体的な日付範囲に変換する。

    「今月」などの基準日は、実行日ではなくデータの最終日(latest)とする。
    """
    if preset == "今月":
        return Period(latest.replace(day=1), latest)
    if preset == "先月":
        prev_end = latest.replace(day=1) - timedelta(days=1)
        return Period(prev_end.replace(day=1), prev_end)
    if preset == "直近3ヶ月":
        return Period(_add_months(latest.replace(day=1), -2), latest)
    if preset == "今年":
        return Period(date(latest.year, 1, 1), latest)
    if preset == "昨年":
        return Period(date(latest.year - 1, 1, 1), date(latest.year - 1, 12, 31))
    if preset == "カスタム":
        if custom is None:
            raise ValueError("カスタム期間には開始日と終了日が必要です")
        start, end = custom
        return Period(min(start, end), max(start, end))
    raise ValueError(f"未対応の期間プリセットです: {preset}")


def _is_whole_months(p: Period) -> bool:
    """期間が月初から月末までの丸ごとの月で構成されているか。"""
    return p.start.day == 1 and p.end == _month_end(p.end)


def comparison_period(p: Period, mode: str) -> Period:
    """比較対象の期間を求める。

    前年同期間:1年前の同じ日付範囲
    前期間    :直前の同じ長さの期間(丸ごとの月なら月単位でずらす)
    """
    if mode == "前年同期間":
        start = _add_months(p.start, -12)
        end = _add_months(p.end, -12)
        if _is_whole_months(p):
            end = _month_end(end)
        return Period(start, end)
    if mode == "前期間":
        if _is_whole_months(p):
            n_months = (p.end.year - p.start.year) * 12 + p.end.month - p.start.month + 1
            start = _add_months(p.start, -n_months)
            return Period(start, _month_end(_add_months(start, n_months - 1)))
        end = p.start - timedelta(days=1)
        return Period(end - timedelta(days=p.days - 1), end)
    raise ValueError(f"未対応の比較方法です: {mode}")


# ---------------------------------------------------------------------------
# 絞り込み条件
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class QueryFilter:
    """期間以外の絞り込み条件。空のタプルは「すべて」を意味する。"""

    prefectures: tuple[str, ...] = field(default_factory=tuple)
    cities: tuple[str, ...] = field(default_factory=tuple)
    formats: tuple[str, ...] = field(default_factory=tuple)
    channels: tuple[str, ...] = field(default_factory=tuple)
    store_ids: tuple[str, ...] = field(default_factory=tuple)


def _where(f: QueryFilter, p: Period) -> tuple[str, list]:
    """絞り込み条件と期間から WHERE 句とパラメータを作る。"""
    clauses = ["date BETWEEN ? AND ?"]
    params: list = [p.start, p.end]
    for column, values in (
        ("prefecture", f.prefectures),
        ("city", f.cities),
        ("format", f.formats),
        ("channel", f.channels),
        ("store_id", f.store_ids),
    ):
        if values:
            clauses.append(f"{column} IN ({', '.join('?' * len(values))})")
            params.extend(values)
    return " AND ".join(clauses), params


def _safe_ratio(num: float | None, den: float | None) -> float | None:
    """0除算・欠損を避けて比率を計算する。"""
    if num is None or den is None or pd.isna(num) or pd.isna(den) or den == 0:
        return None
    return float(num) / float(den)


def growth(cur: float | None, prev: float | None) -> float | None:
    """増減率(cur / prev - 1)。比較値がなければ None。"""
    r = _safe_ratio(cur, prev)
    return None if r is None else r - 1


# ---------------------------------------------------------------------------
# 集計関数
# ---------------------------------------------------------------------------
def data_date_range(con: duckdb.DuckDBPyConnection) -> tuple[date, date]:
    """売上データの最初と最後の日付。"""
    lo, hi = con.execute("SELECT min(date), max(date) FROM sales").fetchone()
    return lo, hi


def kpi_summary(con: duckdb.DuckDBPyConnection, f: QueryFilter, p: Period) -> dict[str, float | None]:
    """主要指標(売上・客数・客単価・営業店舗数・店舗あたり売上)を集計する。"""
    where, params = _where(f, p)
    sales, customers, n_stores = con.execute(
        f"""
        SELECT sum(sales), sum(customers),
               count(DISTINCT store_id) FILTER (WHERE sales > 0)
        FROM sales WHERE {where}
        """,
        params,
    ).fetchone()
    sales = float(sales) if sales is not None else 0.0
    customers = float(customers) if customers is not None else 0.0
    return {
        "sales": sales,
        "customers": customers,
        "unit_price": _safe_ratio(sales, customers),
        "stores": int(n_stores or 0),
        "sales_per_store": _safe_ratio(sales, n_stores),
    }


def kpi_with_comparison(
    con: duckdb.DuckDBPyConnection, f: QueryFilter, cur: Period, cmp: Period
) -> dict[str, dict[str, float | None]]:
    """当期・比較期間の主要指標と増減率をまとめて返す。"""
    a = kpi_summary(con, f, cur)
    b = kpi_summary(con, f, cmp)
    keys = ("sales", "customers", "unit_price", "sales_per_store")
    return {
        k: {
            "current": a[k],
            "compare": b[k] if b["sales"] else None,
            "growth": growth(a[k], b[k]) if b["sales"] else None,
        }
        for k in keys
    } | {"stores": {"current": a["stores"], "compare": b["stores"], "growth": None}}


def sales_trend(
    con: duckdb.DuckDBPyConnection, f: QueryFilter, cur: Period, cmp: Period, grain: str = "month"
) -> pd.DataFrame:
    """当期と比較期間の売上推移を、同じ並び順(期間内の何番目の月/週/日か)で揃えて返す。

    grain:month(暦月)/ week(期間の開始日から7日ごと)/ day
    返り値の列:idx, label(当期の月/週の開始日/日), current, compare
    """
    if grain not in ("month", "week", "day"):
        raise ValueError("grain は month / week / day のいずれかを指定してください")

    def _series(p: Period) -> pd.DataFrame:
        where, params = _where(f, p)
        if grain == "month":
            idx = f"(year(date) - {p.start.year}) * 12 + month(date) - {p.start.month}"
        elif grain == "week":
            idx = f"(date - DATE '{p.start.isoformat()}') // 7"
        else:
            idx = f"date - DATE '{p.start.isoformat()}'"
        return con.execute(
            f"SELECT {idx} AS idx, sum(sales) AS sales FROM sales WHERE {where} GROUP BY 1 ORDER BY 1",
            params,
        ).df()

    a = _series(cur)
    b = _series(cmp)
    # 当期のすべての月/週/日を軸として並べる(データのない区間も表示する)
    if grain == "month":
        n = (cur.end.year - cur.start.year) * 12 + cur.end.month - cur.start.month + 1
        labels = [f"{_add_months(cur.start.replace(day=1), i):%Y/%m}" for i in range(n)]
    elif grain == "week":
        n = (cur.days + 6) // 7
        labels = [f"{cur.start + timedelta(days=7 * i):%m/%d}〜" for i in range(n)]
    else:
        n = cur.days
        labels = [f"{cur.start + timedelta(days=i):%m/%d}" for i in range(n)]
    out = pd.DataFrame({"idx": range(n), "label": labels})
    out = out.merge(a.rename(columns={"sales": "current"}), on="idx", how="left")
    out = out.merge(b.rename(columns={"sales": "compare"}), on="idx", how="left")
    return out


def composition(con: duckdb.DuckDBPyConnection, f: QueryFilter, p: Period, by: str) -> pd.DataFrame:
    """業態別・チャネル別などの売上構成比。列:key, sales, share"""
    if by not in ("format", "channel", "prefecture"):
        raise ValueError(f"未対応の集計軸です: {by}")
    where, params = _where(f, p)
    df = con.execute(
        f"SELECT {by} AS key, sum(sales) AS sales FROM sales WHERE {where} GROUP BY 1 ORDER BY 2 DESC",
        params,
    ).df()
    total = df["sales"].sum()
    df["share"] = df["sales"] / total if total else 0.0
    return df


def store_growth_ranking(
    con: duckdb.DuckDBPyConnection, f: QueryFilter, cur: Period, cmp: Period
) -> pd.DataFrame:
    """店舗別の当期売上・比較期間売上・増減率を、増減率の降順で返す。

    比較期間に売上がない店舗(新店など)は増減率を出せないため除外する。
    列:store_id, store_name, format, prefecture, city, current, compare, growth
    """
    w_cur, p_cur = _where(f, cur)
    w_cmp, p_cmp = _where(f, cmp)
    df = con.execute(
        f"""
        WITH a AS (SELECT store_id, sum(sales) AS current FROM sales WHERE {w_cur} GROUP BY 1),
             b AS (SELECT store_id, sum(sales) AS compare FROM sales WHERE {w_cmp} GROUP BY 1)
        SELECT s.store_id, s.store_name, s.format, s.prefecture, s.city,
               a.current, b.compare, a.current / b.compare - 1 AS growth
        FROM a JOIN b USING (store_id) JOIN stores s USING (store_id)
        WHERE b.compare > 0
        ORDER BY growth DESC, s.store_id
        """,
        p_cur + p_cmp,
    ).df()
    return df


def filter_options(con: duckdb.DuckDBPyConnection, prefectures: tuple[str, ...] = (), cities: tuple[str, ...] = (),
                   formats: tuple[str, ...] = ()) -> dict[str, list]:
    """サイドバーの選択肢を、上位の選択に連動させて返す。"""
    pref_clause = f"prefecture IN ({', '.join('?' * len(prefectures))})" if prefectures else "TRUE"
    cities_df = con.execute(
        f"SELECT DISTINCT prefecture, city FROM stores WHERE {pref_clause} ORDER BY prefecture, city",
        list(prefectures),
    ).df()

    clauses, params = [pref_clause], list(prefectures)
    if cities:
        clauses.append(f"city IN ({', '.join('?' * len(cities))})")
        params.extend(cities)
    if formats:
        clauses.append(f"format IN ({', '.join('?' * len(formats))})")
        params.extend(formats)
    stores_df = con.execute(
        f"SELECT store_id, store_name FROM stores WHERE {' AND '.join(clauses)} ORDER BY store_id", params
    ).df()
    return {
        "cities": cities_df["city"].tolist(),
        "stores": list(stores_df.itertuples(index=False, name=None)),
    }


# ---------------------------------------------------------------------------
# 地域別分析・店舗詳細
# ---------------------------------------------------------------------------
REGION_LEVELS = {"prefecture": "prefecture", "city": "city", "store": "store_id"}


def region_table(
    con: duckdb.DuckDBPyConnection, f: QueryFilter, cur: Period, cmp: Period, level: str
) -> pd.DataFrame:
    """都道府県/市区町村/店舗の単位で実績を集計する(ドリルダウン表用)。

    列:key(都道府県名・市区町村名・店舗ID), name(表示名), sales, compare, growth,
        customers, unit_price, stores, share
    比較期間の売上がない行は growth が欠損になる。
    """
    if level not in REGION_LEVELS:
        raise ValueError(f"未対応の階層です: {level}")
    col = REGION_LEVELS[level]
    name = "any_value(store_name)" if level == "store" else col
    w_cur, p_cur = _where(f, cur)
    w_cmp, p_cmp = _where(f, cmp)
    df = con.execute(
        f"""
        WITH a AS (
            SELECT {col} AS key, {name} AS name, sum(sales) AS sales, sum(customers) AS customers,
                   count(DISTINCT store_id) FILTER (WHERE sales > 0) AS stores
            FROM sales WHERE {w_cur} GROUP BY 1
        ),
        b AS (SELECT {col} AS key, sum(sales) AS compare FROM sales WHERE {w_cmp} GROUP BY 1)
        SELECT a.key, a.name, a.sales, b.compare,
               CASE WHEN b.compare > 0 THEN a.sales / b.compare - 1 END AS growth,
               a.customers,
               CASE WHEN a.customers > 0 THEN a.sales / a.customers END AS unit_price,
               a.stores
        FROM a LEFT JOIN b USING (key)
        ORDER BY a.sales DESC, a.key
        """,
        p_cur + p_cmp,
    ).df()
    total = df["sales"].sum()
    df["share"] = df["sales"] / total if total else 0.0
    return df


def store_info(con: duckdb.DuckDBPyConnection, store_id: str) -> dict | None:
    """店舗マスタの1行を辞書で返す(存在しなければ None)。"""
    df = con.execute("SELECT * FROM stores WHERE store_id = ?", [store_id]).df()
    return None if df.empty else df.iloc[0].to_dict()


def weekday_profile(con: duckdb.DuckDBPyConnection, f: QueryFilter, p: Period) -> pd.DataFrame:
    """曜日別の「1店舗・1営業日あたり平均売上」。売上ゼロの日(休業)は除く。

    列:weekday(0=月〜6=日), avg_sales
    """
    where, params = _where(f, p)
    df = con.execute(
        f"""
        WITH d AS (
            SELECT store_id, date, sum(sales) AS v FROM sales WHERE {where} GROUP BY 1, 2
        )
        SELECT isodow(date) - 1 AS weekday, avg(v) AS avg_sales
        FROM d WHERE v > 0 GROUP BY 1 ORDER BY 1
        """,
        params,
    ).df()
    return pd.DataFrame({"weekday": range(7)}).merge(df, on="weekday", how="left")


def format_peer_stats(
    con: duckdb.DuckDBPyConnection, store_id: str, channels: tuple[str, ...], cur: Period, cmp: Period
) -> pd.DataFrame:
    """対象店舗と同じ業態の全店舗について、当期売上・増減率・順位を返す。

    地域の絞り込みには左右されない(同業態の全店舗と比べるため)。チャネルの絞り込みは反映する。
    列:store_id, store_name, sales, customers, unit_price, growth, mobile_share, sales_rank, growth_rank
    """
    info = store_info(con, store_id)
    if info is None:
        return pd.DataFrame()
    f = QueryFilter(formats=(info["format"],), channels=channels)
    w_cur, p_cur = _where(f, cur)
    w_cmp, p_cmp = _where(f, cmp)
    return con.execute(
        f"""
        WITH a AS (
            SELECT store_id, any_value(store_name) AS store_name, sum(sales) AS sales,
                   sum(customers) AS customers,
                   sum(sales) FILTER (WHERE channel = 'モバイルオーダー') AS mobile_sales
            FROM sales WHERE {w_cur} GROUP BY 1 HAVING sum(sales) > 0
        ),
        b AS (SELECT store_id, sum(sales) AS compare FROM sales WHERE {w_cmp} GROUP BY 1)
        SELECT a.store_id, a.store_name, a.sales, a.customers,
               a.sales / NULLIF(a.customers, 0) AS unit_price,
               CASE WHEN b.compare > 0 THEN a.sales / b.compare - 1 END AS growth,
               coalesce(a.mobile_sales, 0) / a.sales AS mobile_share,
               rank() OVER (ORDER BY a.sales DESC) AS sales_rank,
               CASE WHEN b.compare > 0 THEN
                   rank() OVER (PARTITION BY b.compare > 0 ORDER BY a.sales / b.compare DESC) END AS growth_rank
        FROM a LEFT JOIN b USING (store_id)
        ORDER BY sales_rank, a.store_id
        """,
        p_cur + p_cmp,
    ).df()


def daily_metrics(con: duckdb.DuckDBPyConnection, f: QueryFilter, p: Period) -> pd.DataFrame:
    """日別の売上・客数(データのない日も0で埋める)。列:date, sales, customers"""
    where, params = _where(f, p)
    df = con.execute(
        f"SELECT date, sum(sales) AS sales, sum(customers) AS customers FROM sales WHERE {where} GROUP BY 1",
        params,
    ).df()
    days = pd.DataFrame({"date": pd.date_range(p.start, p.end, freq="D").date})
    out = days.merge(df.assign(date=pd.to_datetime(df["date"]).dt.date), on="date", how="left")
    return out.fillna({"sales": 0, "customers": 0})


def available_months(con: duckdb.DuckDBPyConnection) -> list[date]:
    """データのある月(月初日)を新しい順に返す。"""
    rows = con.execute("SELECT DISTINCT date_trunc('month', date)::DATE FROM sales ORDER BY 1 DESC").fetchall()
    return [r[0] for r in rows]


def month_period(month_start: date) -> Period:
    """月初日からその月の期間を作る。"""
    return Period(month_start, _month_end(month_start))
