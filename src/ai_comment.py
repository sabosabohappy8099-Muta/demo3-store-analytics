"""月次レポートの所見文を生成する(MOCK / CLAUDE / GEMINI)。

- 方式は環境変数または secrets の AI_PROVIDER で切り替える(初期値は MOCK)
- AI には集計済みの数値(要約データ)だけを渡し、生データは渡さない
- API 呼び出しに失敗した場合は MOCK にフォールバックし、注記を付ける
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from src.config import format_count, format_pct, format_yen

PROVIDERS = ("MOCK", "CLAUDE", "GEMINI")
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"

# 店舗の前年比がこれを超えたら「急増」、下回ったら「急減」とみなす
SURGE_THRESHOLD = 0.15
DROP_THRESHOLD = -0.08


@dataclass
class Comment:
    """所見文。headline は1文の総括、points は箇条書き。"""

    headline: str
    points: list[str]
    provider: str  # 実際に生成した方式(フォールバック時は MOCK)
    note: str = ""  # フォールバックなどの注記
    requested: str = "MOCK"  # 設定上の方式
    extra: dict = field(default_factory=dict)

    def as_text(self) -> str:
        """プレーンテキスト(Excel 貼り付け用)に変換する。"""
        return "\n".join([self.headline, *[f"・{p}" for p in self.points]])


# ---------------------------------------------------------------------------
# 設定の読み込み
# ---------------------------------------------------------------------------
def get_setting(name: str, default: str = "") -> str:
    """環境変数 → Streamlit の secrets の順に設定値を探す。"""
    value = os.environ.get(name)
    if value:
        return value
    try:
        import streamlit as st

        return str(st.secrets.get(name, default))
    except Exception:  # secrets.toml がない場合など
        return default


def current_provider() -> str:
    """設定されている方式を返す(不正な値は MOCK)。"""
    value = get_setting("AI_PROVIDER", "MOCK").strip().upper()
    return value if value in PROVIDERS else "MOCK"


# ---------------------------------------------------------------------------
# MOCK:数値のルールからテンプレート文を作る
# ---------------------------------------------------------------------------
def _yoy_text(v: float | None) -> str:
    """前年比を「前年比+5.2%」のような文にする。"""
    return "前年比較なし" if v is None else f"前年比{format_pct(v)}"


def generate_mock(summary: dict) -> Comment:
    """要約データから、ルールベースで所見文を作る(API 不要・無料)。"""
    t = summary["total"]
    month = summary["month_label"]
    yoy = t["sales_yoy"]
    if yoy is None:
        trend = "前年同月のデータがないため比較できません"
    elif yoy >= 0.03:
        trend = "増収"
    elif yoy <= -0.03:
        trend = "減収"
    else:
        trend = "ほぼ横ばい"
    headline = f"{month}の売上は{format_yen(t['sales'])}({_yoy_text(yoy)})で、{trend}でした。"
    same = t.get("same_store_sales_yoy")
    if same is not None and yoy is not None and abs(same - yoy) >= 0.005:
        headline += f"新店を除く既存店ベースでは{_yoy_text(same)}です。"

    points: list[str] = []
    # 客数と客単価のどちらが売上の増減に効いたか
    cy, uy = t["customers_yoy"], t["unit_price_yoy"]
    if cy is not None and uy is not None:
        driver = "客数" if abs(cy) >= abs(uy) else "客単価"
        points.append(
            f"客数は{format_count(t['customers'], '人')}({_yoy_text(cy)})、客単価は{format_count(t['unit_price'], '円')}"
            f"({_yoy_text(uy)})。売上の変化は主に{driver}によるものです。"
        )

    prefs = [p for p in summary["prefectures"] if p["yoy"] is not None]
    if len(prefs) >= 2:
        best = max(prefs, key=lambda p: p["yoy"])
        worst = min(prefs, key=lambda p: p["yoy"])
        points.append(
            f"既存店ベースの都道府県別では{best['name']}が{_yoy_text(best['yoy'])}で最も伸び、"
            f"{worst['name']}は{_yoy_text(worst['yoy'])}にとどまりました。"
        )

    cities = summary["cities_top"], summary["cities_bottom"]
    if cities[0] and cities[1]:
        top = "、".join(f"{c['name']}({format_pct(c['yoy'])})" for c in cities[0])
        bottom = "、".join(f"{c['name']}({format_pct(c['yoy'])})" for c in cities[1])
        points.append(f"市区町村別(既存店)の伸び上位は{top}、下位は{bottom}です。")

    surges = [s for s in summary["stores_top"] if s["yoy"] >= SURGE_THRESHOLD]
    drops = [s for s in summary["stores_bottom"] if s["yoy"] <= DROP_THRESHOLD]
    if surges:
        points.append("急増した店舗:" + "、".join(f"{s['name']}({format_pct(s['yoy'])})" for s in surges) + "。")
    if drops:
        points.append(
            "急減した店舗:" + "、".join(f"{s['name']}({format_pct(s['yoy'])})" for s in drops)
            + "。要因(競合・立地環境・オペレーション)の確認をおすすめします。"
        )

    formats = [f for f in summary["formats"] if f["yoy"] is not None]
    if formats:
        best_f = max(formats, key=lambda f: f["yoy"])
        points.append(f"業態別(既存店)では{best_f['name']}が{_yoy_text(best_f['yoy'])}で最も好調でした。")

    mobile = summary.get("mobile_share")
    if mobile and mobile["current"] is not None:
        if mobile["previous"] is not None:
            diff_pt = (mobile["current"] - mobile["previous"]) * 100
            points.append(
                f"モバイルオーダー比率は{format_pct(mobile['current'], signed=False)}"
                f"(前年同月{format_pct(mobile['previous'], signed=False)}、{diff_pt:+.1f}ポイント)と拡大が続いています。"
                if diff_pt > 0
                else f"モバイルオーダー比率は{format_pct(mobile['current'], signed=False)}(前年同月から{diff_pt:+.1f}ポイント)です。"
            )

    if summary["new_stores"]:
        names = "、".join(f"{s['name']}({s['open_date']}開店)" for s in summary["new_stores"])
        points.append(f"直近1年の新店:{names}。既存店の前年比には含めていませんが、全体の売上を押し上げています。")
    if summary["closed_stores"]:
        names = "、".join(f"{s['name']}({s['days']}日間)" for s in summary["closed_stores"])
        points.append(f"売上ゼロの日があった店舗(改装休業など):{names}。")

    return Comment(headline=headline, points=points, provider="MOCK")


# ---------------------------------------------------------------------------
# CLAUDE / GEMINI
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "あなたはベーカリーカフェチェーンの経営企画担当者です。"
    "渡される月次実績の要約データ(JSON)だけを根拠に、経営会議向けの所見を日本語で書いてください。"
    "データにない数値や事実を作らないこと。金額は「1億2,345万円」「1,234万円」のように読みやすく表記すること。"
    "headline は1文の総括、points は3〜6個の箇条書き(各1〜2文)にし、"
    "好調・不調の要因の仮説と、確認すべき次のアクションを含めてください。"
)

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "points"],
    "additionalProperties": False,
}


def _user_prompt(summary: dict) -> str:
    """要約データを JSON にして指示文と組み合わせる。"""
    return "次の月次実績の要約データをもとに所見を作成してください。\n\n" + json.dumps(
        summary, ensure_ascii=False, sort_keys=True, default=str
    )


def _parse_comment(text: str, provider: str) -> Comment:
    """AI の出力(JSON 文字列)を Comment に変換する。形式が不正なら例外。"""
    data = json.loads(text)
    headline = str(data["headline"]).strip()
    points = [str(p).strip() for p in data["points"] if str(p).strip()]
    if not headline or not points:
        raise ValueError("所見の内容が空でした")
    return Comment(headline=headline, points=points, provider=provider)


def generate_claude(summary: dict) -> Comment:
    """Anthropic API(Claude)で所見を生成する。"""
    import anthropic

    api_key = get_setting("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません")
    client = anthropic.Anthropic(api_key=api_key, timeout=90.0, max_retries=1)
    response = client.beta.messages.create(
        model=get_setting("CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _user_prompt(summary)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        # 安全上の理由で応答が拒否された場合は、サーバー側で別モデルに引き継ぐ
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("AI が応答を辞退しました")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("出力が上限で途切れました")
    text = next((b.text for b in response.content if b.type == "text"), "")
    return _parse_comment(text, "CLAUDE")


def generate_gemini(summary: dict) -> Comment:
    """Google Gemini API で所見を生成する。"""
    from google import genai
    from google.genai import types

    api_key = get_setting("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY が設定されていません")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=get_setting("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
        contents=_user_prompt(summary),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            response_json_schema=OUTPUT_SCHEMA,
        ),
    )
    return _parse_comment(response.text or "", "GEMINI")


def generate_comment(summary: dict, provider: str | None = None) -> Comment:
    """設定に応じて所見を生成する。API が失敗したら MOCK にフォールバックする。"""
    requested = (provider or current_provider()).upper()
    if requested not in PROVIDERS:
        requested = "MOCK"
    if requested == "MOCK":
        return generate_mock(summary)
    try:
        comment = generate_claude(summary) if requested == "CLAUDE" else generate_gemini(summary)
        comment.requested = requested
        return comment
    except Exception as e:  # API キー未設定・通信エラー・形式不正などはすべて MOCK に切り替える
        fallback = generate_mock(summary)
        fallback.requested = requested
        fallback.note = f"{requested} での生成に失敗したため、ルールベース(MOCK)の所見を表示しています。({type(e).__name__}: {e})"
        return fallback
