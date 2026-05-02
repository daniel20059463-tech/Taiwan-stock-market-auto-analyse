"""Tests for DispositionFilter."""
from __future__ import annotations

import json
import os
import tempfile

from disposition_filter import DispositionFilter


def test_is_blocked_with_loaded_symbols() -> None:
    df = DispositionFilter(symbols={"1234", "5678"})
    assert df.is_blocked("1234") is True
    assert df.is_blocked("5678") is True
    assert df.is_blocked("2330") is False


def test_is_blocked_empty_by_default() -> None:
    df = DispositionFilter()
    assert df.is_blocked("1234") is False
    assert df.count == 0


def test_add_and_remove() -> None:
    df = DispositionFilter()
    df.add("1234")
    assert df.is_blocked("1234") is True
    df.remove("1234")
    assert df.is_blocked("1234") is False


def test_case_insensitive_matching() -> None:
    df = DispositionFilter(symbols={"abc"})
    assert df.is_blocked("ABC") is True
    assert df.is_blocked("abc") is True


def test_load_from_json_file() -> None:
    data = {
        "updated_at": "2026-04-06",
        "symbols": ["1234", "5678", "9999"],
        "notes": "test",
    }
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as file:
        json.dump(data, file)
        filepath = file.name

    try:
        disposition_filter = DispositionFilter(filepath=filepath)
        count = disposition_filter.load()
        assert count == 3
        assert disposition_filter.is_blocked("1234") is True
        assert disposition_filter.is_blocked("9999") is True
        assert disposition_filter.updated_at == "2026-04-06"
    finally:
        os.unlink(filepath)


def test_load_returns_zero_when_file_missing() -> None:
    disposition_filter = DispositionFilter(filepath="/nonexistent/path.json")
    count = disposition_filter.load()
    assert count == 0
    assert disposition_filter.is_blocked("1234") is False


def test_snapshot_returns_sorted_symbols() -> None:
    disposition_filter = DispositionFilter(symbols={"5678", "1234"})
    snapshot = disposition_filter.snapshot()
    assert snapshot["count"] == 2
    assert snapshot["symbols"] == ["1234", "5678"]
