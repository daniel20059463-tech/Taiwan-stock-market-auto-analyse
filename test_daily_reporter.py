from __future__ import annotations

from daily_reporter import DailyReporter


def _sample_day_payload() -> dict:
    return {
        "date": "2026-04-04",
        "tradeCount": 4,
        "winRate": 50.0,
        "realizedPnl": 12345.0,
        "unrealizedPnl": 0.0,
        "totalPnl": 12345.0,
        "riskStatus": {
            "isHalted": False,
            "isWeeklyHalted": False,
        },
        "trades": [
            {
                "symbol": "2330",
                "action": "SELL",
                "price": 1010.0,
                "netPnl": 8450.0,
                "reason": "TAKE_PROFIT",
                "decisionReport": {
                    "summary": "新聞與技術面同向，先以小部位搶快進場。",
                    "finalReason": "take_profit",
                    "confidence": 81,
                    "bullCase": "多方觀點：量價同步放大。",
                    "bearCase": "空方觀點：高檔追價仍有震盪風險。",
                    "riskCase": "風控觀點：停損距離不宜放寬。",
                    "bullArgument": "多方論點：新聞催化仍在發酵，買盤承接穩定。",
                    "bearArgument": "空方論點：若量縮則容易快速回吐。",
                    "refereeVerdict": "裁決結論：多方證據較完整，可接受小部位搶快。",
                    "debateWinner": "bull",
                },
            },
            {
                "symbol": "2454",
                "action": "SELL",
                "price": 1280.0,
                "netPnl": -5200.0,
                "reason": "STOP_LOSS",
                "decisionReport": {
                    "summary": "輿情偏弱但仍嘗試進場，最終被停損出場。",
                    "finalReason": "stop_loss",
                    "confidence": 54,
                    "bullCase": "多方觀點：技術面短線有止穩跡象。",
                    "bearCase": "空方觀點：輿情與大盤環境都不夠支持。",
                    "riskCase": "風控觀點：應更早降低部位。",
                    "bullArgument": "多方論點：技術面曾出現短線止穩訊號。",
                    "bearArgument": "空方論點：進場依據不足，風險大於報酬。",
                    "refereeVerdict": "裁決結論：空方顧慮偏多，這筆交易不夠理想。",
                    "debateWinner": "bear",
                },
            },
        ],
    }


def test_daily_reporter_generates_llm_report_from_top_trades() -> None:
    sent: list[tuple[int, str, str]] = []

    def fake_sender(*, chat_id: int, text: str, parse_mode: str) -> None:
        sent.append((chat_id, text, parse_mode))

    class FakeLLM:
        def summarize_trade(self, payload: dict) -> str:
            return f"單筆檢討：{payload['symbol']} {payload['decision_report']['finalReason']}"

        def summarize_day(self, payload: dict) -> str:
            assert payload["highlights"]
            return "盤後日報：今日整體執行穩定，最佳交易由台積電貢獻。"

    reporter = DailyReporter(chat_id=123, telegram_sender=fake_sender, llm_client=FakeLLM())
    result = reporter.build_and_send(day_payload=_sample_day_payload())

    assert "盤後日報" in result.text
    assert "單筆檢討：2330 take_profit" in result.text
    assert sent
    assert sent[0][0] == 123
    assert sent[0][2] == "Markdown"


def test_daily_reporter_falls_back_to_template_when_llm_fails() -> None:
    sent: list[str] = []

    def fake_sender(*, chat_id: int, text: str, parse_mode: str) -> None:
        sent.append(text)

    class FailingLLM:
        def summarize_trade(self, payload: dict) -> str:
            raise RuntimeError("llm down")

        def summarize_day(self, payload: dict) -> str:
            raise RuntimeError("llm down")

    reporter = DailyReporter(chat_id=321, telegram_sender=fake_sender, llm_client=FailingLLM())
    result = reporter.build_and_send(day_payload=_sample_day_payload())

    assert "盤後日報" in result.text
    assert "模板摘要" in result.text
    assert "今日總交易數" in result.text
    assert sent


def test_daily_reporter_respects_telegram_length_limit() -> None:
    sent: list[str] = []

    def fake_sender(*, chat_id: int, text: str, parse_mode: str) -> None:
        sent.append(text)

    class VerboseLLM:
        def summarize_trade(self, payload: dict) -> str:
            return "單筆檢討：" + ("很長的說明" * 300)

        def summarize_day(self, payload: dict) -> str:
            return "盤後日報：" + ("整體摘要" * 1000)

    reporter = DailyReporter(chat_id=999, telegram_sender=fake_sender, llm_client=VerboseLLM())
    result = reporter.build_and_send(day_payload=_sample_day_payload())

    assert len(result.text) <= 4096
    assert sent
    assert len(sent[0]) <= 4096
