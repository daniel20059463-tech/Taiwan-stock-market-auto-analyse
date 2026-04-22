"""
Risk manager for paper trading.

This module enforces daily loss limits, rolling drawdown limits, position caps,
ATR-based stop calculation, and transaction-cost-aware net PnL.
"""
from __future__ import annotations

import datetime
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

MAX_DAILY_LOSS_PCT = 2.0
MAX_POSITIONS = 5
MAX_SINGLE_POS_PCT = 10.0
ATR_MULTIPLIER = 2.0
MIN_STOP_PCT = 1.5
MAX_STOP_PCT = 6.0
RISK_REWARD_RATIO = 2.0
RISK_PCT_PER_TRADE = 1.0   # 每筆最大風險：帳戶資金的 1%

TX_FEE_BUY_PCT = 0.1425
TX_FEE_SELL_PCT = 0.1425
TX_TAX_SELL_PCT = 0.3000
TX_TOTAL_RT_PCT = TX_FEE_BUY_PCT + TX_FEE_SELL_PCT + TX_TAX_SELL_PCT
MIN_NET_PROFIT_PCT = TX_TOTAL_RT_PCT + 0.5  # 來回成本 + 0.5% 安全邊際

ROLLING_5DAY_LOSS_PCT = 6.0
MAX_GLOBAL_DRAWDOWN_PCT = 15.0


CONSECUTIVE_LOSS_LIMIT = 3
COOLDOWN_SECONDS = 3600  # 連續虧損後冷卻 1 小時


@dataclass
class RiskState:
    daily_realized_pnl: float = 0.0
    daily_trade_count: int = 0
    current_date: str = ""
    daily_pnl_history: list = field(default_factory=list)
    peak_equity: float | None = None
    consecutive_losses: int = 0
    cooldown_until_ts: float = 0.0


