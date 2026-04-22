from __future__ import annotations

import json
import os
from collections import defaultdict

from institutional_flow_provider import InstitutionalFlowRow

PERSIST_MAX_DAYS = 30


class InstitutionalFlowCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, InstitutionalFlowRow]] = defaultdict(dict)

    def store(self, *, trade_date: str, rows: list[InstitutionalFlowRow]) -> None:
        self._data[trade_date] = {row.symbol: row for row in rows}

    def get(self, trade_date: str, symbol: str) -> InstitutionalFlowRow | None:
        return self._data.get(trade_date, {}).get(symbol)

    def symbols_for_date(self, trade_date: str) -> list[str]:
        return list(self._data.get(trade_date, {}).keys())

    def rows_for_date(self, trade_date: str) -> list:
        return list(self._data.get(trade_date, {}).values())

    def available_dates(self) -> list[str]:
        return sorted(self._data.keys())

    def save(self, path: str) -> None:
        from dataclasses import asdict
        data = {
            date: {symbol: asdict(row) for symbol, row in rows.items()}
            for date, rows in self._data.items()
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            for date, rows in raw.items():
                for symbol, row_dict in rows.items():
                    try:
                        self._data[date][symbol] = InstitutionalFlowRow(**row_dict)
                    except Exception:
                        pass
        except Exception:
            pass

    def prune(self, keep_days: int = PERSIST_MAX_DAYS) -> None:
        dates = sorted(self._data.keys(), reverse=True)
        for old_date in dates[keep_days:]:
            del self._data[old_date]

    def consecutive_trust_buy_days(self, symbol: str, as_of_date: str, n: int = 5) -> int:
        """回傳截至 as_of_date 為止，投信連續淨買超的天數（最多往回查 n 天）。"""
        dates = sorted([d for d in self._data if d <= as_of_date], reverse=True)[:n]
        count = 0
        for d in dates:
            row = self._data[d].get(symbol)
            if row is None or row.investment_trust_net_buy <= 0:
                break
            count += 1
        return count
