"""
Paper-trading engine for the Taiwan stock simulation system.

The module consumes normalized tick payloads, maintains live bar state for
the active session, evaluates the retail-flow swing strategy, enforces risk
controls, and publishes portfolio summaries through Telegram.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
import datetime
import json
import logging
import math
import os
import time
import uuid
from typing import Any, Optional

import aiohttp
from market_calendar import is_known_open_trading_date
from multi_analyst import (
    AnalystContext,
    DecisionComposer,
    NewsAnalyst,
    RiskAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)
from retail_flow_strategy import RetailFlowSwingStrategy
from trading.paper_execution import PaperExecutionService
from trading import (
    CandleBar,
    DecisionFactor,
    DecisionReport,
    MarketState,
    PaperPosition,
    PositionBook,
    TradeRecord,
    SwingRuntimeCoordinator,
    build_daily_report_payload,
)

logger = logging.getLogger(__name__)

# Signal thresholds
BUY_SIGNAL_PCT = 2.0
OPENING_BREAKOUT_PCT = 1.0   # Lower threshold for the 09:00–09:30 opening window
NEAR_LIMIT_UP_PCT = 9.5
LIMIT_LOCK_UP_PCT = 9.5    # 漲停鎖死判定門檻
LIMIT_LOCK_DOWN_PCT = -9.5 # 跌停鎖死判定門檻

# Ex-dividend gap detection
EX_DIVIDEND_GAP_PCT = 3.0  # open vs previousClose 缺口超過此值且大盤無對應跌幅時，視為除權息

# Slippage simulation
SLIPPAGE_BPS = 5  # 5 bps = 0.05% 的單邊滑價
LIQUIDITY_SLIPPAGE_TIERS = (
    (500_000_000.0, 5),
    (100_000_000.0, 10),
    (0.0, 20),
)
ORDER_PRESSURE_LIMIT = 0.05
ORDER_PRESSURE_PENALTY_BPS = 10
NEAR_HIGH_RATIO = 0.90
VOLUME_CONFIRM_MULT = 1.5
ATR_BARS_NEEDED = 5
LOTS_PER_TRADE = 1
SHARES_PER_LOT = 1000
REPORT_INTERVAL = 1800

# Market-wide protection and trailing-stop rules
MARKET_HALT_PCT = -1.5
TRAIL_STOP_ATR_MULT = 2.0
TRAIL_STOP_FALLBACK = 3.0

MIN_AVG_DAILY_VALUE_20D = 100_000_000.0
MARKET_REGIME_BLOCK_PCT = -1.5
MAX_SECTOR_CAPITAL_PCT = 25.0
MARKET_RS_SYMBOL = "TAIEX"

# Entry quality filters
RSI_OVERBOUGHT = 75.0          # RSI 超買門檻，高於此值不進多方
MAX_SECTOR_POSITIONS = 5       # 同一類股最多同時持有的部位數
PREOPEN_WATCHLIST_THRESHOLD = 0.5  # 籌碼確認標的的盤中進場門檻（低於一般動能觸發）

_EXCLUDED_BUY_SECTOR_CODES = {"17"}
_EXCLUDED_BUY_SECTOR_KEYWORDS = ("金融", "保險", "銀行", "證券", "期貨", "金控")

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))


class AutoTrader:
    """Paper-trading coordinator driven by normalized market ticks."""

    def __init__(
        self,
        *,
        telegram_token: str,
        chat_id: str,
        buy_signal_pct: float = BUY_SIGNAL_PCT,
        lots_per_trade: int = LOTS_PER_TRADE,
        report_interval: int = REPORT_INTERVAL,
        risk_manager: Any = None,
        sentiment_filter: Any = None,
        db_session_factory: Any = None,
        daily_reporter: Any = None,
        eod_report_delay_seconds: float = 180.0,
        strategy_tuner: Any = None,
        disposition_filter: Any = None,
        strategy_mode: str = "retail_flow_swing",
        retail_flow_strategy: RetailFlowSwingStrategy | None = None,
        institutional_flow_cache: Any = None,
        daily_price_cache: Any = None,
        daily_price_cache_path: str | None = None,
        local_positions_path: str | None = None,
        slippage_multiplier: float = 1.0,
    ) -> None:
        self._token = telegram_token
        self._chat_id = chat_id
        self._buy_signal_pct = buy_signal_pct
        self._shares = lots_per_trade * SHARES_PER_LOT
        self._report_interval = report_interval
        self._session_id = uuid.uuid4().hex[:8]

        # Risk control and sentiment filter
        if risk_manager is None:
            from risk_manager import RiskManager
            risk_manager = RiskManager()
        self._risk = risk_manager
        self._sentiment = sentiment_filter

        self._db = db_session_factory
        self._daily_reporter = daily_reporter
        self._eod_report_delay_seconds = max(0.0, float(eod_report_delay_seconds))
        self._strategy_tuner = strategy_tuner
        self._disposition = disposition_filter
        self._strategy_mode = strategy_mode
        self._retail_flow_strategy = retail_flow_strategy or RetailFlowSwingStrategy()
        self._institutional_flow_cache = institutional_flow_cache
        self._daily_price_cache = daily_price_cache
        self._daily_price_cache_path = daily_price_cache_path
        self._local_positions_path = local_positions_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "data",
            "paper_positions.json",
        )
        self._slippage_multiplier = max(0.0, float(slippage_multiplier))
        self._daily_closes_recorded = False  # reset each day

        # Runtime state
        self._market = MarketState()
        self._book = PositionBook()
        self._open_prices = self._market.open_prices
        self._prev_close_cache: dict[str, float] = {}
        self._last_prices = self._market.last_prices
        self._positions = self._book.positions
        self._trade_history = self._book.trade_history
        self._decision_history: list[DecisionReport] = []
        self._last_report_ts: float = time.time()
        
        # Heartbeat & Monitoring
        self._last_tick_ts: float = time.time()
        self._last_heartbeat_ts: float = time.time()
        self._monitor_task: asyncio.Task[None] | None = None
        self._session: aiohttp.ClientSession | None = None
        self._news_analyst = NewsAnalyst()
        self._sentiment_analyst = SentimentAnalyst()
        self._technical_analyst = TechnicalAnalyst()
        self._risk_analyst = RiskAnalyst()
        self._decision_composer = DecisionComposer()

        # LLM-based swing exit judge
        from swing_exit_judge import swing_exit_judge_from_env
        self._swing_judge = swing_exit_judge_from_env()

        # Live 1-minute bars are stored in MarketState and reused by the
        # current swing entry / exit logic.
        self._current_bar = self._market.current_bar
        self._candle_history = self._market.bar_history
        self._volume_history = self._market.volume_history

        # Trading-day state
        self._current_date: str = ""
        self._eod_closed: bool = False
        self._eod_report_task: asyncio.Task[Any] | None = None
        self._last_eod_report_date: str | None = None

        # Extracted metrics
        self._market_change_pct: float = 0.0
        self._limit_locked: dict[str, str] = {}  # symbol -> 'up' or 'down'
        self._gap_checked: set[str] = set()       # symbols already gap-checked today
        self._persistence_disabled_reason: str | None = None

        # Sector concentration tracking
        self._symbol_sectors: dict[str, str] = {}   # symbol -> sector（由外部掃描器設定）
        self._position_sectors: dict[str, str] = {}  # 目前持倉的類股對應
        self._execution = PaperExecutionService(
            buy_executor=self._paper_buy,
            sell_executor=self._paper_sell,
        )

        # Pre-open watchlist: stocks with consecutive institutional buying
        self._preopen_watchlist: set[str] = set()
        self._swing_runtime = SwingRuntimeCoordinator()
        self._retail_flow_non_entry_reasons: dict[str, str] = {}
        self._sector_signal_cache: Any = None

        # Sector rotation: cached today's hot/cold sector flow + alert dedup
        self._sector_flows_today: dict[str, Any] = {}   # sector -> SectorFlowSnapshot
        self._rotation_alerted_date: str = ""

        self._build_preopen_watchlist()

    async def on_tick(self, payload: dict[str, Any]) -> None:
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor_loop(), name="autotrader-monitor")
            
        symbol: str = payload["symbol"]
        price: float = float(payload["price"])
        volume: int = int(payload.get("volume", 0))
        ts_ms: int = int(payload["ts"])

        self._last_tick_ts = time.time()

        # Reset daily state when the trading date changes.
        self._maybe_reset_day(ts_ms)

        # ② 更新 K 棒（第一 tick 時會寫入 open_prices）
        is_first_tick_today = symbol not in self._open_prices
        self._market.update_tick(symbol, price=price, volume=volume, ts_ms=ts_ms)

        # ②-a 隔夜跳空保護：換日後對每個有持倉的標的只執行一次
        if is_first_tick_today and symbol not in self._gap_checked:
            self._gap_checked.add(symbol)
            if symbol in self._book.positions:
                await self._check_overnight_gap(symbol, price, ts_ms)

        # ③ 記錄最新價
        if payload.get("previousClose"):
            self._prev_close_cache[symbol] = float(payload["previousClose"])

        # ④ 計算漲跌幅
        previous_close = payload.get("previousClose") or self._open_prices[symbol]
        change_pct = (
            (price - previous_close) / previous_close * 100
            if previous_close else 0.0
        )

        self._update_limit_lock_state(symbol, change_pct, payload)

        # ⑤ 交易時段檢查
        if self._strategy_mode == "retail_flow_swing":
            if not _is_trading_hours(ts_ms):
                return
            # EOD：記錄今日收盤價到日線快取
            if _is_eod_close_time(ts_ms):
                self._record_daily_closes(ts_ms)
            await self._handle_retail_flow_tick(symbol, price, change_pct, ts_ms, payload)
            if time.time() - self._last_report_ts >= self._report_interval:
                await self._send_performance_report()
                self._last_report_ts = time.time()
            return

        raise RuntimeError(
            f"Unsupported strategy_mode at runtime: {self._strategy_mode}. "
            "Only retail_flow_swing is supported."
        )

    # ── 大盤方向更新（由外部 tick 流呼叫）────────────────────────────────────

    def update_market_index(self, change_pct: float) -> None:
        """Update the TAIEX day-change filter used to block new buys."""
        self._market_change_pct = change_pct

    def set_symbol_sector(self, symbol: str, sector: str) -> None:
        """Register a symbol's sector (called by the scanner layer)."""
        self._symbol_sectors[symbol] = sector

    def set_daily_price_cache(self, cache: Any, path: str | None = None) -> None:
        """Inject the daily price cache after construction (called by run.py)."""
        self._daily_price_cache = cache
        if path is not None:
            self._daily_price_cache_path = path

    def set_sector_signal_cache(self, cache: Any) -> None:
        self._sector_signal_cache = cache

    def _maybe_reset_day(self, ts_ms: int) -> None:
        date_str = _ts_to_date(ts_ms)
        if date_str != self._current_date:
            if self._current_date:
                logger.info("AutoTrader: trading day rolled from %s to %s", self._current_date, date_str)
            if self._eod_closed:
                self._detect_ex_dividend_adjustments(ts_ms)
            self._current_date = date_str
            self._market.reset_intraday()
            self._limit_locked.clear()
            self._gap_checked.clear()
            self._eod_closed = False
            self._daily_closes_recorded = False
            if self._eod_report_task is not None and not self._eod_report_task.done():
                self._eod_report_task.cancel()
            self._eod_report_task = None
            self._last_eod_report_date = None
            self._market_change_pct = 0.0
            self._swing_runtime.reset_for_new_day()
            self._retail_flow_non_entry_reasons.clear()
            self._build_preopen_watchlist()

    async def _check_overnight_gap(self, symbol: str, open_price: float, ts_ms: int) -> None:
        """
        換日後第一 tick：檢查開盤價是否跳空越過停損。
        多方持倉開盤跳空向下 → 立即以開盤價平倉。
        空方持倉開盤跳空向上 → 立即以開盤價回補。
        """
        position = self._book.positions.get(symbol)
        if position is None:
            return
        if position.side != "long":
            return

        if open_price < position.stop_price:
            gap_pct = (open_price - position.entry_price) / position.entry_price * 100
            logger.warning(
                "%s overnight gap-down: open=%.2f stop=%.2f entry=%.2f (%.2f%%)",
                symbol, open_price, position.stop_price, position.entry_price, gap_pct,
            )
            await self._send(
                f"[跳空警示] {symbol} 開盤跳空跌破停損\n"
                f"開盤價 {open_price:.2f}（停損 {position.stop_price:.2f}，進場 {position.entry_price:.2f}）\n"
                f"以開盤價強制平倉，損益 {gap_pct:+.2f}%"
            )
            await self._execution.execute_sell(
                symbol=symbol,
                price=open_price,
                reason="STOP_LOSS",
                pct_from_entry=gap_pct,
                ts_ms=ts_ms,
            )

    def _update_limit_lock_state(self, symbol: str, change_pct: float, payload: dict[str, Any]) -> None:
        """更新漲跌停鎖死狀態。"""
        if payload.get("nearLimitUp") and change_pct >= LIMIT_LOCK_UP_PCT:
            self._limit_locked[symbol] = "up"
        elif payload.get("nearLimitDown") and change_pct <= LIMIT_LOCK_DOWN_PCT:
            self._limit_locked[symbol] = "down"
        else:
            self._limit_locked.pop(symbol, None)

    def _detect_ex_dividend_adjustments(self, ts_ms: int) -> None:
        """偵測除權息跳空，校準持倉價位。"""
        # 如果大盤大跌，可能是系統性風險而非除權息
        if self._market_change_pct < -2.0:
            return

        for symbol, pos in list(self._book.positions.items()):
            open_p = self._open_prices.get(symbol)
            prev_p = self._prev_close_cache.get(symbol)
            if not open_p or not prev_p:
                continue

            gap_pct = ((open_p - prev_p) / prev_p) * 100
            if gap_pct <= -EX_DIVIDEND_GAP_PCT:
                adj_ratio = open_p / prev_p
                self._adjust_position_for_ex_dividend(symbol, pos, adj_ratio)

    def _adjust_position_for_ex_dividend(self, symbol: str, pos: PaperPosition, adj_ratio: float) -> None:
        """等比例縮放持倉價位。"""
        pos.entry_price = round(pos.entry_price * adj_ratio, 2)
        pos.stop_price = round(pos.stop_price * adj_ratio, 2)
        pos.target_price = round(pos.target_price * adj_ratio, 2)
        pos.peak_price = round(pos.peak_price * adj_ratio, 2)
        pos.trail_stop_price = round(pos.trail_stop_price * adj_ratio, 2)

    def _calc_atr(self, symbol: str) -> Optional[float]:
        """Calculate a simple ATR from recent 1-minute candles."""
        return self._market.calculate_atr(symbol)

    def _daily_atr(self, symbol: str, period: int = 14) -> Optional[float]:
        """Return daily ATR from the persisted daily price cache.

        Falls back to 1-min ATR when the cache has insufficient history.
        Swing strategies should use this for stop calculation.
        """
        if self._daily_price_cache is not None:
            atr = self._daily_price_cache.atr(
                symbol, period=period, as_of_date=self._prev_trade_date()
            )
            if atr is not None and atr > 0:
                return atr
        return self._calc_atr(symbol)

    def _is_volume_confirmed(self, symbol: str) -> bool:
        """Require the active bar volume to beat the recent 5-bar average."""
        avg_vol = self._market.average_volume(symbol)
        if avg_vol is None:
            return True

        if avg_vol <= 0:
            return True

        current_bar = self._market.latest_bar(symbol)
        current_vol = current_bar.volume if current_bar else 0
        confirmed = current_vol >= avg_vol * VOLUME_CONFIRM_MULT
        if not confirmed:
            logger.debug(
                "%s volume not confirmed: current=%d average=%.0f x %.1f",
                symbol,
                current_vol,
                avg_vol,
                VOLUME_CONFIRM_MULT,
            )
        return confirmed

    def _is_near_day_high(self, symbol: str, price: float, payload: dict[str, Any]) -> bool:
        """Avoid chasing names already trading in the top 10% of the day range."""
        day_high = float(payload.get("high") or price)
        day_low = float(payload.get("low") or price)
        day_range = day_high - day_low
        if day_range <= 0:
            return False

        threshold = day_low + day_range * NEAR_HIGH_RATIO
        if price > threshold:
            logger.debug(
                "%s is too close to the day high: price=%.2f threshold=%.2f range=%.2f",
                symbol,
                price,
                threshold,
                day_range,
            )
            return True
        return False

    def _swing_trade_date(self) -> str:
        current_trade_date = self._current_date or datetime.datetime.now(tz=_TZ_TW).strftime("%Y-%m-%d")
        return _previous_known_open_trading_date(current_trade_date)

    def _average_daily_volume_20d(self, symbol: str) -> float | None:
        if self._daily_price_cache is None:
            return None
        return self._daily_price_cache.average_volume(
            symbol,
            period=20,
            as_of_date=self._prev_trade_date(),
        )

    def _average_daily_value_20d(self, symbol: str) -> float | None:
        if self._daily_price_cache is None:
            return None
        return self._daily_price_cache.average_value(
            symbol,
            period=20,
            as_of_date=self._prev_trade_date(),
        )

    def _latest_bar_notional(self, symbol: str) -> float | None:
        current_bar = self._market.latest_bar(symbol)
        if current_bar is None:
            return None
        close_price = float(getattr(current_bar, "close", 0.0) or 0.0)
        volume = float(getattr(current_bar, "volume", 0) or 0.0)
        if close_price <= 0 or volume <= 0:
            return None
        return close_price * volume

    def _resolve_slippage_bps(self, symbol: str, *, price: float, shares: int) -> int:
        avg_daily_value = self._average_daily_value_20d(symbol) or 0.0
        resolved = SLIPPAGE_BPS
        for min_value, bps in LIQUIDITY_SLIPPAGE_TIERS:
            if avg_daily_value >= min_value:
                resolved = bps
                break

        latest_bar_notional = self._latest_bar_notional(symbol)
        order_notional = price * shares
        if latest_bar_notional and latest_bar_notional > 0:
            if order_notional / latest_bar_notional > ORDER_PRESSURE_LIMIT:
                resolved += ORDER_PRESSURE_PENALTY_BPS
        return max(0, int(round(resolved * getattr(self, "_slippage_multiplier", 1.0))))

    def _passes_market_regime(self) -> bool:
        return self._market_change_pct > MARKET_REGIME_BLOCK_PCT

    def _passes_liquidity_filter(self, symbol: str) -> bool:
        avg_daily_value = self._average_daily_value_20d(symbol)
        if avg_daily_value is None:
            return True
        return avg_daily_value >= MIN_AVG_DAILY_VALUE_20D

    def _sector_position_count(self, sector: str) -> int:
        return sum(1 for value in self._position_sectors.values() if value == sector)

    def _sector_capital_used(self, sector: str) -> float:
        total = 0.0
        for symbol, position in self._book.positions.items():
            if self._position_sectors.get(symbol) != sector:
                continue
            total += float(position.entry_price) * float(position.shares)
        return total

    def _passes_sector_limits(self, sector: str, *, pending_notional: float) -> tuple[bool, str]:
        if not sector:
            return True, "OK"
        if self._sector_position_count(sector) >= MAX_SECTOR_POSITIONS:
            return False, "sector_position_limit"
        account_capital = float(getattr(self._risk, "account_capital", 1_000_000.0))
        sector_cap = account_capital * MAX_SECTOR_CAPITAL_PCT / 100
        if self._sector_capital_used(sector) + pending_notional > sector_cap:
            return False, "sector_capital_limit"
        return True, "OK"

    def _window_return_pct(self, symbol: str, days: int) -> float | None:
        if self._daily_price_cache is None:
            return None
        bars = self._daily_price_cache.get_bars(
            symbol,
            as_of_date=self._prev_trade_date(),
            n=days + 1,
        )
        if len(bars) < days + 1:
            return None
        start_close = float(bars[0].close)
        end_close = float(bars[-1].close)
        if start_close <= 0:
            return None
        return (end_close - start_close) / start_close * 100

    def _relative_strength(self, symbol: str, days: int) -> float | None:
        stock_ret = self._window_return_pct(symbol, days)
        market_ret = self._window_return_pct(MARKET_RS_SYMBOL, days)
        if stock_ret is None or market_ret is None:
            return None
        return stock_ret - market_ret

    def _passes_relative_strength_filter(self, symbol: str) -> bool:
        rs20 = self._relative_strength(symbol, 20)
        rs60 = self._relative_strength(symbol, 60)
        if rs20 is None or rs60 is None:
            return True
        return rs20 > 0 and rs60 > 0

    def _get_sector_state(self, sector: str, trade_date: str | None = None) -> str | None:
        if not sector or self._sector_signal_cache is None:
            return None
        lookup_date = trade_date or self._swing_trade_date()
        record = self._sector_signal_cache.get(lookup_date, sector)
        if record is None:
            latest_date = getattr(self._sector_signal_cache, "latest_trade_date", lambda: None)()
            if latest_date:
                record = self._sector_signal_cache.get(latest_date, sector)
        return None if record is None else record.state

    def get_retail_flow_watch_state(self, symbol: str) -> str | None:
        return self._swing_runtime.watch_states.get(symbol)

    def get_retail_flow_last_non_entry_reason(self, symbol: str) -> str | None:
        return self._retail_flow_non_entry_reasons.get(symbol)

    def get_retail_flow_candidates(self) -> list[str]:
        if self._institutional_flow_cache is None:
            return []
        return sorted(self._institutional_flow_cache.symbols_for_date(self._swing_trade_date()))

    def get_retail_flow_watchlist(self) -> list[str]:
        return sorted(self._preopen_watchlist)

    def get_required_symbols(self) -> list[str]:
        """Return symbols the bridge must subscribe to: watchlist + open positions."""
        symbols = set(self._preopen_watchlist)
        symbols.update(self._book.positions.keys())
        return sorted(symbols)

    def _set_retail_flow_non_entry_reason(self, symbol: str, reason: str) -> None:
        self._retail_flow_non_entry_reasons[symbol] = reason

    def _clear_retail_flow_non_entry_reason(self, symbol: str) -> None:
        self._retail_flow_non_entry_reasons.pop(symbol, None)

    def _is_financial_sector(self, sector: str) -> bool:
        normalized = str(sector or "").strip()
        if not normalized:
            return False
        if normalized in _EXCLUDED_BUY_SECTOR_CODES:
            return True
        return any(keyword in normalized for keyword in _EXCLUDED_BUY_SECTOR_KEYWORDS)

    def _build_preopen_watchlist(self) -> None:
        """每日換日時建立今日籌碼確認標的清單，讓這些股票以較低門檻進場。"""
        if self._institutional_flow_cache is None:
            self._preopen_watchlist = set()
            return
        today = self._swing_trade_date()
        symbols = self._institutional_flow_cache.symbols_for_date(today)
        watchlist: set[str] = set()
        for symbol in symbols:
            if self._institutional_flow_cache.consecutive_trust_buy_days(symbol, today, n=3) >= 2:
                watchlist.add(symbol)
        self._preopen_watchlist = watchlist
        if watchlist:
            logger.info("Pre-open watchlist: %d symbols with ≥2 consecutive trust buy days", len(watchlist))
        self._refresh_sector_flows()

    def _refresh_sector_flows(self) -> None:
        """重新計算今日類股資金熱度，供進場過濾使用。"""
        if self._institutional_flow_cache is None or not self._symbol_sectors:
            self._sector_flows_today = {}
            return
        from sector_rotation import aggregate_sector_flows
        today = self._swing_trade_date()
        rows = self._institutional_flow_cache.rows_for_date(today)
        self._sector_flows_today = aggregate_sector_flows(rows, self._symbol_sectors)

    def _is_sector_cold(self, symbol: str) -> bool:
        """
        回傳 True 表示該標的的類股今日投信為淨賣超（資金正在撤退）。
        若無類股資料或類股未被追蹤，回傳 False（不阻擋）。
        """
        sector = self._symbol_sectors.get(symbol, "")
        if not sector or not self._sector_flows_today:
            return False
        snap = self._sector_flows_today.get(sector)
        if snap is None:
            return False
        return snap.trust_net_buy < 0

    async def _check_sector_rotation(self, ts_ms: int) -> None:
        """
        收盤後偵測類股輪動訊號，只有發現大資金（非當沖）顯著進場才通知。
        同一天只發一次。
        """
        if self._institutional_flow_cache is None or not self._symbol_sectors:
            return
        trade_date = _ts_to_date(ts_ms)
        if self._rotation_alerted_date == trade_date:
            return

        from sector_rotation import aggregate_sector_flows, detect_rotation_signals, format_rotation_alert

        all_dates = self._institutional_flow_cache.available_dates()
        if not all_dates:
            return

        today_rows = self._institutional_flow_cache.rows_for_date(trade_date)
        today_flows = aggregate_sector_flows(today_rows, self._symbol_sectors)
        if not today_flows:
            return

        history_dates = [d for d in all_dates if d < trade_date][-10:]
        history_flows = [
            aggregate_sector_flows(
                self._institutional_flow_cache.rows_for_date(d),
                self._symbol_sectors,
            )
            for d in history_dates
        ]

        signals = detect_rotation_signals(today_flows, history_flows)
        if not signals:
            return

        self._rotation_alerted_date = trade_date
        msg = format_rotation_alert(signals, trade_date)
        if msg:
            await self._send(msg)
            logger.info("Sector rotation alert sent: %d signals", len(signals))

    def _ma_close(self, symbol: str, period: int) -> float | None:
        """1 分鐘 K 棒均線（僅作備用，波段請用 _daily_ma）。"""
        history = list(self._candle_history.get(symbol, ()))
        current_bar = self._current_bar.get(symbol)
        closes = [bar.close for bar in history]
        if current_bar is not None:
            closes.append(current_bar.close)
        if len(closes) < period:
            return None
        recent = closes[-period:]
        return sum(recent) / period

    def _daily_ma(self, symbol: str, period: int) -> float | None:
        """日線 MA，優先用 daily_price_cache，無快取時回傳 None。"""
        if self._daily_price_cache is None:
            return None
        # 用昨日為基準（今日未收盤）
        yesterday = self._prev_trade_date()
        return self._daily_price_cache.ma(symbol, period, as_of_date=yesterday)

    def _daily_rsi(self, symbol: str, period: int = 14) -> float | None:
        """日線 RSI，優先用 daily_price_cache，無快取時回傳 None。"""
        if self._daily_price_cache is None:
            return None
        yesterday = self._prev_trade_date()
        return self._daily_price_cache.rsi(symbol, period, as_of_date=yesterday)

    def _ma10_gap_pct(self, symbol: str, price: float) -> float | None:
        ma10 = self._daily_ma(symbol, 10)
        if ma10 is None or ma10 <= 0:
            return None
        return (price - ma10) / ma10 * 100

    def _consecutive_weak_flow_days(self, symbol: str, as_of_date: str, n: int = 3) -> int:
        if self._institutional_flow_cache is None or self._retail_flow_strategy is None:
            return 0
        dates = sorted(
            [d for d in self._institutional_flow_cache.available_dates() if d <= as_of_date],
            reverse=True,
        )[:n]
        count = 0
        for date_str in dates:
            row = self._institutional_flow_cache.get(date_str, symbol)
            if row is None:
                break
            score = self._retail_flow_strategy.compute_flow_score(row)
            if score > 0:
                break
            count += 1
        return count

    def _prev_trade_date(self) -> str:
        """回傳前一個交易日日期字串（用於日線指標，因今日未收盤）。"""
        current_trade_date = self._current_date or datetime.datetime.now(tz=_TZ_TW).strftime("%Y-%m-%d")
        if self._daily_price_cache is not None:
            return _previous_known_open_trading_date(current_trade_date)
        return current_trade_date

    def _is_above_ma10(self, symbol: str, price: float) -> bool:
        """判斷現價是否在 10 日均線上方。優先使用日線快取；無資料時寬鬆通過。"""
        ma10 = self._daily_ma(symbol, 10)
        if ma10 is not None:
            return price >= ma10
        # 回退到分鐘線（不夠準，但總比完全跳過好）
        ma10_min = self._ma_close(symbol, 10)
        if ma10_min is not None:
            return price >= ma10_min
        return True  # 無資料時不阻擋（寬鬆）

    def _record_daily_closes(self, ts_ms: int) -> None:
        """在 EOD 時把所有已知最新價記入日線快取並存檔。"""
        if self._daily_price_cache is None:
            return
        if self._daily_closes_recorded:
            return
        self._daily_closes_recorded = True
        trade_date = _ts_to_date(ts_ms)
        updated = 0
        for symbol, price in list(self._market.last_prices.items()):
            if price > 0:
                self._daily_price_cache.update_close(symbol, trade_date, price)
                updated += 1
        if updated:
            self._daily_price_cache.prune()
            if self._daily_price_cache_path:
                try:
                    self._daily_price_cache.save(self._daily_price_cache_path)
                except Exception as exc:
                    logger.warning("Failed to save daily price cache: %s", exc)
            logger.info("Recorded daily closes for %d symbols on %s", updated, trade_date)

    async def _handle_retail_flow_tick(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        ts_ms: int,
        payload: dict[str, Any],
    ) -> None:
        position = self._book.positions.get(symbol)
        if position is not None and position.side == "long":
            self._swing_runtime.mark_entered(symbol)
            await self._check_retail_flow_exit(symbol, price, ts_ms)
            return
        if position is not None:
            return
        await self._evaluate_retail_flow_entry(symbol, price, change_pct, ts_ms, payload)

    async def _evaluate_retail_flow_entry(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        ts_ms: int,
        payload: dict[str, Any],
    ) -> None:
        sector = self._symbol_sectors.get(symbol) or str(payload.get("sector", "")).strip()
        if self._is_financial_sector(sector):
            self._set_retail_flow_non_entry_reason(symbol, "financial_sector")
            logger.info("Skip retail_flow_swing entry for %s: excluded sector=%s", symbol, sector)
            return

        if self._institutional_flow_cache is None or self._retail_flow_strategy is None:
            self._set_retail_flow_non_entry_reason(symbol, "strategy_unavailable")
            return

        sector_state = self._get_sector_state(sector)
        if sector_state in {"watch", "weakening", "exit"}:
            self._set_retail_flow_non_entry_reason(symbol, f"sector_state_{sector_state}")
            return

        if not self._passes_market_regime():
            self._set_retail_flow_non_entry_reason(symbol, "market_regime_blocked")
            return

        if not self._passes_liquidity_filter(symbol):
            self._set_retail_flow_non_entry_reason(symbol, "liquidity_below_threshold")
            return

        # 籌碼資料是前一日的（T+1 延遲），以 _swing_trade_date() 取前一交易日
        if not self._passes_relative_strength_filter(symbol):
            self._set_retail_flow_non_entry_reason(symbol, "relative_strength_weak")
            return

        flow_row = self._institutional_flow_cache.get(self._swing_trade_date(), symbol)
        if flow_row is None:
            self._set_retail_flow_non_entry_reason(symbol, "flow_row_missing")
            return

        avg_daily_volume = self._average_daily_volume_20d(symbol)
        avg_daily_value = self._average_daily_value_20d(symbol)
        if avg_daily_volume is not None or avg_daily_value is not None:
            flow_row = replace(
                flow_row,
                avg_daily_volume_20d=avg_daily_volume,
                avg_daily_value_20d=avg_daily_value,
            )

        flow_score = self._retail_flow_strategy.compute_flow_score(flow_row)
        consecutive_days = self._institutional_flow_cache.consecutive_trust_buy_days(
            symbol, self._swing_trade_date(), n=5
        )
        recent_5d_return = self._window_return_pct(symbol, 5)
        recent_runup_pct = recent_5d_return if recent_5d_return is not None else change_pct
        watch_state = self._swing_runtime.classify_entry_state(
            symbol=symbol,
            flow_score=flow_score,
            above_ma10=self._is_above_ma10(symbol, price),
            volume_confirmed=self._is_volume_confirmed(symbol),
            recent_runup_pct=recent_runup_pct,
            consecutive_trust_days=consecutive_days,
            classifier=self._retail_flow_strategy.classify_watch_state,
        )
        if not self._retail_flow_strategy.should_enter_position(watch_state=watch_state):
            self._set_retail_flow_non_entry_reason(symbol, f"watch_state_{watch_state}")
            return
        if not self._swing_runtime.should_trigger_entry(symbol, watch_state):
            self._set_retail_flow_non_entry_reason(symbol, "duplicate_ready_state")
            return

        atr = self._daily_atr(symbol)
        stop_price = self._risk.calc_stop_price(price, atr)
        shares = self._risk.calc_position_shares(price, stop_price)
        allowed, reason = self._passes_sector_limits(sector, pending_notional=price * shares)
        if not allowed:
            self._set_retail_flow_non_entry_reason(symbol, reason)
            return
        allowed, _reason = self._risk.can_buy(symbol, price, shares, len(self._book.positions))
        if not allowed:
            self._set_retail_flow_non_entry_reason(symbol, "risk_rejected")
            return

        target_price = self._risk.calc_target_price(price, stop_price)
        await self._execution.execute_buy(
            symbol=symbol,
            price=price,
            change_pct=change_pct,
            ts_ms=ts_ms,
            stop_price=stop_price,
            target_price=target_price,
            atr=atr,
            decision_report=None,
            shares=shares,
        )
        self._swing_runtime.mark_entered(symbol)
        self._clear_retail_flow_non_entry_reason(symbol)
        logger.info(
            "SwingEntry %s @ %.2f shares=%d stop=%.2f target=%.2f atr=%.2f (籌碼為前日 T+1 資料)",
            symbol, price, shares, stop_price, target_price, atr or 0.0,
        )

    async def _check_retail_flow_exit(self, symbol: str, price: float, ts_ms: int) -> None:
        position = self._book.positions.get(symbol)
        if position is None or position.side != "long":
            return

        # Trailing stop: raise stop as price makes new highs (daily ATR × 3 trail distance)
        if price > position.peak_price:
            position.peak_price = price
            daily_atr = self._daily_atr(symbol)
            trail_dist = (daily_atr * 3.0) if (daily_atr and daily_atr > 0) else (price * TRAIL_STOP_FALLBACK / 100)
            new_trail = position.peak_price - trail_dist
            if new_trail > position.trail_stop_price:
                position.trail_stop_price = round(new_trail, 2)
                logger.debug(
                    "%s swing trail stop raised: peak=%.2f trail=%.2f",
                    symbol, position.peak_price, position.trail_stop_price,
                )

        effective_stop = max(position.stop_price, position.trail_stop_price)

        flow_row = (
            self._institutional_flow_cache.get(self._swing_trade_date(), symbol)
            if self._institutional_flow_cache is not None
            else None
        )
        flow_score = 0.0
        if flow_row is not None and self._retail_flow_strategy is not None:
            flow_score = self._retail_flow_strategy.compute_flow_score(flow_row)
        flow_weak_streak = self._consecutive_weak_flow_days(symbol, self._swing_trade_date(), n=3)

        holding_days = max(0, int((ts_ms - position.entry_ts) / 86_400_000))
        pct_from_entry = (
            (price - position.entry_price) / position.entry_price * 100
            if position.entry_price
            else 0.0
        )
        sentiment_score = self._sentiment.get_score(symbol) if self._sentiment is not None else None
        ma10_gap_pct = self._ma10_gap_pct(symbol, price)
        daily_atr = self._daily_atr(symbol)
        atr_pct = (daily_atr / price * 100) if (daily_atr and price > 0) else None
        sector = self._position_sectors.get(symbol) or self._symbol_sectors.get(symbol, "")
        sector_state = self._get_sector_state(sector)

        judgment = await self._swing_judge.judge(
            symbol=symbol,
            holding_days=holding_days,
            entry_price=position.entry_price,
            current_price=price,
            unrealized_pnl_pct=pct_from_entry,
            above_ma10=self._is_above_ma10(symbol, price),
            flow_score=flow_score,
            flow_weak_streak=flow_weak_streak,
            sentiment_score=sentiment_score,
            market_change_pct=self._market_change_pct,
            stop_loss_hit=price <= effective_stop,
            ma10_gap_pct=ma10_gap_pct,
            atr_pct=atr_pct,
            sector_state=sector_state,
        )

        if judgment.action != "exit":
            return

        reason_map = {
            "stop_loss": "TRAIL_STOP" if position.trail_stop_price > position.stop_price else "STOP_LOSS",
            "ma10_break": "MA10_BREAK",
            "flow_weakened": "FLOW_WEAKENED",
            "time_exit": "TIME_EXIT",
            "sector_exit": "SECTOR_EXIT",
        }
        mapped_reason = reason_map.get(judgment.exit_reason_code or "", "AI_EXIT")
        await self._execution.execute_sell(
            symbol=symbol,
            price=price,
            reason=mapped_reason,
            pct_from_entry=pct_from_entry,
            ts_ms=ts_ms,
        )

    def _build_market_source_events(
        self,
        symbol: str,
        *,
        price: float,
        change_pct: float,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        source_events: list[dict[str, Any]] = [
            {
                "source": "price_momentum",
                "changePct": round(change_pct, 2),
                "price": round(price, 2),
            }
        ]

        sentiment_score = self._sentiment.get_score(symbol) if self._sentiment is not None else None
        if sentiment_score is not None:
            source_events.append(
                {
                    "source": "sentiment_filter",
                    "score": round(sentiment_score, 4),
                }
            )

        if payload.get("article_id"):
            source_events.append(
                {
                    "source": "news_event",
                    "articleId": str(payload["article_id"]),
                }
            )

        return source_events

    def _build_confidence(
        self,
        *,
        change_pct: float,
        volume_confirmed: bool,
        sentiment_score: float | None,
        risk_penalty: int = 0,
    ) -> int:
        confidence = 42
        confidence += min(24, int(abs(change_pct) * 8))
        if volume_confirmed:
            confidence += 12
        if sentiment_score is not None:
            confidence += max(-18, min(18, int(sentiment_score * 20)))
        confidence -= risk_penalty
        return max(5, min(95, confidence))

    def _append_decision_report(self, report: DecisionReport) -> DecisionReport:
        self._decision_history.append(report)
        self._decision_history = self._decision_history[-100:]
        return report

    def _build_portfolio_context(self) -> dict[str, Any]:
        """建立投資組合層級的語境，供 AnalystContext 使用。"""
        closed_trades = [t for t in self._book.trade_history if t.action == "SELL"]
        wins = sum(1 for t in closed_trades if t.pnl > 0)
        win_rate = wins / len(closed_trades) if closed_trades else 0.0
        
        unrealized_pnl = sum(
            (self._last_prices.get(symbol, position.entry_price) - position.entry_price) * position.shares
            for symbol, position in self._book.positions.items()
        )
        
        daily_pnl = self._risk.daily_pnl
        limit = self._risk.status_dict().get("dailyLossLimit", -20_000.0)
        budget_used = 0.0
        if limit < 0 and daily_pnl < 0:
            budget_used = daily_pnl / limit
            
        return {
            "portfolio_positions_count": len(self._book.positions),
            "portfolio_unrealized_pnl": unrealized_pnl,
            "portfolio_daily_win_rate": win_rate,
            "portfolio_risk_budget_used_pct": budget_used,
        }

    def _build_decision_bundle(
        self,
        *,
        symbol: str,
        ts_ms: int,
        decision_type: str,
        trigger_type: str,
        price: float,
        change_pct: float,
        volume_confirmed: bool,
        sentiment_score: float | None,
        risk_allowed: bool,
        risk_reason: str,
        risk_flags: list[str],
        source_events: list[dict[str, Any]],
        supporting_factors: list[DecisionFactor],
        opposing_factors: list[DecisionFactor],
        entry_price: float | None = None,
        current_price: float | None = None,
    ):
        portfolio_ctx = self._build_portfolio_context()
        context = AnalystContext(
            symbol=symbol,
            ts=ts_ms,
            decision_type=decision_type,
            trigger_type=trigger_type,
            price=price,
            change_pct=change_pct,
            volume_confirmed=volume_confirmed,
            sentiment_score=sentiment_score,
            market_change_pct=self._market_change_pct,
            risk_allowed=risk_allowed,
            risk_reason=risk_reason,
            risk_flags=list(risk_flags),
            source_events=list(source_events),
            supporting_factors=[{"label": item.label, "detail": item.detail} for item in supporting_factors],
            opposing_factors=[{"label": item.label, "detail": item.detail} for item in opposing_factors],
            entry_price=entry_price,
            current_price=current_price,
            **portfolio_ctx
        )
        views = [
            self._news_analyst.analyze(context),
            self._sentiment_analyst.analyze(context),
            self._technical_analyst.analyze(context),
            self._risk_analyst.analyze(context),
        ]
        return self._decision_composer.compose(context, views)

    def _record_skip_decision(
        self,
        *,
        symbol: str,
        ts_ms: int,
        final_reason: str,
        summary: str,
        price: float,
        change_pct: float,
        payload: dict[str, Any],
        supporting_factors: list[DecisionFactor] | None = None,
        opposing_factors: list[DecisionFactor] | None = None,
        risk_flags: list[str] | None = None,
        trigger_type: str = "mixed",
        confidence: int = 25,
    ) -> DecisionReport:
        source_events = self._build_market_source_events(
            symbol,
            price=price,
            change_pct=change_pct,
            payload=payload,
        )
        bundle = self._build_decision_bundle(
            symbol=symbol,
            ts_ms=ts_ms,
            decision_type="skip",
            trigger_type=trigger_type,
            price=price,
            change_pct=change_pct,
            volume_confirmed="volume_unconfirmed" not in (risk_flags or []),
            sentiment_score=self._sentiment.get_score(symbol) if self._sentiment is not None else None,
            risk_allowed=False,
            risk_reason=final_reason,
            risk_flags=risk_flags or [],
            source_events=source_events,
            supporting_factors=supporting_factors or [],
            opposing_factors=opposing_factors or [],
        )
        report = DecisionReport(
            report_id=f"{symbol}-{final_reason}-{ts_ms}",
            symbol=symbol,
            ts=ts_ms,
            decision_type="skip",
            trigger_type=trigger_type,
            confidence=confidence,
            final_reason=final_reason,
            summary=summary,
            supporting_factors=supporting_factors or [],
            opposing_factors=opposing_factors or [],
            risk_flags=risk_flags or [],
            source_events=source_events,
            order_result={"status": "skipped"},
            bull_case=bundle.bull_case,
            bear_case=bundle.bear_case,
            risk_case=bundle.risk_case,
            bull_argument=bundle.bull_argument,
            bear_argument=bundle.bear_argument,
            referee_verdict=bundle.referee_verdict,
            debate_winner=bundle.debate_winner,
        )
        return self._append_decision_report(report)

    async def _paper_buy(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        ts_ms: int,
        stop_price: float,
        target_price: float,
        atr: Optional[float],
        decision_report: DecisionReport | None = None,
        shares: int | None = None,
    ) -> None:
        shares = shares if shares is not None else self._shares
        
        # 模擬買進滑價（買得更貴）
        slippage_bps = self._resolve_slippage_bps(symbol, price=price, shares=shares)
        execution_price = round(price * (1 + slippage_bps / 10000), 2)
        
        position = PaperPosition(
            symbol=symbol,
            side="long",
            entry_price=execution_price,
            shares=shares,
            entry_ts=ts_ms,
            entry_change_pct=change_pct,
            stop_price=stop_price,
            target_price=target_price,
            entry_atr=atr,
            peak_price=execution_price,
            trail_stop_price=stop_price,
        )
        self._book.positions[symbol] = position
        sector = self._symbol_sectors.get(symbol, "")
        if sector:
            self._position_sectors[symbol] = sector
        await self._persist_position_open(symbol)

        record = TradeRecord(
            symbol=symbol,
            action="BUY",
            price=execution_price,
            shares=shares,
            reason="SIGNAL",
            pnl=0.0,
            ts=ts_ms,
            stop_price=stop_price,
            target_price=target_price,
            decision_report=decision_report,
        )
        self._book.trade_history.append(record)

        self._risk.on_buy(symbol, execution_price, shares)
        await self._persist_trade(record)

        cost = price * shares
        atr_label = f"{atr:.3f}" if atr is not None else "N/A"
        text = "\n".join(
            [
                "[模擬交易] 買進成交",
                f"股票：{symbol}",
                f"觸發漲幅：+{change_pct:.2f}%",
                f"成交價：{price:,.2f}",
                f"張數：{shares // SHARES_PER_LOT} 張（{shares:,} 股）",
                f"成交金額：{cost:,.0f} 元",
                f"初始停損：{stop_price:,.2f}",
                f"預估停利：{target_price:,.2f}",
                f"ATR：{atr_label}",
                f"時間：{_ms_to_time(ts_ms)}",
            ]
        )
        logger.info(
            "[PAPER BUY] %s @ %.2f change=%.2f%% stop=%.2f target=%.2f atr=%s",
            symbol,
            price,
            change_pct,
            stop_price,
            target_price,
            f"{atr:.4f}" if atr is not None else "N/A",
        )

    async def _check_exit(self, symbol: str, price: float, ts_ms: int) -> None:
        """Check exit conditions for a long position."""
        if self._limit_locked.get(symbol) == "down":
            return
            
        position = self._book.positions[symbol]

        if price > position.peak_price:
            position.peak_price = price
            atr = self._calc_atr(symbol)
            if atr is not None and atr > 0:
                new_trail = position.peak_price - TRAIL_STOP_ATR_MULT * atr
            else:
                new_trail = position.peak_price * (1 - TRAIL_STOP_FALLBACK / 100)
            if new_trail > position.trail_stop_price:
                position.trail_stop_price = round(new_trail, 2)
                logger.debug(
                    "%s trail stop raised: peak=%.2f trail_stop=%.2f",
                    symbol,
                    position.peak_price,
                    position.trail_stop_price,
                )

        # 分批出場：達到 1:1 盈虧比時先出 50%（限 2 張以上持倉），停損移至成本
        if not position.partial_exit_done and position.shares >= 2 * SHARES_PER_LOT:
            risk = position.entry_price - position.stop_price
            if risk > 0 and price >= position.entry_price + risk:
                partial_shares = position.shares // 2
                await self._paper_partial_sell(symbol, price, ts_ms, partial_shares)
                return  # 下一 tick 再繼續追蹤剩餘部位

        effective_stop = max(position.stop_price, position.trail_stop_price)
        reason: Optional[str] = None
        if price <= effective_stop:
            reason = "TRAIL_STOP" if position.trail_stop_price > position.stop_price else "STOP_LOSS"
        elif price >= position.target_price:
            reason = "TAKE_PROFIT"

        if reason:
            pct_from_entry = (price - position.entry_price) / position.entry_price * 100
            await self._execution.execute_sell(
                symbol=symbol,
                price=price,
                reason=reason,
                pct_from_entry=pct_from_entry,
                ts_ms=ts_ms,
            )

    async def _paper_sell(
        self,
        symbol: str,
        price: float,
        reason: str,
        pct_from_entry: float,
        ts_ms: int,
    ) -> None:
        position = self._book.positions.pop(symbol)
        gross_pnl = (price - position.entry_price) * position.shares
        net_pnl = self._risk.calc_net_pnl(position.entry_price, price, position.shares)
        final_reason = {
            "STOP_LOSS": "stop_loss",
            "TRAIL_STOP": "trailing_stop",
            "TAKE_PROFIT": "take_profit",
            "EOD": "end_of_day_exit",
        }.get(reason, reason.lower())
        risk_flag = {
            "STOP_LOSS": "stop_hit",
            "TRAIL_STOP": "trail_stop_hit",
            "TAKE_PROFIT": "target_hit",
            "EOD": "eod_flatten",
        }.get(reason, "exit")
        decision_report = self._append_decision_report(
            DecisionReport(
                report_id=f"{symbol}-sell-{ts_ms}",
                symbol=symbol,
                ts=ts_ms,
                decision_type="sell",
                trigger_type="risk" if reason in {"STOP_LOSS", "TRAIL_STOP", "EOD"} else "technical",
                confidence=max(20, min(92, 60 + int(abs(pct_from_entry) * 4))),
                final_reason=final_reason,
                summary={
                    "STOP_LOSS": "價格跌破保護價位，立即退出以控制單筆損失。",
                    "TRAIL_STOP": "價格自高檔回落至追蹤停損，先保留已獲利部位。",
                    "TAKE_PROFIT": "目標價到達，依計畫先落袋部分事件利潤。",
                    "EOD": "收盤前平倉，避免隔夜事件風險。",
                }.get(reason, "模擬部位已完成出場。"),
                supporting_factors=[
                    DecisionFactor("support", "出場條件", reason),
                    DecisionFactor("support", "報酬變化", f"相對進場 {pct_from_entry:+.2f}%"),
                ],
                opposing_factors=[
                    DecisionFactor("oppose", "放棄後續延伸", "提前出場可能錯過後續趨勢延續"),
                ],
                risk_flags=[risk_flag],
                source_events=[
                    {"source": "position_management", "entryPrice": round(position.entry_price, 2), "currentPrice": round(price, 2)}
                ],
                order_result={
                    "status": "executed",
                    "action": "SELL",
                    "price": round(price, 2),
                    "shares": position.shares,
                    "pnl": round(net_pnl, 2),
                },
            )
        )

        record = TradeRecord(
            symbol=symbol,
            action="SELL",
            price=execution_price,
            shares=position.shares,
            reason=reason,
            pnl=net_pnl,
            ts=ts_ms,
            gross_pnl=gross_pnl,
            decision_report=decision_report,
        )
        self._book.trade_history.append(record)

        self._risk.on_sell(symbol, net_pnl)
        await self._persist_trade(record)

        icon = "停損" if reason in {"STOP_LOSS", "TRAIL_STOP"} else "停利" if reason == "TAKE_PROFIT" else "收盤"
        reason_labels = {
            "STOP_LOSS": "初始停損",
            "TRAIL_STOP": "追蹤停損",
            "TAKE_PROFIT": "目標停利",
            "EOD": "收盤平倉",
        }
        tx_cost = gross_pnl - net_pnl
        daily_pnl = self._risk.daily_pnl
        text = "\n".join(
            [
                f"[模擬交易] {icon}出場",
                f"標的：{symbol}",
                f"原因：{reason_labels.get(reason, reason)}",
                f"進場 / 出場：{position.entry_price:,.2f} / {price:,.2f} (滑價後: {execution_price:,.2f})",
                f"相對報酬：{pct_from_entry:+.2f}%",
                f"毛損益：{gross_pnl:+,.0f} 元",
                f"交易成本：{tx_cost:,.0f} 元",
                f"淨損益：{net_pnl:+,.0f} 元",
                f"當日累計：{daily_pnl:+,.0f} 元",
                f"時間：{_ms_to_time(ts_ms)}",
            ]
        )
        logger.info(
            "[PAPER SELL] %s @ %.2f reason=%s net_pnl=%.0f",
            symbol,
            price,
            reason,
            net_pnl,
        )

        if self._risk.is_halted:
            await self._send(
                f"[風控警示] 當日損益已達限制，今日累計 {daily_pnl:+,.0f} 元，系統暫停新倉。"
            )
        if self._risk.just_entered_cooldown:
            await self._send(
                f"[風控警示] 連續虧損 {self._risk.consecutive_losses + 1} 筆，"
                "系統進入 1 小時冷卻期，暫停所有新開倉。"
            )

    # ── 系統健康監控 (Heartbeat & Stale Data) ───────────────────────────

    async def _monitor_loop(self) -> None:
        """背景監控 Task：定時發送 Heartbeat，並偵測盤中連續無行情斷線"""
        import time
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                ts_ms = int(now * 1000)
                
                # 只在交易時段內監測
                if not _is_trading_hours(ts_ms):
                    continue
                
                time_since_last_tick = now - self._last_tick_ts
                time_since_heartbeat = now - self._last_heartbeat_ts
                
                # 1. Heartbeat - 每 60 分鐘發送一次存活證明
                if time_since_heartbeat >= 3600:
                    try:
                        await self._send("💓 **[連線健康檢查]**\nAutoTrader 系統穩定運行中，資料集收發正常。")
                        self._last_heartbeat_ts = now
                    except Exception as e:
                        logger.debug("Heartbeat send failed (will retry next minute): %s", e)
                
                # 2. 斷線預警 - 盤中超過 15 分鐘無任何行情
                if time_since_last_tick > 900:
                    logger.warning("No ticks received for %.1f seconds during market hours!", time_since_last_tick)
                    # 避免連續狂發，斷線告警也受 heartbeat_ts 節流（至少隔 60 分鐘再發）
                    if time_since_heartbeat >= 3600:
                        try:
                            await self._send("⚠️ **[系統告警]**\n盤中已超過 15 分鐘未收到任何報價 Tick！請檢查券商連線狀態。")
                            self._last_heartbeat_ts = now
                        except Exception as e:
                            logger.error("Failed to send disconnect warning: %s", e)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Monitor loop error: %s", e)
                await asyncio.sleep(60)

    # ── 空方進出場方法 ────────────────────────────────────────────────────────────

    async def _evaluate_short(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        ts_ms: int,
        payload: dict[str, Any],
    ) -> None:
        """評估空方進場條件：利空新聞確認 + 技術轉弱。"""
        sentiment_score = self._sentiment.get_score(symbol) if self._sentiment is not None else None
        supporting_factors = [
            DecisionFactor("support", "盤中弱勢", f"盤中跌幅 {change_pct:+.2f}%"),
        ]

        if self._disposition and self._disposition.is_blocked(symbol):
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="disposition_blocked",
                summary="設定為處置股/全額交割，阻擋進場。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "處置/緩搓", "限制名單")],
                risk_flags=["disposition_blocked"],
                trigger_type="risk",
                confidence=10,
            )
            return

        if sentiment_score is None or sentiment_score >= SHORT_SENTIMENT_THRESHOLD:
            score_str = f"{sentiment_score:.3f}" if sentiment_score is not None else "N/A"
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="sentiment_not_negative",
                summary=f"輿情分數 {score_str} 未達空方門檻，略過放空評估。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "輿情不足", f"情緒分數 {score_str} 需低於 {SHORT_SENTIMENT_THRESHOLD}")],
                risk_flags=["sentiment_not_negative"],
                trigger_type="mixed",
                confidence=30,
            )
            return

        if change_pct > SHORT_SIGNAL_PCT:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="drop_not_sufficient",
                summary=f"跌幅 {change_pct:+.2f}% 未達空方進場門檻 {SHORT_SIGNAL_PCT}%，略過。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "跌幅不足", f"需跌幅 <= {SHORT_SIGNAL_PCT}%")],
                risk_flags=["drop_not_sufficient"],
                trigger_type="technical",
                confidence=25,
            )
            return

        volume_confirmed = self._is_volume_confirmed(symbol)
        if not volume_confirmed:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="volume_not_confirmed",
                summary="量能尚未放大，不追空。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "量能不足", "成交量未達放量門檻")],
                risk_flags=["volume_unconfirmed"],
                trigger_type="technical",
                confidence=28,
            )
            return

        if self._risk.is_weekly_halted:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="weekly_risk_halt",
                summary="近五日風險超限，不開新空倉。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "週風控", f"近五日損益 {self._risk.rolling_5day_pnl:,.0f}")],
                risk_flags=["weekly_halt"],
                trigger_type="risk",
                confidence=12,
            )
            return

        atr = self._calc_atr(symbol)
        long_stop = self._risk.calc_stop_price(price, atr)
        shares = self._risk.calc_position_shares(price, long_stop)

        allowed, reason = self._risk.can_buy(symbol, price, shares, len(self._book.positions))
        if not allowed:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="risk_rejected",
                summary="風控不允許新增空方部位。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "風控限制", reason)],
                risk_flags=["risk_rejected"],
                trigger_type="risk",
                confidence=15,
            )
            return

        long_target = self._risk.calc_target_price(price, long_stop)
        # 空方：停損在進場價上方（反彈即止損），停利在進場價下方
        short_stop = round(price + (price - long_stop), 2)
        short_target = round(price - (long_target - price), 2)

        room_to_target_pct = (price - short_target) / price * 100
        if room_to_target_pct < self._risk.min_net_profit_pct:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="insufficient_profit_room",
                summary=f"空方目標空間 {room_to_target_pct:.2f}% 不足以覆蓋交易成本 {self._risk.min_net_profit_pct:.2f}%。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "獲利空間不足", f"目標 {room_to_target_pct:.2f}% < 門檻 {self._risk.min_net_profit_pct:.2f}%")],
                risk_flags=["insufficient_profit_room"],
                trigger_type="risk",
                confidence=20,
            )
            return

        sector = self._symbol_sectors.get(symbol, "")
        if sector:
            snap = self._sector_flows_today.get(sector)
            if snap is not None and snap.trust_net_buy > 500:
                self._record_skip_decision(
                    symbol=symbol,
                    ts_ms=ts_ms,
                    final_reason="hot_sector_blocks_short",
                    summary=f"類股「{sector}」投信淨買超 {snap.trust_net_buy:+,} 張，資金方向不利放空。",
                    price=price,
                    change_pct=change_pct,
                    payload=payload,
                    supporting_factors=supporting_factors,
                    opposing_factors=[DecisionFactor("oppose", "類股資金反向", f"投信買超 {snap.trust_net_buy:+,} 張")],
                    risk_flags=["hot_sector_blocks_short"],
                    trigger_type="risk",
                    confidence=20,
                )
                return

        source_events = self._build_market_source_events(symbol, price=price, change_pct=change_pct, payload=payload)
        short_supporting = [
            *supporting_factors,
            DecisionFactor("support", "量能確認", "成交量已達放量條件"),
            DecisionFactor("support", "輿情負向", f"情緒分數 {sentiment_score:.3f} 確認利空"),
        ]
        bundle = self._build_decision_bundle(
            symbol=symbol,
            ts_ms=ts_ms,
            decision_type="short",
            trigger_type="mixed",
            price=price,
            change_pct=change_pct,
            volume_confirmed=volume_confirmed,
            sentiment_score=sentiment_score,
            risk_allowed=True,
            risk_reason="風控放行",
            risk_flags=[],
            source_events=source_events,
            supporting_factors=short_supporting,
            opposing_factors=[],
        )
        confidence = self._build_confidence(
            change_pct=change_pct,
            volume_confirmed=volume_confirmed,
            sentiment_score=sentiment_score,
        )
        decision_report = self._append_decision_report(
            DecisionReport(
                report_id=f"{symbol}-short-{ts_ms}",
                symbol=symbol,
                ts=ts_ms,
                decision_type="short",
                trigger_type="mixed",
                confidence=confidence,
                final_reason="short_entry_confirmed",
                summary="利空新聞與盤中轉弱同向，建立空方模擬部位。",
                supporting_factors=short_supporting,
                opposing_factors=[],
                risk_flags=[],
                source_events=source_events,
                order_result={
                    "status": "executed",
                    "action": "SHORT",
                    "price": round(price, 2),
                    "shares": shares,
                },
                bull_case=bundle.bull_case,
                bear_case=bundle.bear_case,
                risk_case=bundle.risk_case,
                bull_argument=bundle.bull_argument,
                bear_argument=bundle.bear_argument,
                referee_verdict=bundle.referee_verdict,
                debate_winner=bundle.debate_winner,
            )
        )
        await self._execution.execute_short(
            symbol=symbol,
            price=price,
            change_pct=change_pct,
            ts_ms=ts_ms,
            stop_price=short_stop,
            target_price=short_target,
            atr=atr,
            decision_report=decision_report,
            shares=shares,
        )

    async def _paper_short(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        ts_ms: int,
        stop_price: float,
        target_price: float,
        atr: Optional[float],
        decision_report: "DecisionReport | None" = None,
        shares: int | None = None,
    ) -> None:
        shares = shares if shares is not None else self._shares
        
        # 模擬放空白價（賣得更便宜）
        slippage_bps = self._resolve_slippage_bps(symbol, price=price, shares=partial_shares)
        execution_price = round(price * (1 - slippage_bps / 10000), 2)
        
        position = PaperPosition(
            symbol=symbol,
            side="short",
            entry_price=execution_price,
            shares=shares,
            entry_ts=ts_ms,
            entry_change_pct=change_pct,
            stop_price=stop_price,
            target_price=target_price,
            entry_atr=atr,
            peak_price=execution_price,
            trail_stop_price=stop_price,
        )
        self._book.positions[symbol] = position
        await self._persist_position_open(symbol)

        record = TradeRecord(
            symbol=symbol,
            action="SHORT",
            price=execution_price,
            shares=shares,
            reason="SIGNAL",
            pnl=0.0,
            ts=ts_ms,
            stop_price=stop_price,
            target_price=target_price,
            decision_report=decision_report,
        )
        self._book.trade_history.append(record)

        self._risk.on_buy(symbol, execution_price, shares)
        await self._persist_trade(record)

        atr_label = f"{atr:.3f}" if atr is not None else "N/A"
        cost = price * shares
        text = "\n".join(
            [
                "[模擬交易] 放空成交",
                f"股票：{symbol}",
                f"觸發跌幅：{change_pct:+.2f}%",
                f"成交價：{price:,.2f} (滑價後: {execution_price:,.2f})",
                f"張數：{shares // SHARES_PER_LOT} 張（{shares:,} 股）",
                f"名義金額：{cost:,.0f} 元",
                f"停損回補：{stop_price:,.2f}",
                f"目標停利：{target_price:,.2f}",
                f"ATR：{atr_label}",
                f"時間：{_ms_to_time(ts_ms)}",
            ]
        )
        logger.info(
            "[PAPER SHORT] %s @ %.2f change=%.2f%% stop=%.2f target=%.2f",
            symbol, price, change_pct, stop_price, target_price,
        )

    async def _check_short_exit(self, symbol: str, price: float, ts_ms: int) -> None:
        """檢查空方出場條件（停損 / 停利）。不使用追蹤停利。"""
        if self._limit_locked.get(symbol) == "up":
            return
            
        position = self._book.positions[symbol]
        reason: Optional[str] = None
        if price >= position.stop_price:
            reason = "STOP_LOSS"
        elif price <= position.target_price:
            reason = "TAKE_PROFIT"

        if reason:
            pct_from_entry = (position.entry_price - price) / position.entry_price * 100
            await self._execution.execute_cover(
                symbol=symbol,
                price=price,
                reason=reason,
                pct_from_entry=pct_from_entry,
                ts_ms=ts_ms,
            )

    async def _paper_cover(
        self,
        symbol: str,
        price: float,
        reason: str,
        pct_from_entry: float,
        ts_ms: int,
    ) -> None:
        """回補空方部位，計算損益並記錄 COVER 成交。"""
        position = self._book.positions.pop(symbol)
        self._position_sectors.pop(symbol, None)
        await self._persist_position_close(symbol)
        
        # 模擬回補滑價（買得更貴）
        execution_price = round(price * (1 + SLIPPAGE_BPS / 10000), 2)
        
        gross_pnl = (position.entry_price - execution_price) * position.shares
        # 參數對調：calc_net_pnl(cover_price, entry_price, shares)
        # → (entry_price - cover_price) * shares - costs ✓
        net_pnl = self._risk.calc_net_pnl(execution_price, position.entry_price, position.shares)

        final_reason = {
            "STOP_LOSS": "stop_loss",
            "TAKE_PROFIT": "take_profit",
            "EOD": "end_of_day_exit",
        }.get(reason, reason.lower())
        risk_flag = {
            "STOP_LOSS": "stop_hit",
            "TAKE_PROFIT": "target_hit",
            "EOD": "eod_flatten",
        }.get(reason, "exit")

        decision_report = self._append_decision_report(
            DecisionReport(
                report_id=f"{symbol}-cover-{ts_ms}",
                symbol=symbol,
                ts=ts_ms,
                decision_type="cover",
                trigger_type="risk" if reason in {"STOP_LOSS", "EOD"} else "technical",
                confidence=max(20, min(92, 60 + int(abs(pct_from_entry) * 4))),
                final_reason=final_reason,
                summary={
                    "STOP_LOSS": "空方部位反向觸及停損，立即回補控制損失。",
                    "TAKE_PROFIT": "空方目標價到達，回補鎖定利潤。",
                    "EOD": "收盤前強制回補，避免隔夜風險。",
                }.get(reason, "空方部位已回補。"),
                supporting_factors=[
                    DecisionFactor("support", "回補條件", reason),
                    DecisionFactor("support", "損益變化", f"相對進場 {pct_from_entry:+.2f}%"),
                ],
                opposing_factors=[
                    DecisionFactor("oppose", "放棄後續空間", "提前回補可能錯過後續跌段"),
                ],
                risk_flags=[risk_flag],
                source_events=[
                    {"source": "position_management", "entryPrice": round(position.entry_price, 2), "currentPrice": round(price, 2)}
                ],
                order_result={
                    "status": "executed",
                    "action": "COVER",
                    "price": round(execution_price, 2),
                    "shares": position.shares,
                    "pnl": round(net_pnl, 2),
                },
            )
        )

        record = TradeRecord(
            symbol=symbol,
            action="COVER",
            price=execution_price,
            shares=position.shares,
            reason=reason,
            pnl=net_pnl,
            ts=ts_ms,
            gross_pnl=gross_pnl,
            decision_report=decision_report,
        )
        self._book.trade_history.append(record)

        self._risk.on_sell(symbol, net_pnl)
        await self._persist_trade(record)

        icon = "停損" if reason == "STOP_LOSS" else "停利" if reason == "TAKE_PROFIT" else "收盤"
        tx_cost = gross_pnl - net_pnl
        daily_pnl = self._risk.daily_pnl
        text = "\n".join(
            [
                f"[模擬交易] 空方{icon}回補",
                f"股票：{symbol}",
                f"原因：{_cover_reason_label(reason)}",
                f"進場 / 回補：{position.entry_price:,.2f} / {price:,.2f} (滑價後: {execution_price:,.2f})",
                f"毛損益：{gross_pnl:+,.0f} 元",
                f"交易成本：{tx_cost:,.0f} 元",
                f"淨損益：{net_pnl:+,.0f} 元",
                f"當日累計：{daily_pnl:+,.0f} 元",
                f"時間：{_ms_to_time(ts_ms)}",
            ]
        )
        logger.info(
            "[PAPER COVER] %s @ %.2f reason=%s net_pnl=%.0f",
            symbol, price, reason, net_pnl,
        )
        if self._risk.just_entered_cooldown:
            await self._send(
                f"[風控警示] 連續虧損 {self._risk.consecutive_losses + 1} 筆，"
                "系統進入 1 小時冷卻期，暫停所有新開倉。"
            )

    async def _close_all_eod(self, ts_ms: int) -> None:
        """Force-close all positions after 13:25."""
        symbols = list(self._book.positions.keys())
        if not symbols:
            return

        logger.info("AutoTrader: EOD close triggered for %d open positions", len(symbols))
        for symbol in symbols:
            position = self._book.positions[symbol]
            if position.side == "long" and self._limit_locked.get(symbol) == "down":
                await self._send(f"⚠️ [警告] {symbol} 跌停鎖死，EOD 模擬平倉可能失真！")
            elif position.side == "short" and self._limit_locked.get(symbol) == "up":
                await self._send(f"⚠️ [警告] {symbol} 漲停鎖死，EOD 模擬回補可能失真！")

            price = self._last_prices.get(symbol, position.entry_price)
            if position.side == "short":
                pct = (position.entry_price - price) / position.entry_price * 100
                await self._execution.execute_cover(
                    symbol=symbol,
                    price=price,
                    reason="EOD",
                    pct_from_entry=pct,
                    ts_ms=ts_ms,
                )
            else:
                pct = (price - position.entry_price) / position.entry_price * 100
                await self._execution.execute_sell(
                    symbol=symbol,
                    price=price,
                    reason="EOD",
                    pct_from_entry=pct,
                    ts_ms=ts_ms,
                )

        await self._send_performance_report()
        await self._check_sector_rotation(ts_ms)
        self._schedule_eod_report(ts_ms)

    async def _persist_trade(self, record: TradeRecord) -> None:
        """Persist trade records asynchronously without blocking the trading loop."""
        if self._db is None:
            return
        try:
            from models import get_session, save_paper_trade

            async with get_session() as session:
                await save_paper_trade(
                    session,
                    session_id=self._session_id,
                    symbol=record.symbol,
                    action=record.action,
                    price=record.price,
                    shares=record.shares,
                    reason=record.reason,
                    pnl=record.pnl,
                    gross_pnl=record.gross_pnl,
                    trade_ts_ms=record.ts,
                    stop_price=record.stop_price,
                    target_price=record.target_price,
                )
        except Exception as exc:
            self._handle_persistence_failure(
                exc,
                "Trade persistence failed for %s %s: %s",
                record.action,
                record.symbol,
                exc,
            )

    async def restore_positions(self, trade_date: str) -> int:
        """從資料庫還原當日持倉狀態。"""
        if self._db is None:
            return self._restore_positions_from_local_snapshot(trade_date)
        try:
            from models import get_session, load_today_positions
            
            async with get_session() as session:
                rows = await load_today_positions(session, trade_date=trade_date)
                
                for row in rows:
                    if row["side"] != "long":
                        continue
                    position = PaperPosition(
                        symbol=row["symbol"],
                        side=row["side"],
                        entry_price=row["entry_price"],
                        shares=row["shares"],
                        entry_ts=row["entry_ts"],
                        entry_change_pct=row.get("entry_change_pct", 0.0),
                        stop_price=row["stop_price"],
                        target_price=row["target_price"],
                        entry_atr=row.get("entry_atr"),
                        peak_price=row.get("peak_price", row["entry_price"]),
                        trail_stop_price=row.get("trail_stop_price", row["stop_price"]),
                    )
                    self._book.positions[row["symbol"]] = position
                    
                logger.info("AutoTrader restored %d positions for date %s", len(rows), trade_date)
                return len(rows)
        except Exception as exc:
            self._handle_persistence_failure(exc, "Failed to restore positions: %s", exc)
            return self._restore_positions_from_local_snapshot(trade_date)

    async def _persist_position_open(self, symbol: str) -> None:
        """Persist a new or modified open position."""
        if self._db is None:
            self._write_local_positions_snapshot()
            return
        try:
            from models import get_session, upsert_paper_position
            position = self._book.positions.get(symbol)
            if not position:
                return
            async with get_session() as session:
                await upsert_paper_position(
                    session,
                    trade_date=self._position_trade_date(position.entry_ts),
                    symbol=symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    shares=position.shares,
                    entry_ts=position.entry_ts,
                    entry_change_pct=position.entry_change_pct,
                    stop_price=position.stop_price,
                    target_price=position.target_price,
                    peak_price=position.peak_price,
                    trail_stop_price=position.trail_stop_price,
                    entry_atr=position.entry_atr,
                )
        except Exception as exc:
            self._handle_persistence_failure(
                exc,
                "Failed to persist open position %s: %s",
                symbol,
                exc,
            )
        finally:
            self._write_local_positions_snapshot()

    async def _persist_position_close(self, symbol: str) -> None:
        """Remove a closed position from persistence."""
        if self._db is None:
            self._write_local_positions_snapshot()
            return
        try:
            from models import get_session, delete_paper_position
            async with get_session() as session:
                await delete_paper_position(
                    session,
                    trade_date=self._position_trade_date(),
                    symbol=symbol,
                )
        except Exception as exc:
            self._handle_persistence_failure(
                exc,
                "Failed to persist closed position %s: %s",
                symbol,
                exc,
            )
        finally:
            self._write_local_positions_snapshot()

    def _position_trade_date(self, ts_ms: int | None = None) -> str:
        if ts_ms is not None:
            return _ts_to_datetime(ts_ms).strftime("%Y%m%d")
        if self._current_date:
            return self._current_date.replace("-", "")
        return datetime.datetime.now(tz=_TZ_TW).strftime("%Y%m%d")

    def _handle_persistence_failure(self, exc: Exception, message: str, *args: object) -> None:
        if self._is_persistence_connection_error(exc):
            if self._db is not None:
                logger.warning(message, *args)
                logger.warning("Persistence disabled for current session: %s", exc)
            self._db = None
            self._persistence_disabled_reason = str(exc)
            return
        logger.warning(message, *args)

    def _write_local_positions_snapshot(self) -> None:
        path = self._local_positions_path
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        snapshot_trade_date = self._position_trade_date()
        if self._book.positions:
            first_position = next(iter(self._book.positions.values()))
            snapshot_trade_date = self._position_trade_date(first_position.entry_ts)
        payload = {
            "trade_date": snapshot_trade_date,
            "positions": {
                symbol: {
                    "symbol": position.symbol,
                    "side": position.side,
                    "entry_price": position.entry_price,
                    "shares": position.shares,
                    "entry_ts": position.entry_ts,
                    "entry_change_pct": position.entry_change_pct,
                    "stop_price": position.stop_price,
                    "target_price": position.target_price,
                    "peak_price": position.peak_price,
                    "trail_stop_price": position.trail_stop_price,
                    "entry_atr": position.entry_atr,
                }
                for symbol, position in self._book.positions.items()
            },
        }
        with open(path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)

    def _restore_positions_from_local_snapshot(self, trade_date: str) -> int:
        path = self._local_positions_path
        if not os.path.exists(path):
            return 0
        try:
            with open(path, "r", encoding="utf-8") as file:
                payload = json.load(file)
            if str(payload.get("trade_date", "")).strip() != trade_date:
                return 0
            rows = payload.get("positions", {})
            restored = 0
            for row in rows.values():
                if str(row["side"]) != "long":
                    continue
                position = PaperPosition(
                    symbol=str(row["symbol"]),
                    side=str(row["side"]),
                    entry_price=float(row["entry_price"]),
                    shares=int(row["shares"]),
                    entry_ts=int(row["entry_ts"]),
                    entry_change_pct=float(row.get("entry_change_pct", 0.0)),
                    stop_price=float(row["stop_price"]),
                    target_price=float(row["target_price"]),
                    entry_atr=(float(row["entry_atr"]) if row.get("entry_atr") is not None else None),
                    peak_price=float(row.get("peak_price", row["entry_price"])),
                    trail_stop_price=float(row.get("trail_stop_price", row["stop_price"])),
                    partial_exit_done=bool(row.get("partial_exit_done", False)),
                )
                self._book.positions[position.symbol] = position
                restored += 1
            if restored:
                logger.info("AutoTrader restored %d positions from local snapshot %s", restored, path)
            return restored
        except Exception as exc:
            logger.warning("Failed to restore local position snapshot %s: %s", path, exc)
            return 0

    @staticmethod
    def _is_persistence_connection_error(exc: Exception) -> bool:
        if isinstance(exc, OSError):
            return True
        text = str(exc).lower()
        return any(
            token in text
            for token in (
                "connection refused",
                "connect call failed",
                "could not connect",
                "refused",
                "遠端電腦拒絕網路連線",
            )
        )

    def get_portfolio_snapshot(self) -> dict[str, Any]:
        snapshot = self._book.build_snapshot(self._last_prices, session_id=self._session_id)
        recent_decisions = [report.to_dict() for report in self._decision_history[-40:]]

        sells = [trade for trade in self._book.trade_history if trade.action == "SELL"]
        realized_pnl = sum(trade.pnl for trade in sells)
        unrealized_pnl = self._book.unrealized_pnl(self._last_prices)
        wins = sum(1 for trade in sells if trade.pnl > 0)
        win_rate = wins / len(sells) * 100 if sells else 0.0

        snapshot["recentDecisions"] = recent_decisions
        snapshot["realizedPnl"] = round(realized_pnl, 0)
        snapshot["totalPnl"] = round(realized_pnl + unrealized_pnl, 0)
        snapshot["tradeCount"] = len(sells)
        snapshot["winRate"] = round(win_rate, 1)
        snapshot["marketChangePct"] = round(self._market_change_pct, 2)
        snapshot["riskStatus"] = self._risk.status_dict()
        snapshot["retailFlow"] = {
            "watchStates": dict(self._swing_runtime.watch_states),
            "lastNonEntryReasons": dict(self._retail_flow_non_entry_reasons),
            "candidates": self.get_retail_flow_candidates(),
            "watchlist": self.get_retail_flow_watchlist(),
        }
        return snapshot

    async def execute_manual_trade(
        self,
        *,
        symbol: str,
        action: str,
        shares: int,
        ts_ms: int | None = None,
    ) -> dict[str, Any]:
        symbol = str(symbol).strip()
        action = str(action).upper().strip()
        shares = int(shares)
        ts_ms = int(ts_ms or time.time() * 1000)

        if not symbol:
            raise ValueError("symbol_required")
        if action not in {"BUY", "SELL"}:
            raise ValueError("unsupported_action")
        if shares <= 0:
            raise ValueError("invalid_shares")

        price = (
            self._last_prices.get(symbol)
            or self._open_prices.get(symbol)
            or self._prev_close_cache.get(symbol)
        )
        if price is None:
            raise ValueError("price_unavailable")
        price = float(price)

        position = self._book.positions.get(symbol)
        if action == "BUY":
            if position is not None:
                raise ValueError("position_exists")

            allowed, _reason = self._risk.can_buy(symbol, price, shares, len(self._book.positions))
            if not allowed:
                raise ValueError("risk_rejected")

            previous_close = self._prev_close_cache.get(symbol) or self._open_prices.get(symbol) or price
            change_pct = ((price - previous_close) / previous_close * 100) if previous_close else 0.0
            atr = self._calc_atr(symbol)
            stop_price = self._risk.calc_stop_price(price, atr)
            target_price = self._risk.calc_target_price(price, stop_price)
            sentiment_score = self._sentiment.get_score(symbol) if self._sentiment is not None else None
            source_events = [
                {"source": "manual_trade", "symbol": symbol, "action": action},
                {"source": "quote_snapshot", "price": round(price, 2), "changePct": round(change_pct, 2)},
            ]
            bundle = self._build_decision_bundle(
                symbol=symbol,
                ts_ms=ts_ms,
                decision_type="buy",
                trigger_type="manual",
                price=price,
                change_pct=change_pct,
                volume_confirmed=True,
                sentiment_score=sentiment_score,
                risk_allowed=True,
                risk_reason="manual_order",
                risk_flags=[],
                source_events=source_events,
                supporting_factors=[
                    DecisionFactor("support", "手動下單", "使用者從個股頁面發送模擬買進"),
                ],
                opposing_factors=[],
            )
            decision_report = self._append_decision_report(
                DecisionReport(
                    report_id=f"{symbol}-manual-buy-{ts_ms}",
                    symbol=symbol,
                    ts=ts_ms,
                    decision_type="buy",
                    trigger_type="manual",
                    confidence=60,
                    final_reason="manual_buy",
                    summary="使用者從個股頁面手動送出模擬買進。",
                    supporting_factors=[DecisionFactor("support", "手動下單", "個股頁面買進按鈕")],
                    opposing_factors=[],
                    risk_flags=[],
                    source_events=source_events,
                    order_result={
                        "status": "executed",
                        "action": "BUY",
                        "price": round(price, 2),
                        "shares": shares,
                    },
                    bull_case=bundle.bull_case,
                    bear_case=bundle.bear_case,
                    risk_case=bundle.risk_case,
                    bull_argument=bundle.bull_argument,
                    bear_argument=bundle.bear_argument,
                    referee_verdict=bundle.referee_verdict,
                    debate_winner=bundle.debate_winner,
                )
            )
            await self._execution.execute_buy(
                symbol=symbol,
                price=price,
                change_pct=change_pct,
                ts_ms=ts_ms,
                stop_price=stop_price,
                target_price=target_price,
                atr=atr,
                decision_report=decision_report,
                shares=shares,
            )
            return self.get_portfolio_snapshot()

        if position is None or position.side != "long":
            raise ValueError("long_position_required")
        if shares != position.shares:
            raise ValueError("share_mismatch")

        pct_from_entry = ((price - position.entry_price) / position.entry_price * 100) if position.entry_price else 0.0
        await self._execution.execute_sell(
            symbol=symbol,
            price=price,
            reason="MANUAL",
            pct_from_entry=pct_from_entry,
            ts_ms=ts_ms,
        )
        return self.get_portfolio_snapshot()

    def _schedule_eod_report(self, ts_ms: int) -> None:
        if self._daily_reporter is None:
            return
        report_date = _ts_to_date(ts_ms)
        if self._last_eod_report_date == report_date:
            return
        if self._eod_report_task is not None and not self._eod_report_task.done():
            self._eod_report_task.cancel()
        self._eod_report_task = asyncio.create_task(self._run_eod_report_after_delay(ts_ms))

    async def _run_eod_report_after_delay(self, ts_ms: int) -> None:
        report_date = _ts_to_date(ts_ms)
        try:
            await asyncio.sleep(self._eod_report_delay_seconds)
            payload = self._build_daily_report_payload(ts_ms)
            has_activity = (
                int(payload.get("tradeCount", 0) or 0) > 0
                or len(payload.get("newPositions") or []) > 0
            )
            if not has_activity:
                return
            result = self._daily_reporter.build_and_send(day_payload=payload)
            if asyncio.iscoroutine(result):
                await result
            self._last_eod_report_date = report_date
            logger.info(
                "Daily EOD report sent for %s trades=%d new_positions=%d",
                report_date,
                int(payload.get("tradeCount", 0) or 0),
                len(payload.get("newPositions") or []),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Daily EOD report failed for %s trades=%d new_positions=%d: %s",
                report_date,
                int(payload.get("tradeCount", 0) or 0) if "payload" in locals() else 0,
                len(payload.get("newPositions") or []) if "payload" in locals() else 0,
                exc,
            )

    def _build_daily_report_payload(self, ts_ms: int) -> dict[str, Any]:
        return build_daily_report_payload(
            ts_ms,
            self._book.trade_history,
            self._book.positions,
            self._last_prices,
            self._risk,
        )

    async def _evaluate_buy(
        self,
        symbol: str,
        price: float,
        change_pct: float,
        ts_ms: int,
        payload: dict[str, Any],
    ) -> None:
        sentiment_score = self._sentiment.get_score(symbol) if self._sentiment is not None else None
        supporting_factors = [
            DecisionFactor("support", "價格動能", f"盤中漲幅 {change_pct:+.2f}%"),
        ]

        if self._disposition and self._disposition.is_blocked(symbol):
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="disposition_blocked",
                summary="設定為處置股/全額交割，阻擋進場。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "處置/緩搓", "限制名單")],
                risk_flags=["disposition_blocked"],
                trigger_type="risk",
                confidence=10,
            )
            return

        if self._market_change_pct <= MARKET_HALT_PCT:
            logger.info("Market filter blocked %s: taiex=%.2f%% threshold=%.2f%%", symbol, self._market_change_pct, MARKET_HALT_PCT)
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="market_halt",
                summary=f"大盤急跌保護（{self._market_change_pct:+.2f}%），暫停新進場。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "大盤條件", f"加權指數 {self._market_change_pct:+.2f}% 超過急跌門檻 {MARKET_HALT_PCT:.1f}%")],
                risk_flags=["market_halt"],
                trigger_type="risk",
                confidence=18,
            )
            return

        if self._risk.is_weekly_halted:
            logger.info("%s weekly risk halt active: rolling_5day_pnl=%.0f", symbol, self._risk.rolling_5day_pnl)
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="weekly_risk_halt",
                summary="近五日風險超限，新的事件單暫不啟動。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "週風控", f"近五日損益 {self._risk.rolling_5day_pnl:,.0f} 已觸發停用")],
                risk_flags=["weekly_halt"],
                trigger_type="risk",
                confidence=12,
            )
            return

        if change_pct >= NEAR_LIMIT_UP_PCT:
            logger.debug("%s skipped near limit-up: %.2f%%", symbol, change_pct)
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="near_limit_up",
                summary="漲幅已逼近漲停，風險報酬比不足，不追價。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "漲停風險", f"漲幅 {change_pct:+.2f}% 已接近漲停")],
                risk_flags=["limit_up_chase"],
                trigger_type="technical",
                confidence=24,
            )
            return

        if self._is_near_day_high(symbol, price, payload):
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="near_day_high",
                summary="價格已接近日內高點，先避免高位追價。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "追價風險", "現價已處於日內區間高位")],
                risk_flags=["near_day_high"],
                trigger_type="technical",
                confidence=30,
            )
            return

        volume_confirmed = self._is_volume_confirmed(symbol)
        if not volume_confirmed:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="volume_not_confirmed",
                summary="量能尚未跟上價格推進，先不執行搶快單。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "量能不足", "目前成交量未達近五根平均量的放大門檻")],
                risk_flags=["volume_unconfirmed"],
                trigger_type="technical",
                confidence=34,
            )
            return

        if self._sentiment is not None and self._sentiment.is_buy_blocked(symbol):
            score = self._sentiment.get_score(symbol) or 0.0
            logger.info("%s buy blocked by sentiment filter: score=%.3f", symbol, score)
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="sentiment_blocked",
                summary="輿情分數偏弱，先保留事件觀察，不直接進場。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "輿情分數", f"情緒分數 {score:.3f} 低於買進門檻")],
                risk_flags=["sentiment_block"],
                trigger_type="mixed",
                confidence=self._build_confidence(
                    change_pct=change_pct,
                    volume_confirmed=volume_confirmed,
                    sentiment_score=score,
                    risk_penalty=18,
                ),
            )
            return

        # RSI 超買過濾：RSI > 75 不追高（日線優先，無日線資料則用分鐘線）
        rsi = self._daily_rsi(symbol) or self._market.calculate_rsi(symbol)
        if rsi is not None and rsi > RSI_OVERBOUGHT:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="rsi_overbought",
                summary=f"RSI {rsi:.1f} 超過 {RSI_OVERBOUGHT} 超買門檻，避免追高。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "RSI 超買", f"RSI={rsi:.1f} 動能過熱")],
                risk_flags=["rsi_overbought"],
                trigger_type="technical",
                confidence=38,
            )
            return

        # 同類股集中度限制：同一類股最多 MAX_SECTOR_POSITIONS 個持倉
        sector = self._symbol_sectors.get(symbol, "")
        if not sector:
            logger.debug("sector_check skipped: %s has no registered sector", symbol)
        if sector:
            sector_count = sum(1 for s in self._position_sectors.values() if s == sector)
            if sector_count >= MAX_SECTOR_POSITIONS:
                self._record_skip_decision(
                    symbol=symbol,
                    ts_ms=ts_ms,
                    final_reason="sector_concentration",
                    summary=f"類股「{sector}」已有 {sector_count} 個持倉，達上限 {MAX_SECTOR_POSITIONS}，略過。",
                    price=price,
                    change_pct=change_pct,
                    payload=payload,
                    supporting_factors=supporting_factors,
                    opposing_factors=[DecisionFactor("oppose", "類股集中度", f"{sector} 已持 {sector_count} 倉")],
                    risk_flags=["sector_concentration"],
                    trigger_type="risk",
                    confidence=30,
                )
                return

        # 類股資金過濾：若該類股今日投信為淨賣超，視為冷門資金撤退，不進場
        if self._is_sector_cold(symbol):
            sector_name = self._symbol_sectors.get(symbol, "")
            snap = self._sector_flows_today.get(sector_name)
            trust_val = snap.trust_net_buy if snap else 0
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="cold_sector",
                summary=f"類股「{sector_name}」今日投信淨賣超 {trust_val:+,} 張，資金撤退中，略過。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "類股冷門", f"{sector_name} 投信淨賣超 {trust_val:+,} 張")],
                risk_flags=["cold_sector"],
                trigger_type="risk",
                confidence=28,
            )
            return

        # 依信心度動態決定倉位：< 40 不進場，40-69 → 1 張，≥ 70 → 2 張
        confidence = self._build_confidence(
            change_pct=change_pct,
            volume_confirmed=volume_confirmed,
            sentiment_score=sentiment_score,
        )

        if confidence < 40:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="low_confidence",
                summary=f"綜合信心度 {confidence} 未達進場門檻（40），略過。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "信心不足", f"綜合評分 {confidence} < 40")],
                risk_flags=["low_confidence"],
                trigger_type="mixed",
                confidence=confidence,
            )
            return

        atr = self._calc_atr(symbol)
        stop_price_est = self._risk.calc_stop_price(price, atr)
        shares = self._risk.calc_position_shares(price, stop_price_est)

        allowed, reason = self._risk.can_buy(symbol, price, shares, len(self._book.positions))
        if not allowed:
            logger.info("%s buy rejected by risk manager: %s", symbol, reason)
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="risk_rejected",
                summary="風控沒有放行新的事件單，暫不建立模擬部位。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "風控限制", reason)],
                risk_flags=["risk_rejected"],
                trigger_type="risk",
                confidence=self._build_confidence(
                    change_pct=change_pct,
                    volume_confirmed=volume_confirmed,
                    sentiment_score=sentiment_score,
                    risk_penalty=20,
                ),
            )
            return

        stop_price = stop_price_est
        target_price = self._risk.calc_target_price(price, stop_price)

        room_to_target_pct = (target_price - price) / price * 100
        if room_to_target_pct < self._risk.min_net_profit_pct:
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="insufficient_profit_room",
                summary=f"目標空間 {room_to_target_pct:.2f}% 低於成本門檻 {self._risk.min_net_profit_pct:.2f}%，略過。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "成本門檻", f"目標空間 {room_to_target_pct:.2f}% 不足以覆蓋來回成本與安全邊際")],
                risk_flags=["insufficient_profit_room"],
                trigger_type="risk",
                confidence=25,
            )
            return

        trigger_type = "mixed" if sentiment_score is not None else "technical"
        risk_flags = ["tight_stop" if stop_price >= price * 0.97 else "wide_stop"]
        buy_supporting_factors = [
            *supporting_factors,
            DecisionFactor("support", "量能確認", "目前成交量已達放量條件"),
            DecisionFactor("support", "風控放行", "部位與日內風險限制允許進場"),
            *(
                [DecisionFactor("support", "輿情偏多", f"情緒分數 {sentiment_score:.3f} 支持做多")]
                if sentiment_score is not None and sentiment_score > 0
                else []
            ),
        ]
        buy_opposing_factors = [
            *(
                [DecisionFactor("oppose", "情緒偏弱", f"情緒分數 {sentiment_score:.3f} 代表市場仍有雜訊")]
                if sentiment_score is not None and sentiment_score <= 0
                else []
            ),
        ]
        source_events = self._build_market_source_events(symbol, price=price, change_pct=change_pct, payload=payload)
        bundle = self._build_decision_bundle(
            symbol=symbol,
            ts_ms=ts_ms,
            decision_type="buy",
            trigger_type=trigger_type,
            price=price,
            change_pct=change_pct,
            volume_confirmed=volume_confirmed,
            sentiment_score=sentiment_score,
            risk_allowed=True,
            risk_reason="風控放行",
            risk_flags=risk_flags,
            source_events=source_events,
            supporting_factors=buy_supporting_factors,
            opposing_factors=buy_opposing_factors,
        )
        decision_report = self._append_decision_report(
            DecisionReport(
                report_id=f"{symbol}-buy-{ts_ms}",
                symbol=symbol,
                ts=ts_ms,
                decision_type="buy",
                trigger_type=trigger_type,
                confidence=confidence,
                final_reason="fast_entry_confirmed",
                summary="新聞與技術面同向，先以小部位搶快進場。",
                supporting_factors=buy_supporting_factors,
                opposing_factors=buy_opposing_factors,
                risk_flags=risk_flags,
                source_events=source_events,
                order_result={
                    "status": "executed",
                    "action": "BUY",
                    "price": round(price, 2),
                    "shares": shares,
                },
                bull_case=bundle.bull_case,
                bear_case=bundle.bear_case,
                risk_case=bundle.risk_case,
                bull_argument=bundle.bull_argument,
                bear_argument=bundle.bear_argument,
                referee_verdict=bundle.referee_verdict,
                debate_winner=bundle.debate_winner,
            )
        )
        await self._execution.execute_buy(
            symbol=symbol,
            price=price,
            change_pct=change_pct,
            ts_ms=ts_ms,
            stop_price=stop_price,
            target_price=target_price,
            atr=atr,
            decision_report=decision_report,
            shares=shares,
        )

    async def _paper_partial_sell(
        self,
        symbol: str,
        price: float,
        ts_ms: int,
        partial_shares: int,
    ) -> None:
        """出場 50% 部位：鎖定 1:1 利潤，停損移至進場成本價，剩餘繼續追蹤。"""
        position = self._book.positions[symbol]
        slippage_bps = self._resolve_slippage_bps(symbol, price=price, shares=position.shares)
        execution_price = round(price * (1 - slippage_bps / 10000), 2)
        gross_pnl = (execution_price - position.entry_price) * partial_shares
        net_pnl = self._risk.calc_net_pnl(position.entry_price, execution_price, partial_shares)

        # 更新持倉：減少張數、停損移至成本、標記已做過分批
        position.shares -= partial_shares
        position.stop_price = position.entry_price
        position.trail_stop_price = max(position.trail_stop_price, position.entry_price)
        position.partial_exit_done = True
        await self._persist_position_open(symbol)

        record = TradeRecord(
            symbol=symbol,
            action="SELL",
            price=execution_price,
            shares=partial_shares,
            reason="PARTIAL_PROFIT",
            pnl=net_pnl,
            ts=ts_ms,
            gross_pnl=gross_pnl,
        )
        self._book.trade_history.append(record)
        self._risk.on_sell(symbol, net_pnl)
        await self._persist_trade(record)

        tx_cost = gross_pnl - net_pnl
        text = "\n".join(
            [
                "[模擬交易] 分批停利（50%）",
                f"標的：{symbol}",
                f"出場價：{price:,.2f} (滑價後: {execution_price:,.2f})",
                f"張數：{partial_shares // SHARES_PER_LOT} 張（{partial_shares:,} 股）",
                f"毛損益：{gross_pnl:+,.0f} 元",
                f"交易成本：{tx_cost:,.0f} 元",
                f"淨損益：{net_pnl:+,.0f} 元",
                f"剩餘持倉：{position.shares:,} 股，停損已移至成本 {position.entry_price:,.2f}",
                f"時間：{_ms_to_time(ts_ms)}",
            ]
        )
        logger.info(
            "[PAPER PARTIAL SELL] %s @ %.2f partial=%d remaining=%d net_pnl=%.0f",
            symbol, price, partial_shares, position.shares, net_pnl,
        )

    async def _paper_sell(
        self,
        symbol: str,
        price: float,
        reason: str,
        pct_from_entry: float,
        ts_ms: int,
    ) -> None:
        position = self._book.positions.pop(symbol)
        self._position_sectors.pop(symbol, None)
        await self._persist_position_close(symbol)
        
        # 模擬賣出滑價（賣得更便宜）
        execution_price = round(price * (1 - SLIPPAGE_BPS / 10000), 2)
        
        gross_pnl = (execution_price - position.entry_price) * position.shares
        net_pnl = self._risk.calc_net_pnl(position.entry_price, execution_price, position.shares)
        final_reason = {
            "STOP_LOSS": "stop_loss",
            "TRAIL_STOP": "trailing_stop",
            "TAKE_PROFIT": "take_profit",
            "EOD": "end_of_day_exit",
        }.get(reason, reason.lower())
        risk_flag = {
            "STOP_LOSS": "stop_hit",
            "TRAIL_STOP": "trail_stop_hit",
            "TAKE_PROFIT": "target_hit",
            "EOD": "eod_flatten",
        }.get(reason, "exit")
        trigger_type = "risk" if reason in {"STOP_LOSS", "TRAIL_STOP", "EOD"} else "technical"
        sell_supporting_factors = [
            DecisionFactor("support", "出場條件", reason),
            DecisionFactor("support", "報酬變化", f"相對進場 {pct_from_entry:+.2f}%"),
        ]
        sell_opposing_factors = [
            DecisionFactor("oppose", "放棄後續延伸", "提前出場可能錯過後續趨勢延續"),
        ]
        source_events = [
            {"source": "position_management", "entryPrice": round(position.entry_price, 2), "currentPrice": round(price, 2)}
        ]
        bundle = self._build_decision_bundle(
            symbol=symbol,
            ts_ms=ts_ms,
            decision_type="sell",
            trigger_type=trigger_type,
            price=price,
            change_pct=pct_from_entry,
            volume_confirmed=True,
            sentiment_score=self._sentiment.get_score(symbol) if self._sentiment is not None else None,
            risk_allowed=True,
            risk_reason=reason,
            risk_flags=[risk_flag],
            source_events=source_events,
            supporting_factors=sell_supporting_factors,
            opposing_factors=sell_opposing_factors,
            entry_price=position.entry_price,
            current_price=price,
        )
        decision_report = self._append_decision_report(
            DecisionReport(
                report_id=f"{symbol}-sell-{ts_ms}",
                symbol=symbol,
                ts=ts_ms,
                decision_type="sell",
                trigger_type=trigger_type,
                confidence=max(20, min(92, 60 + int(abs(pct_from_entry) * 4))),
                final_reason=final_reason,
                summary={
                    "STOP_LOSS": "價格跌破保護價位，立即退出以控制單筆損失。",
                    "TRAIL_STOP": "價格自高檔回落至追蹤停損，先保留已獲利部位。",
                    "TAKE_PROFIT": "目標價到達，依計畫先落袋部分事件利潤。",
                    "EOD": "收盤前平倉，避免隔夜事件風險。",
                }.get(reason, "模擬部位已完成出場。"),
                supporting_factors=sell_supporting_factors,
                opposing_factors=sell_opposing_factors,
                risk_flags=[risk_flag],
                source_events=source_events,
                order_result={
                    "status": "executed",
                    "action": "SELL",
                    "price": round(execution_price, 2),
                    "shares": position.shares,
                    "pnl": round(net_pnl, 2),
                },
                bull_case=bundle.bull_case,
                bear_case=bundle.bear_case,
                risk_case=bundle.risk_case,
                bull_argument=bundle.bull_argument,
                bear_argument=bundle.bear_argument,
                referee_verdict=bundle.referee_verdict,
                debate_winner=bundle.debate_winner,
            )
        )

        record = TradeRecord(
            symbol=symbol,
            action="SELL",
            price=execution_price,
            shares=position.shares,
            reason=reason,
            pnl=net_pnl,
            ts=ts_ms,
            gross_pnl=gross_pnl,
            decision_report=decision_report,
        )
        self._book.trade_history.append(record)

        self._risk.on_sell(symbol, net_pnl)
        await self._persist_trade(record)

        icon = "停損" if reason in {"STOP_LOSS", "TRAIL_STOP"} else "停利" if reason == "TAKE_PROFIT" else "收盤"
        reason_labels = {
            "STOP_LOSS": "保護停損",
            "TRAIL_STOP": "追蹤停損",
            "TAKE_PROFIT": "目標停利",
            "EOD": "收盤平倉",
        }
        tx_cost = gross_pnl - net_pnl
        daily_pnl = self._risk.daily_pnl
        text = "\n".join(
            [
                f"[模擬交易] {icon}出場",
                f"標的：{symbol}",
                f"原因：{reason_labels.get(reason, reason)}",
                f"進場 / 出場：{position.entry_price:,.2f} / {price:,.2f} (滑價後: {execution_price:,.2f})",
                f"相對報酬：{pct_from_entry:+.2f}%",
                f"毛損益：{gross_pnl:+,.0f} 元",
                f"交易成本：{tx_cost:,.0f} 元",
                f"淨損益：{net_pnl:+,.0f} 元",
                f"當日累計：{daily_pnl:+,.0f} 元",
                f"時間：{_ms_to_time(ts_ms)}",
            ]
        )
        logger.info("[PAPER SELL] %s @ %.2f reason=%s net_pnl=%.0f", symbol, price, reason, net_pnl)

        if self._risk.is_halted:
            await self._send(f"[風控警示] 當日損益已達限制：{daily_pnl:+,.0f} 元，系統將暫停新單。")

    async def _send_performance_report(self) -> None:
        today = _ts_to_date(int(time.time() * 1000))
        sells = [t for t in self._book.trade_history if t.action == "SELL" and _ts_to_date(t.ts) == today]
        realized_pnl = sum(trade.pnl for trade in sells)
        wins = sum(1 for trade in sells if trade.pnl > 0)
        win_rate = wins / len(sells) * 100 if sells else 0.0
        unrealized = sum(
            (self._last_prices.get(symbol, position.entry_price) - position.entry_price) * position.shares
            for symbol, position in self._book.positions.items()
        )
        total = realized_pnl + unrealized
        risk = self._risk.status_dict()

        def sign(value: float) -> str:
            return "+" if value >= 0 else ""

        if risk["isWeeklyHalted"]:
            halt_msg = "近五日風控已觸發，系統暫停新倉。"
        elif risk["isHalted"]:
            halt_msg = "當日風控已觸發，系統暫停新倉。"
        else:
            halt_msg = "風控狀態正常。"

        if self._market_change_pct <= MARKET_HALT_PCT:
            market_msg = f"大盤過濾啟動：{self._market_change_pct:+.2f}%"
        else:
            market_msg = f"大盤漲跌：{self._market_change_pct:+.2f}%"

        text = "\n".join(
            [
                "[模擬交易] 績效摘要",
                f"持倉：{len(self._book.positions)} / {risk['maxPositions']} 檔",
                f"已完成交易：{len(sells)} 筆，勝率 {wins}/{len(sells) or 1} = {win_rate:.1f}%",
                f"已實現損益：{sign(realized_pnl)}{realized_pnl:,.0f} 元",
                f"未實現損益：{sign(unrealized)}{unrealized:,.0f} 元",
                f"總損益：{sign(total)}{total:,.0f} 元",
                f"當日損益 / 上限：{sign(risk['dailyPnl'])}{risk['dailyPnl']:,.0f} / {risk['dailyLossLimit']:,.0f}",
                f"近五日損益 / 上限：{sign(risk['rolling5DayPnl'])}{risk['rolling5DayPnl']:,.0f} / {risk['rolling5DayLimit']:,.0f}",
                market_msg,
                halt_msg,
            ]
        )
        await self._send(text)

    async def _send(self, text: str) -> None:
        if not self._token or not self._chat_id:
            return
        try:
            session = await self._get_session()
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            await session.post(
                url,
                json={"chat_id": self._chat_id, "text": text},
                timeout=aiohttp.ClientTimeout(total=8),
            )
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