class RiskManager:
    """Stateful portfolio risk manager used by AutoTrader."""

    def __init__(
        self,
        *,
        account_capital: float = 1_000_000.0,
        max_daily_loss_pct: float = MAX_DAILY_LOSS_PCT,
        max_positions: int = MAX_POSITIONS,
        max_single_pos_pct: float = MAX_SINGLE_POS_PCT,
        atr_multiplier: float = ATR_MULTIPLIER,
        min_stop_pct: float = MIN_STOP_PCT,
        max_stop_pct: float = MAX_STOP_PCT,
        risk_reward_ratio: float = RISK_REWARD_RATIO,
        rolling_5day_loss_pct: float = ROLLING_5DAY_LOSS_PCT,
        min_net_profit_pct: float = MIN_NET_PROFIT_PCT,
    ) -> None:
        self.account_capital = account_capital
        self.max_daily_loss = account_capital * max_daily_loss_pct / 100
        self.max_rolling_loss = account_capital * rolling_5day_loss_pct / 100
        self.max_positions = max_positions
        self.max_single_position = account_capital * max_single_pos_pct / 100
        self.atr_multiplier = atr_multiplier
        self.min_stop_pct = min_stop_pct
        self.max_stop_pct = max_stop_pct
        self.risk_reward_ratio = risk_reward_ratio
        self.min_net_profit_pct = min_net_profit_pct
        self.max_global_drawdown_pct = MAX_GLOBAL_DRAWDOWN_PCT
        self.risk_pct_per_trade = RISK_PCT_PER_TRADE

        self._state = RiskState()
        self._state.peak_equity = account_capital
        self._just_entered_cooldown: bool = False

    def _check_date_reset(self) -> None:
        """Roll daily counters and keep a 5-day realized PnL window."""
        today = _today_tw()
        if self._state.current_date != today:
            if self._state.current_date:
                history = self._state.daily_pnl_history
                history.append((self._state.current_date, self._state.daily_realized_pnl))
                if len(history) > 5:
                    history.pop(0)
                logger.info(
                    "RiskManager: rolled date to %s, archived %s pnl=%.0f trades=%d",
                    today,
                    self._state.current_date,
                    self._state.daily_realized_pnl,
                    self._state.daily_trade_count,
                )
            self._state.daily_realized_pnl = 0.0
            self._state.daily_trade_count = 0
            self._state.current_date = today

    def can_buy(
        self,
        symbol: str,
        price: float,
        shares: int,
        current_positions: int,
    ) -> tuple[bool, str]:
        """Check whether a new position is allowed under current risk constraints."""
        self._check_date_reset()

        if self._state.daily_realized_pnl <= -self.max_daily_loss:
            return False, (
                f"今日已實現損益 {self._state.daily_realized_pnl:,.0f}，"
                f"已超過每日損失限制 -{self.max_daily_loss:,.0f}。"
            )

        if self.rolling_5day_pnl <= -self.max_rolling_loss:
            return False, (
                f"近五日損益 {self.rolling_5day_pnl:,.0f}，"
                f"已超過限制 -{self.max_rolling_loss:,.0f}，暫停新單。"
            )

        current_dd_pct = self.current_drawdown_pct
        if current_dd_pct >= self.max_global_drawdown_pct:
            return False, (
                f"目前回撤 {current_dd_pct:.2f}% ，"
                f"已超過 {self.max_global_drawdown_pct:.1f}% 上限，停止開倉。"
            )

        if time.time() < self._state.cooldown_until_ts:
            remaining_min = int((self._state.cooldown_until_ts - time.time()) / 60) + 1
            return False, f"連續虧損冷卻中，約 {remaining_min} 分鐘後恢復交易。"

        if current_positions >= self.max_positions:
            return False, f"持倉檔數已達上限 {self.max_positions}。"

        position_cost = price * shares
        if position_cost > self.max_single_position:
            return False, (
                f"單筆部位金額 {position_cost:,.0f}，"
                f"超過上限 {self.max_single_position:,.0f}。"
            )

        return True, "OK"

    def calc_stop_price(self, entry_price: float, atr: Optional[float]) -> float:
        """Calculate a bounded ATR stop price."""
        if atr is not None and atr > 0:
            raw_stop_pct = self.atr_multiplier * atr / entry_price * 100
            stop_pct = max(self.min_stop_pct, min(self.max_stop_pct, raw_stop_pct))
        else:
            stop_pct = (self.min_stop_pct + self.max_stop_pct) / 2

        stop_price = entry_price * (1 - stop_pct / 100)
        logger.debug(
            "calc_stop_price: entry=%.2f atr=%s stop_pct=%.2f%% stop=%.2f",
            entry_price,
            f"{atr:.4f}" if atr else "N/A",
            stop_pct,
            stop_price,
        )
        return round(stop_price, 2)

    def calc_position_shares(
        self,
        entry_price: float,
        stop_price: float,
        lot_size: int = 1000,
    ) -> int:
        """
        以「每筆最大風險金額」反推持倉張數。

        risk_amount = account_capital × risk_pct_per_trade%
        shares_raw  = risk_amount / (entry_price - stop_price)

        結果：
        - 向下取整到最近的 lot_size 倍數
        - 下限 1 張，上限受 max_single_position 約束
        """
        risk_per_share = entry_price - stop_price
        if risk_per_share <= 0:
            return lot_size

        risk_amount = self.account_capital * self.risk_pct_per_trade / 100
        shares_raw = risk_amount / risk_per_share
        shares = max(lot_size, int(shares_raw // lot_size) * lot_size)

        max_shares_by_capital = int(self.max_single_position / entry_price // lot_size) * lot_size
        shares = min(shares, max(lot_size, max_shares_by_capital))

        return shares

    def calc_target_price(self, entry_price: float, stop_price: float) -> float:
        """Calculate a reward target using the configured risk/reward ratio."""
        risk = entry_price - stop_price
        target = entry_price + risk * self.risk_reward_ratio
        return round(target, 2)

    def on_buy(self, symbol: str, price: float, shares: int) -> None:
        self._check_date_reset()
        self._state.daily_trade_count += 1
        logger.debug("RiskManager.on_buy: %s @ %.2f x %d", symbol, price, shares)

    def on_sell(self, symbol: str, pnl: float) -> None:
        self._check_date_reset()
        self._state.daily_realized_pnl += pnl

        if pnl < 0:
            self._state.consecutive_losses += 1
            if self._state.consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                self._state.cooldown_until_ts = time.time() + COOLDOWN_SECONDS
                self._just_entered_cooldown = True
                logger.warning(
                    "RiskManager: %d consecutive losses, entering %d-second cooldown",
                    self._state.consecutive_losses,
                    COOLDOWN_SECONDS,
                )
        else:
            self._state.consecutive_losses = 0

        current_eq = (
            self.account_capital
            + sum(h_pnl for _, h_pnl in self._state.daily_pnl_history)
            + self._state.daily_realized_pnl
        )
        if self._state.peak_equity is None or current_eq > self._state.peak_equity:
            self._state.peak_equity = current_eq

        logger.info(
            "RiskManager.on_sell: %s pnl=%.0f daily=%.0f current_mdd=%.2f%%",
            symbol,
            pnl,
            self._state.daily_realized_pnl,
            self.current_drawdown_pct,
        )

    def calc_net_pnl(
        self, entry_price: float, sell_price: float, shares: int
    ) -> float:
        """Calculate round-trip net PnL after fees and sell-side tax."""
        gross_pnl = (sell_price - entry_price) * shares
        buy_fee = entry_price * shares * TX_FEE_BUY_PCT / 100
        sell_fee = sell_price * shares * (TX_FEE_SELL_PCT + TX_TAX_SELL_PCT) / 100
        net_pnl = gross_pnl - buy_fee - sell_fee
        logger.debug(
            "calc_net_pnl: gross=%.0f buy_fee=%.0f sell_fee=%.0f net=%.0f",
            gross_pnl,
            buy_fee,
            sell_fee,
            net_pnl,
        )
        return round(net_pnl, 2)

    @property
    def rolling_5day_pnl(self) -> float:
        archived = sum(pnl for _, pnl in self._state.daily_pnl_history)
        return archived + self._state.daily_realized_pnl

    @property
    def is_weekly_halted(self) -> bool:
        return self.rolling_5day_pnl <= -self.max_rolling_loss

    @property
    def is_in_cooldown(self) -> bool:
        return time.time() < self._state.cooldown_until_ts

    @property
    def consecutive_losses(self) -> int:
        return self._state.consecutive_losses

    @property
    def just_entered_cooldown(self) -> bool:
        """Returns True once after cooldown is triggered, then resets."""
        if self._just_entered_cooldown:
            self._just_entered_cooldown = False
            return True
        return False

    @property
    def is_halted(self) -> bool:
        self._check_date_reset()
        return self._state.daily_realized_pnl <= -self.max_daily_loss

    @property
    def daily_pnl(self) -> float:
        return self._state.daily_realized_pnl

    @property
    def daily_trade_count(self) -> int:
        return self._state.daily_trade_count

    @property
    def current_drawdown_pct(self) -> float:
        if self._state.peak_equity is None or self._state.peak_equity <= 0:
            return 0.0
        current_eq = (
            self.account_capital
            + sum(h_pnl for _, h_pnl in self._state.daily_pnl_history)
            + self._state.daily_realized_pnl
        )
        if current_eq >= self._state.peak_equity:
            return 0.0
        return (self._state.peak_equity - current_eq) / self._state.peak_equity * 100.0

    def status_dict(self) -> dict:
        """Return a serializable summary for UI, logs, or Telegram."""
        self._check_date_reset()
        return {
            "date": self._state.current_date,
            "dailyPnl": round(self._state.daily_realized_pnl, 0),
            "dailyLossLimit": round(-self.max_daily_loss, 0),
            "isHalted": self.is_halted,
            "rolling5DayPnl": round(self.rolling_5day_pnl, 0),
            "rolling5DayLimit": round(-self.max_rolling_loss, 0),
            "isWeeklyHalted": self.is_weekly_halted,
            "currentDrawdownPct": round(self.current_drawdown_pct, 2),
            "dailyTradeCount": self._state.daily_trade_count,
            "maxPositions": self.max_positions,
            "maxSinglePosition": round(self.max_single_position, 0),
            "txCostRoundtripPct": TX_TOTAL_RT_PCT,
            "isInCooldown": self.is_in_cooldown,
            "consecutiveLosses": self._state.consecutive_losses,
        }


def _today_tw() -> str:
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(tz=tz_tw).strftime("%Y-%m-%d")


def risk_manager_from_env() -> RiskManager:
    import os

    capital = float(os.getenv("ACCOUNT_CAPITAL", "1000000"))
    return RiskManager(account_capital=capital)
