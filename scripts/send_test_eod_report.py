from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daily_reporter import daily_reporter_from_env


def _sample_payload() -> dict:
    return {
        "date": "2026-04-04",
        "tradeCount": 3,
        "winRate": 66.7,
        "realizedPnl": 12450.0,
        "unrealizedPnl": 0.0,
        "totalPnl": 12450.0,
        "riskStatus": {
            "isHalted": False,
            "isWeeklyHalted": False,
        },
        "trades": [
            {
                "symbol": "2330",
                "action": "SELL",
                "price": 1012.0,
                "netPnl": 8250.0,
                "reason": "TAKE_PROFIT",
                "decisionReport": {
                    "summary": "新聞催化與技術面同向，事件單按照計畫獲利出場。",
                    "finalReason": "take_profit",
                    "confidence": 82,
                    "bullCase": "多方觀點偏強，量價配合良好。",
                    "bearCase": "空方提醒追價風險仍在，但短線壓力未完全形成。",
                    "riskCase": "風控允許持倉，且報酬風險比仍在可接受區間。",
                    "bullArgument": "多方認為事件催化仍有效，短線續強機率較高。",
                    "bearArgument": "空方認為追價後若量能衰退，容易快速回吐。",
                    "refereeVerdict": "裁決偏向多方，因為量能與價格動能都站在有利位置。",
                    "debateWinner": "bull",
                },
            },
            {
                "symbol": "2454",
                "action": "SELL",
                "price": 1284.0,
                "netPnl": -3100.0,
                "reason": "STOP_LOSS",
                "decisionReport": {
                    "summary": "輿情與技術面出現背離，停損執行正確但進場節奏偏急。",
                    "finalReason": "stop_loss",
                    "confidence": 56,
                    "bullCase": "多方原本期待事件延續，但後續追價承接不足。",
                    "bearCase": "空方認為量價背離已經出現，回落風險偏高。",
                    "riskCase": "風控機制正常，停損有按規則出場。",
                    "bullArgument": "多方認為事件熱度仍在，只是市場需要時間消化。",
                    "bearArgument": "空方認為失守關鍵價位後不應再戀戰。",
                    "refereeVerdict": "裁決偏向空方，因為技術面轉弱後沒有新的支撐證據。",
                    "debateWinner": "bear",
                },
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a test end-of-day report. Sending is opt-in.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send the test report to Telegram. Omit this flag for render-only output.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local", override=False)

    reporter = daily_reporter_from_env()
    if reporter is None:
        raise SystemExit("缺少 Telegram 設定，請先在 .env 補上 TELEGRAM_BOT_TOKEN 與 TELEGRAM_CHAT_ID。")

    payload = _sample_payload()
    if not args.send:
        result = reporter.build_fallback_report(payload, reporter.select_highlight_trades(payload["trades"]))
        print("DRY_RUN_ONLY")
        print(result)
        return 0

    result = reporter.build_and_send(day_payload=payload)
    print(json.dumps({"usedFallback": result.used_fallback, "highlightCount": result.highlight_count}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
