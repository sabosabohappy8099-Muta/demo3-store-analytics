"""定数・色・パス・表示用の書式関数をまとめたモジュール。"""

from __future__ import annotations

import math
from pathlib import Path

# ---------------------------------------------------------------------------
# パス
# ---------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

# ---------------------------------------------------------------------------
# マスタ的な定数
# ---------------------------------------------------------------------------
APP_TITLE = "こむぎ堂 実績分析ダッシュボード"
COMPANY_NAME = "こむぎ堂ホールディングス株式会社(架空)"
PREFECTURES = ("東京都", "神奈川県", "埼玉県", "千葉県")
FORMATS = ("駅ナカ型", "ロードサイド型", "商業施設型")
CHANNELS = ("店内飲食", "テイクアウト", "モバイルオーダー")
WEEKDAY_LABELS = ("月", "火", "水", "木", "金", "土", "日")

PERIOD_PRESETS = ("今月", "先月", "直近3ヶ月", "今年", "昨年", "カスタム")
COMPARE_MODES = ("前年同期間", "前期間")

# ---------------------------------------------------------------------------
# 色(白基調+小麦色アクセント、増加=緑/減少=赤)
# 緑と赤は色覚によって見分けにくいため、必ず ▲▼ や符号と併用すること
# ---------------------------------------------------------------------------
COLOR_ACCENT = "#B9832A"  # 小麦色(当期・主役の系列)
COLOR_ACCENT_LIGHT = "#F3E6CC"
COLOR_COMPARE = "#A3A29C"  # 比較期間(控えめなグレー)
COLOR_UP = "#1A8A3A"
COLOR_DOWN = "#D23C3C"
COLOR_NEUTRAL = "#6B6A65"
COLOR_TEXT = "#2B2B2B"
COLOR_TEXT_MUTED = "#6B6A65"
COLOR_GRID = "#ECEAE4"
COLOR_SURFACE = "#FFFFFF"

# 業態・チャネルの識別色(固定順。並び順で色が変わらないよう名前に紐づける)
FORMAT_COLORS = {"駅ナカ型": "#B9832A", "ロードサイド型": "#2A78D6", "商業施設型": "#1BAF7A"}
CHANNEL_COLORS = {"店内飲食": "#B9832A", "テイクアウト": "#2A78D6", "モバイルオーダー": "#1BAF7A"}

FONT_FAMILY = '"Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans JP", "Meiryo", sans-serif'


# ---------------------------------------------------------------------------
# 書式関数
# ---------------------------------------------------------------------------
def _is_missing(value: float | None) -> bool:
    """None や NaN を欠損として判定する。"""
    return value is None or (isinstance(value, float) and math.isnan(value))


def format_yen(value: float | None) -> str:
    """金額を「3億8,612万円」「1,234万円」「980円」のような読みやすい表記にする。"""
    if _is_missing(value):
        return "—"
    sign = "-" if value < 0 else ""
    v = abs(value)
    if v >= 1e8:
        oku = int(v // 1e8)
        man = int(round((v - oku * 1e8) / 1e4))
        if man == 10_000:  # 四捨五入で繰り上がった場合
            oku, man = oku + 1, 0
        return f"{sign}{oku}億{man:,}万円" if man else f"{sign}{oku}億円"
    if v >= 1e4:
        return f"{sign}{round(v / 1e4):,}万円"
    return f"{sign}{round(v):,}円"


def format_yen_short(value: float | None) -> str:
    """指標カード用の短い金額表記(1億円以上は「11.50億円」、それ未満は「2,875万円」)。"""
    if _is_missing(value):
        return "—"
    if abs(value) >= 1e8:
        return f"{value / 1e8:,.2f}億円"
    return format_yen(value)


def format_count(value: float | None, unit: str = "") -> str:
    """件数・人数を桁区切りで表示する。"""
    if _is_missing(value):
        return "—"
    return f"{round(value):,}{unit}"


def format_pct(value: float | None, digits: int = 1, signed: bool = True) -> str:
    """比率(0.052 → +5.2%)を表示する。"""
    if _is_missing(value):
        return "—"
    return f"{value * 100:+.{digits}f}%" if signed else f"{value * 100:.{digits}f}%"


def format_delta(value: float | None) -> str:
    """増減率を ▲▼ 付きで表示する(色に頼らず増減が分かるように)。"""
    if _is_missing(value):
        return "比較データなし"
    # 表示上 0.0% になるわずかな増減は「±」とし、記号と数値が食い違わないようにする
    if abs(value) < 0.0005:
        return "± 0.0%"
    mark = "▲" if value > 0 else "▼"
    return f"{mark} {format_pct(value)}"


def delta_color(value: float | None) -> str:
    """増減率に対応する色を返す。"""
    if _is_missing(value) or abs(value) < 0.0005:
        return COLOR_NEUTRAL
    return COLOR_UP if value > 0 else COLOR_DOWN
