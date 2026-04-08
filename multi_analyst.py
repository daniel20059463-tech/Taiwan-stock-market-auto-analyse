from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalystFactor:
    label: str
    detail: str


@dataclass
class AnalystView:
    agent_name: str
    stance: str
    score: int
    summary: str
    supporting_factors: list[AnalystFactor] = field(default_factory=list)
    opposing_factors: list[AnalystFactor] = field(default_factory=list)
    blocking: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalystContext:
    symbol: str
    ts: int
    decision_type: str
    trigger_type: str
    price: float
    change_pct: float
    volume_confirmed: bool
    sentiment_score: float | None
    market_change_pct: float
    risk_allowed: bool
    risk_reason: str
    risk_flags: list[str]
    source_events: list[dict[str, Any]] = field(default_factory=list)
    supporting_factors: list[dict[str, str]] = field(default_factory=list)
    opposing_factors: list[dict[str, str]] = field(default_factory=list)
    entry_price: float | None = None
    current_price: float | None = None
    portfolio_positions_count: int = 0
    portfolio_unrealized_pnl: float = 0.0
    portfolio_daily_win_rate: float = 0.0
    portfolio_risk_budget_used_pct: float = 0.0


@dataclass
class DebateResult:
    bull_argument: str
    bear_argument: str
    referee_verdict: str
    debate_winner: str


@dataclass
class DecisionBundle:
    symbol: str
    ts: int
    views: list[AnalystView]
    bull_case: str
    bear_case: str
    risk_case: str
    bull_argument: str
    bear_argument: str
    referee_verdict: str
    debate_winner: str
    final_decision: str
    confidence: int


class NewsAnalyst:
    agent_name = "新聞分析"

    def analyze(self, context: AnalystContext) -> AnalystView:
        news_events = [event for event in context.source_events if event.get("source") == "news_event"]
        has_news = bool(news_events)
        article_id = news_events[0].get("articleId") if has_news else None
        score = 72 if has_news else 45
        stance = (
            "bullish"
            if context.decision_type == "buy"
            else "bearish"
            if context.decision_type == "short"
            else "neutral"
        )
        support: list[AnalystFactor] = []
        if has_news:
            support.append(AnalystFactor("事件來源", f"已取得新聞事件，article_id={article_id}"))
            summary = "新聞分析認為目前事件具備方向性資訊，可作為決策依據。"
        else:
            support.append(AnalystFactor("事件空窗", "目前沒有新的新聞事件，僅能依價格與量能判斷。"))
            summary = "新聞分析未取得明確事件，判斷權重下降。"
        return AnalystView(
            agent_name=self.agent_name,
            stance=stance,
            score=score,
            summary=summary,
            supporting_factors=support,
            metadata={"articleId": article_id} if article_id else {},
        )


class SentimentAnalyst:
    agent_name = "情緒分析"

    def analyze(self, context: AnalystContext) -> AnalystView:
        score_value = context.sentiment_score or 0.0
        score = max(0, min(100, 50 + int(score_value * 40)))
        blocking = score_value < -0.2
        if score_value > 0.2:
            stance = "bullish"
            summary = f"情緒分析偏多，分數 {score_value:.3f}，支持順勢交易。"
            support = [AnalystFactor("情緒分數", f"情緒分數 {score_value:.3f}，偏多。")]
            oppose: list[AnalystFactor] = []
        elif score_value < -0.2:
            stance = "bearish"
            summary = f"情緒分析偏空，分數 {score_value:.3f}，需提高警覺。"
            support = []
            oppose = [AnalystFactor("情緒分數", f"情緒分數 {score_value:.3f}，偏空。")]
        else:
            stance = "neutral"
            summary = "情緒分析中性，無法提供明顯方向。"
            support = [AnalystFactor("情緒持平", "情緒分數接近中性，需依其他條件補強。")]
            oppose = []
        return AnalystView(
            agent_name=self.agent_name,
            stance=stance,
            score=score,
            summary=summary,
            supporting_factors=support,
            opposing_factors=oppose,
            blocking=blocking,
            metadata={"sentimentScore": round(score_value, 4)},
        )


