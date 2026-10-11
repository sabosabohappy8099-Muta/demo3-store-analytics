"""月次レポートのサンプル(Excel)を data/ に出力するスクリプト。

実行方法:
    python scripts/make_sample_report.py            # 最新月・MOCK の所見で作成
    python scripts/make_sample_report.py 2026-06    # 対象月を指定
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ai_comment import generate_comment  # noqa: E402
from src.config import DATA_DIR  # noqa: E402
from src.data_loader import create_connection  # noqa: E402
from src.queries import available_months  # noqa: E402
from src.report import build_monthly_summary, build_report  # noqa: E402


def main() -> None:
    """対象月のレポートを作成して保存する。"""
    con = create_connection()
    if len(sys.argv) > 1:
        y, m = (int(x) for x in sys.argv[1].split("-"))
        month = date(y, m, 1)
    else:
        month = available_months(con)[0]
    summary = build_monthly_summary(con, month)
    comment = generate_comment(summary, provider="MOCK")
    path = DATA_DIR / f"sample_monthly_report_{month:%Y%m}.xlsx"
    path.write_bytes(build_report(con, month, summary, comment))
    print(f"作成しました: {path.relative_to(DATA_DIR.parent)}")
    print(comment.as_text())


if __name__ == "__main__":
    main()
