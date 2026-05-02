from __future__ import annotations

import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trading.positions import PaperPosition, TradeRecord

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))


def _ts_to_date(ts_ms: int) -> str:
    dt = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=_TZ_TW)
    return dt.strftime("%Y-%m-%d")


def build_daily_report_payload(
    ts_ms: int,
    trade_history: list[TradeRecord],
    positions: dict[str, PaperPosition],
    last_prices: dict[str, float],
    risk: Any,
) -> dict[str, Any]:
    """Build the end-of-day report payload from current session state."""
    report_date = _ts_to_date(ts_ms)
    trades = [t for t in trade_history if _ts_to_date(t.ts) == report_date]
    closed_trades = [t for t in trades if t.action in {"SELL", "COVER"}]
    new_positions = [t for t in trades if t.action in {"BUY", "SHORT"}]
    realized_pnl = sum(t.pnl for t in closed_trades)
    wins = sum(1 for t in closed_trades if t.pnl > 0)
    win_rate = wins / len(closed_trades) * 100 if closed_trades else 0.0
    unrealized_pnl = sum(
        (
            (pos.entry_price - last_prices.get(sym, pos.entry_price)) * pos.shares
            if pos.side == "short"
            else (last_prices.get(sym, pos.entry_price) - pos.entry_price) * pos.shares
        )
        for sym, pos in positions.items()
    )
    return {
        "source": "runtime_eod",
        "date": report_date,
        "tradeCount": len(closed_trades),
        "winRate": round(win_rate, 1),
        "realizedPnl": round(realized_pnl, 0),
        "unrealizedPnl": round(unrealized_pnl, 0),
        "totalPnl": round(realized_pnl + unrealized_pnl, 0),
        "riskStatus": risk.status_dict(),
        "newPositions": [
            {
                "symbol": t.symbol,
                "action": t.action,
                "price": round(t.price, 2),
                "shares": t.shares,
                "stopPrice": round(t.stop_price, 2) if t.stop_price else None,
                "ts": t.ts,
            }
            for t in new_positions
        ],
        "trades": [
            {
                "symbol": t.symbol,
                "action": t.action,
                "price": round(t.price, 2),
                "shares": t.shares,
                "reason": t.reason,
                "netPnl": round(t.pnl, 2),
                "grossPnl": round(t.gross_pnl, 2),
                "ts": t.ts,
                "decisionReport": t.decision_report.to_dict()
                if t.decision_report is not None
                and callable(getattr(t.decision_report, "to_dict", None))
                else t.decision_report,
            }
            for t in trades
        ],
    }
