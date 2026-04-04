"""
Paper-trading engine for the Taiwan stock simulation system.

The module consumes normalized tick payloads, maintains intraday bars,
evaluates buy and exit conditions, enforces risk controls, and publishes
portfolio summaries through Telegram.
"""
from __future__ import annotations

import asyncio
import collections
import datetime
import logging
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import aiohttp
from multi_analyst import (
    AnalystContext,
    DecisionComposer,
    NewsAnalyst,
    RiskAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)

logger = logging.getLogger(__name__)

# Signal thresholds
BUY_SIGNAL_PCT = 2.0
OPENING_BREAKOUT_PCT = 1.0   # Lower threshold for the 09:00–09:30 opening window
SHORT_SIGNAL_PCT = -1.5      # Minimum drop required to trigger short evaluation
SHORT_SENTIMENT_THRESHOLD = -0.25  # Sentiment must be below this to allow shorting
NEAR_LIMIT_UP_PCT = 9.5
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
_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))


@dataclass
class CandleBar:
    """Single 1-minute bar aggregated from ticks."""

    ts_min: int
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass
class PaperPosition:
    symbol: str
    side: str  # "long" | "short"
    entry_price: float
    shares: int
    entry_ts: int
    entry_change_pct: float
    stop_price: float
    target_price: float
    entry_atr: Optional[float] = None
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
    decision_report: "DecisionReport | None" = None


@dataclass
class DecisionFactor:
    kind: str
    label: str
    detail: str


