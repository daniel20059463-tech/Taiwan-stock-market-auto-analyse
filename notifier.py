from __future__ import annotations

import heapq
import itertools
import logging
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Iterable, Mapping

logger = logging.getLogger(__name__)


MAX_TELEGRAM_MESSAGE_LENGTH = 4096
PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2}


@dataclass(slots=True)
class WebhookResponse:
    status_code: int
    accepted: bool
    queued: bool
    duplicate: bool = False
    reason: str = "ok"


@dataclass(slots=True)
class EmergencyCloseRequest:
    update_id: int
    chat_id: int
    user_id: int
    command_text: str
    requested_at: float
    expires_at: float
    status: str = "requested"


@dataclass(slots=True)
class TradingCommandRequest:
    """
    代表從 Telegram 收到的 /buy 或 /sell 指令。

    action   : "buy" | "sell"
    symbol   : 股票代號，例如 "2330"
    quantity : 股數（張數 × 1000，或直接輸入股數）
    """
    update_id: int
    chat_id: int
    user_id: int
    action: str
    symbol: str
    quantity: int
    raw_text: str
    requested_at: float


@dataclass(slots=True)
class Notification:
    chat_id: int
    priority: str
    category: str
    text: str
    created_at: float


@dataclass(slots=True)
class DeliveryRecord:
    chat_id: int
    priority: str
    text: str
    sent_at: float
    notification_count: int
    degraded: bool


class TelegramRateLimitError(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"telegram rate limited, retry after {retry_after}s")
        self.retry_after = float(retry_after)


class TokenBucket:
    def __init__(self, *, capacity: int, refill_rate: float, clock: Callable[[], float]) -> None:
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._clock = clock
        self._tokens = float(capacity)
        self._last_refill = clock()

    def consume(self, tokens: float = 1.0) -> bool:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now
        if self._tokens < tokens:
            return False
        self._tokens -= tokens
        return True


