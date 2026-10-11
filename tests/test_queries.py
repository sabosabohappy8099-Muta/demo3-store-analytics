"""queries.py(集計関数・期間計算)と config.py(書式関数)のテスト。"""

from __future__ import annotations

from datetime import date

import duckdb
import pandas as pd
import pytest

from src.config import format_delta, format_yen, format_yen_short
from src.queries import (
    Period,
    QueryFilter,
    comparison_period,
    composition,
    filter_options,
    format_peer_stats,
    growth,
    kpi_summary,
    kpi_with_comparison,
    region_table,
    resolve_period,
    sales_trend,
    store_growth_ranking,
    weekday_profile,
)


@pytest.fixture()
def con() -> duckdb.DuckDBPyConnection:
    """手計算で検証できる小さなテスト用データベース。

    店舗A(東京・駅ナカ):2025年1月・2026年1月に売上あり
    店舗B(神奈川・ロードサイド):2025年1月・2026年1月に売上あり
    店舗C(神奈川・駅ナカ):2026年1月のみ(新店)
    """
    c = duckdb.connect(":memory:")
    stores = pd.DataFrame(
        {
            "store_id": ["A", "B", "C"],
            "store_name": ["A店", "B店", "C店"],
            "format": ["駅ナカ型", "ロードサイド型", "駅ナカ型"],
            "prefecture": ["東京都", "神奈川県", "神奈川県"],
            "city": ["新宿区", "藤沢市", "横浜市西区"],
        }
    )
    rows = [
        # date, store, channel, sales, customers
        ("2025-01-10", "A", "店内飲食", 1000, 10),
        ("2025-01-10", "A", "テイクアウト", 1000, 20),
        ("2025-01-15", "B", "店内飲食", 2000, 10),
        ("2026-01-10", "A", "店内飲食", 1500, 10),
        ("2026-01-10", "A", "テイクアウト", 1500, 20),
        ("2026-01-15", "B", "店内飲食", 1000, 5),
        ("2026-01-20", "C", "モバイルオーダー", 4000, 20),
        ("2026-02-01", "A", "店内飲食", 500, 5),
    ]
    sales = pd.DataFrame(rows, columns=["date", "store_id", "channel", "sales", "customers"])
    sales["date"] = pd.to_datetime(sales["date"]).dt.date
    c.register("stores_df", stores)
    c.register("sales_df", sales)
    c.execute("CREATE TABLE stores AS SELECT * FROM stores_df")
    c.execute("CREATE TABLE sales AS SELECT d.*, s.store_name, s.format, s.prefecture, s.city "
              "FROM sales_df d JOIN stores s USING (store_id)")
    return c


JAN_2026 = Period(date(2026, 1, 1), date(2026, 1, 31))
JAN_2025 = Period(date(2025, 1, 1), date(2025, 1, 31))


# ---------------------------------------------------------------------------
# 期間計算
# ---------------------------------------------------------------------------
class TestPeriods:
    LATEST = date(2026, 9, 30)

    @pytest.mark.parametrize(
        ("preset", "expected"),
        [
            ("今月", Period(date(2026, 9, 1), date(2026, 9, 30))),
            ("先月", Period(date(2026, 8, 1), date(2026, 8, 31))),
            ("直近3ヶ月", Period(date(2026, 7, 1), date(2026, 9, 30))),
            ("今年", Period(date(2026, 1, 1), date(2026, 9, 30))),
            ("昨年", Period(date(2025, 1, 1), date(2025, 12, 31))),
        ],
    )
    def test_resolve_presets(self, preset: str, expected: Period) -> None:
        assert resolve_period(preset, self.LATEST) == expected

    def test_custom_swaps_reversed_dates(self) -> None:
        p = resolve_period("カスタム", self.LATEST, (date(2026, 3, 10), date(2026, 3, 1)))
        assert p == Period(date(2026, 3, 1), date(2026, 3, 10))

    def test_custom_requires_dates(self) -> None:
        with pytest.raises(ValueError):
            resolve_period("カスタム", self.LATEST)

    def test_previous_year(self) -> None:
        assert comparison_period(JAN_2026, "前年同期間") == JAN_2025

    def test_previous_year_leap_month_end(self) -> None:
        # 2025年2月(28日まで)の前年同期間は2024年2月の29日までになる
        p = Period(date(2025, 2, 1), date(2025, 2, 28))
        assert comparison_period(p, "前年同期間") == Period(date(2024, 2, 1), date(2024, 2, 29))

    def test_previous_period_whole_months(self) -> None:
        p = Period(date(2026, 7, 1), date(2026, 9, 30))
        assert comparison_period(p, "前期間") == Period(date(2026, 4, 1), date(2026, 6, 30))

    def test_previous_period_one_month_uses_calendar_month(self) -> None:
        # 3月の前期間は2月(日数ではなく月単位でずらす)
        p = Period(date(2026, 3, 1), date(2026, 3, 31))
        assert comparison_period(p, "前期間") == Period(date(2026, 2, 1), date(2026, 2, 28))

    def test_previous_period_days(self) -> None:
        p = Period(date(2026, 3, 11), date(2026, 3, 20))
        assert comparison_period(p, "前期間") == Period(date(2026, 3, 1), date(2026, 3, 10))