for _legacy_method_name in (
    "_evaluate_buy",
    "_check_exit",
    "_evaluate_short",
    "_paper_short",
    "_check_short_exit",
    "_paper_cover",
    "_close_all_eod",
):
    if hasattr(AutoTrader, _legacy_method_name):
        delattr(AutoTrader, _legacy_method_name)

# Time helpers

def _ts_to_datetime(ts_ms: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ts_ms / 1000, tz=_TZ_TW)


def _ts_to_date(ts_ms: int) -> str:
    return _ts_to_datetime(ts_ms).strftime("%Y-%m-%d")


def _previous_known_open_trading_date(date_str: str) -> str:
    base_date = datetime.date.fromisoformat(date_str)
    for offset in range(1, 15):
        candidate = base_date - datetime.timedelta(days=offset)
        if is_known_open_trading_date(candidate):
            return candidate.isoformat()
    return (base_date - datetime.timedelta(days=1)).isoformat()


def _is_trading_hours(ts_ms: int) -> bool:
    """Return True during the trading session window (09:00–13:30).

    In MOCK mode the calendar date check is skipped so simulation can run
    on weekends and non-trading days.
    """
    if os.getenv("SINOPAC_MOCK", "false").lower() == "true":
        return True
    dt = _ts_to_datetime(ts_ms)
    if not is_known_open_trading_date(dt.date()):
        return False
    t = dt.hour * 60 + dt.minute
    return 9 * 60 <= t <= 13 * 60 + 30


