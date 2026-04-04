from __future__ import annotations

import time
from unittest.mock import Mock

from notifier import MAX_TELEGRAM_MESSAGE_LENGTH, NotifierService, TelegramRateLimitError


class ManualClock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.current = start

    def time(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


def build_webhook_payload(update_id: int, *, message_date: float, text: str = "/emergency_close") -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id * 10,
            "date": message_date,
            "text": text,
            "chat": {"id": 5566, "type": "private"},
            "from": {"id": 7788, "is_bot": False},
        },
    }


def test_batch_summary_and_truncation_for_50_notifications() -> None:
    clock = ManualClock()
    sender = Mock(return_value={"ok": True})
    service = NotifierService(
        telegram_sender=sender,
        secret_token="secret",
        clock=clock.time,
        batch_window_seconds=3.0,
    )

    for index in range(50):
        service.enqueue_notification(
            chat_id=1001,
            priority="P1",
            category="earnings",
            text=f"Earnings alert #{index}: revenue momentum remains strong",
        )

    clock.advance(3.1)
    deliveries = service.pump()

    assert len(deliveries) == 1
    assert sender.call_count == 1
    sent_text = sender.call_args.kwargs["text"]
    assert len(sent_text) <= MAX_TELEGRAM_MESSAGE_LENGTH
    assert "P1 Summary" in sent_text
    assert "earnings" in sent_text


def test_429_triggers_degraded_backoff_and_single_recovery_summary() -> None:
    clock = ManualClock()
    sender = Mock(side_effect=[TelegramRateLimitError(retry_after=5), {"ok": True}])
    service = NotifierService(
        telegram_sender=sender,
        secret_token="secret",
        clock=clock.time,
        batch_window_seconds=3.0,
    )

    service.enqueue_notification(chat_id=2002, priority="P1", category="risk", text="drawdown alert")
    clock.advance(3.1)
    first_deliveries = service.pump()

    assert first_deliveries == []
    assert sender.call_count == 1
    assert service.degraded_until == clock.time() + 5

    clock.advance(1.0)
    for index in range(4):
        service.enqueue_notification(
            chat_id=2002,
            priority="P1",
            category="risk",
            text=f"follow-up alert #{index}",
        )
    service.pump()
    assert sender.call_count == 1

    clock.advance(4.1)
    recovered = service.pump()

    assert len(recovered) == 1
    assert sender.call_count == 2
    recovered_text = sender.call_args.kwargs["text"]
    assert "Degraded Summary" in recovered_text
    assert "buffered=5" in recovered_text


def test_webhook_duplicate_is_ignored_and_ack_is_fast() -> None:
    clock = ManualClock()
    sender = Mock(return_value={"ok": True})
    service = NotifierService(
        telegram_sender=sender,
        secret_token="secret",
        clock=clock.time,
        batch_window_seconds=3.0,
    )
    service.inbound_processing_delay_seconds = 0.25

    headers = {"X-Telegram-Bot-Api-Secret-Token": "secret"}
    payload = build_webhook_payload(9001, message_date=clock.time())

    start = time.perf_counter()
    first = service.handle_webhook(headers, payload)
    elapsed_ms = (time.perf_counter() - start) * 1000

    second = service.handle_webhook(headers, payload)

    assert first.status_code == 200
    assert first.accepted is True
    assert first.queued is True
    assert elapsed_ms < 10.0, f"webhook ack took {elapsed_ms:.3f}ms"

    assert second.status_code == 200
    assert second.accepted is False
    assert second.duplicate is True
    assert len(service.inbound_payload_queue) == 1

    requests = service.drain_inbound_requests()
    assert len(requests) == 1
    assert requests[0].status == "requested"
    assert requests[0].command_text == "/emergency_close"
