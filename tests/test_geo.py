"""geo.py(距離計算・半径検索・商圏集計)のテスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.geo import (
    circle_polygon,
    haversine_km,
    hex_bin,
    radius_table,
    trade_area_stats,
    with_distance,
    within_radius,
)

# 東京駅と新宿駅(実際の距離は約6.1km)
TOKYO = (35.6812, 139.7671)
SHINJUKU = (35.6900, 139.7003)

# 緯度1度 ≒ 111.2km(地球の平均半径から)
KM_PER_DEG_LAT = 2 * np.pi * 6371.0088 / 360


class TestHaversine:
    def test_same_point_is_zero(self) -> None:
        assert haversine_km(*TOKYO, *TOKYO) == pytest.approx(0.0)

    def test_tokyo_shinjuku(self) -> None:
        assert haversine_km(*TOKYO, *SHINJUKU) == pytest.approx(6.1, abs=0.1)

    def test_symmetric(self) -> None:
        assert haversine_km(*TOKYO, *SHINJUKU) == pytest.approx(haversine_km(*SHINJUKU, *TOKYO))

    def test_one_degree_latitude(self) -> None:
        assert haversine_km(35.0, 139.0, 36.0, 139.0) == pytest.approx(KM_PER_DEG_LAT, rel=1e-6)

    def test_vectorized(self) -> None:
        d = haversine_km(35.0, 139.0, np.array([35.0, 36.0]), np.array([139.0, 139.0]))
        assert d.shape == (2,)
        assert d[0] == pytest.approx(0.0)


def _points_north(distances_km: list[float], base: tuple[float, float] = (35.0, 139.0)) -> pd.DataFrame:
    """基準点から真北に指定距離だけ離れた点を作る(テスト用)。"""
    return pd.DataFrame(
        {
            "id": [f"P{i}" for i in range(len(distances_km))],
            "lat": [base[0] + d / KM_PER_DEG_LAT for d in distances_km],
            "lon": [base[1]] * len(distances_km),
        }
    )


class TestRadiusSearch:
    def test_with_distance(self) -> None:
        df = with_distance(_points_north([0.0, 1.0, 2.5]), 35.0, 139.0)
        assert df["distance_km"].tolist() == pytest.approx([0.0, 1.0, 2.5], abs=1e-6)

    def test_within_radius_sorted_and_boundary(self) -> None:
        df = _points_north([3.0, 0.5, 0.9999, 1.0001]).sample(frac=1, random_state=0)
        hit = within_radius(df, 35.0, 139.0, 1.0)
        # 境界のすぐ内側(0.9999km)は含み、すぐ外側(1.0001km)は含まない。近い順に並ぶ
        assert hit["id"].tolist() == ["P1", "P2"]

    def test_within_radius_empty(self) -> None:
        assert within_radius(_points_north([5.0]), 35.0, 139.0, 1.0).empty

    def test_negative_radius(self) -> None:
        with pytest.raises(ValueError):
            within_radius(_points_north([1.0]), 35.0, 139.0, -1)

    def test_circle_polygon_radius(self) -> None:
        ring = circle_polygon(35.0, 139.0, 2.0)
        assert ring[0] == ring[-1]  # 閉じた多角形
        d = haversine_km(35.0, 139.0, [p[1] for p in ring], [p[0] for p in ring])
        assert d == pytest.approx(np.full(len(ring), 2.0), rel=0.01)


@pytest.fixture()
def area() -> dict[str, pd.DataFrame]:
    """中心(35.0, 139.0)の真北に会員・店舗・競合を配置したテスト用データ。

    店舗 A:0.4km、B:1.8km、C:6km
    会員:0.2km(A・来店あり)、0.9km(B・来店なし)、1.5km(C・来店あり)、4km(A・来店あり)
    競合:1.2km、3km
    """
    s = _points_north([0.4, 1.8, 6.0]).assign(store_id=["A", "B", "C"], sales=[100.0, 200.0, 400.0])
    m = _points_north([0.2, 0.9, 1.5, 4.0]).rename(columns={"lat": "home_lat", "lon": "home_lon"})
    m = m.assign(main_store_id=["A", "B", "C", "A"], visits_12m=[3, 0, 5, 1])
    c = _points_north([1.2, 3.0])
    return {"stores": s, "members": m, "competitors": c}


class TestTradeArea:
    def test_stats_1km(self, area: dict[str, pd.DataFrame]) -> None:
        st = trade_area_stats(35.0, 139.0, 1.0, area["members"], area["stores"], area["competitors"])
        assert st["members"] == 2
        assert st["active_members"] == 1
        assert st["stores"] == 1 and st["store_sales"] == 100.0
        assert st["competitors"] == 0
        # 半径内の会員2人のうち、メイン店舗(A)が半径内にあるのは1人
        assert st["overlap_members"] == 1
        assert st["overlap_rate"] == pytest.approx(0.5)

    def test_stats_2km(self, area: dict[str, pd.DataFrame]) -> None:
        st = trade_area_stats(35.0, 139.0, 2.0, area["members"], area["stores"], area["competitors"])
        assert st["members"] == 3
        assert st["stores"] == 2 and st["store_sales"] == 300.0
        assert st["competitors"] == 1
        # 会員3人のうち、メイン店舗が半径内(A・B)なのは2人(Cは6km先)
        assert st["overlap_rate"] == pytest.approx(2 / 3)

    def test_exclude_candidate_store(self, area: dict[str, pd.DataFrame]) -> None:
        st = trade_area_stats(35.0, 139.0, 1.0, area["members"], area["stores"], area["competitors"],
                              exclude_store_id="A")
        assert st["stores"] == 0
        assert st["overlap_members"] == 0

    def test_no_members(self, area: dict[str, pd.DataFrame]) -> None:
        st = trade_area_stats(40.0, 139.0, 1.0, area["members"], area["stores"], area["competitors"])
        assert st["members"] == 0
        assert st["overlap_rate"] is None

    def test_radius_table_monotonic(self, area: dict[str, pd.DataFrame]) -> None:
        radii = [0.5 * i for i in range(1, 11)]
        df = radius_table(35.0, 139.0, radii, area["members"], area["stores"], area["competitors"])
        assert df["radius_km"].tolist() == radii
        for col in ("members", "stores", "competitors", "store_sales"):
            assert df[col].is_monotonic_increasing
        assert df.loc[df["radius_km"] == 5.0, "members"].item() == 4


class TestHexBin:
    def test_counts_preserved_and_grouped(self) -> None:
        rng = np.random.default_rng(0)
        lat = 35.7 + rng.normal(0, 0.02, 500)
        lon = 139.7 + rng.normal(0, 0.02, 500)
        active = (rng.random(500) < 0.6).astype(int)
        df = hex_bin(lat, lon, size_km=1.0, weights={"active": active})
        assert df["count"].sum() == 500
        assert df["active"].sum() == active.sum()
        assert len(df) < 500  # 近くの点はまとめられる

    def test_points_belong_to_nearest_center(self) -> None:
        rng = np.random.default_rng(1)
        lat = 35.7 + rng.normal(0, 0.03, 300)
        lon = 139.7 + rng.normal(0, 0.03, 300)
        df = hex_bin(lat, lon, size_km=1.0)
        # 各六角形の中心から頂点までの距離は約1km
        for poly, clat, clon in zip(df["polygon"], df["lat"], df["lon"]):
            d = haversine_km(clat, clon, [p[1] for p in poly], [p[0] for p in poly])
            assert d == pytest.approx(np.full(6, 1.0), rel=0.02)
        # どの点も、いずれかの六角形の中心から1km以内にある
        dist_to_nearest = [
            haversine_km(a, b, df["lat"].to_numpy(), df["lon"].to_numpy()).min() for a, b in zip(lat, lon)
        ]
        assert max(dist_to_nearest) <= 1.0 + 1e-6

    def test_empty(self) -> None:
        df = hex_bin(np.array([]), np.array([]))
        assert df.empty and "polygon" in df.columns
