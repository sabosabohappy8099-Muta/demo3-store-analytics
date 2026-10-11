"""全ページのスモークテスト:さまざまな絞り込み条件で、例外が出ずに表示できることを確認する。"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
PAGES = [
    None,  # 全体サマリー(app.py)
    "app_pages/1_地域別分析.py",
    "app_pages/2_店舗詳細.py",
    "app_pages/3_地図分析.py",
    "app_pages/4_商圏シミュレーション.py",
    "app_pages/5_レポート出力.py",
]

# 保存用キーに直接値を入れて、条件を再現する
SCENARIOS = {
    "初期状態": {},
    "今月": {"flt_preset": "今月"},
    "昨年(比較期間がデータ範囲外)": {"flt_preset": "昨年"},
    "前期間比較": {"flt_compare": "前期間", "flt_preset": "今年"},
    "カスタム1日": {"flt_preset": "カスタム", "flt_custom": (__import__("datetime").date(2026, 2, 18),) * 2},
    "神奈川・駅ナカ": {"flt_prefs": ["神奈川県"], "flt_formats": ["駅ナカ型"]},
    "モバイルのみ": {"flt_channels": ["モバイルオーダー"]},
    # 新店(2026/6開店)だけを選び、開店前の期間を表示 → 該当データなしになる
    "該当データなし": {"flt_stores": ["S010"], "flt_preset": "昨年"},
    "全レイヤー": {"map_layers": ["店舗バブル", "会員の分布", "競合店"]},
}


def _run(page: str | None, state: dict) -> AppTest:
    """指定ページを、指定した session_state で実行する。"""
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    for k, v in state.items():
        at.session_state[k] = v
    at.run()
    if page:
        at.switch_page(page)
        at.run()
    return at


@pytest.mark.parametrize("scenario", list(SCENARIOS))
@pytest.mark.parametrize("page", PAGES, ids=lambda p: Path(p).stem if p else "全体サマリー")
def test_page_renders_without_error(page: str | None, scenario: str) -> None:
    at = _run(page, SCENARIOS[scenario])
    assert not at.exception, [e.message for e in at.exception]
    assert at.title  # 見出しまで描画されている


def test_empty_data_message() -> None:
    at = _run(None, SCENARIOS["該当データなし"])
    assert any("該当データがありません" in i.value for i in at.info)


@pytest.mark.parametrize("method", ["既存店を選ぶ", "緯度経度を入力", "市区町村の中心点"])
def test_trade_area_methods(method: str) -> None:
    at = _run("app_pages/4_商圏シミュレーション.py", {"ta_method": method, "ta_radius": 5.0})
    assert not at.exception, [e.message for e in at.exception]


def test_report_button() -> None:
    at = _run("app_pages/5_レポート出力.py", {})
    next(b for b in at.button if b.label == "月次レポートを作成").click()
    at.run()
    assert not at.exception
    assert any("所見コメント" == s.value for s in at.subheader)
