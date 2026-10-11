"""距離計算・半径検索・商圏の集計(Streamlit に依存しない純粋な関数)。"""

from __future__ import annotations

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0088  # 地球の平均半径(km)


def haversine_km(
    lat1: float | np.ndarray, lon1: float | np.ndarray, lat2: float | np.ndarray, lon2: float | np.ndarray
) -> np.ndarray:
    """2点間の大圏距離(km)を求める。配列を渡すとまとめて計算する。"""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def with_distance(df: pd.DataFrame, lat: float, lon: float, lat_col: str = "lat", lon_col: str = "lon") -> pd.DataFrame:
    """中心点からの距離(km)を distance_km 列として追加したコピーを返す。"""
    out = df.copy()
    out["distance_km"] = haversine_km(lat, lon, out[lat_col].to_numpy(), out[lon_col].to_numpy())
    return out


def within_radius(
    df: pd.DataFrame, lat: float, lon: float, radius_km: float, lat_col: str = "lat", lon_col: str = "lon"
) -> pd.DataFrame:
    """中心点から半径 radius_km 以内(境界を含む)の行を、距離の近い順に返す。"""
    if radius_km < 0:
        raise ValueError("半径は0以上を指定してください")
    out = with_distance(df, lat, lon, lat_col, lon_col)
    return out[out["distance_km"] <= radius_km].sort_values("distance_km")


def circle_polygon(lat: float, lon: float, radius_km: float, n_points: int = 72) -> list[list[float]]:
    """中心と半径から、地図に描く円の頂点リスト [[経度, 緯度], ...] を作る。"""
    angles = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    dlat = radius_km / 111.32 * np.sin(angles)
    dlon = radius_km / (111.32 * np.cos(np.radians(lat))) * np.cos(angles)
    ring = [[float(lon + x), float(lat + y)] for x, y in zip(dlon, dlat)]
    return ring + [ring[0]]


def trade_area_stats(
    lat: float,
    lon: float,
    radius_km: float,
    members: pd.DataFrame,
    stores: pd.DataFrame,
    competitors: pd.DataFrame,
    exclude_store_id: str | None = None,
) -> dict[str, float | int | None]:
    """候補地の商圏(半径内)の指標をまとめて計算する。

    members    :home_lat, home_lon, main_store_id, visits_12m
    stores     :store_id, lat, lon, sales(期間売上)
    competitors:lat, lon
    exclude_store_id:候補地が既存店そのものの場合、その店舗を「既存店」から除く

    重なり率 = 半径内の会員のうち、メイン店舗が同じ半径内の既存店である会員の割合
              (高いほど既存店と商圏が重なり、売上を奪い合う可能性が高い)
    """
    return radius_table(lat, lon, [radius_km], members, stores, competitors, exclude_store_id).iloc[0].to_dict()


def radius_table(
    lat: float,
    lon: float,
    radii_km: list[float],
    members: pd.DataFrame,
    stores: pd.DataFrame,
    competitors: pd.DataFrame,
    exclude_store_id: str | None = None,
) -> pd.DataFrame:
    """複数の半径について商圏の指標を計算し、1半径1行の表で返す。

    列:radius_km, members, active_members, stores, store_sales, competitors, overlap_members, overlap_rate
    """
    m_dist = haversine_km(lat, lon, members["home_lat"].to_numpy(), members["home_lon"].to_numpy())
    own = stores if exclude_store_id is None else stores[stores["store_id"] != exclude_store_id]
    s_dist = haversine_km(lat, lon, own["lat"].to_numpy(), own["lon"].to_numpy())
    c_dist = haversine_km(lat, lon, competitors["lat"].to_numpy(), competitors["lon"].to_numpy())
    active = members["visits_12m"].to_numpy() > 0
    main_ids = members["main_store_id"].to_numpy()
    sales = own["sales"].fillna(0).to_numpy() if "sales" in own else np.zeros(len(own))
    own_ids = own["store_id"].to_numpy()

    rows = []
    for r in radii_km:
        in_m = m_dist <= r
        in_s = s_dist <= r
        stores_in = set(own_ids[in_s])
        overlap = in_m & np.isin(main_ids, list(stores_in)) if stores_in else np.zeros_like(in_m)
        n_members = int(in_m.sum())
        rows.append(
            {
                "radius_km": float(r),
                "members": n_members,
                "active_members": int((in_m & active).sum()),
                "stores": int(in_s.sum()),
                "store_sales": float(sales[in_s].sum()),
                "competitors": int((c_dist <= r).sum()),
                "overlap_members": int(overlap.sum()),
                "overlap_rate": overlap.sum() / n_members if n_members else None,
            }
        )
    return pd.DataFrame(rows)


def hex_bin(
    lat: np.ndarray | pd.Series,
    lon: np.ndarray | pd.Series,
    size_km: float = 1.0,
    weights: dict[str, np.ndarray | pd.Series] | None = None,
) -> pd.DataFrame:
    """点を六角形のマス(頂点が上向き)に集計する。

    緯度経度を中心付近で平面(km)に近似し、六角形の中心から頂点までを size_km とする。
    weights に {列名: 0/1 などの配列} を渡すと、その合計も列として追加する。
    返り値の列:lat, lon(六角形の中心), count, <weights の列>, polygon([[経度, 緯度], ...])
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    if len(lat) == 0:
        return pd.DataFrame(columns=["lat", "lon", "count", *(weights or {}), "polygon"])
    lat0 = float(np.mean(lat))
    kx = 111.32 * np.cos(np.radians(lat0))  # 経度1度あたりの km
    ky = 111.32  # 緯度1度あたりの km
    x = lon * kx
    y = lat * ky

    # 平面座標 → 六角形の軸座標(q, r)→ 立方座標で丸める
    q = (np.sqrt(3) / 3 * x - y / 3) / size_km
    r = (2 / 3 * y) / size_km
    s = -q - r
    rq, rr, rs = np.round(q), np.round(r), np.round(s)
    dq, dr, ds = np.abs(rq - q), np.abs(rr - r), np.abs(rs - s)
    fix_q = (dq > dr) & (dq > ds)
    fix_r = ~fix_q & (dr > ds)
    rq = np.where(fix_q, -rr - rs, rq)
    rr = np.where(fix_r, -rq - rs, rr)

    df = pd.DataFrame({"q": rq.astype(int), "r": rr.astype(int), "count": 1})
    for name, values in (weights or {}).items():
        df[name] = np.asarray(values, dtype=float)
    agg = df.groupby(["q", "r"], as_index=False).sum()

    cx = size_km * np.sqrt(3) * (agg["q"] + agg["r"] / 2)
    cy = size_km * 1.5 * agg["r"]
    angles = np.radians(np.arange(6) * 60 - 30)
    agg["lat"] = cy / ky
    agg["lon"] = cx / kx
    agg["polygon"] = [
        [[float((xx + size_km * np.cos(a)) / kx), float((yy + size_km * np.sin(a)) / ky)] for a in angles]
        for xx, yy in zip(cx, cy)
    ]
    return agg.drop(columns=["q", "r"]).sort_values("count", ascending=False).reset_index(drop=True)
