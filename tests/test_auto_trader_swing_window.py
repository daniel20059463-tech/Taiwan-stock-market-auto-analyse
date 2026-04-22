from __future__ import annotations

import datetime as dt

from auto_trader import _is_swing_entry_window


_TZ_TW = dt.timezone(dt.timedelta(hours=8))


def _ts_ms(year: int, month: int, day: int, hour: int, minute: int) -> int:
    return int(dt.datetime(year, month, day, hour, minute, tzinfo=_TZ_TW).timestamp() * 1000)


def test_swing_entry_window_stays_open_during_regular_session():
    assert _is_swing_entry_window(_ts_ms(2026, 4, 21, 10, 30)) is True
