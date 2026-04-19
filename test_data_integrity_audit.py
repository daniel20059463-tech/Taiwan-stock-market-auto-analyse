from __future__ import annotations

import importlib


def test_audit_quote_snapshot_flags_change_pct_mismatch() -> None:
    audit = importlib.import_module("data_integrity_audit")

    snapshot = {
        "symbol": "2330",
        "price": 105.0,
        "previousClose": 100.0,
        "changePct": 0.0,
        "volume": 12000,
        "inTradingHours": True,
        "source": "sinopac",
    }

    issues = audit.audit_quote_snapshot(snapshot)

    assert "CHANGE_PCT_MISMATCH" in issues


def test_audit_quote_snapshot_flags_seed_volume_in_live_mode() -> None:
    audit = importlib.import_module("data_integrity_audit")

    snapshot = {
        "symbol": "1101",
        "price": 25.25,
        "previousClose": 25.10,
        "changePct": 0.60,
        "volume": 117,
        "inTradingHours": True,
        "source": "sinopac",
    }

    issues = audit.audit_quote_snapshot(snapshot)

    assert "SUSPICIOUS_LIVE_VOLUME" in issues


def test_audit_quote_snapshot_flags_non_flat_price_with_zero_change() -> None:
    audit = importlib.import_module("data_integrity_audit")

    snapshot = {
        "symbol": "2454",
        "price": 1280.0,
        "previousClose": 1270.0,
        "change": 0.0,
        "changePct": 0.79,
        "volume": 5200,
        "inTradingHours": True,
        "source": "sinopac",
    }

    issues = audit.audit_quote_snapshot(snapshot)

    assert "CHANGE_VALUE_MISMATCH" in issues


def test_audit_quote_snapshot_allows_flat_preopen_snapshot() -> None:
    audit = importlib.import_module("data_integrity_audit")

    snapshot = {
        "symbol": "2330",
        "price": 920.0,
        "previousClose": 920.0,
        "change": 0.0,
        "changePct": 0.0,
        "volume": 0,
        "inTradingHours": False,
        "source": "fallback",
    }

    issues = audit.audit_quote_snapshot(snapshot)

    assert issues == []
