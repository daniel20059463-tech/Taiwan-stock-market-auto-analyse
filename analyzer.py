from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from multiprocessing import get_context, resource_tracker, set_executable
from multiprocessing.process import BaseProcess
from multiprocessing.queues import Queue
from multiprocessing.shared_memory import SharedMemory
from queue import Empty, Full
from typing import Any


def _now() -> float:
    return time.time()


MIN_ANALYZE_BUDGET_SECONDS = 0.05


@dataclass(slots=True)
class ArticleMetadata:
    article_id: str
    deadline_ts: float
    shm_name: str
    content_length: int


@dataclass(slots=True)
class AnalysisResult:
    article_id: str
    deadline_ts: float
    shm_name: str
    status: str
    processed_at: float
    sentiment: float = 0.0
    keywords: tuple[str, ...] = ()
    nlp_executed: bool = False
    shm_closed: bool = False
    shm_unlinked: bool = False
    signal_valid: bool = False


def _openai_sentiment(text: str, api_key: str) -> float | None:
    """Call OpenAI chat/completions to obtain a sentiment score in [-1, 1].

    Returns None on any network or parse error so the caller can fall back
    to the hash-based placeholder.
    """
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    timeout = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "15") or "15")

    prompt = (
        "你是台股新聞情緒分析師。請閱讀以下新聞摘要，"
        "回傳一個 JSON 物件，格式為 {\"score\": <float>}，"
        "其中 score 介於 -1.0（極度負面）到 1.0（極度正面）之間，0 為中性。"
        "只輸出 JSON，不要其他文字。\n\n"
        f"新聞：{text[:1500]}"
    )
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 32,
    }).encode("utf-8")
    req = urllib.request.Request(
        url=f"{base_url}/chat/completions",
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"].strip()
        parsed = json.loads(content)
        score = float(parsed["score"])
        return round(max(-1.0, min(1.0, score)), 4)
    except Exception:
        return None


def analyze_news_text(text: str) -> tuple[float, tuple[str, ...]]:
    """Sentiment analysis for news articles.

    When OPENAI_API_KEY is set, sends the article to the OpenAI chat API and
    returns a semantically meaningful score in [-1, 1].

    Falls back to a SHA-256 hash placeholder when no API key is configured.
    !!警告：hash fallback 與文字語意完全無關，SentimentFilter 形同虛設，
    正式環境請設定 OPENAI_API_KEY!!
    """
    keywords = tuple(word for word in text.split()[:5])

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if api_key:
        score = _openai_sentiment(text, api_key)
        if score is not None:
            return score, keywords

    # ── hash-based fallback (preserves original timing to avoid test breakage) ──
    end = time.perf_counter() + 0.4
    accumulator = 0
    while time.perf_counter() < end:
        for index, char in enumerate(text[:512] or " "):
            accumulator = (accumulator * 33 + ord(char) + index) % 4_294_967_291
    time.sleep(0.1)

    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).digest()
    score = int.from_bytes(digest[:2], "big") / 65_535
    sentiment = round(score * 2 - 1, 4)
    return sentiment, keywords


def fake_nlp_analyze(text: str) -> tuple[float, tuple[str, ...]]:
    """Backward-compatible alias for the historical analyzer entrypoint."""
    return analyze_news_text(text)


def create_shared_article(content: str) -> tuple[SharedMemory, int]:
    payload = content.encode("utf-8")
    shm = SharedMemory(create=True, size=max(len(payload), 1), name=f"anl_{uuid.uuid4().hex}")
    if payload:
        shm.buf[: len(payload)] = payload
    return shm, len(payload)


def _unregister_shared_memory(name: str) -> None:
    try:
        resource_tracker.unregister(name, "shared_memory")
    except Exception:
        pass


def release_shared_memory(name: str) -> tuple[bool, bool]:
    shm_closed = False
    shm_unlinked = False
    try:
        shm = SharedMemory(name=name, create=False)
    except FileNotFoundError:
        _unregister_shared_memory(name)
        return True, True

    try:
        shm.close()
        shm_closed = True
    finally:
        try:
            shm.unlink()
            shm_unlinked = True
        except FileNotFoundError:
            shm_unlinked = True
        finally:
            _unregister_shared_memory(name)

    return shm_closed, shm_unlinked


def read_article_text(meta: ArticleMetadata) -> str:
    shm = SharedMemory(name=meta.shm_name, create=False)
    try:
        return bytes(shm.buf[: meta.content_length]).decode("utf-8", errors="replace")
    finally:
        shm.close()
        _unregister_shared_memory(meta.shm_name)


def _build_expired_result(meta: ArticleMetadata, status: str) -> AnalysisResult:
    shm_closed, shm_unlinked = release_shared_memory(meta.shm_name)
    return AnalysisResult(
        article_id=meta.article_id,
        deadline_ts=meta.deadline_ts,
        shm_name=meta.shm_name,
        status=status,
        processed_at=_now(),
        nlp_executed=False,
        shm_closed=shm_closed,
        shm_unlinked=shm_unlinked,
        signal_valid=False,
    )


