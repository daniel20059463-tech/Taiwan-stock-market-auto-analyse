from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import requests


@dataclass(frozen=True)
class InstitutionalFlowRow:
    symbol: str
    name: str
    foreign_net_buy: int
    investment_trust_net_buy: int
    major_net_buy: int
    margin_net_change: int = 0
    avg_daily_volume_20d: float | None = None
    avg_daily_value_20d: float | None = None


DEFAULT_TWSE_T86_URL = "https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999"
DEFAULT_TPEX_DETAIL_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&response=json"
DEFAULT_TWSE_MARGIN_URL = "https://www.twse.com.tw/exchangeReport/MI_MARGN"


def _parse_number(text: str | int | float | None) -> int:
    if text is None:
        return 0
    if isinstance(text, (int, float)):
        return int(text)
    raw = str(text).replace(",", "").replace("\u3000", "").strip()
    if not raw:
        return 0
    return int(float(raw))


def _is_regular_stock_symbol(symbol: str) -> bool:
    return bool(re.fullmatch(r"\d{4}", symbol))


def parse_twse_t86_payload(payload: dict[str, Any]) -> list[InstitutionalFlowRow]:
    rows: list[InstitutionalFlowRow] = []
    for item in payload.get("data", []):
        if len(item) < 12:
            continue
        symbol = str(item[0]).strip()
        if not _is_regular_stock_symbol(symbol):
            continue
        rows.append(
            InstitutionalFlowRow(
                symbol=symbol,
                name=str(item[1]).strip(),
                foreign_net_buy=_parse_number(item[4]),
                investment_trust_net_buy=_parse_number(item[10]),
                major_net_buy=_parse_number(item[11]),
            )
        )
    return rows


def parse_tpex_daily_trade_payload(payload: dict[str, Any]) -> list[InstitutionalFlowRow]:
    rows: list[InstitutionalFlowRow] = []
    tables = payload.get("tables", [])
    if not tables:
        return rows
    for item in tables[0].get("data", []):
        if len(item) < 14:
            continue
        symbol = str(item[0]).strip()
        if not _is_regular_stock_symbol(symbol):
            continue
        rows.append(
            InstitutionalFlowRow(
                symbol=symbol,
                name=str(item[1]).strip(),
                foreign_net_buy=_parse_number(item[4]),
                investment_trust_net_buy=_parse_number(item[13]),
                major_net_buy=0,
            )
        )
    return rows


def parse_twse_margin_payload(payload: dict[str, Any]) -> dict[str, int]:
    """Return {symbol: margin_net_change} from MI_MARGN response."""
    margin_map: dict[str, int] = {}
    tables = payload.get("tables", [])
    if len(tables) < 2:
        return margin_map
    for item in tables[1].get("data", []):
        if len(item) < 4:
            continue
        symbol = str(item[0]).strip()
        if not _is_regular_stock_symbol(symbol):
            continue
        net = _parse_number(item[2]) - _parse_number(item[3])
        margin_map[symbol] = net
    return margin_map


def merge_margin_into_rows(
    rows: list[InstitutionalFlowRow],
    margin_map: dict[str, int],
) -> list[InstitutionalFlowRow]:
    if not margin_map:
        return rows
    return [
        InstitutionalFlowRow(
            symbol=r.symbol,
            name=r.name,
            foreign_net_buy=r.foreign_net_buy,
            investment_trust_net_buy=r.investment_trust_net_buy,
            major_net_buy=r.major_net_buy,
            margin_net_change=margin_map.get(r.symbol, 0),
            avg_daily_volume_20d=r.avg_daily_volume_20d,
            avg_daily_value_20d=r.avg_daily_value_20d,
        )
        for r in rows
    ]


class MarginDataProvider:
    def __init__(
        self,
        *,
        margin_url: str = DEFAULT_TWSE_MARGIN_URL,
        user_agent: str = "Mozilla/5.0",
        timeout_seconds: float = 20.0,
    ) -> None:
        self._margin_url = margin_url
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds

    def fetch_margin_map(self, date: str) -> dict[str, int]:
        response = requests.get(
            self._margin_url,
            params={"response": "json", "date": date, "selectType": "ALL"},
            headers={"User-Agent": self._user_agent},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return parse_twse_margin_payload(response.json())


class InstitutionalFlowProvider:
    def __init__(
        self,
        *,
        twse_url: str = DEFAULT_TWSE_T86_URL,
        tpex_url: str = DEFAULT_TPEX_DETAIL_URL,
        user_agent: str = "Mozilla/5.0",
        timeout_seconds: float = 20.0,
        chrome_binary: str = r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ) -> None:
        self._twse_url = twse_url
        self._tpex_url = tpex_url
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds
        self._chrome_binary = chrome_binary

    def _fetch_twse_payload(self) -> dict[str, Any]:
        response = requests.get(
            self._twse_url,
            headers={"User-Agent": self._user_agent},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def _fetch_tpex_payload(self) -> dict[str, Any]:
        response = requests.get(
            self._tpex_url,
            headers={"User-Agent": self._user_agent},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def fetch_rank_rows(
        self, margin_map: dict[str, int] | None = None
    ) -> list[InstitutionalFlowRow]:
        twse_rows = parse_twse_t86_payload(self._fetch_twse_payload())
        tpex_rows = parse_tpex_daily_trade_payload(self._fetch_tpex_payload())
        rows = twse_rows + tpex_rows
        if margin_map:
            rows = merge_margin_into_rows(rows, margin_map)
        return rows
