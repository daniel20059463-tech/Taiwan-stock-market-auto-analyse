from __future__ import annotations

import datetime
import json
import os
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable

from market_calendar import load_known_open_trading_dates
from sector_rotation_signal_cache import SectorSignalCache

_TZ_TW = datetime.timezone(datetime.timedelta(hours=8))
_DEFAULT_CAPITAL = 1_000_000.0
_ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SECTOR_SIGNAL_PATH = os.path.join(_ROOT, "data", "sector_rotation_signals.json")


@dataclass(frozen=True)
class FormalSimulationPreflightResult:
    ok: bool
    errors: list[str]
    account_capital: float
    use_mock: bool
    latest_sector_trade_date: str | None
    expected_sector_trade_date: str | None
    telegram_ok: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resolve_account_capital(env: dict[str, str] | None = None) -> float:
    values = env or os.environ
    raw = str(values.get("ACCOUNT_CAPITAL", "")).strip()
    return float(raw) if raw else _DEFAULT_CAPITAL


def expected_previous_open_trade_date(
    *,
    now: datetime.datetime | None = None,
    known_open_dates: set[str] | frozenset[str] | None = None,
) -> str | None:
    target = now or datetime.datetime.now(tz=_TZ_TW)
    current_date = target.date().isoformat()
    if known_open_dates is None:
        dates = set(load_known_open_trading_dates(target.year))
        dates.update(load_known_open_trading_dates(target.year - 1))
    else:
        dates = set(known_open_dates)
    ordered = sorted(date for date in dates if date <= current_date)
    if not ordered:
        return None
    if current_date in dates:
        return ordered[-2] if len(ordered) >= 2 else None
    return ordered[-1]


def validate_telegram_credentials(
    *,
    bot_token: str,
    chat_id: str,
    timeout_seconds: float = 10.0,
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not bot_token:
        errors.append("telegram_bot_token_missing")
    if not chat_id:
        errors.append("telegram_chat_id_missing")
    if errors:
        return False, errors

    for method, payload in (
        ("getMe", {}),
        ("getChat", {"chat_id": chat_id}),
    ):
        request = urllib.request.Request(
            url=f"https://api.telegram.org/bot{bot_token}/{method}",
            method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # pragma: no cover - covered through injected failures
            errors.append(f"telegram_{method}_failed:{exc}")
            continue
        if not body.get("ok"):
            errors.append(f"telegram_{method}_rejected:{body.get('description', 'unknown_error')}")
    return not errors, errors


def run_formal_simulation_preflight(
    *,
    env: dict[str, str] | None = None,
    now: datetime.datetime | None = None,
    sector_signal_path: str = DEFAULT_SECTOR_SIGNAL_PATH,
    known_open_dates: set[str] | frozenset[str] | None = None,
    telegram_validator: Callable[..., tuple[bool, list[str]]] = validate_telegram_credentials,
) -> FormalSimulationPreflightResult:
    values = env or os.environ
    errors: list[str] = []

    use_mock = str(values.get("SINOPAC_MOCK", "false")).strip().lower() == "true"
    if use_mock:
        errors.append("sinopac_mock_enabled")

    account_capital = resolve_account_capital(values)
    if account_capital != _DEFAULT_CAPITAL:
        errors.append(f"account_capital_mismatch:{account_capital:,.2f}")

    cache = SectorSignalCache()
    cache.load(sector_signal_path)
    latest_sector_trade_date = cache.latest_trade_date()
    expected_sector_trade_date = expected_previous_open_trade_date(now=now, known_open_dates=known_open_dates)
    if latest_sector_trade_date is None:
        errors.append("sector_signal_cache_missing")
    elif expected_sector_trade_date and latest_sector_trade_date < expected_sector_trade_date:
        errors.append(
            f"sector_signal_cache_stale:latest={latest_sector_trade_date}:expected={expected_sector_trade_date}"
        )

    telegram_ok, telegram_errors = telegram_validator(
        bot_token=str(values.get("TELEGRAM_BOT_TOKEN", "")).strip(),
        chat_id=str(values.get("TELEGRAM_CHAT_ID", "")).strip(),
    )
    errors.extend(telegram_errors)

    return FormalSimulationPreflightResult(
        ok=not errors,
        errors=errors,
        account_capital=account_capital,
        use_mock=use_mock,
        latest_sector_trade_date=latest_sector_trade_date,
        expected_sector_trade_date=expected_sector_trade_date,
        telegram_ok=telegram_ok,
    )
