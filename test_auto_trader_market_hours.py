from __future__ import annotations

import datetime

from auto_trader import _TZ_TW, _is_eod_close_time, _is_trading_hours


def _tw_ts(hour: int, minute: int) -> int:
    dt = datetime.datetime(2026, 4, 20, hour, minute, tzinfo=_TZ_TW)
    return int(dt.timestamp() * 1000)


def test_trading_hours_match_twse_regular_session() -> None:
    assert _is_trading_hours(_tw_ts(8, 59)) is False
    assert _is_trading_hours(_tw_ts(9, 0)) is True
    assert _is_trading_hours(_tw_ts(13, 30)) is True
    assert _is_trading_hours(_tw_ts(13, 31)) is False


def test_eod_close_window_starts_at_1325_tw() -> None:
    assert _is_eod_close_time(_tw_ts(13, 24)) is False
    assert _is_eod_close_time(_tw_ts(13, 25)) is True
    assert _is_eod_close_time(_tw_ts(13, 30)) is True


def test_trading_hours_are_false_on_confirmed_holiday_even_during_session() -> None:
    holiday = datetime.datetime(2026, 6, 19, 10, 0, tzinfo=_TZ_TW)
    assert _is_trading_hours(int(holiday.timestamp() * 1000)) is False
