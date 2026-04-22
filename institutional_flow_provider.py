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


DEFAULT_TWSE_T86_URL = "https://www.twse.com.tw/fund/T86?response=json&selectType=ALLBUT0999"
DEFAULT_TPEX_DETAIL_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade?type=Daily&sect=EW&response=json"


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
        if len(item) < 11:
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
                major_net_buy=0,
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

    def fetch_rank_rows(self) -> list[InstitutionalFlowRow]:
        twse_rows = parse_twse_t86_payload(self._fetch_twse_payload())
        tpex_rows = parse_tpex_daily_trade_payload(self._fetch_tpex_payload())
        return twse_rows + tpex_rows
