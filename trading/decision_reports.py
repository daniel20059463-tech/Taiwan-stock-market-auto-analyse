from __future__ import annotations

from dataclasses import dataclass
from typing import Any


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