class TechnicalAnalyst:
    agent_name = "技術分析"

    def analyze(self, context: AnalystContext) -> AnalystView:
        score = 48
        support: list[AnalystFactor] = []
        oppose: list[AnalystFactor] = []

        if abs(context.change_pct) >= 2:
            score += 18
            support.append(AnalystFactor("波動強度", f"日內漲跌 {context.change_pct:+.2f}%，波動已展開。"))
        else:
            oppose.append(AnalystFactor("波動不足", f"日內漲跌 {context.change_pct:+.2f}%，動能仍偏弱。"))

        if context.volume_confirmed:
            score += 16
            support.append(AnalystFactor("量能確認", "成交量通過確認，價格變動較有可信度。"))
        else:
            score -= 12
            oppose.append(AnalystFactor("量能不足", "成交量未通過確認，訊號可靠度下降。"))

        if context.portfolio_unrealized_pnl < -5000:
            score -= 8
            oppose.append(
                AnalystFactor(
                    "組合浮虧偏重",
                    f"帳本未實現損益 {context.portfolio_unrealized_pnl:+,.0f}，目前不宜過度擴張風險。",
                )
            )

        stance = (
            "bullish"
            if context.decision_type in {"buy", "cover"}
            else "bearish"
            if context.decision_type in {"sell", "short"}
            else "neutral"
        )
        summary = (
            "技術分析給出偏正向的確認。"
            if score >= 60
            else "技術分析訊號尚未完全成立。"
        )
        return AnalystView(
            agent_name=self.agent_name,
            stance=stance,
            score=max(0, min(100, score)),
            summary=summary,
            supporting_factors=support,
            opposing_factors=oppose,
        )


class RiskAnalyst:
    agent_name = "風控分析"

    def analyze(self, context: AnalystContext) -> AnalystView:
        score = 70 if context.risk_allowed else 20
        support = [AnalystFactor("風控判斷", context.risk_reason)]
        oppose: list[AnalystFactor] = []
        blocking = not context.risk_allowed

        if context.market_change_pct <= -1.5:
            score -= 18
            oppose.append(AnalystFactor("大盤壓力", f"大盤變動 {context.market_change_pct:+.2f}%，市場風險升高。"))
        if context.risk_flags:
            oppose.extend(AnalystFactor("風險旗標", flag) for flag in context.risk_flags)

        if context.portfolio_positions_count >= 4:
            score -= 10
            oppose.append(
                AnalystFactor(
                    "持倉接近上限",
                    f"目前持倉 {context.portfolio_positions_count} 檔，新增部位會拉高整體風險。",
                )
            )
        if context.portfolio_risk_budget_used_pct >= 0.8:
            blocking = True
            oppose.append(
                AnalystFactor(
                    "風控預算耗盡",
                    f"風險預算使用率 {context.portfolio_risk_budget_used_pct:.0%}，不宜再開新部位。",
                )
            )
        elif context.portfolio_risk_budget_used_pct >= 0.5:
            score -= 15
            oppose.append(
                AnalystFactor(
                    "風控預算過半",
                    f"風險預算使用率 {context.portfolio_risk_budget_used_pct:.0%}，需降低積極度。",
                )
            )

        summary = (
            "風控分析允許進場。"
            if context.risk_allowed and not blocking
            else "風控分析不建議進場。"
        )
        return AnalystView(
            agent_name=self.agent_name,
            stance="bullish" if context.risk_allowed and not blocking else "bearish",
            score=max(0, min(100, score)),
            summary=summary,
            supporting_factors=support,
            opposing_factors=oppose,
            blocking=blocking,
            metadata={"riskFlags": list(context.risk_flags)},
        )


class BullResearcher:
    def argue(self, context: AnalystContext, views: list[AnalystView]) -> str:
        points: list[str] = []
        for view in views:
            if view.stance == "bullish":
                factor = view.supporting_factors[0].detail if view.supporting_factors else view.summary
                points.append(factor)
        if context.volume_confirmed:
            points.append("量能已確認，市場對這個方向至少有短線共識。")
        if context.decision_type == "buy":
            conclusion = "綜合判斷偏向做多。"
        elif context.decision_type == "cover":
            conclusion = "綜合判斷偏向回補空單。"
        else:
            conclusion = "多方論點存在，但不一定足以主導最終決策。"
        return f"多方論點：{'；'.join(points) if points else '目前缺乏強而有力的多方理由。'} {conclusion}"