# ---------------------------------------------------------------------------
# 集計
# ---------------------------------------------------------------------------
class TestKpi:
    def test_totals(self, con: duckdb.DuckDBPyConnection) -> None:
        k = kpi_summary(con, QueryFilter(), JAN_2026)
        assert k["sales"] == 8000
        assert k["customers"] == 55
        assert k["unit_price"] == pytest.approx(8000 / 55)
        assert k["stores"] == 3
        assert k["sales_per_store"] == pytest.approx(8000 / 3)

    def test_filter_by_prefecture_and_channel(self, con: duckdb.DuckDBPyConnection) -> None:
        k = kpi_summary(con, QueryFilter(prefectures=("東京都",), channels=("店内飲食",)), JAN_2026)
        assert k["sales"] == 1500
        assert k["stores"] == 1

    def test_empty_result(self, con: duckdb.DuckDBPyConnection) -> None:
        k = kpi_summary(con, QueryFilter(cities=("存在しない市",)), JAN_2026)
        assert k["sales"] == 0
        assert k["unit_price"] is None
        assert k["sales_per_store"] is None

    def test_comparison_growth(self, con: duckdb.DuckDBPyConnection) -> None:
        k = kpi_with_comparison(con, QueryFilter(), JAN_2026, JAN_2025)
        assert k["sales"]["current"] == 8000
        assert k["sales"]["compare"] == 4000
        assert k["sales"]["growth"] == pytest.approx(1.0)

    def test_comparison_without_data(self, con: duckdb.DuckDBPyConnection) -> None:
        k = kpi_with_comparison(con, QueryFilter(), JAN_2026, Period(date(2020, 1, 1), date(2020, 1, 31)))
        assert k["sales"]["growth"] is None
        assert k["sales"]["compare"] is None


def test_growth_handles_zero_and_none() -> None:
    assert growth(110, 100) == pytest.approx(0.1)
    assert growth(100, 0) is None
    assert growth(100, None) is None


def test_composition_shares_sum_to_one(con: duckdb.DuckDBPyConnection) -> None:
    df = composition(con, QueryFilter(), JAN_2026, "format")
    assert df["share"].sum() == pytest.approx(1.0)
    assert dict(zip(df["key"], df["sales"])) == {"駅ナカ型": 7000, "ロードサイド型": 1000}


def test_composition_rejects_unknown_axis(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError):
        composition(con, QueryFilter(), JAN_2026, "store_name; DROP TABLE sales")


def test_store_growth_ranking_excludes_new_store(con: duckdb.DuckDBPyConnection) -> None:
    df = store_growth_ranking(con, QueryFilter(), JAN_2026, JAN_2025)
    assert df["store_id"].tolist() == ["A", "B"]  # C(新店)は比較できないため除外
    assert df["growth"].tolist() == pytest.approx([0.5, -0.5])


def test_sales_trend_monthly_alignment(con: duckdb.DuckDBPyConnection) -> None:
    cur = Period(date(2026, 1, 1), date(2026, 2, 28))
    cmp = comparison_period(cur, "前年同期間")
    df = sales_trend(con, QueryFilter(), cur, cmp, "month")
    assert df["label"].tolist() == ["2026/01", "2026/02"]
    assert df["current"].tolist() == [8000, 500]
    assert df["compare"].iloc[0] == 4000
    assert pd.isna(df["compare"].iloc[1])  # 2025年2月はデータなし


def test_sales_trend_daily(con: duckdb.DuckDBPyConnection) -> None:
    df = sales_trend(con, QueryFilter(), JAN_2026, JAN_2025, "day")
    assert len(df) == 31
    assert df.loc[df["label"] == "01/10", "current"].item() == 3000
    assert df.loc[df["label"] == "01/10", "compare"].item() == 2000


def test_filter_options_cascade(con: duckdb.DuckDBPyConnection) -> None:
    opts = filter_options(con, prefectures=("神奈川県",))
    assert opts["cities"] == ["横浜市西区", "藤沢市"]
    assert [s[0] for s in opts["stores"]] == ["B", "C"]
    opts = filter_options(con, prefectures=("神奈川県",), formats=("駅ナカ型",))
    assert [s[0] for s in opts["stores"]] == ["C"]


