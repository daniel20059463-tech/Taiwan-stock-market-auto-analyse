from __future__ import annotations

from typing import Any


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def audit_quote_snapshot(snapshot: dict) -> list[str]:
    issues: list[str] = []

    price = _as_float(snapshot.get("price"))
    if price is None:
        price = _as_float(snapshot.get("last"))
    previous_close = _as_float(snapshot.get("previousClose"))
    change = _as_float(snapshot.get("change"))
    change_pct = _as_float(snapshot.get("changePct"))
    volume = _as_float(snapshot.get("volume"))
    in_trading_hours = _as_bool(snapshot.get("inTradingHours"))
    source = str(snapshot.get("source", "")).strip().lower()

    if price is None or previous_close is None or previous_close <= 0:
        return issues

    expected_change = price - previous_close
    expected_change_pct = (expected_change / previous_close) * 100

    if change is not None and abs(change - expected_change) >= 0.01:
        issues.append("CHANGE_VALUE_MISMATCH")

    if change_pct is not None and abs(change_pct - expected_change_pct) >= 0.05:
        issues.append("CHANGE_PCT_MISMATCH")

    # During live trading we should not see the obvious seed/fallback volume
    # values that previously leaked into the UI and looked like real成交量.
    if (
        in_trading_hours is True
        and source in {"sinopac", "live", "native"}
        and volume is not None
        and volume in {117.0, 118.0}
    ):
        issues.append("SUSPICIOUS_LIVE_VOLUME")

    return issues
