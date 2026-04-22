from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backtest_results" / "strong_stocks_intraday.json"
TARGET = ROOT / "backtest_results" / "strong_stocks_intraday.md"


def _fmt_signed(value: float) -> str:
    rounded = round(value, 0)
    return f"{rounded:+,.0f}"


def main() -> int:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    results = payload["results"]

    overall = sorted(results, key=lambda item: (item["total_pnl"], item["win_rate"]), reverse=True)
    profitable = [item for item in overall if item["total_pnl"] > 0]
    win_rate = sorted(
        [item for item in results if item["total_trades"] > 0],
        key=lambda item: (item["win_rate"], item["total_pnl"]),
        reverse=True,
    )
    low_drawdown = sorted(
        [item for item in results if item["total_trades"] > 0],
        key=lambda item: (item["max_drawdown_pct"], -item["total_pnl"]),
    )
    inactive = [item for item in results if item["total_trades"] == 0]

    lines: list[str] = []
    lines.append("# 強勢股回測排行榜")
    lines.append("")
    lines.append(f"期間：`{payload['period']}`")
    lines.append(f"模式：`{payload['mode']}`")
    lines.append(f"更新時間：`{payload['generated_at']}`")
    lines.append("")
    lines.append("## 總排名")
    lines.append("")
    lines.append("| 排名 | 代號 | 名稱 | 總損益 | 勝率 | 交易數 | 最大回撤 | 平均每筆 |")
    lines.append("|---:|---|---|---:|---:|---:|---:|---:|")
    for index, item in enumerate(overall, 1):
        lines.append(
            f"| {index} | {item['symbol']} | {item['name']} | {_fmt_signed(item['total_pnl'])} | "
            f"{item['win_rate']:.1f}% | {item['total_trades']} | {item['max_drawdown_pct']:.2f}% | "
            f"{_fmt_signed(item['avg_pnl_per_trade'])} |"
        )

    lines.append("")
    lines.append("## 獲利前三")
    lines.append("")
    for item in profitable[:3]:
        lines.append(
            f"- `{item['symbol']} {item['name']}`：總損益 `{_fmt_signed(item['total_pnl'])}`，"
            f"勝率 `{item['win_rate']:.1f}%`，最大回撤 `{item['max_drawdown_pct']:.2f}%`。"
        )

    lines.append("")
    lines.append("## 勝率前三")
    lines.append("")
    for item in win_rate[:3]:
        lines.append(
            f"- `{item['symbol']} {item['name']}`：勝率 `{item['win_rate']:.1f}%`，"
            f"交易 `{item['total_trades']}` 筆，總損益 `{_fmt_signed(item['total_pnl'])}`。"
        )

    lines.append("")
    lines.append("## 低回撤前三")
    lines.append("")
    for item in low_drawdown[:3]:
        lines.append(
            f"- `{item['symbol']} {item['name']}`：最大回撤 `{item['max_drawdown_pct']:.2f}%`，"
            f"總損益 `{_fmt_signed(item['total_pnl'])}`，交易 `{item['total_trades']}` 筆。"
        )

    lines.append("")
    lines.append("## 零成交清單")
    lines.append("")
    if inactive:
        for item in inactive:
            lines.append(f"- `{item['symbol']} {item['name']}`：本期未出手。")
    else:
        lines.append("- 本期所有標的都有成交。")

    lines.append("")
    lines.append("## 單檔出場原因摘要")
    lines.append("")
    for item in overall:
        lines.append(f"### {item['symbol']} {item['name']}")
        if item["total_trades"] == 0:
            lines.append("- 本期未出手。")
            lines.append("")
            continue
        counter = Counter(trade.get("reason", "unknown") for trade in item["trade_records"])
        for reason, count in counter.most_common(4):
            lines.append(f"- `{reason}`：{count}")
        lines.append("")

    TARGET.write_text("\n".join(lines), encoding="utf-8")
    print(TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
