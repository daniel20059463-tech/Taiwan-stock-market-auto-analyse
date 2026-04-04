"""
risk_manager.py — 交易風險控制管理器

執行以下風控規則：
  1. 每日最大虧損上限  ─ 帳戶資本 × MAX_DAILY_LOSS_PCT（預設 2%）
  2. 最大同時持倉檔數  ─ MAX_POSITIONS（預設 5 檔）
  3. 單一持倉資金上限  ─ 帳戶資本 × MAX_SINGLE_POSITION_PCT（預設 10%）
  4. ATR 動態停損計算  ─ stop = entry - ATR_MULTIPLIER × ATR（預設 2.0 倍）
     停損幅度限制在 [MIN_STOP_PCT, MAX_STOP_PCT] 之間（避免過鬆/過緊）
  5. 停利目標維持至少 2:1 風報比
  6. 交易成本計入損益  ─ 買進手續費 0.1425%、賣出手續費 0.1425% + 證交稅 0.3%
  7. 5 日滾動損益追蹤  ─ 近 5 交易日累計虧損 >= 帳戶 5% 時暫停買入

使用方式：
    rm = RiskManager(account_capital=1_000_000)
    allowed, reason = rm.can_buy("2330", price=900, shares=1000, current_positions=2)
    if allowed:
        rm.on_buy("2330", price=900, shares=1000)
"""
from __future__ import annotations

import datetime
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── 預設風控參數 ──────────────────────────────────────────────────────────────
MAX_DAILY_LOSS_PCT   = 2.0   # 每日最大虧損：帳戶 2%
MAX_POSITIONS        = 5     # 最多同時持有 5 檔
MAX_SINGLE_POS_PCT   = 10.0  # 單一持倉不超過帳戶 10%
ATR_MULTIPLIER       = 2.0   # ATR 停損倍數
MIN_STOP_PCT         = 1.5   # 最小停損幅度（%）—— 低波動股
MAX_STOP_PCT         = 6.0   # 最大停損幅度（%）—— 高波動股
RISK_REWARD_RATIO    = 2.0   # 最低風報比（停利 / 停損）

# ── 交易成本（台股）─────────────────────────────────────────────────────────
TX_FEE_BUY_PCT    = 0.1425   # 買進手續費（%）
TX_FEE_SELL_PCT   = 0.1425   # 賣出手續費（%）
TX_TAX_SELL_PCT   = 0.3000   # 證交稅（%，僅賣出收取）
TX_TOTAL_RT_PCT   = TX_FEE_BUY_PCT + TX_FEE_SELL_PCT + TX_TAX_SELL_PCT  # 來回 0.585%

# ── 5 日滾動損益上限 ─────────────────────────────────────────────────────────
ROLLING_5DAY_LOSS_PCT = 5.0  # 近 5 交易日累計虧損超過帳戶 5% → 暫停買入


@dataclass
class RiskState:
    daily_realized_pnl: float = 0.0
    daily_trade_count: int = 0
    current_date: str = ""          # YYYY-MM-DD（台北時間）
    daily_pnl_history: list = field(default_factory=list)  # [(date, net_pnl), ...] 最多 5 筆


