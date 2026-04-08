from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass
class PaperPosition:
    symbol: str
    side: str
    entry_price: float
    shares: int
    entry_ts: int
    entry_change_pct: float
    stop_price: float
    target_price: float
    entry_atr: float | None = None
    peak_price: float = 0.0
    trail_stop_price: float = 0.0


@dataclass
class TradeRecord:
    symbol: str
    action: str
    price: float
    shares: int
    reason: str
    pnl: float
    ts: int
    stop_price: float = 0.0
    target_price: float = 0.0
    gross_pnl: float = 0.0
    decision_report: Any = None


@dataclass
class PositionBook:
    positions: dict[str, PaperPosition] = field(default_factory=dict)
    trade_history: list[TradeRecord] = field(default_factory=list)

    def unrealized_pnl(self, last_prices: Mapping[str, float]) -> float:
        total = 0.0
        for symbol, position in self.positions.items():
            last_price = float(last_prices.get(symbol, position.entry_price))
            if position.side == "short":
                total += (position.entry_price - last_price) * position.shares
            else:
                total += (last_price - position.entry_price) * position.shares
        return total

    def build_snapshot(
        self,
        last_prices: Mapping[str, float],
        *,
        session_id: str,
    ) -> dict[str, Any]:
        positions_payload: list[dict[str, Any]] = []
        unrealized_total = 0.0

        for symbol, position in self.positions.items():
            last_price = float(last_prices.get(symbol, position.entry_price))
            if position.side == "short":
                pnl = (position.entry_price - last_price) * position.shares
                pct = (
                    (position.entry_price - last_price) / position.entry_price * 100
                    if position.entry_price
                    else 0.0
                )
            else:
                pnl = (last_price - position.entry_price) * position.shares
                pct = (
                    (last_price - position.entry_price) / position.entry_price * 100
                    if position.entry_price
                    else 0.0
                )

            unrealized_total += pnl
            positions_payload.append(
                {
                    "symbol": position.symbol,
                    "side": position.side,
                    "entryPrice": position.entry_price,
                    "currentPrice": last_price,
                    "shares": position.shares,
                    "entryTs": position.entry_ts,
                    "stopPrice": position.stop_price,
                    "targetPrice": position.target_price,
                    "trailStopPrice": position.trail_stop_price,
                    "pnl": round(pnl, 0),
                    "pct": round(pct, 2),
                }
            )

        recent_trades = [self._trade_to_payload(trade) for trade in self.trade_history[-20:]]

        return {
            "type": "PAPER_PORTFOLIO",
            "sessionId": session_id,
            "positions": positions_payload,
            "recentTrades": recent_trades,
            "unrealizedPnl": round(unrealized_total, 0),
        }

    @staticmethod
    def _trade_to_payload(trade: TradeRecord) -> dict[str, Any]:
        return {
            "symbol": trade.symbol,
            "action": trade.action,
            "price": trade.price,
            "shares": trade.shares,
            "reason": trade.reason,
            "netPnl": round(trade.pnl, 0),
            "ts": trade.ts,
            "stopPrice": trade.stop_price,
            "targetPrice": trade.target_price,
            "grossPnl": round(trade.gross_pnl, 0),
            "decisionReport": PositionBook._serialize_decision_report(trade.decision_report),
        }

    @staticmethod
    def _serialize_decision_report(value: Any) -> Any:
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return to_dict()
        return value
