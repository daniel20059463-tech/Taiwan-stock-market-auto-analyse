from __future__ import annotations

from trading.positions import PaperPosition, PositionBook, TradeRecord


class _SerializableDecisionReport:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def to_dict(self) -> dict[str, object]:
        return dict(self.value)


def test_build_snapshot_includes_side_and_unrealized_pnl_for_long_and_short() -> None:
    book = PositionBook()
    book.positions["2330"] = PaperPosition(
        symbol="2330",
        side="long",
        entry_price=100.0,
        shares=10,
        entry_ts=1,
        entry_change_pct=2.5,
        stop_price=95.0,
        target_price=110.0,
    )
    book.positions["2454"] = PaperPosition(
        symbol="2454",
        side="short",
        entry_price=200.0,
        shares=5,
        entry_ts=2,
        entry_change_pct=-3.0,
        stop_price=210.0,
        target_price=180.0,
    )
    book.trade_history.append(
        TradeRecord(
            symbol="2330",
            action="BUY",
            price=100.0,
            shares=10,
            reason="SIGNAL",
            pnl=0.0,
            ts=1,
            stop_price=95.0,
            target_price=110.0,
            gross_pnl=0.0,
            decision_report={"decisionType": "buy"},
        )
    )
    book.trade_history.append(
        TradeRecord(
            symbol="2330",
            action="SELL",
            price=106.0,
            shares=10,
            reason="TAKE_PROFIT",
            pnl=12.34,
            ts=2,
            gross_pnl=13.56,
            decision_report=_SerializableDecisionReport({"decisionType": "sell"}),
        )
    )
    for index in range(24):
        book.trade_history.append(
            TradeRecord(
                symbol=f"9{index:03d}",
                action="SELL",
                price=100.0 + index,
                shares=1,
                reason="SIGNAL",
                pnl=float(index) + 0.25,
                ts=100 + index,
                gross_pnl=float(index) + 0.75,
                decision_report={"index": index},
            )
        )
    book.trade_history.append(
        TradeRecord(
            symbol="9999",
            action="COVER",
            price=88.0,
            shares=2,
            reason="TAKE_PROFIT",
            pnl=12.0,
            ts=999,
            stop_price=90.0,
            target_price=85.0,
            gross_pnl=13.0,
            decision_report={"decisionType": "cover"},
        )
    )

    snapshot = book.build_snapshot({"2330": 108.0, "2454": 190.0}, session_id="sess-1")

    assert snapshot["type"] == "PAPER_PORTFOLIO"
    assert snapshot["sessionId"] == "sess-1"
    assert "recentDecisions" not in snapshot
    assert "realizedPnl" not in snapshot
    assert "totalPnl" not in snapshot
    assert "tradeCount" not in snapshot
    assert "winRate" not in snapshot
    assert "marketChangePct" not in snapshot
    assert "riskStatus" not in snapshot
    assert snapshot["unrealizedPnl"] == 130.0
    assert len(snapshot["recentTrades"]) == 20
    assert snapshot["recentTrades"][0]["netPnl"] == 5.0
    assert snapshot["recentTrades"][0]["grossPnl"] == 6.0
    assert snapshot["recentTrades"][-1]["decisionReport"] == {"decisionType": "cover"}
    assert snapshot["recentTrades"][0]["decisionReport"] == {"index": 5}

    positions_by_symbol = {position["symbol"]: position for position in snapshot["positions"]}
    assert positions_by_symbol["2330"]["side"] == "long"
    assert positions_by_symbol["2454"]["side"] == "short"
    assert positions_by_symbol["2330"]["pnl"] == 80.0
    assert positions_by_symbol["2454"]["pnl"] == 50.0
    assert positions_by_symbol["2330"]["entryTs"] == 1
    assert positions_by_symbol["2330"]["trailStopPrice"] == 0.0
    assert positions_by_symbol["2454"]["targetPrice"] == 180.0


def test_trade_record_decision_report_serializes_payload() -> None:
    record = TradeRecord(
        symbol="2330",
        action="SELL",
        price=105.0,
        shares=10,
        reason="TAKE_PROFIT",
        pnl=50.4,
        ts=99,
        gross_pnl=51.6,
        decision_report=_SerializableDecisionReport({"decisionType": "sell", "confidence": 88}),
    )

    snapshot = PositionBook(trade_history=[record]).build_snapshot({}, session_id="sess-2")

    assert snapshot["recentTrades"][0]["decisionReport"] == {"decisionType": "sell", "confidence": 88}
    assert snapshot["recentTrades"][0]["netPnl"] == 50.0
    assert snapshot["recentTrades"][0]["grossPnl"] == 52.0
