"""ダミーデータ生成スクリプト。

架空のベーカリーカフェチェーン「こむぎ堂」の店舗・日次売上・会員・競合店データを作り、
data/ に Parquet 形式で保存する。乱数シードは固定しているため、何度実行しても同じデータになる。

実行方法:
    python scripts/generate_dummy_data.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
SEED = 42
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# 期間:直近の月末までの2年分(再現性のため固定値にしている)
START_DATE = pd.Timestamp("2024-10-01")
END_DATE = pd.Timestamp("2026-09-30")

N_MEMBERS = 20_000
N_COMPETITORS = 60

FORMATS = ("駅ナカ型", "ロードサイド型", "商業施設型")
CHANNELS = ("店内飲食", "テイクアウト", "モバイルオーダー")

# 店舗定義:(店名の地名, 業態, 都道府県, 市区町村, 緯度, 経度)
# 座標は各駅・地域周辺のおおよその位置
STORE_DEFS: list[tuple[str, str, str, str, float, float]] = [
    # 東京都
    ("新宿", "駅ナカ型", "東京都", "新宿区", 35.6900, 139.7003),
    ("渋谷", "駅ナカ型", "東京都", "渋谷区", 35.6580, 139.7016),
    ("池袋", "駅ナカ型", "東京都", "豊島区", 35.7295, 139.7109),
    ("品川", "駅ナカ型", "東京都", "港区", 35.6285, 139.7388),
    ("北千住", "駅ナカ型", "東京都", "足立区", 35.7497, 139.8049),
    ("大森", "駅ナカ型", "東京都", "大田区", 35.5885, 139.7280),
    ("吉祥寺", "商業施設型", "東京都", "武蔵野市", 35.7030, 139.5797),
    ("立川", "商業施設型", "東京都", "立川市", 35.6980, 139.4136),
    ("町田", "商業施設型", "東京都", "町田市", 35.5420, 139.4466),
    ("二子玉川", "商業施設型", "東京都", "世田谷区", 35.6116, 139.6268),
    ("錦糸町", "商業施設型", "東京都", "墨田区", 35.6969, 139.8144),
    ("八王子", "ロードサイド型", "東京都", "八王子市", 35.6400, 139.3300),
    ("府中", "ロードサイド型", "東京都", "府中市", 35.6680, 139.4850),
    ("練馬", "ロードサイド型", "東京都", "練馬区", 35.7400, 139.6480),
    # 神奈川県
    ("横浜", "駅ナカ型", "神奈川県", "横浜市西区", 35.4660, 139.6223),
    ("新横浜", "駅ナカ型", "神奈川県", "横浜市港北区", 35.5069, 139.6176),
    ("武蔵小杉", "駅ナカ型", "神奈川県", "川崎市中原区", 35.5765, 139.6596),
    ("藤沢", "駅ナカ型", "神奈川県", "藤沢市", 35.3389, 139.4875),
    ("みなとみらい", "商業施設型", "神奈川県", "横浜市西区", 35.4570, 139.6320),
    ("センター北", "商業施設型", "神奈川県", "横浜市都筑区", 35.5506, 139.5793),
    ("川崎", "商業施設型", "神奈川県", "川崎市川崎区", 35.5313, 139.6970),
    ("海老名", "商業施設型", "神奈川県", "海老名市", 35.4525, 139.3910),
    ("相模原", "ロードサイド型", "神奈川県", "相模原市中央区", 35.5710, 139.3730),
    ("厚木", "ロードサイド型", "神奈川県", "厚木市", 35.4430, 139.3620),
    ("平塚", "ロードサイド型", "神奈川県", "平塚市", 35.3290, 139.3500),
    # 埼玉県
    ("大宮", "駅ナカ型", "埼玉県", "さいたま市大宮区", 35.9064, 139.6237),
    ("浦和", "駅ナカ型", "埼玉県", "さいたま市浦和区", 35.8586, 139.6570),
    ("所沢", "駅ナカ型", "埼玉県", "所沢市", 35.7870, 139.4730),
    ("川口", "商業施設型", "埼玉県", "川口市", 35.8020, 139.7180),
    ("越谷レイクタウン", "商業施設型", "埼玉県", "越谷市", 35.8760, 139.8230),
    ("川越", "ロードサイド型", "埼玉県", "川越市", 35.9070, 139.4830),
    ("春日部", "ロードサイド型", "埼玉県", "春日部市", 35.9800, 139.7520),
    ("熊谷", "ロードサイド型", "埼玉県", "熊谷市", 36.1470, 139.3890),
    # 千葉県
    ("船橋", "駅ナカ型", "千葉県", "船橋市", 35.7016, 139.9853),
    ("千葉", "駅ナカ型", "千葉県", "千葉市中央区", 35.6130, 140.1130),
    ("松戸", "駅ナカ型", "千葉県", "松戸市", 35.7840, 139.9010),
    ("海浜幕張", "商業施設型", "千葉県", "千葉市美浜区", 35.6486, 140.0420),
    ("柏", "商業施設型", "千葉県", "柏市", 35.8620, 139.9710),
    ("市原", "ロードサイド型", "千葉県", "市原市", 35.4980, 140.1150),
    ("千葉ニュータウン", "ロードサイド型", "千葉県", "印西市", 35.7976, 140.1806),
]

# 新店(直近1年以内に開店):店名の地名 → 開店日
NEW_STORES: dict[str, str] = {
    "海老名": "2025-11-15",
    "千葉ニュータウン": "2026-04-10",
    "二子玉川": "2026-06-01",
}

# 好調・不調エリア(市区町村単位):年率の成長率
GOOD_CITIES: dict[str, float] = {
    "横浜市港北区": 0.14,
    "横浜市都筑区": 0.16,
    "川崎市中原区": 0.13,
    "横浜市西区": 0.10,
}
BAD_CITIES: dict[str, float] = {
    "熊谷市": -0.12,
    "春日部市": -0.09,
    "市原市": -0.10,
    "豊島区": -0.06,
}
BASE_GROWTH = 0.02  # その他の店舗の平均的な年率成長

# 改装休業:店名の地名 → (休業開始日, 休業終了日)
RENOVATIONS: dict[str, tuple[str, str]] = {
    "渋谷": ("2025-06-09", "2025-06-15"),
    "柏": ("2026-02-16", "2026-02-20"),
}

# 業態ごとの基準値
BASE_DAILY_SALES = {"駅ナカ型": 350_000, "ロードサイド型": 250_000, "商業施設型": 300_000}
BASE_UNIT_PRICE = {"駅ナカ型": 650, "ロードサイド型": 950, "商業施設型": 800}
SEAT_RANGE = {"駅ナカ型": (10, 24), "ロードサイド型": (40, 80), "商業施設型": (30, 60)}
# モバイルオーダーを除いた残りのうち、店内飲食が占める割合
DINE_IN_SHARE = {"駅ナカ型": 0.25, "ロードサイド型": 0.50, "商業施設型": 0.40}
# チャネル別の客単価倍率(店内飲食はドリンク付きで高め)
CHANNEL_PRICE_FACTOR = {"店内飲食": 1.20, "テイクアウト": 0.88, "モバイルオーダー": 1.00}

# 曜日係数(月〜日)
WEEKDAY_FACTOR = {
    "駅ナカ型": [1.10, 1.10, 1.10, 1.10, 1.12, 0.82, 0.72],
    "ロードサイド型": [0.85, 0.83, 0.85, 0.86, 0.92, 1.32, 1.37],
    "商業施設型": [0.88, 0.86, 0.88, 0.88, 0.95, 1.27, 1.28],
}
# 月別の季節係数(1〜12月):12月が高く、2月・8月がやや低い
MONTH_FACTOR = [0.95, 0.88, 1.00, 1.00, 1.02, 0.97, 0.98, 0.90, 0.97, 1.00, 1.03, 1.18]

# モバイルオーダー比率:期間の始めと終わり
MOBILE_SHARE_START = 0.08
MOBILE_SHARE_END = 0.18


# ---------------------------------------------------------------------------
# 生成関数
# ---------------------------------------------------------------------------
def make_stores(rng: np.random.Generator) -> pd.DataFrame:
    """店舗マスタ(40件)を作成する。"""
    rows = []
    for i, (place, fmt, pref, city, lat, lon) in enumerate(STORE_DEFS, start=1):
        if place in NEW_STORES:
            open_date = pd.Timestamp(NEW_STORES[place])
        else:
            # 既存店は2010〜2023年のどこかで開店
            open_date = pd.Timestamp("2010-01-01") + pd.Timedelta(days=int(rng.integers(0, 365 * 14)))
        lo, hi = SEAT_RANGE[fmt]
        rows.append(
            {
                "store_id": f"S{i:03d}",
                "store_name": f"こむぎ堂 {place}店",
                "format": fmt,
                "prefecture": pref,
                "city": city,
                "lat": lat,
                "lon": lon,
                "open_date": open_date.date(),
                "seats": int(rng.integers(lo, hi + 1)),
            }
        )
    return pd.DataFrame(rows)


def _store_growth(city: str, rng: np.random.Generator) -> float:
    """市区町村に応じた年率成長率を返す(店舗ごとに少しばらつかせる)。"""
    if city in GOOD_CITIES:
        base = GOOD_CITIES[city]
    elif city in BAD_CITIES:
        base = BAD_CITIES[city]
    else:
        base = BASE_GROWTH
    return base + rng.normal(0, 0.02)


def make_daily_sales(stores: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """日次売上(店舗×日付×チャネル)を作成する。"""
    dates = pd.date_range(START_DATE, END_DATE, freq="D")
    n_days = len(dates)
    t_years = (dates - START_DATE).days.to_numpy() / 365.0
    progress = np.arange(n_days) / (n_days - 1)  # 期間の進み具合(0→1)
    month_f = np.array(MONTH_FACTOR)[dates.month.to_numpy() - 1]
    weekday = dates.weekday.to_numpy()
    mobile_share = MOBILE_SHARE_START + (MOBILE_SHARE_END - MOBILE_SHARE_START) * progress

    frames = []
    for store in stores.itertuples(index=False):
        fmt = store.format
        place = store.store_name.removeprefix("こむぎ堂 ").removesuffix("店")
        open_ts = pd.Timestamp(store.open_date)

        # 店舗固有の規模感(同じ業態でも店ごとに差をつける)
        scale = rng.lognormal(0, 0.18)
        growth = _store_growth(store.city, rng)

        total = (
            BASE_DAILY_SALES[fmt]
            * scale
            * np.power(1 + growth, t_years)
            * month_f
            * np.array(WEEKDAY_FACTOR[fmt])[weekday]
            * rng.lognormal(0, 0.08, n_days)
        )

        # 新店:開店日以前は対象外、開店後は約3ヶ月かけて立ち上がる
        days_since_open = (dates - open_ts).days.to_numpy()
        is_open = days_since_open >= 0
        ramp = np.where(is_open, 1.0 - 0.40 * np.exp(-np.maximum(days_since_open, 0) / 45.0), 0.0)
        # オープン直後の1週間は話題性で少し上振れ
        ramp = ramp * np.where((days_since_open >= 0) & (days_since_open < 7), 1.35, 1.0)
        total = total * ramp

        # 改装休業期間は売上ゼロ
        if place in RENOVATIONS:
            s, e = (pd.Timestamp(x) for x in RENOVATIONS[place])
            total = np.where((dates >= s) & (dates <= e), 0.0, total)

        # チャネル配分(店舗ごとに店内飲食の比率とモバイルオーダーの普及度をばらつかせる)
        dine_in = float(np.clip(DINE_IN_SHARE[fmt] + rng.normal(0, 0.07), 0.10, 0.70))
        store_mobile = np.clip(mobile_share * rng.lognormal(0, 0.30), 0.02, 0.40)
        shares = {
            "店内飲食": (1 - store_mobile) * dine_in,
            "テイクアウト": (1 - store_mobile) * (1 - dine_in),
            "モバイルオーダー": store_mobile,
        }
        unit_price = BASE_UNIT_PRICE[fmt] * rng.lognormal(0, 0.05)

        for ch in CHANNELS:
            ch_sales = total * shares[ch] * rng.lognormal(0, 0.05, n_days)
            ch_price = unit_price * CHANNEL_PRICE_FACTOR[ch] * rng.lognormal(0, 0.03, n_days)
            ch_sales = np.round(ch_sales, -1)  # 10円単位
            customers = np.round(ch_sales / ch_price)
            frames.append(
                pd.DataFrame(
                    {
                        "date": dates[is_open],
                        "store_id": store.store_id,
                        "channel": ch,
                        "sales": ch_sales[is_open].astype("int64"),
                        "customers": customers[is_open].astype("int64"),
                    }
                )
            )

    df = pd.concat(frames, ignore_index=True)
    df["date"] = df["date"].dt.date
    return df.sort_values(["date", "store_id", "channel"]).reset_index(drop=True)


def _excel_style_label(n: int) -> str:
    """0始まりの番号を A, B, ..., Z, AA, AB ... の表記に変換する。"""
    label = ""
    n += 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        label = chr(65 + r) + label
    return label


def make_members(stores: pd.DataFrame, daily_sales: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """会員(約20,000件)を作成する。居住地はメイン店舗の周辺に分布させる。"""
    # 店舗ごとの会員数は直近12ヶ月の売上に比例させる
    recent = daily_sales[pd.to_datetime(daily_sales["date"]) > END_DATE - pd.Timedelta(days=365)]
    weight = recent.groupby("store_id")["sales"].sum().reindex(stores["store_id"]).fillna(0).to_numpy()
    weight = weight / weight.sum()
    store_idx = rng.choice(len(stores), size=N_MEMBERS, p=weight)

    st = stores.iloc[store_idx].reset_index(drop=True)

    # 店舗からの距離:多くは近所(〜2km)、一部は遠方(通勤・通学)
    dist_km = np.where(rng.random(N_MEMBERS) < 0.8, rng.gamma(2.0, 0.6, N_MEMBERS), rng.gamma(3.0, 1.5, N_MEMBERS))
    angle = rng.uniform(0, 2 * np.pi, N_MEMBERS)
    lat = st["lat"].to_numpy() + dist_km * np.sin(angle) / 111.0
    lon = st["lon"].to_numpy() + dist_km * np.cos(angle) / (111.0 * np.cos(np.radians(st["lat"].to_numpy())))

    # 入会日:2019年以降、かつメイン店舗の開店日以降
    earliest = np.maximum(
        pd.to_datetime(st["open_date"]).to_numpy(), np.datetime64("2019-01-01")
    ).astype("datetime64[D]")
    span = (np.datetime64(END_DATE.date()) - earliest).astype(int)
    join_date = earliest + (rng.random(N_MEMBERS) * span).astype(int)

    # 直近12ヶ月の来店回数:約25%は休眠(0回)、好調エリアはやや多め
    city = st["city"].to_numpy()
    mean_visits = np.where(np.isin(city, list(GOOD_CITIES)), 14.0, np.where(np.isin(city, list(BAD_CITIES)), 8.0, 11.0))
    visits = rng.negative_binomial(1.5, 1.5 / (1.5 + mean_visits))
    visits = np.where(rng.random(N_MEMBERS) < 0.25, 0, visits)

    # 入会から1年未満の会員は、在籍期間に応じて来店回数を按分
    tenure_ratio = np.clip((np.datetime64(END_DATE.date()) - join_date).astype(int) / 365.0, 0, 1)
    visits = np.round(visits * tenure_ratio).astype("int64")

    return pd.DataFrame(
        {
            "member_id": [f"M{i:05d}" for i in range(1, N_MEMBERS + 1)],
            # 個人を特定できないよう、約100m単位に丸める
            "home_lat": np.round(lat, 3),
            "home_lon": np.round(lon, 3),
            "main_store_id": st["store_id"].to_numpy(),
            "join_date": pd.to_datetime(join_date).date,
            "visits_12m": visits,
        }
    )


def make_competitors(stores: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """競合店(約60件)を作成する。多くは自社店舗の周辺、一部は周辺地域に分散させる。"""
    n_near = 45
    near_idx = rng.choice(len(stores), size=n_near)
    near_dist = rng.uniform(0.3, 3.0, n_near)
    near_angle = rng.uniform(0, 2 * np.pi, n_near)
    base_lat = stores["lat"].to_numpy()[near_idx]
    base_lon = stores["lon"].to_numpy()[near_idx]
    lat_near = base_lat + near_dist * np.sin(near_angle) / 111.0
    lon_near = base_lon + near_dist * np.cos(near_angle) / (111.0 * np.cos(np.radians(base_lat)))

    n_far = N_COMPETITORS - n_near
    far_idx = rng.choice(len(stores), size=n_far)
    far_dist = rng.uniform(4.0, 10.0, n_far)
    far_angle = rng.uniform(0, 2 * np.pi, n_far)
    fb_lat = stores["lat"].to_numpy()[far_idx]
    fb_lon = stores["lon"].to_numpy()[far_idx]
    lat_far = fb_lat + far_dist * np.sin(far_angle) / 111.0
    lon_far = fb_lon + far_dist * np.cos(far_angle) / (111.0 * np.cos(np.radians(fb_lat)))

    return pd.DataFrame(
        {
            "competitor_id": [f"C{i:03d}" for i in range(1, N_COMPETITORS + 1)],
            "name": [f"競合ベーカリー{_excel_style_label(i)}" for i in range(N_COMPETITORS)],
            "lat": np.round(np.concatenate([lat_near, lat_far]), 4),
            "lon": np.round(np.concatenate([lon_near, lon_far]), 4),
        }
    )


def main() -> None:
    """全データを生成して data/ に保存する。"""
    rng = np.random.default_rng(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    stores = make_stores(rng)
    daily_sales = make_daily_sales(stores, rng)
    members = make_members(stores, daily_sales, rng)
    competitors = make_competitors(stores, rng)

    outputs = {
        "stores": stores,
        "daily_sales": daily_sales,
        "members": members,
        "competitors": competitors,
    }
    for name, df in outputs.items():
        path = DATA_DIR / f"{name}.parquet"
        df.to_parquet(path, index=False)
        print(f"{name:12s}: {len(df):>7,} 件 → {path.relative_to(DATA_DIR.parent)}")


if __name__ == "__main__":
    main()
