from __future__ import annotations

import time
from multiprocessing.shared_memory import SharedMemory

import pytest

from analyzer import AnalyzerService, analyze_news_text, fake_nlp_analyze


def assert_shm_absent(shm_name: str) -> None:
    deadline = time.time() + 1.0
    while time.time() < deadline:
        try:
            shm = SharedMemory(name=shm_name, create=False)
        except FileNotFoundError:
            return
        else:
            shm.close()
            time.sleep(0.02)

    pytest.fail(f"shared memory {shm_name!r} was not reclaimed")


def test_ttl_discard_does_not_run_nlp() -> None:
    service = AnalyzerService(num_workers=1)
    service.start()

    try:
        start = time.perf_counter()
        meta = service.publish_with_deadline(
            "expired-before-enqueue",
            "this article must be rejected at ingress",
            deadline_ts=time.time() - 1.0,
        )
        elapsed = time.perf_counter() - start

        assert meta is None
        assert elapsed < 0.1
        assert service.get_result(timeout=0.2) is None
    finally:
        service.stop()

    service = AnalyzerService(num_workers=1)
    service.start()

    try:
        meta = service.publish("expires-in-worker", "stale news", ttl_seconds=0.02)
        assert meta is not None

        time.sleep(0.08)
        start = time.perf_counter()
        result = service.get_result(timeout=2.0)
        elapsed = time.perf_counter() - start

        assert result is not None
        assert result.article_id == "expires-in-worker"
        assert result.status == "expired_in_worker"
        assert result.nlp_executed is False
        assert elapsed < 0.2
        assert result.shm_closed is True
        assert result.shm_unlinked is True
        assert_shm_absent(result.shm_name)
    finally:
        service.stop()


def test_quote_loop_p99_stays_below_1ms_during_heavy_analysis() -> None:
    service = AnalyzerService(num_workers=2)
    service.start()

    try:
        payload = ("Taiwan stocks semiconductor AI server demand remains strong " * 400).strip()
        for index in range(8):
            meta = service.publish(f"heavy-{index}", payload, ttl_seconds=30.0)
            assert meta is not None

        latencies_ns: list[int] = []
        until = time.perf_counter() + 1.25
        while time.perf_counter() < until:
            start = time.perf_counter_ns()
            price = 950.0 + ((start // 17) % 97) * 0.01
            bid = price - 0.05
            ask = price + 0.05
            spread = ask - bid
            _ = (price, bid, ask, spread)
            latencies_ns.append(time.perf_counter_ns() - start)

        results = [service.get_result(timeout=10.0) for _ in range(8)]
        assert all(result is not None for result in results)
        assert all(result.status == "processed" for result in results if result is not None)

        samples_ms = sorted(latency / 1_000_000 for latency in latencies_ns)
        p99 = samples_ms[min(len(samples_ms) - 1, int(len(samples_ms) * 0.99))]
        assert p99 < 1.0, f"quote loop p99 latency was {p99:.6f}ms"
    finally:
        service.stop()


def test_shared_memory_is_reclaimed_after_process_or_discard() -> None:
    service = AnalyzerService(num_workers=1)
    service.start()

    try:
        normal_meta = service.publish("normal-path", "bullish earnings beat", ttl_seconds=10.0)
        assert normal_meta is not None
        normal_result = service.get_result(timeout=5.0)
        assert normal_result is not None
        assert normal_result.status == "processed"
        assert normal_result.nlp_executed is True
        assert normal_result.shm_closed is True
        assert normal_result.shm_unlinked is True
        assert_shm_absent(normal_result.shm_name)

        blocker_meta = service.publish(
            "blocker",
            ("queue blocker for worker stage two expiry " * 300).strip(),
            ttl_seconds=10.0,
        )
        assert blocker_meta is not None

        expired_meta = service.publish("expired-path", "late macro data", ttl_seconds=0.05)
        assert expired_meta is not None
        blocker_result = service.get_result(timeout=5.0)
        assert blocker_result is not None
        assert blocker_result.status == "processed"

        expired_result = service.get_result(timeout=5.0)
        assert expired_result is not None
        assert expired_result.status == "expired_in_worker"
        assert expired_result.nlp_executed is False
        assert expired_result.shm_closed is True
        assert expired_result.shm_unlinked is True
        assert_shm_absent(expired_result.shm_name)
    finally:
        service.stop()


def test_analyze_news_text_keeps_backward_compatible_alias() -> None:
    text = "Taiwan semiconductor demand stays resilient through the quarter"

    canonical_score, canonical_keywords = analyze_news_text(text)
    alias_score, alias_keywords = fake_nlp_analyze(text)

    assert (canonical_score, canonical_keywords) == (alias_score, alias_keywords)
