"""データ読み込み(キャッシュ付き)と DuckDB 接続の管理。"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

from src.config import DATA_DIR

DATASETS = ("stores", "daily_sales", "members", "competitors")


def create_connection(data_dir: Path = DATA_DIR) -> duckdb.DuckDBPyConnection:
    """Parquet をメモリ上の DuckDB に読み込み、集計用のテーブルを作る。

    sales テーブルは日次売上に店舗属性を結合した「横持ち」の形にして、
    絞り込み条件を JOIN なしで適用できるようにしている。
    """
    missing = [name for name in ("stores", "daily_sales") if not (data_dir / f"{name}.parquet").exists()]
    if missing:
        raise FileNotFoundError(
            f"データファイルが見つかりません: {', '.join(missing)}。"
            "先に python scripts/generate_dummy_data.py を実行してください。"
        )
    con = duckdb.connect(database=":memory:")
    stores_path = (data_dir / "stores.parquet").as_posix()
    sales_path = (data_dir / "daily_sales.parquet").as_posix()
    con.execute(f"CREATE TABLE stores AS SELECT * FROM read_parquet('{stores_path}')")
    con.execute(
        f"""
        CREATE TABLE sales AS
        SELECT d.date, d.store_id, d.channel, d.sales, d.customers,
               s.store_name, s.format, s.prefecture, s.city
        FROM read_parquet('{sales_path}') d JOIN stores s USING (store_id)
        ORDER BY d.date
        """
    )
    return con


@st.cache_resource(show_spinner="データを読み込んでいます…")
def _shared_connection() -> duckdb.DuckDBPyConnection:
    """アプリ全体で共有する DuckDB 接続(初回のみ作成)。"""
    return create_connection()


def get_cursor() -> duckdb.DuckDBPyConnection:
    """共有接続からカーソルを取得する(複数セッションの同時実行に備えて毎回分ける)。"""
    return _shared_connection().cursor()


@st.cache_data(show_spinner=False)
def load_table(name: str) -> pd.DataFrame:
    """Parquet ファイルを DataFrame として読み込む。"""
    if name not in DATASETS:
        raise ValueError(f"未知のデータセットです: {name}")
    return pd.read_parquet(DATA_DIR / f"{name}.parquet")