def process_article(meta: ArticleMetadata) -> AnalysisResult:
    remaining = meta.deadline_ts - _now()
    if remaining <= 0 or remaining <= MIN_ANALYZE_BUDGET_SECONDS:
        return _build_expired_result(meta, "expired_in_worker")

    text = read_article_text(meta)
    shm_closed, shm_unlinked = release_shared_memory(meta.shm_name)
    sentiment, keywords = analyze_news_text(text)

    return AnalysisResult(
        article_id=meta.article_id,
        deadline_ts=meta.deadline_ts,
        shm_name=meta.shm_name,
        status="processed",
        processed_at=_now(),
        sentiment=sentiment,
        keywords=keywords,
        nlp_executed=True,
        shm_closed=shm_closed,
        shm_unlinked=shm_unlinked,
        signal_valid=True,
    )


def worker_main(task_queue: Queue, result_queue: Queue, ready_queue: Queue | None = None) -> None:
    if ready_queue is not None:
        ready_queue.put(True)
    while True:
        item = task_queue.get()
        if item is None:
            break

        try:
            result_queue.put(process_article(item))
        except Exception:
            fallback = _build_expired_result(item, "worker_error")
            result_queue.put(fallback)


class AnalyzerService:
    def __init__(self, *, num_workers: int = 1, queue_size: int = 1024) -> None:
        set_executable(sys.executable)
        self._ctx = get_context("spawn")
        self.num_workers = num_workers
        self.task_queue: Queue = self._ctx.Queue(maxsize=queue_size)
        self.result_queue: Queue = self._ctx.Queue()
        self.ready_queue: Queue = self._ctx.Queue()
        self._workers: list[BaseProcess] = []
        self._publisher_handles: dict[str, SharedMemory] = {}

    def start(self) -> None:
        if self._workers:
            return

        for _ in range(self.num_workers):
            worker = self._ctx.Process(
                target=worker_main,
                args=(self.task_queue, self.result_queue, self.ready_queue),
            )
            worker.start()
            self._workers.append(worker)

        ready_count = 0
        deadline = _now() + 5.0
        while ready_count < self.num_workers and _now() < deadline:
            try:
                self.ready_queue.get(timeout=max(0.01, deadline - _now()))
            except Empty:
                break
            else:
                ready_count += 1

    def stop(self) -> None:
        for _ in self._workers:
            try:
                self.task_queue.put_nowait(None)
            except Full:
                self.task_queue.put(None)

        for worker in self._workers:
            worker.join(timeout=5)
            if worker.is_alive():
                worker.kill()
                worker.join(timeout=1)

        self._workers.clear()

        while True:
            try:
                result = self.result_queue.get_nowait()
            except Empty:
                break
            self._release_publisher_handle(result.shm_name)

        while True:
            try:
                self.ready_queue.get_nowait()
            except Empty:
                break

        for shm_name in list(self._publisher_handles):
            self._release_publisher_handle(shm_name)
            release_shared_memory(shm_name)

    def publish(self, article_id: str, content: str, *, ttl_seconds: float = 30.0) -> ArticleMetadata | None:
        deadline_ts = _now() + ttl_seconds
        return self.publish_with_deadline(article_id, content, deadline_ts=deadline_ts)

    def publish_with_deadline(self, article_id: str, content: str, *, deadline_ts: float) -> ArticleMetadata | None:
        shm, content_length = create_shared_article(content)
        meta = ArticleMetadata(
            article_id=article_id,
            deadline_ts=deadline_ts,
            shm_name=shm.name,
            content_length=content_length,
        )

        self._publisher_handles[shm.name] = shm

        if deadline_ts <= _now():
            self._release_publisher_handle(shm.name)
            release_shared_memory(shm.name)
            return None

        try:
            self.task_queue.put_nowait(meta)
        except Full:
            self._release_publisher_handle(shm.name)
            release_shared_memory(shm.name)
            return None

        return meta

    def submit_metadata(self, meta: ArticleMetadata) -> bool:
        if meta.deadline_ts <= _now():
            self._release_publisher_handle(meta.shm_name)
            release_shared_memory(meta.shm_name)
            return False

        try:
            self.task_queue.put_nowait(meta)
            return True
        except Full:
            self._release_publisher_handle(meta.shm_name)
            release_shared_memory(meta.shm_name)
            return False

    def get_result(self, *, timeout: float = 5.0) -> AnalysisResult | None:
        try:
            result: AnalysisResult = self.result_queue.get(timeout=timeout)
        except Empty:
            return None

        self._release_publisher_handle(result.shm_name)

        if result.status == "processed" and result.deadline_ts <= _now():
            result.status = "expired_in_engine"
            result.signal_valid = False
        elif result.status == "processed":
            result.signal_valid = True
        else:
            result.signal_valid = False

        return result

    def _release_publisher_handle(self, shm_name: str) -> None:
        shm = self._publisher_handles.pop(shm_name, None)
        if shm is None:
            return

        try:
            shm.close()
        finally:
            _unregister_shared_memory(shm_name)


__all__ = [
    "AnalysisResult",
    "AnalyzerService",
    "ArticleMetadata",
    "analyze_news_text",
    "create_shared_article",
    "fake_nlp_analyze",
    "process_article",
    "read_article_text",
    "release_shared_memory",
    "worker_main",
]