class NotifierService:
    def __init__(
        self,
        *,
        telegram_sender: Callable[..., Any],
        secret_token: str,
        allowed_chat_ids: Iterable[int] | None = None,
        allowed_user_ids: Iterable[int] | None = None,
        clock: Callable[[], float] | None = None,
        command_ttl_seconds: float = 30.0,
        dedupe_ttl_seconds: float = 300.0,
        batch_window_seconds: float = 3.0,
        per_chat_bucket_capacity: int = 4,
        per_chat_bucket_refill_rate: float = 2.0,
        global_max_inflight: int = 2,
    ) -> None:
        self.telegram_sender = telegram_sender
        self.secret_token = secret_token
        self.allowed_chat_ids = {int(chat_id) for chat_id in (allowed_chat_ids or [])}
        self.allowed_user_ids = {int(user_id) for user_id in (allowed_user_ids or [])}
        self.clock = clock or time.time
        self.command_ttl_seconds = command_ttl_seconds
        self.dedupe_ttl_seconds = dedupe_ttl_seconds
        self.batch_window_seconds = batch_window_seconds
        self.per_chat_bucket_capacity = per_chat_bucket_capacity
        self.per_chat_bucket_refill_rate = per_chat_bucket_refill_rate
        self.global_semaphore = threading.BoundedSemaphore(global_max_inflight)

        self.inbound_payload_queue: Deque[dict[str, Any]] = deque()
        self.request_queue: Deque[EmergencyCloseRequest] = deque()
        self.trading_command_queue: Deque[TradingCommandRequest] = deque()
        self._seen_update_ids: dict[int, float] = {}
        self._pending_notifications: list[tuple[int, float, int, Notification]] = []
        self._sequence = itertools.count()
        self._chat_buckets: dict[int, TokenBucket] = {}

        self.degraded_until: float = 0.0
        self.sent_records: list[DeliveryRecord] = []
        self.inbound_processing_delay_seconds: float = 0.0

    def handle_webhook(self, headers: Mapping[str, str], payload: Mapping[str, Any]) -> WebhookResponse:
        secret = headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != self.secret_token:
            return WebhookResponse(status_code=403, accepted=False, queued=False, reason="invalid_secret")

        update_id = payload.get("update_id")
        if not isinstance(update_id, int):
            return WebhookResponse(status_code=400, accepted=False, queued=False, reason="invalid_update_id")

        self._cleanup_seen_updates()
        if update_id in self._seen_update_ids:
            return WebhookResponse(
                status_code=200,
                accepted=False,
                queued=False,
                duplicate=True,
                reason="duplicate_update",
            )

        self._seen_update_ids[update_id] = self.clock() + self.dedupe_ttl_seconds
        self.inbound_payload_queue.append(dict(payload))
        return WebhookResponse(status_code=200, accepted=True, queued=True)

    def drain_inbound_requests(self, *, max_items: int | None = None) -> list[EmergencyCloseRequest]:
        produced: list[EmergencyCloseRequest] = []
        processed = 0
        while self.inbound_payload_queue and (max_items is None or processed < max_items):
            raw_payload = self.inbound_payload_queue.popleft()
            if self.inbound_processing_delay_seconds:
                time.sleep(self.inbound_processing_delay_seconds)

            # 優先嘗試緊急平倉指令。
            emergency = self._build_request(raw_payload)
            if emergency is not None:
                self.request_queue.append(emergency)
                produced.append(emergency)
                processed += 1
                continue

            # 嘗試交易指令（/buy / /sell）。
            trade = self._try_parse_trading_command(raw_payload)
            if trade is not None:
                self.trading_command_queue.append(trade)
                self._ack_trading_command(trade)
            processed += 1

        return produced

    def drain_trading_commands(self, *, max_items: int | None = None) -> list[TradingCommandRequest]:
        """取出所有待處理的交易委託指令（由 AppSupervisor / Analyzer 消費）。"""
        result: list[TradingCommandRequest] = []
        while self.trading_command_queue and (max_items is None or len(result) < max_items):
            result.append(self.trading_command_queue.popleft())
        return result

    def enqueue_notification(self, *, chat_id: int, priority: str, category: str, text: str) -> None:
        if priority not in PRIORITY_RANK:
            raise ValueError(f"unknown priority {priority!r}")

        notification = Notification(
            chat_id=chat_id,
            priority=priority,
            category=category,
            text=text,
            created_at=self.clock(),
        )
        heapq.heappush(
            self._pending_notifications,
            (PRIORITY_RANK[priority], notification.created_at, next(self._sequence), notification),
        )

    def pump(self, *, force: bool = False) -> list[DeliveryRecord]:
        deliveries: list[DeliveryRecord] = []
        while True:
            batch, degraded = self._next_batch(force=force)
            if not batch:
                break

            record = self._deliver_batch(batch, degraded=degraded)
            if record is None:
                self._requeue_notifications(batch)
                break
            deliveries.append(record)

        return deliveries

    def _build_request(self, payload: Mapping[str, Any]) -> EmergencyCloseRequest | None:
        message = payload.get("message")
        if not isinstance(message, Mapping):
            return None

        command_text = str(message.get("text", "")).strip()
        if not command_text.startswith("/emergency_close"):
            return None

        command_ts = float(message.get("date", 0))
        now = self.clock()
        if now - command_ts > self.command_ttl_seconds:
            return None

        chat = message.get("chat") if isinstance(message.get("chat"), Mapping) else {}
        sender = message.get("from") if isinstance(message.get("from"), Mapping) else {}
        chat_id = int(chat.get("id", 0))
        user_id = int(sender.get("id", 0))
        if not self._is_authorized(chat_id=chat_id, user_id=user_id):
            return None
        return EmergencyCloseRequest(
            update_id=int(payload["update_id"]),
            chat_id=chat_id,
            user_id=user_id,
            command_text=command_text,
            requested_at=now,
            expires_at=command_ts + self.command_ttl_seconds,
        )

    def _try_parse_trading_command(self, payload: Mapping[str, Any]) -> TradingCommandRequest | None:
        """
        解析 /buy SYMBOL QUANTITY 或 /sell SYMBOL QUANTITY 指令。

        格式：
            /buy 2330 1000   → 買入 2330，1000 股
            /sell 2317 500   → 賣出 2317，500 股
            /buy 2454 1      → 買入 2454，1 股（小數單位）

        指令逾期（超過 command_ttl_seconds）一律拒絕，防止 Telegram 重送舊訊息。
        """
        message = payload.get("message")
        if not isinstance(message, Mapping):
            return None

        text = str(message.get("text", "")).strip()
        parts = text.split()
        if len(parts) < 3:
            return None

        # 支援 /buy@botname 格式
        base_command = parts[0].lower().split("@")[0]
        if base_command not in ("/buy", "/sell"):
            return None

        symbol = parts[1].upper()
        try:
            quantity = int(parts[2])
        except ValueError:
            return None
        if quantity <= 0:
            return None

        command_ts = float(message.get("date", 0))
        now = self.clock()
        if now - command_ts > self.command_ttl_seconds:
            return None

        chat = message.get("chat") if isinstance(message.get("chat"), Mapping) else {}
        sender = message.get("from") if isinstance(message.get("from"), Mapping) else {}
        chat_id = int(chat.get("id", 0))
        user_id = int(sender.get("id", 0))
        if not self._is_authorized(chat_id=chat_id, user_id=user_id):
            return None

        return TradingCommandRequest(
            update_id=int(payload["update_id"]),
            chat_id=chat_id,
            user_id=user_id,
            action=base_command[1:],  # "buy" | "sell"
            symbol=symbol,
            quantity=quantity,
            raw_text=text,
            requested_at=now,
        )

    def _is_authorized(self, *, chat_id: int, user_id: int) -> bool:
        if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
            return False
        if self.allowed_user_ids and user_id not in self.allowed_user_ids:
            return False
        return True

    def _ack_trading_command(self, cmd: TradingCommandRequest) -> None:
        """收到交易指令後立即回覆 Telegram 確認訊息。"""
        action_label = "買入" if cmd.action == "buy" else "賣出"
        action_emoji = "📈" if cmd.action == "buy" else "📉"
        text = (
            f"{action_emoji} *{action_label}委託已收到*\n"
            f"股票代號：`{cmd.symbol}`\n"
            f"數量：`{cmd.quantity:,}` 股\n"
            f"狀態：⏳ 待執行（尚未下單）"
        )
        try:
            self.telegram_sender(chat_id=cmd.chat_id, text=text, parse_mode="Markdown")
        except Exception as exc:
            logger.warning("Failed to ack trading command %s: %s", cmd.raw_text, exc)

    def _cleanup_seen_updates(self) -> None:
        now = self.clock()
        expired = [update_id for update_id, expiry in self._seen_update_ids.items() if expiry <= now]
        for update_id in expired:
            self._seen_update_ids.pop(update_id, None)

    def _next_batch(self, *, force: bool) -> tuple[list[Notification], bool]:
        if not self._pending_notifications:
            return [], False

        now = self.clock()
        if now < self.degraded_until:
            return [], False

        ready: list[tuple[int, float, int, Notification]] = []
        deferred: list[tuple[int, float, int, Notification]] = []
        draining_degraded_summary = self.degraded_until > 0.0 and now >= self.degraded_until

        while self._pending_notifications:
            item = heapq.heappop(self._pending_notifications)
            _, created_at, _, notification = item
            if draining_degraded_summary or force or created_at + self.batch_window_seconds <= now:
                ready.append(item)
            else:
                deferred.append(item)

        for item in deferred:
            heapq.heappush(self._pending_notifications, item)

        if not ready:
            return [], False

        if draining_degraded_summary:
            self.degraded_until = 0.0
            return [item[3] for item in ready], True

        first = ready[0][3]
        selected: list[Notification] = []
        remainder: list[tuple[int, float, int, Notification]] = []
        for item in ready:
            notification = item[3]
            if (
                notification.chat_id == first.chat_id
                and notification.priority == first.priority
                and notification.category == first.category
            ):
                selected.append(notification)
            else:
                remainder.append(item)

        for item in remainder:
            heapq.heappush(self._pending_notifications, item)

        return selected, False

    def _deliver_batch(self, batch: Iterable[Notification], *, degraded: bool) -> DeliveryRecord | None:
        notifications = list(batch)
        if not notifications:
            return None

        chat_id = notifications[0].chat_id
        if not self._chat_bucket(chat_id).consume():
            return None

        if not self.global_semaphore.acquire(blocking=False):
            return None

        try:
            text = self._build_message(notifications, degraded=degraded)
            try:
                self.telegram_sender(chat_id=chat_id, text=text, parse_mode="Markdown")
            except TelegramRateLimitError as exc:
                self.degraded_until = max(self.degraded_until, self.clock() + exc.retry_after)
                return None

            record = DeliveryRecord(
                chat_id=chat_id,
                priority=notifications[0].priority,
                text=text,
                sent_at=self.clock(),
                notification_count=len(notifications),
                degraded=degraded,
            )
            self.sent_records.append(record)
            return record
        finally:
            self.global_semaphore.release()

    def _chat_bucket(self, chat_id: int) -> TokenBucket:
        bucket = self._chat_buckets.get(chat_id)
        if bucket is None:
            bucket = TokenBucket(
                capacity=self.per_chat_bucket_capacity,
                refill_rate=self.per_chat_bucket_refill_rate,
                clock=self.clock,
            )
            self._chat_buckets[chat_id] = bucket
        return bucket

    def _requeue_notifications(self, notifications: Iterable[Notification]) -> None:
        for notification in notifications:
            heapq.heappush(
                self._pending_notifications,
                (PRIORITY_RANK[notification.priority], notification.created_at, next(self._sequence), notification),
            )

    def _build_message(self, notifications: list[Notification], *, degraded: bool) -> str:
        if degraded:
            return self._build_degraded_summary(notifications)
        return self._build_priority_summary(notifications)

    def _build_priority_summary(self, notifications: list[Notification]) -> str:
        priority = notifications[0].priority
        category = notifications[0].category
        counts = Counter(notification.text for notification in notifications)
        header = f"*{priority} Summary* `{category}` x{len(notifications)}"
        lines = [
            f"- {text}" if count == 1 else f"- {text} x{count}"
            for text, count in counts.items()
        ]
        return self._truncate_message([header, *lines])

    def _build_degraded_summary(self, notifications: list[Notification]) -> str:
        counts = Counter((notification.priority, notification.category) for notification in notifications)
        header = f"*Degraded Summary* buffered={len(notifications)}"
        lines = [
            f"- {priority} `{category}` x{count}"
            for (priority, category), count in sorted(counts.items(), key=lambda item: (PRIORITY_RANK[item[0][0]], item[0][1]))
        ]
        sample_texts = Counter(notification.text for notification in notifications)
        for text, count in sample_texts.most_common(5):
            lines.append(f"- sample: {text}" if count == 1 else f"- sample: {text} x{count}")
        return self._truncate_message([header, *lines])

    def _truncate_message(self, lines: list[str]) -> str:
        if not lines:
            return ""

        message = lines[0]
        omitted = 0
        for line in lines[1:]:
            candidate = f"{message}\n{line}"
            if len(candidate) <= MAX_TELEGRAM_MESSAGE_LENGTH:
                message = candidate
            else:
                omitted += 1

        if omitted == 0:
            return message

        suffix = f"\n- ... truncated {omitted} line(s)"
        if len(message) + len(suffix) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            return message + suffix

        hard_limit = MAX_TELEGRAM_MESSAGE_LENGTH - len(suffix)
        return message[:hard_limit] + suffix


__all__ = [
    "DeliveryRecord",
    "EmergencyCloseRequest",
    "MAX_TELEGRAM_MESSAGE_LENGTH",
    "Notification",
    "NotifierService",
    "PRIORITY_RANK",
    "TelegramRateLimitError",
    "TokenBucket",
    "TradingCommandRequest",
    "WebhookResponse",
]