class RiskManager:
    """
    集中管理所有風控邏輯。AutoTrader 在買入/賣出前後呼叫此類方法。
    所有方法為同步呼叫，可安全地在 asyncio 事件迴圈中使用。
    """

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

        self._state = RiskState()

    # ── 每日重置 ─────────────────────────────────────────────────────────────

    def _check_date_reset(self) -> None:
        """偵測台北時區日期變更，自動重置當日損益計數，並封存前日損益至 5 日歷史。"""
        today = _today_tw()
        if self._state.current_date != today:
            # 封存前日損益（current_date 非空才有資料）
            if self._state.current_date:
                history = self._state.daily_pnl_history
                history.append((self._state.current_date, self._state.daily_realized_pnl))
                # 僅保留最近 5 個交易日
                if len(history) > 5:
                    history.pop(0)
                logger.info(
                    "RiskManager: 新交易日 %s，前日 %s 損益 %.0f 元（%d 筆）存入 5 日歷史",
                    today,
                    self._state.current_date,
                    self._state.daily_realized_pnl,
                    self._state.daily_trade_count,
                )
            self._state.daily_realized_pnl = 0.0
            self._state.daily_trade_count = 0
            self._state.current_date = today

    # ── 買入前審核 ────────────────────────────────────────────────────────────

    def can_buy(
        self,
        symbol: str,
        price: float,
        shares: int,
        current_positions: int,
    ) -> tuple[bool, str]:
        """
        審核是否允許買入。
        回傳 (allowed: bool, reason: str)。
        reason 在 allowed=False 時說明拒絕原因。
        """
        self._check_date_reset()

        # 規則 1：每日最大虧損上限
        if self._state.daily_realized_pnl <= -self.max_daily_loss:
            return False, (
                f"每日虧損上限已達 {self._state.daily_realized_pnl:,.0f} 元"
                f"（上限 -{self.max_daily_loss:,.0f} 元）"
            )

        # 規則 1b：5 日滾動虧損上限
        if self.rolling_5day_pnl <= -self.max_rolling_loss:
            return False, (
                f"近 5 日滾動虧損 {self.rolling_5day_pnl:,.0f} 元"
                f" 超過上限 -{self.max_rolling_loss:,.0f} 元，暫停買入"
            )

        # 規則 2：最大同時持倉檔數
        if current_positions >= self.max_positions:
            return False, f"持倉已達上限 {self.max_positions} 檔"

        # 規則 3：單一持倉資金上限
        position_cost = price * shares
        if position_cost > self.max_single_position:
            return False, (
                f"單一持倉成本 {position_cost:,.0f} 元"
                f" 超過上限 {self.max_single_position:,.0f} 元"
            )

        return True, "OK"

    # ── ATR 動態停損計算 ──────────────────────────────────────────────────────

    def calc_stop_price(self, entry_price: float, atr: Optional[float]) -> float:
        """
        以 ATR 計算停損價格。
        停損幅度：atr_multiplier × ATR，但限制在 [min_stop_pct, max_stop_pct]。
        若 ATR 不可用，退回固定停損（min + max 的中間值）。
        """
        if atr is not None and atr > 0:
            raw_stop_pct = self.atr_multiplier * atr / entry_price * 100
            stop_pct = max(self.min_stop_pct, min(self.max_stop_pct, raw_stop_pct))
        else:
            # 無 ATR 時使用固定中間值
            stop_pct = (self.min_stop_pct + self.max_stop_pct) / 2

        stop_price = entry_price * (1 - stop_pct / 100)
        logger.debug(
            "calc_stop_price: entry=%.2f atr=%s stop_pct=%.2f%% → stop=%.2f",
            entry_price,
            f"{atr:.4f}" if atr else "N/A",
            stop_pct,
            stop_price,
        )
        return round(stop_price, 2)

    def calc_target_price(self, entry_price: float, stop_price: float) -> float:
        """
        停利目標 = entry + risk × risk_reward_ratio（維持 2:1 風報比）。
        """
        risk = entry_price - stop_price
        target = entry_price + risk * self.risk_reward_ratio
        return round(target, 2)

    # ── 交易後更新 ────────────────────────────────────────────────────────────

    def on_buy(self, symbol: str, price: float, shares: int) -> None:
        self._check_date_reset()
        self._state.daily_trade_count += 1
        logger.debug("RiskManager.on_buy: %s @ %.2f × %d", symbol, price, shares)

    def on_sell(self, symbol: str, pnl: float) -> None:
        self._check_date_reset()
        self._state.daily_realized_pnl += pnl
        logger.info(
            "RiskManager.on_sell: %s pnl=%.0f 今日累計=%.0f 元",
            symbol,
            pnl,
            self._state.daily_realized_pnl,
        )

    # ── 交易成本計算 ──────────────────────────────────────────────────────────

    def calc_net_pnl(
        self, entry_price: float, sell_price: float, shares: int
    ) -> float:
        """
        計算扣除台股交易成本後的淨損益。
          買進手續費：entry_price × shares × 0.1425%
          賣出手續費：sell_price × shares × 0.1425%
          賣出證交稅：sell_price × shares × 0.3%
        """
        gross_pnl = (sell_price - entry_price) * shares
        buy_fee  = entry_price * shares * TX_FEE_BUY_PCT / 100
        sell_fee = sell_price  * shares * (TX_FEE_SELL_PCT + TX_TAX_SELL_PCT) / 100
        net_pnl  = gross_pnl - buy_fee - sell_fee
        logger.debug(
            "calc_net_pnl: gross=%.0f buy_fee=%.0f sell_fee=%.0f → net=%.0f",
            gross_pnl, buy_fee, sell_fee, net_pnl,
        )
        return round(net_pnl, 2)

    # ── 狀態查詢 ─────────────────────────────────────────────────────────────

    @property
    def rolling_5day_pnl(self) -> float:
        """近 5 個交易日（已封存）的淨損益總和，不含今日。"""
        return sum(pnl for _, pnl in self._state.daily_pnl_history)

    @property
    def is_weekly_halted(self) -> bool:
        """近 5 日滾動虧損達上限，應暫停買入。"""
        return self.rolling_5day_pnl <= -self.max_rolling_loss

    @property
    def is_halted(self) -> bool:
        """今日虧損已達上限，應暫停全部買入。"""
        self._check_date_reset()
        return self._state.daily_realized_pnl <= -self.max_daily_loss

    @property
    def daily_pnl(self) -> float:
        return self._state.daily_realized_pnl

    @property
    def daily_trade_count(self) -> int:
        return self._state.daily_trade_count

    def status_dict(self) -> dict:
        """回傳風控狀態摘要，供前端或 Telegram 顯示。"""
        self._check_date_reset()
        return {
            "date": self._state.current_date,
            "dailyPnl": round(self._state.daily_realized_pnl, 0),
            "dailyLossLimit": round(-self.max_daily_loss, 0),
            "isHalted": self.is_halted,
            "rolling5DayPnl": round(self.rolling_5day_pnl, 0),
            "rolling5DayLimit": round(-self.max_rolling_loss, 0),
            "isWeeklyHalted": self.is_weekly_halted,
            "dailyTradeCount": self._state.daily_trade_count,
            "maxPositions": self.max_positions,
            "maxSinglePosition": round(self.max_single_position, 0),
            "txCostRoundtripPct": TX_TOTAL_RT_PCT,
        }


# ── 工具函式 ──────────────────────────────────────────────────────────────────

def _today_tw() -> str:
    tz_tw = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(tz=tz_tw).strftime("%Y-%m-%d")


def risk_manager_from_env() -> RiskManager:
    import os
    capital = float(os.getenv("ACCOUNT_CAPITAL", "1000000"))
    return RiskManager(account_capital=capital)
