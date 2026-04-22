from __future__ import annotations

import datetime

from market_calendar import (
    TZ_TW,
    is_known_open_trading_date,
    is_known_open_trading_datetime,
    load_known_open_trading_dates,
)


def test_known_open_trading_date_accepts_confirmed_open_day() -> None:
    assert is_known_open_trading_date("2026-04-20") is True


def test_load_known_open_trading_dates_reads_2026_year_file() -> None:
    assert "2026-04-20" in load_known_open_trading_dates(2026)


def test_known_open_trading_date_rejects_confirmed_holiday() -> None:
    assert is_known_open_trading_date("2026-06-19") is False


def test_known_open_trading_date_rejects_unknown_2027_date() -> None:
    assert is_known_open_trading_date("2027-01-05") is False


def test_load_known_open_trading_dates_reads_2027_placeholder_without_crashing() -> None:
    assert load_known_open_trading_dates(2027) == frozenset()


def test_load_known_open_trading_dates_fail_closed_when_year_file_is_absent() -> None:
    assert load_known_open_trading_dates(2028) == frozenset()


def test_known_open_trading_datetime_uses_taipei_timezone() -> None:
    dt = datetime.datetime(2026, 10, 26, 10, 0, tzinfo=TZ_TW)
    assert is_known_open_trading_datetime(dt) is False
