from multi_analyst import (
    AnalystContext,
    DecisionComposer,
    NewsAnalyst,
    RiskAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
)


def test_decision_bundle_contains_bull_bear_and_risk_cases() -> None:
    context = AnalystContext(
        symbol="2330",
        ts=1_775_500_400_000,
        decision_type="buy",
        trigger_type="mixed",
        price=101.0,
        change_pct=2.32,
        volume_confirmed=True,
        sentiment_score=0.42,
        market_change_pct=0.35,
        risk_allowed=True,
        risk_reason="風控允許",
        risk_flags=["tight_stop"],
        source_events=[
            {"source": "news_event", "articleId": "article-1", "score": 0.81},
            {"source": "market", "price": 101.0, "changePct": 2.32},
        ],
        supporting_factors=[
            {"label": "盤中轉強", "detail": "盤中漲幅 +2.32%"},
        ],
        opposing_factors=[
            {"label": "高點風險", "detail": "距離日高不遠，需注意追價風險"},
        ],
    )

    views = [
        NewsAnalyst().analyze(context),
        SentimentAnalyst().analyze(context),
        TechnicalAnalyst().analyze(context),
        RiskAnalyst().analyze(context),
    ]
    bundle = DecisionComposer().compose(context, views)

    assert bundle.final_decision == "buy"
    assert bundle.confidence > 0
    assert "多方觀點" in bundle.bull_case
    assert "空方觀點" in bundle.bear_case
    assert "風控觀點" in bundle.risk_case
    assert "多方論點" in bundle.bull_argument
    assert "空方論點" in bundle.bear_argument
    assert "裁決" in bundle.referee_verdict
    assert bundle.debate_winner in {"bull", "bear", "tie"}
    assert len(bundle.views) == 4


def test_news_analyst_marks_short_news_as_bearish() -> None:
    context = AnalystContext(
        symbol="2454",
        ts=1_775_500_700_000,
        decision_type="short",
        trigger_type="mixed",
        price=1288.0,
        change_pct=-2.1,
        volume_confirmed=True,
        sentiment_score=-0.55,
        market_change_pct=-0.4,
        risk_allowed=True,
        risk_reason="風控允許",
        risk_flags=[],
        source_events=[{"source": "news_event", "articleId": "article-short-1"}],
    )

    view = NewsAnalyst().analyze(context)

    assert view.stance == "bearish"