@dataclass
class DecisionReport:
    report_id: str
    symbol: str
    ts: int
    decision_type: str
    trigger_type: str
    confidence: int
    final_reason: str
    summary: str
    supporting_factors: list[DecisionFactor]
    opposing_factors: list[DecisionFactor]
    risk_flags: list[str]
    source_events: list[dict[str, Any]]
    order_result: dict[str, Any]
    bull_case: str = ""
    bear_case: str = ""
    risk_case: str = ""
    bull_argument: str = ""
    bear_argument: str = ""
    referee_verdict: str = ""
    debate_winner: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "reportId": self.report_id,
            "symbol": self.symbol,
            "ts": self.ts,
            "decisionType": self.decision_type,
            "triggerType": self.trigger_type,
            "confidence": self.confidence,
            "finalReason": self.final_reason,
            "summary": self.summary,
            "supportingFactors": [
                {"kind": factor.kind, "label": factor.label, "detail": factor.detail}
                for factor in self.supporting_factors
            ],
            "opposingFactors": [
                {"kind": factor.kind, "label": factor.label, "detail": factor.detail}
                for factor in self.opposing_factors
            ],
            "riskFlags": list(self.risk_flags),
            "sourceEvents": list(self.source_events),
            "orderResult": dict(self.order_result),
            "bullCase": self.bull_case,
            "bearCase": self.bear_case,
            "riskCase": self.risk_case,
            "bullArgument": self.bull_argument,
            "bearArgument": self.bear_argument,
            "refereeVerdict": self.referee_verdict,
            "debateWinner": self.debate_winner,
        }


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

        # Runtime state
        self._open_prices: dict[str, float] = {}
        self._last_prices: dict[str, float] = {}
        self._positions: dict[str, PaperPosition] = {}
        self._trade_history: list[TradeRecord] = []
        self._decision_history: list[DecisionReport] = []
        self._last_report_ts: float = time.time()
        self._session: aiohttp.ClientSession | None = None
        self._news_analyst = NewsAnalyst()
        self._sentiment_analyst = SentimentAnalyst()
        self._technical_analyst = TechnicalAnalyst()
        self._risk_analyst = RiskAnalyst()
        self._decision_composer = DecisionComposer()

        # Intraday 1-minute bars
        self._current_bar: dict[str, CandleBar] = {}
        self._candle_history: dict[str, collections.deque] = {}
        self._volume_history: dict[str, collections.deque] = {}

        # Trading-day state
        self._current_date: str = ""
        self._eod_closed: bool = False
        self._eod_report_task: asyncio.Task[Any] | None = None
        self._last_eod_report_date: str | None = None

        # TAIEX filter state
        self._market_change_pct: float = 0.0

    async def on_tick(self, payload: dict[str, Any]) -> None:
        symbol: str = payload["symbol"]
        price: float = float(payload["price"])
        volume: int = int(payload.get("volume", 0))
        ts_ms: int = int(payload["ts"])

        # Reset daily state when the trading date changes.
        self._maybe_reset_day(ts_ms)

        # ② 更新 K 棒
        self._update_candle(symbol, price, volume, ts_ms)

        # ③ 記錄最新價
        if symbol not in self._open_prices:
            self._open_prices[symbol] = price
        self._last_prices[symbol] = price

        # ④ 計算漲跌幅
        previous_close = payload.get("previousClose") or self._open_prices[symbol]
        change_pct = (
            (price - previous_close) / previous_close * 100
            if previous_close else 0.0
        )

        # ⑤ 交易時段檢查
        if not _is_trading_hours(ts_ms):
            return

        # ⑥ EOD 自動平倉（13:25 後）
        if _is_eod_close_time(ts_ms) and not self._eod_closed:
            await self._close_all_eod(ts_ms)
            self._eod_closed = True
            return

        # ⑦ 持倉出場檢查（動態停損/停利）
        position = self._positions.get(symbol)
        if position is not None and position.side == "long":
            await self._check_exit(symbol, price, ts_ms)
        elif position is not None and position.side == "short":
            await self._check_short_exit(symbol, price, ts_ms)
        else:
            # 無持倉：評估多方進場
            if _is_opening_breakout_window(ts_ms) and change_pct >= OPENING_BREAKOUT_PCT:
                await self._evaluate_buy(symbol, price, change_pct, ts_ms, payload)
            elif change_pct >= self._buy_signal_pct:
                await self._evaluate_buy(symbol, price, change_pct, ts_ms, payload)
            # 評估空方進場（與多方互斥，同一標的只能一個方向）
            if symbol not in self._positions:
                await self._evaluate_short(symbol, price, change_pct, ts_ms, payload)

        # ⑧ 定時績效報告
        if time.time() - self._last_report_ts >= self._report_interval:
            await self._send_performance_report()
            self._last_report_ts = time.time()

    # ── 大盤方向更新（由外部 tick 流呼叫）────────────────────────────────────

    def update_market_index(self, change_pct: float) -> None:
        """Update the TAIEX day-change filter used to block new buys."""
        self._market_change_pct = change_pct

    def _maybe_reset_day(self, ts_ms: int) -> None:
        date_str = _ts_to_date(ts_ms)
        if date_str != self._current_date:
            if self._current_date:
                logger.info("AutoTrader: trading day rolled from %s to %s", self._current_date, date_str)
            self._current_date = date_str
            self._open_prices.clear()
            self._current_bar.clear()
            self._eod_closed = False
            if self._eod_report_task is not None and not self._eod_report_task.done():
                self._eod_report_task.cancel()
            self._eod_report_task = None
            self._last_eod_report_date = None
            self._market_change_pct = 0.0
            # ???? K ???????? ATR / ????????

    def _update_candle(self, symbol: str, price: float, volume: int, ts_ms: int) -> None:
        """Aggregate incoming ticks into 1-minute candles."""
        ts_min = ts_ms // 60_000

        if symbol not in self._current_bar:
            self._current_bar[symbol] = CandleBar(
                ts_min=ts_min,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
            return

        bar = self._current_bar[symbol]
        if ts_min != bar.ts_min:
            self._candle_history.setdefault(symbol, collections.deque(maxlen=20)).append(bar)
            self._volume_history.setdefault(symbol, collections.deque(maxlen=10)).append(bar.volume)
            self._current_bar[symbol] = CandleBar(
                ts_min=ts_min,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
            )
            return

        bar.high = max(bar.high, price)
        bar.low = min(bar.low, price)
        bar.close = price
        bar.volume += volume

    def _calc_atr(self, symbol: str) -> Optional[float]:
        """Calculate a simple ATR from recent 1-minute candles."""
        hist = self._candle_history.get(symbol)
        if hist is None or len(hist) < ATR_BARS_NEEDED:
            return None

        bars = list(hist)
        true_ranges: list[float] = []
        for index in range(1, len(bars)):
            prev_close = bars[index - 1].close
            bar = bars[index]
            true_ranges.append(
                max(
                    bar.high - bar.low,
                    abs(bar.high - prev_close),
                    abs(bar.low - prev_close),
                )
            )

        if not true_ranges:
            return None

        return round(sum(true_ranges) / len(true_ranges), 4)

    def _is_volume_confirmed(self, symbol: str) -> bool:
        """Require the active bar volume to beat the recent 5-bar average."""
        vol_hist = self._volume_history.get(symbol)
        if vol_hist is None or len(vol_hist) < ATR_BARS_NEEDED:
            return True

        recent = list(vol_hist)[-5:]
        avg_vol = sum(recent) / len(recent)
        if avg_vol <= 0:
            return True

        current_bar = self._current_bar.get(symbol)
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
        position = PaperPosition(
            symbol=symbol,
            side="long",
            entry_price=price,
            shares=shares,
            entry_ts=ts_ms,
            entry_change_pct=change_pct,
            stop_price=stop_price,
            target_price=target_price,
            entry_atr=atr,
            peak_price=price,
            trail_stop_price=stop_price,
        )
        self._positions[symbol] = position

        record = TradeRecord(
            symbol=symbol,
            action="BUY",
            price=price,
            shares=shares,
            reason="SIGNAL",
            pnl=0.0,
            ts=ts_ms,
            stop_price=stop_price,
            target_price=target_price,
            decision_report=decision_report,
        )
        self._trade_history.append(record)

        self._risk.on_buy(symbol, price, shares)
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
        await self._send(text)

    async def _check_exit(self, symbol: str, price: float, ts_ms: int) -> None:
        position = self._positions[symbol]

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

        effective_stop = max(position.stop_price, position.trail_stop_price)
        reason: Optional[str] = None
        if price <= effective_stop:
            reason = "TRAIL_STOP" if position.trail_stop_price > position.stop_price else "STOP_LOSS"
        elif price >= position.target_price:
            reason = "TAKE_PROFIT"

        if reason:
            pct_from_entry = (price - position.entry_price) / position.entry_price * 100
            await self._paper_sell(symbol, price, reason, pct_from_entry, ts_ms)

    async def _paper_sell(
        self,
        symbol: str,
        price: float,
        reason: str,
        pct_from_entry: float,
        ts_ms: int,
    ) -> None:
        position = self._positions.pop(symbol)
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
            price=price,
            shares=position.shares,
            reason=reason,
            pnl=net_pnl,
            ts=ts_ms,
            gross_pnl=gross_pnl,
            decision_report=decision_report,
        )
        self._trade_history.append(record)

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
                f"股票：{symbol}",
                f"原因：{reason_labels.get(reason, reason)}",
                f"進場 / 出場：{position.entry_price:,.2f} / {price:,.2f}",
                f"毛報酬：{pct_from_entry:+.2f}%",
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
        await self._send(text)

        if self._risk.is_halted:
            await self._send(
                f"[風控警示] 當日損益已達限制，今日累計 {daily_pnl:+,.0f} 元，系統暫停新倉。"
            )

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

        shares = self._shares
        allowed, reason = self._risk.can_buy(symbol, price, shares, len(self._positions))
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

        atr = self._calc_atr(symbol)
        long_stop = self._risk.calc_stop_price(price, atr)
        long_target = self._risk.calc_target_price(price, long_stop)
        # 空方：停損在進場價上方（反彈即止損），停利在進場價下方
        short_stop = round(price + (price - long_stop), 2)
        short_target = round(price - (long_target - price), 2)

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
        await self._paper_short(
            symbol,
            price,
            change_pct,
            ts_ms,
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
        position = PaperPosition(
            symbol=symbol,
            side="short",
            entry_price=price,
            shares=shares,
            entry_ts=ts_ms,
            entry_change_pct=change_pct,
            stop_price=stop_price,
            target_price=target_price,
            entry_atr=atr,
            peak_price=price,
            trail_stop_price=stop_price,
        )
        self._positions[symbol] = position

        record = TradeRecord(
            symbol=symbol,
            action="SHORT",
            price=price,
            shares=shares,
            reason="SIGNAL",
            pnl=0.0,
            ts=ts_ms,
            stop_price=stop_price,
            target_price=target_price,
            decision_report=decision_report,
        )
        self._trade_history.append(record)

        self._risk.on_buy(symbol, price, shares)
        await self._persist_trade(record)

        atr_label = f"{atr:.3f}" if atr is not None else "N/A"
        cost = price * shares
        text = "\n".join(
            [
                "[模擬交易] 放空成交",
                f"股票：{symbol}",
                f"觸發跌幅：{change_pct:+.2f}%",
                f"成交價：{price:,.2f}",
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
        await self._send(text)

    async def _check_short_exit(self, symbol: str, price: float, ts_ms: int) -> None:
        """檢查空方出場條件（停損 / 停利）。不使用追蹤停利。"""
        position = self._positions[symbol]
        reason: Optional[str] = None
        if price >= position.stop_price:
            reason = "STOP_LOSS"
        elif price <= position.target_price:
            reason = "TAKE_PROFIT"

        if reason:
            pct_from_entry = (position.entry_price - price) / position.entry_price * 100
            await self._paper_cover(symbol, price, reason, pct_from_entry, ts_ms)

    async def _paper_cover(
        self,
        symbol: str,
        price: float,
        reason: str,
        pct_from_entry: float,
        ts_ms: int,
    ) -> None:
        """回補空方部位，計算損益並記錄 COVER 成交。"""
        position = self._positions.pop(symbol)
        gross_pnl = (position.entry_price - price) * position.shares
        # 參數對調：calc_net_pnl(cover_price, entry_price, shares)
        # → (entry_price - cover_price) * shares - costs ✓
        net_pnl = self._risk.calc_net_pnl(price, position.entry_price, position.shares)

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
                    "price": round(price, 2),
                    "shares": position.shares,
                    "pnl": round(net_pnl, 2),
                },
            )
        )

        record = TradeRecord(
            symbol=symbol,
            action="COVER",
            price=price,
            shares=position.shares,
            reason=reason,
            pnl=net_pnl,
            ts=ts_ms,
            gross_pnl=gross_pnl,
            decision_report=decision_report,
        )
        self._trade_history.append(record)

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
                f"進場 / 回補：{position.entry_price:,.2f} / {price:,.2f}",
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
        await self._send(text)

    async def _close_all_eod(self, ts_ms: int) -> None:
        """Force-close all positions after 13:25."""
        symbols = list(self._positions.keys())
        if not symbols:
            return

        logger.info("AutoTrader: EOD close triggered for %d open positions", len(symbols))
        for symbol in symbols:
            position = self._positions[symbol]
            price = self._last_prices.get(symbol, position.entry_price)
            if position.side == "short":
                pct = (position.entry_price - price) / position.entry_price * 100
                await self._paper_cover(symbol, price, "EOD", pct, ts_ms)
            else:
                pct = (price - position.entry_price) / position.entry_price * 100
                await self._paper_sell(symbol, price, "EOD", pct, ts_ms)

        await self._send_performance_report()
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
            logger.warning("Trade persistence failed for %s %s: %s", record.action, record.symbol, exc)

    def get_portfolio_snapshot(self) -> dict[str, Any]:
        sells = [trade for trade in self._trade_history if trade.action in {"SELL", "COVER"}]
        realized_pnl = sum(trade.pnl for trade in sells)
        wins = sum(1 for trade in sells if trade.pnl > 0)
        win_rate = wins / len(sells) * 100 if sells else 0.0

        positions = []
        unrealized_total = 0.0
        for symbol, position in self._positions.items():
            last = self._last_prices.get(symbol, position.entry_price)
            if position.side == "short":
                pnl = (position.entry_price - last) * position.shares
                pct = (position.entry_price - last) / position.entry_price * 100
            else:
                pnl = (last - position.entry_price) * position.shares
                pct = (last - position.entry_price) / position.entry_price * 100
            unrealized_total += pnl
            positions.append(
                {
                    "symbol": symbol,
                    "side": position.side,
                    "entryPrice": position.entry_price,
                    "currentPrice": last,
                    "shares": position.shares,
                    "pnl": round(pnl, 0),
                    "pct": round(pct, 2),
                    "entryTs": position.entry_ts,
                    "stopPrice": position.stop_price,
                    "targetPrice": position.target_price,
                    "trailStopPrice": position.trail_stop_price,
                }
            )

        recent_trades = [
            {
                "symbol": trade.symbol,
                "action": trade.action,
                "price": trade.price,
                "shares": trade.shares,
                "reason": trade.reason,
                "netPnl": round(trade.pnl, 0),
                "grossPnl": round(trade.gross_pnl, 0),
                "ts": trade.ts,
                "decisionReport": trade.decision_report.to_dict() if trade.decision_report is not None else None,
            }
            for trade in self._trade_history[-20:]
        ]
        recent_decisions = [report.to_dict() for report in self._decision_history[-40:]]

        return {
            "type": "PAPER_PORTFOLIO",
            "positions": positions,
            "recentTrades": recent_trades,
            "recentDecisions": recent_decisions,
            "realizedPnl": round(realized_pnl, 0),
            "unrealizedPnl": round(unrealized_total, 0),
            "totalPnl": round(realized_pnl + unrealized_total, 0),
            "tradeCount": len(sells),
            "winRate": round(win_rate, 1),
            "marketChangePct": round(self._market_change_pct, 2),
            "riskStatus": self._risk.status_dict(),
            "sessionId": self._session_id,
        }

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
            if int(payload.get("tradeCount", 0) or 0) <= 0:
                return
            result = self._daily_reporter.build_and_send(day_payload=payload)
            if asyncio.iscoroutine(result):
                await result
            self._last_eod_report_date = report_date
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Daily EOD report failed: %s", exc)

    def _build_daily_report_payload(self, ts_ms: int) -> dict[str, Any]:
        report_date = _ts_to_date(ts_ms)
        trades = [
            trade for trade in self._trade_history
            if _ts_to_date(trade.ts) == report_date
        ]
        closed_trades = [trade for trade in trades if trade.action in {"SELL", "COVER"}]
        realized_pnl = sum(trade.pnl for trade in closed_trades)
        wins = sum(1 for trade in closed_trades if trade.pnl > 0)
        win_rate = wins / len(closed_trades) * 100 if closed_trades else 0.0
        unrealized_pnl = sum(
            (
                (position.entry_price - self._last_prices.get(symbol, position.entry_price)) * position.shares
                if position.side == "short"
                else (self._last_prices.get(symbol, position.entry_price) - position.entry_price) * position.shares
            )
            for symbol, position in self._positions.items()
        )
        return {
            "date": report_date,
            "tradeCount": len(closed_trades),
            "winRate": round(win_rate, 1),
            "realizedPnl": round(realized_pnl, 0),
            "unrealizedPnl": round(unrealized_pnl, 0),
            "totalPnl": round(realized_pnl + unrealized_pnl, 0),
            "riskStatus": self._risk.status_dict(),
            "trades": [
                {
                    "symbol": trade.symbol,
                    "action": trade.action,
                    "price": round(trade.price, 2),
                    "shares": trade.shares,
                    "reason": trade.reason,
                    "netPnl": round(trade.pnl, 2),
                    "grossPnl": round(trade.gross_pnl, 2),
                    "ts": trade.ts,
                    "decisionReport": trade.decision_report.to_dict() if trade.decision_report is not None else None,
                }
                for trade in trades
            ],
        }

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

        if self._market_change_pct <= MARKET_HALT_PCT:
            logger.info("Market filter blocked %s: taiex=%.2f%% threshold=%.2f%%", symbol, self._market_change_pct, MARKET_HALT_PCT)
            self._record_skip_decision(
                symbol=symbol,
                ts_ms=ts_ms,
                final_reason="market_halt",
                summary="大盤風險閘門啟動，暫停新的搶快進場。",
                price=price,
                change_pct=change_pct,
                payload=payload,
                supporting_factors=supporting_factors,
                opposing_factors=[DecisionFactor("oppose", "大盤條件", f"加權指數 {self._market_change_pct:+.2f}% 低於風控門檻")],
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

        # Scale position size by signal confidence: strong signals (≥80) get 2 lots,
        # others get 1 lot.  Risk manager still enforces the single-position cap.
        confidence = self._build_confidence(
            change_pct=change_pct,
            volume_confirmed=volume_confirmed,
            sentiment_score=sentiment_score,
        )
        lots = 2 if confidence >= 80 else 1
        shares = lots * SHARES_PER_LOT

        allowed, reason = self._risk.can_buy(symbol, price, shares, len(self._positions))
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

        atr = self._calc_atr(symbol)
        stop_price = self._risk.calc_stop_price(price, atr)
        target_price = self._risk.calc_target_price(price, stop_price)
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
        await self._paper_buy(
            symbol,
            price,
            change_pct,
            ts_ms,
            stop_price=stop_price,
            target_price=target_price,
            atr=atr,
            decision_report=decision_report,
            shares=shares,
        )

    async def _paper_sell(
        self,
        symbol: str,
        price: float,
        reason: str,
        pct_from_entry: float,
        ts_ms: int,
    ) -> None:
        position = self._positions.pop(symbol)
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
                    "price": round(price, 2),
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
            price=price,
            shares=position.shares,
            reason=reason,
            pnl=net_pnl,
            ts=ts_ms,
            gross_pnl=gross_pnl,
            decision_report=decision_report,
        )
        self._trade_history.append(record)

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
                f"進場 / 出場：{position.entry_price:,.2f} / {price:,.2f}",
                f"相對報酬：{pct_from_entry:+.2f}%",
                f"毛損益：{gross_pnl:+,.0f} 元",
                f"交易成本：{tx_cost:,.0f} 元",
                f"淨損益：{net_pnl:+,.0f} 元",
                f"當日累計：{daily_pnl:+,.0f} 元",
                f"時間：{_ms_to_time(ts_ms)}",
            ]
        )
        logger.info("[PAPER SELL] %s @ %.2f reason=%s net_pnl=%.0f", symbol, price, reason, net_pnl)
        await self._send(text)

        if self._risk.is_halted:
            await self._send(f"[風控警示] 當日損益已達限制：{daily_pnl:+,.0f} 元，系統將暫停新單。")

    async def _send_performance_report(self) -> None:
        sells = [trade for trade in self._trade_history if trade.action in {"SELL", "COVER"}]
        realized_pnl = sum(trade.pnl for trade in sells)
        wins = sum(1 for trade in sells if trade.pnl > 0)
        win_rate = wins / len(sells) * 100 if sells else 0.0
        unrealized = sum(
            (self._last_prices.get(symbol, position.entry_price) - position.entry_price) * position.shares
            for symbol, position in self._positions.items()
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
                f"持倉：{len(self._positions)} / {risk['maxPositions']} 檔",
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

# Time helpers

def _ts_to_datetime(ts_ms: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ts_ms / 1000, tz=_TZ_TW)


def _ts_to_date(ts_ms: int) -> str:
    return _ts_to_datetime(ts_ms).strftime("%Y-%m-%d")


def _is_trading_hours(ts_ms: int) -> bool:
    """Return True during the trading session window (08:00–17:00)."""
    dt = _ts_to_datetime(ts_ms)
    t = dt.hour * 60 + dt.minute
    return 9 * 60 <= t <= 13 * 60 + 30


def _is_eod_close_time(ts_ms: int) -> bool:
    """Return True once the 13:25 end-of-day liquidation window starts."""
    dt = _ts_to_datetime(ts_ms)
    t = dt.hour * 60 + dt.minute
    return t >= 13 * 60 + 25


def _is_opening_breakout_window(ts_ms: int) -> bool:
    """Return True during Taiwan market opening breakout window (09:00–09:30)."""
    dt = _ts_to_datetime(ts_ms)
    t = dt.hour * 60 + dt.minute
    return 9 * 60 <= t <= 9 * 60 + 30


def _cover_reason_label(reason: str) -> str:
    return {"STOP_LOSS": "停損回補", "TAKE_PROFIT": "目標停利", "EOD": "收盤回補"}.get(reason, reason)


def _ms_to_time(ts_ms: int) -> str:
    return _ts_to_datetime(ts_ms).strftime("%H:%M:%S")


# Factory

def trader_from_env() -> AutoTrader:
    from daily_reporter import daily_reporter_from_env
    from risk_manager import risk_manager_from_env
    from sentiment_filter import SentimentFilter

    return AutoTrader(
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
        risk_manager=risk_manager_from_env(),
        sentiment_filter=SentimentFilter(),
        daily_reporter=daily_reporter_from_env(),
    )