def _is_eod_close_time(ts_ms: int) -> bool:
    """Return True once the 13:25 end-of-day liquidation window starts."""
    dt = _ts_to_datetime(ts_ms)
    t = dt.hour * 60 + dt.minute
    return t >= 13 * 60 + 25


def _is_opening_breakout_window(ts_ms: int) -> bool:
    """Legacy opening-window helper retained for compatibility."""
    dt = _ts_to_datetime(ts_ms)
    t = dt.hour * 60 + dt.minute
    return 9 * 60 <= t <= 9 * 60 + 30


def _is_swing_entry_window(ts_ms: int) -> bool:
    """Return True during the regular Taiwan cash-session hours.

    For swing trading, entries should remain available throughout the normal
    session rather than being limited to the first hour.
    """
    return _is_trading_hours(ts_ms)


def _cover_reason_label(reason: str) -> str:
    return {"STOP_LOSS": "停損回補", "TAKE_PROFIT": "目標停利", "EOD": "收盤回補"}.get(reason, reason)


def _ms_to_time(ts_ms: int) -> str:
    return _ts_to_datetime(ts_ms).strftime("%H:%M:%S")


# Factory

def _apply_strategy_params(params: dict) -> None:
    """將 strategy_params.json 的值覆蓋模組級常數。"""
    import auto_trader as _self
    if "BUY_SIGNAL_PCT" in params:
        _self.BUY_SIGNAL_PCT = float(params["BUY_SIGNAL_PCT"])
    if "TRAIL_STOP_ATR_MULT" in params:
        _self.TRAIL_STOP_ATR_MULT = float(params["TRAIL_STOP_ATR_MULT"])


def trader_from_env(
    *,
    strategy_mode: str = "retail_flow_swing",
    institutional_flow_provider: Any = None,
    institutional_flow_cache: Any = None,
    retail_flow_strategy: RetailFlowSwingStrategy | None = None,
) -> AutoTrader:
    from daily_reporter import daily_reporter_from_env
    from risk_manager import risk_manager_from_env
    from sentiment_filter import SentimentFilter
    from disposition_filter import DispositionFilter
    from strategy_tuner import StrategyTuner

    db_factory = None
    try:
        from models import get_session
        db_factory = get_session
    except Exception:
        pass

    disposition = DispositionFilter()
    disposition.load()

    strategy_tuner = StrategyTuner(
        db_session_factory=db_factory,
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
    )

    params = StrategyTuner.load_params()
    _apply_strategy_params(params)

    return AutoTrader(
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        risk_manager=risk_manager_from_env(),
        sentiment_filter=SentimentFilter(),
        daily_reporter=daily_reporter_from_env(),
        db_session_factory=db_factory,
        strategy_tuner=strategy_tuner,
        disposition_filter=disposition,
        strategy_mode=strategy_mode,
        retail_flow_strategy=retail_flow_strategy,
        institutional_flow_cache=institutional_flow_cache,
    )