# ---------------------------------------------------------------------------
# 書式
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (980, "980円"),
        (12_340_000, "1,234万円"),
        (386_120_000, "3億8,612万円"),
        (200_000_000, "2億円"),
        (199_999_999, "2億円"),
        (-50_000, "-5万円"),
        (None, "—"),
    ],
)
def test_format_yen(value: float | None, expected: str) -> None:
    assert format_yen(value) == expected


def test_format_delta() -> None:
    assert format_delta(0.052) == "▲ +5.2%"
    assert format_delta(-0.1) == "▼ -10.0%"
    assert format_delta(None) == "比較データなし"
    assert format_delta(0.0003) == "± 0.0%"  # 表示上0.0%なら▲を付けない


def test_format_yen_short() -> None:
    assert format_yen_short(1_149_830_000) == "11.50億円"
    assert format_yen_short(28_750_000) == "2,875万円"


# ---------------------------------------------------------------------------
# 地域別分析・店舗詳細
# ---------------------------------------------------------------------------
def test_sales_trend_weekly(con: duckdb.DuckDBPyConnection) -> None:
    df = sales_trend(con, QueryFilter(), JAN_2026, JAN_2025, "week")
    assert len(df) == 5  # 31日 → 7日ごとに5区間
    assert df["label"].iloc[0] == "01/01〜"
    # 1/8〜1/14 の区間に 1/10 の 3000円、1/15〜21 に B 1000円 + C 4000円
    assert df["current"].tolist()[1:3] == [3000, 5000]


def test_region_table_prefecture(con: duckdb.DuckDBPyConnection) -> None:
    df = region_table(con, QueryFilter(), JAN_2026, JAN_2025, "prefecture").set_index("key")
    assert df.loc["神奈川県", "sales"] == 5000
    assert df.loc["神奈川県", "stores"] == 2
    assert df.loc["神奈川県", "growth"] == pytest.approx(5000 / 2000 - 1)
    assert df.loc["東京都", "growth"] == pytest.approx(0.5)
    assert df["share"].sum() == pytest.approx(1.0)
    assert df.loc["東京都", "unit_price"] == pytest.approx(3000 / 30)


def test_region_table_new_city_has_no_growth(con: duckdb.DuckDBPyConnection) -> None:
    f = QueryFilter(prefectures=("神奈川県",))
    df = region_table(con, f, JAN_2026, JAN_2025, "city").set_index("key")
    assert list(df.index) == ["横浜市西区", "藤沢市"]  # 売上の大きい順
    assert pd.isna(df.loc["横浜市西区", "growth"])  # 新店のみの市区町村は比較できない


def test_region_table_store_level_uses_names(con: duckdb.DuckDBPyConnection) -> None:
    df = region_table(con, QueryFilter(cities=("新宿区",)), JAN_2026, JAN_2025, "store")
    assert df[["key", "name"]].values.tolist() == [["A", "A店"]]


def test_region_table_rejects_unknown_level(con: duckdb.DuckDBPyConnection) -> None:
    with pytest.raises(ValueError):
        region_table(con, QueryFilter(), JAN_2026, JAN_2025, "format")


def test_weekday_profile(con: duckdb.DuckDBPyConnection) -> None:
    df = weekday_profile(con, QueryFilter(store_ids=("A",)), JAN_2026)
    assert len(df) == 7
    # 2026/1/10 は土曜日(weekday=5)。A店のその日の合計は 3000円
    assert df.loc[df["weekday"] == 5, "avg_sales"].item() == 3000
    assert df["avg_sales"].isna().sum() == 6


def test_format_peer_stats_ranks(con: duckdb.DuckDBPyConnection) -> None:
    df = format_peer_stats(con, "A", (), JAN_2026, JAN_2025).set_index("store_id")
    # 駅ナカ型は A(3000円)と C(4000円)
    assert list(df.index) == ["C", "A"]
    assert df.loc["C", "sales_rank"] == 1 and df.loc["A", "sales_rank"] == 2
    assert df.loc["A", "growth_rank"] == 1
    assert pd.isna(df.loc["C", "growth_rank"])  # 新店は伸び率の順位なし
    assert df.loc["C", "mobile_share"] == pytest.approx(1.0)


def test_format_peer_stats_unknown_store(con: duckdb.DuckDBPyConnection) -> None:
    assert format_peer_stats(con, "ZZZ", (), JAN_2026, JAN_2025).empty
