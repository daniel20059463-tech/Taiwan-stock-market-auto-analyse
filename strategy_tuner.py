"""
Strategy tuner for end-of-day parameter adjustment.

The tuner reviews recent closed trades, estimates whether the current entry and
trailing-stop settings are too loose or too strict, and writes recommended
values back to `strategy_params.json`.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

_PARAMS_FILE = os.path.join(os.path.dirname(__file__), "strategy_params.json")
_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))

_DEFAULTS: dict[str, float] = {
    "BUY_SIGNAL_PCT": 2.0,
    "TRAIL_STOP_ATR_MULT": 2.0,
    "VOLUME_CONFIRM_MULT": 1.5,
}

_MAX_CHANGE_RATIO = 0.20
_MIN_TRADE_COUNT = 10


@dataclass
class ParamChange:
    param_name: str
    old_value: float
    new_value: float
    reason: str
    trade_count_basis: int


@dataclass
class ParamRecommendation:
    changes: list[ParamChange] = field(default_factory=list)

    def is_empty(self) -> bool:
        return len(self.changes) == 0


class StrategyTuner:
    """Analyze recent trades and recommend conservative parameter updates."""

    def __init__(
        self,
        *,
        db_session_factory: Any,
        telegram_token: str = "",
        chat_id: str = "",
    ) -> None:
        self._db = db_session_factory
        self._token = telegram_token
        self._chat_id = chat_id

    async def run(self, ts_ms: int) -> None:
        """Load recent trades, compute recommendations, and publish results."""
        trades = await self._load_trades()
        if len(trades) < _MIN_TRADE_COUNT:
            logger.info(
                "StrategyTuner: only %d closed trades, need %d, skipping",
                len(trades),
                _MIN_TRADE_COUNT,
            )
            return

        current_params = self.load_params()
        rec = self._analyze_trades(trades, current_params)

        if rec.is_empty():
            logger.info("StrategyTuner: no parameter changes recommended")
            return

        await self._apply(rec, ts_ms)
        await self._send_summary(rec)

    @staticmethod
    def load_params() -> dict[str, float]:
        """Load strategy parameters from JSON, falling back to defaults."""
        try:
            with open(_PARAMS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            params = {k: float(data[k]) for k in _DEFAULTS if k in data}
            return {**_DEFAULTS, **params}
        except FileNotFoundError:
            return dict(_DEFAULTS)
        except Exception as exc:
            logger.warning("Failed to load strategy_params.json: %s", exc)
            return dict(_DEFAULTS)

    def _analyze_trades(
        self, trades: list[dict], current_params: dict[str, float]
    ) -> ParamRecommendation:
        rec = ParamRecommendation()

        buy_trades = [t for t in trades if t["action"] == "SELL"]
        change = self._tune_entry_threshold(
            buy_trades,
            param_name="BUY_SIGNAL_PCT",
            current_value=current_params["BUY_SIGNAL_PCT"],
            direction="long",
        )
        if change:
            rec.changes.append(change)

        all_closed = [t for t in trades if t["action"] == "SELL"]
        change = self._tune_trail_stop_mult(
            all_closed,
            current_value=current_params["TRAIL_STOP_ATR_MULT"],
        )
        if change:
            rec.changes.append(change)

        return rec

    def _tune_entry_threshold(
        self,
        trades: list[dict],
        *,
        param_name: str,
        current_value: float,
        direction: str,
    ) -> ParamChange | None:
        """
        Compare weaker vs stronger entry signals and only tighten thresholds when
        weaker signals materially underperform.
        """
        if len(trades) < _MIN_TRADE_COUNT:
            return None

        def signal_strength(t: dict) -> float:
            if t["price"] <= 0:
                return 0.0
            return abs(t["price"] - t["stop_price"]) / t["price"] * 100

        median_strength = sorted(signal_strength(t) for t in trades)[len(trades) // 2]
        weak = [t for t in trades if signal_strength(t) <= median_strength]
        strong = [t for t in trades if signal_strength(t) > median_strength]

        if not weak or not strong:
            return None

        ev_weak = self._expected_value(weak)
        ev_strong = self._expected_value(strong)

        if ev_strong > 0 and ev_weak < ev_strong * 0.8 and len(weak) >= 5:
            if direction == "long":
                new_value = round(
                    min(current_value * (1 + _MAX_CHANGE_RATIO), current_value + 0.5), 2
                )
            else:
                new_value = round(
                    max(current_value * (1 + _MAX_CHANGE_RATIO), current_value - 0.5), 2
                )

            if abs(new_value - current_value) < 0.01:
                return None

            return ParamChange(
                param_name=param_name,
                old_value=current_value,
                new_value=new_value,
                reason=(
                    f"Weak signals EV={ev_weak:+.0f}, strong signals EV={ev_strong:+.0f}, "
                    f"sample size={len(trades)}"
                ),
                trade_count_basis=len(trades),
            )

        return None

    def _tune_trail_stop_mult(
        self,
        trades: list[dict],
        *,
        current_value: float,
    ) -> ParamChange | None:
        """Widen trailing stops when trail exits underperform take-profit exits."""
        trail_trades = [t for t in trades if t["reason"] == "TRAIL_STOP"]
        profit_trades = [t for t in trades if t["reason"] == "TAKE_PROFIT"]

        if len(trail_trades) < 3 or len(profit_trades) < 3:
            return None

        avg_trail_pnl = sum(t["pnl"] for t in trail_trades) / len(trail_trades)
        avg_profit_pnl = sum(t["pnl"] for t in profit_trades) / len(profit_trades)

        if avg_profit_pnl > 0 and avg_trail_pnl < avg_profit_pnl * 0.6:
            new_value = round(
                min(current_value * (1 + _MAX_CHANGE_RATIO), current_value + 0.5), 2
            )
            if abs(new_value - current_value) < 0.01:
                return None
            return ParamChange(
                param_name="TRAIL_STOP_ATR_MULT",
                old_value=current_value,
                new_value=new_value,
                reason=(
                    f"TRAIL_STOP avg PnL={avg_trail_pnl:+.0f}, "
                    f"TAKE_PROFIT avg PnL={avg_profit_pnl:+.0f}, "
                    f"trail sample size={len(trail_trades)}"
                ),
                trade_count_basis=len(trail_trades) + len(profit_trades),
            )

        return None

    @staticmethod
    def _expected_value(trades: list[dict]) -> float:
        """Estimate expected value from win rate and average win/loss."""
        if not trades:
            return 0.0
        wins = [t["pnl"] for t in trades if t["pnl"] > 0]
        losses = [t["pnl"] for t in trades if t["pnl"] <= 0]
        win_rate = len(wins) / len(trades)
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        return win_rate * avg_win + (1 - win_rate) * avg_loss

    async def _apply(self, rec: ParamRecommendation, ts_ms: int) -> None:
        """Persist recommended values to JSON and store a DB audit log."""
        current = self.load_params()
        for change in rec.changes:
            current[change.param_name] = change.new_value

        now_str = datetime.datetime.fromtimestamp(ts_ms / 1000, tz=_TZ_TW).isoformat()
        reasons = "; ".join(c.reason for c in rec.changes)
        current["updated_at"] = now_str
        current["reason"] = reasons

        try:
            with open(_PARAMS_FILE, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
            logger.info("StrategyTuner: wrote %s", _PARAMS_FILE)
        except Exception as exc:
            logger.warning("Failed to write strategy_params.json: %s", exc)

        await self._save_logs_to_db(rec)

    async def _save_logs_to_db(self, rec: ParamRecommendation) -> None:
        if self._db is None:
            return
        try:
            from models import get_session, save_param_log

            for change in rec.changes:
                async with get_session() as session:
                    await save_param_log(
                        session,
                        param_name=change.param_name,
                        old_value=change.old_value,
                        new_value=change.new_value,
                        reason=change.reason,
                        trade_count_basis=change.trade_count_basis,
                    )
        except Exception as exc:
            logger.warning("StrategyTuner DB log failed: %s", exc)

    async def _load_trades(self) -> list[dict]:
        if self._db is None:
            return []
        try:
            from models import get_session, load_closed_trades

            async with get_session() as session:
                return await load_closed_trades(session, days=30)
        except Exception as exc:
            logger.warning("StrategyTuner failed to load trades: %s", exc)
            return []

    async def _send_summary(self, rec: ParamRecommendation) -> None:
        if not self._token or not self._chat_id or not rec.changes:
            return

        lines = ["[策略調參] 今日參數建議"]
        for c in rec.changes:
            lines.append(f"- {c.param_name}: {c.old_value} -> {c.new_value}")
            lines.append(f"  理由: {c.reason}")
        text = "\n".join(lines)

        try:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{self._token}/sendMessage"
                await session.post(
                    url,
                    json={"chat_id": self._chat_id, "text": text},
                    timeout=aiohttp.ClientTimeout(total=8),
                )
        except Exception as exc:
            logger.warning("StrategyTuner Telegram send failed: %s", exc)
