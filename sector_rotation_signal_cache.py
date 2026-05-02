from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SectorSignalRecord:
    sector: str
    state: str
    sector_flow_score: float
    chip_score: float
    relative_strength_20: float
    relative_strength_60: float
    breadth_positive_return_pct: float
    breadth_above_ma10_pct: float
    breadth_positive_flow_pct: float
    top_symbols: list[str]


class SectorSignalCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, SectorSignalRecord]] = {}

    def store(self, *, trade_date: str, sectors: dict[str, SectorSignalRecord]) -> None:
        self._data[trade_date] = dict(sectors)

    def get(self, trade_date: str, sector: str) -> SectorSignalRecord | None:
        return self._data.get(trade_date, {}).get(sector)

    def sectors_for_date(self, trade_date: str) -> dict[str, SectorSignalRecord]:
        return dict(self._data.get(trade_date, {}))

    def latest_trade_date(self) -> str | None:
        if not self._data:
            return None
        return sorted(self._data.keys())[-1]

    def available_dates(self) -> list[str]:
        return sorted(self._data.keys())

    def save(self, path: str) -> None:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        payload = {
            trade_date: {
                sector: asdict(record)
                for sector, record in sectors.items()
            }
            for trade_date, sectors in self._data.items()
            if sectors
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            return
        with open(path, encoding="utf-8") as handle:
            raw = json.load(handle)
        for trade_date, sectors in raw.items():
            if not sectors:
                continue
            restored: dict[str, SectorSignalRecord] = {}
            for sector, record in sectors.items():
                restored[sector] = SectorSignalRecord(**record)
            self._data[trade_date] = restored
