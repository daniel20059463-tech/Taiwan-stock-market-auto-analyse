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
            support.append(AnalystFactor("事件催化", f"偵測到新聞事件 {article_id}，具備短線催化條件。"))
            summary = "新聞分析認為事件仍在時效內，適合納入盤中判斷。"
        else:
            support.append(AnalystFactor("事件背景", "目前沒有新的新聞事件，主要依賴盤面資料判讀。"))
            summary = "新聞分析未發現新的催化來源，傾向作為中性背景。"
        return AnalystView(
            agent_name=self.agent_name,
            stance=stance,
            score=score,
            summary=summary,
            supporting_factors=support,
            metadata={"articleId": article_id} if article_id else {},
        )


class SentimentAnalyst:
    agent_name = "輿情分析"

    def analyze(self, context: AnalystContext) -> AnalystView:
        score_value = context.sentiment_score or 0.0
        score = max(0, min(100, 50 + int(score_value * 40)))
        blocking = score_value < -0.2
        if score_value > 0.2:
            stance = "bullish"
            summary = f"輿情分析偏多，情緒分數 {score_value:.3f} 對多方有利。"
            support = [AnalystFactor("市場情緒", f"情緒分數 {score_value:.3f} 支持偏多解讀。")]
            oppose: list[AnalystFactor] = []
        elif score_value < -0.2:
            stance = "bearish"
            summary = f"輿情分析偏空，情緒分數 {score_value:.3f} 建議保守處理。"
            support = []
            oppose = [AnalystFactor("市場情緒", f"情緒分數 {score_value:.3f} 顯示市場雜訊偏空。")]
        else:
            stance = "neutral"
            summary = "輿情分析接近中性，暫時不單獨決定進出場。"
            support = [AnalystFactor("情緒平衡", "情緒分數接近中性，需交由其他角色補強。")]
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
            support.append(AnalystFactor("價格動能", f"盤中漲跌幅 {context.change_pct:+.2f}% 代表動能已明顯展開。"))
        else:
            oppose.append(AnalystFactor("動能不足", f"盤中漲跌幅 {context.change_pct:+.2f}% 尚未完全擴散。"))

        if context.volume_confirmed:
            score += 16
            support.append(AnalystFactor("量能確認", "成交量已達放量門檻，技術面支持事件延續。"))
        else:
            score -= 12
            oppose.append(AnalystFactor("量能不足", "價格有變化但量能沒有同步放大。"))

        stance = "bullish" if context.decision_type in {"buy", "cover"} else "bearish" if context.decision_type in {"sell", "short"} else "neutral"
        summary = "技術分析認為量價結構完整，可配合事件單執行。" if score >= 60 else "技術分析認為確認度有限，建議降低信心。"
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
        support = [AnalystFactor("風控狀態", context.risk_reason)]
        oppose: list[AnalystFactor] = []
        if context.market_change_pct <= -1.5:
            score -= 18
            oppose.append(AnalystFactor("大盤壓力", f"加權指數 {context.market_change_pct:+.2f}% 代表市場承壓。"))
        if context.risk_flags:
            oppose.extend(AnalystFactor("風險旗標", flag) for flag in context.risk_flags)
        summary = "風控分析允許進場，但需要嚴守停損與部位限制。" if context.risk_allowed else "風控分析不建議進場，需先等待風險解除。"
        return AnalystView(
            agent_name=self.agent_name,
            stance="bullish" if context.risk_allowed else "bearish",
            score=max(0, min(100, score)),
            summary=summary,
            supporting_factors=support,
            opposing_factors=oppose,
            blocking=not context.risk_allowed,
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
            points.append("量能有跟上，短線追價的勝率提升。")
        if context.decision_type == "buy":
            conclusion = "多方主張先搶小部位，等事件擴散後再觀察是否加碼。"
        elif context.decision_type == "cover":
            conclusion = "多方認為主要跌段已完成，回補空單可以保住已實現利潤。"
        else:
            conclusion = "多方主張目前不急著反手，先觀察多頭是否還有延續。"
        return f"多方論點：{'；'.join(points) if points else '目前多方缺乏明確優勢。'} {conclusion}"


class BearResearcher:
    def argue(self, context: AnalystContext, views: list[AnalystView]) -> str:
        points: list[str] = []
        for view in views:
            if view.stance == "bearish" or view.blocking:
                factor = view.opposing_factors[0].detail if view.opposing_factors else view.summary
                points.append(factor)
        if not context.volume_confirmed:
            points.append("量能沒有同步擴大，容易出現假突破。")
        if context.market_change_pct <= 0:
            points.append(f"大盤變化 {context.market_change_pct:+.2f}% ，整體環境不夠友善。")
        if context.decision_type == "short":
            conclusion = "空方觀點認為利空事件與盤中轉弱已形成有效放空視窗。"
        elif context.decision_type == "cover":
            conclusion = "空方提醒若過早回補可能錯過後續跌段，需確認主跌段已完成。"
        else:
            conclusion = "空方提醒不要因為單一事件忽略回落與洗盤風險。"
        return f"空方論點：{'；'.join(points) if points else '目前空方缺乏足夠證據。'} {conclusion}"


class DebateReferee:
    def decide(self, context: AnalystContext, views: list[AnalystView], bull_argument: str, bear_argument: str) -> DebateResult:
        bull_score = sum(view.score for view in views if view.stance == "bullish")
        bear_score = sum(view.score for view in views if view.stance == "bearish" or view.blocking)

        if any(view.blocking for view in views):
            winner = "bear"
            verdict = "裁決結論：風控或輿情已出現阻擋訊號，先不執行新的事件單。"
        elif bull_score > bear_score + 10:
            winner = "bull"
            verdict = "裁決結論：多方證據較完整，可執行小部位搶快單，但仍要嚴守停損。"
        elif bear_score > bull_score + 10:
            winner = "bear"
            verdict = "裁決結論：空方顧慮偏多，暫時以觀察或減碼為主。"
        else:
            winner = "tie"
            verdict = "裁決結論：多空證據接近，若要交易也應縮小部位並提高警戒。"

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
        ) or "目前沒有足夠的多方優勢。"
        bear_points = "；".join(
            factor.detail
            for view in negative_views
            for factor in (view.opposing_factors[:1] or [AnalystFactor(view.agent_name, view.summary)])
        ) or "目前沒有明顯的空方壓力。"
        risk_points = "；".join(view.summary for view in views if view.agent_name == "風控分析") or "風控分析尚未提供額外限制。"

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