class BearResearcher:
    def argue(self, context: AnalystContext, views: list[AnalystView]) -> str:
        points: list[str] = []
        for view in views:
            if view.stance == "bearish" or view.blocking:
                factor = view.opposing_factors[0].detail if view.opposing_factors else view.summary
                points.append(factor)
        if not context.volume_confirmed:
            points.append("量能不足，訊號延續性不高。")
        if context.market_change_pct <= 0:
            points.append(f"大盤變動 {context.market_change_pct:+.2f}%，市場背景不利。")
        if context.decision_type == "short":
            conclusion = "綜合判斷偏向放空。"
        elif context.decision_type == "cover":
            conclusion = "綜合判斷偏向先回補，避免風險反轉。"
        else:
            conclusion = "空方疑慮仍在，必須保留反向風險。"
        return f"空方論點：{'；'.join(points) if points else '目前缺乏強而有力的空方理由。'} {conclusion}"


class DebateReferee:
    def decide(
        self,
        context: AnalystContext,
        views: list[AnalystView],
        bull_argument: str,
        bear_argument: str,
    ) -> DebateResult:
        bull_score = sum(view.score for view in views if view.stance == "bullish")
        bear_score = sum(view.score for view in views if view.stance == "bearish" or view.blocking)

        if any(view.blocking for view in views):
            winner = "bear"
            verdict = "裁決結論：風控或反向條件已構成阻擋，偏向保守處理。"
        elif bull_score > bear_score + 10:
            winner = "bull"
            verdict = "裁決結論：多方理由較完整，支持目前決策方向。"
        elif bear_score > bull_score + 10:
            winner = "bear"
            verdict = "裁決結論：空方理由較強，需優先重視風險。"
        else:
            winner = "tie"
            verdict = "裁決結論：正反理由接近，代表信心不足，應控制倉位。"

        return DebateResult(
            bull_argument=bull_argument,
            bear_argument=bear_argument,
            referee_verdict=verdict,
            debate_winner=winner,
        )


class DecisionComposer:
    def __init__(self) -> None:
        self._bull_researcher = BullResearcher()
        self._bear_researcher = BearResearcher()
        self._referee = DebateReferee()

    def compose(self, context: AnalystContext, views: list[AnalystView]) -> DecisionBundle:
        positive_views = [view for view in views if view.stance == "bullish"]
        negative_views = [view for view in views if view.stance == "bearish" or view.blocking]
        avg_score = round(sum(view.score for view in views) / max(1, len(views)))

        if any(view.blocking for view in views):
            final_decision = "skip" if context.decision_type == "buy" else context.decision_type
        else:
            final_decision = context.decision_type

        bull_points = "；".join(
            factor.detail
            for view in positive_views
            for factor in (view.supporting_factors[:1] or [AnalystFactor(view.agent_name, view.summary)])
        ) or "目前沒有足夠的多方支持。"
        bear_points = "；".join(
            factor.detail
            for view in negative_views
            for factor in (view.opposing_factors[:1] or [AnalystFactor(view.agent_name, view.summary)])
        ) or "目前沒有足夠的空方疑慮。"
        risk_points = "；".join(view.summary for view in views if view.agent_name == "風控分析") or "風控分析未提供額外限制。"

        bull_argument = self._bull_researcher.argue(context, views)
        bear_argument = self._bear_researcher.argue(context, views)
        debate = self._referee.decide(context, views, bull_argument, bear_argument)

        return DecisionBundle(
            symbol=context.symbol,
            ts=context.ts,
            views=views,
            bull_case=f"多方觀點：{bull_points}",
            bear_case=f"空方觀點：{bear_points}",
            risk_case=f"風控觀點：{risk_points}",
            bull_argument=debate.bull_argument,
            bear_argument=debate.bear_argument,
            referee_verdict=debate.referee_verdict,
            debate_winner=debate.debate_winner,
            final_decision=final_decision,
            confidence=max(5, min(95, avg_score)),
        )
