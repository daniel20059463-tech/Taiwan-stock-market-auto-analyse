from __future__ import annotations

import datetime
import json
from functools import lru_cache
from pathlib import Path

TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
_CALENDAR_DIR = Path(__file__).resolve().parent / "data" / "market_calendar"


def _calendar_path_for_year(year: int) -> Path:
    return _CALENDAR_DIR / f"twse_open_dates_{year}.json"


@lru_cache(maxsize=8)
def load_known_open_trading_dates(year: int | None = None) -> frozenset[str]:
    target_year = year if year is not None else datetime.datetime.now(tz=TZ_TW).year
    path = _calendar_path_for_year(target_year)
    if not path.exists():
        return frozenset()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(str(item) for item in payload.get("open_dates", []))


def is_known_open_trading_date(value: datetime.date | datetime.datetime | str) -> bool:
    if isinstance(value, datetime.datetime):
        date_value = value.astimezone(TZ_TW).date()
    elif isinstance(value, datetime.date):
        date_value = value
    else:
        date_value = datetime.date.fromisoformat(value)
    return date_value.isoformat() in load_known_open_trading_dates(date_value.year)


def is_known_open_trading_datetime(value: datetime.datetime | None = None) -> bool:
    target = value or datetime.datetime.now(tz=TZ_TW)
    return is_known_open_trading_date(target)
