"""
disposition_filter.py

Load a local symbol blocklist and expose a simple lookup interface.

The expected file format is `disposition_symbols.json`:
{
  "updated_at": "2026-04-06",
  "symbols": ["1234", "5678"],
  "notes": "manually maintained blocklist"
}
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_FILE = os.path.join(os.path.dirname(__file__), "disposition_symbols.json")


class DispositionFilter:
    """Maintain a normalized set of blocked symbols loaded from JSON."""

    def __init__(
        self,
        *,
        filepath: str = _DEFAULT_FILE,
        symbols: set[str] | None = None,
    ) -> None:
        self._filepath = filepath
        self._symbols: set[str] = {s.strip().upper() for s in symbols} if symbols else set()
        self._updated_at: str = ""

    def load(self) -> int:
        """
        Load the JSON blocklist.

        Missing or malformed files are treated as an empty list so the caller can
        continue running without a hard dependency on this file.
        """
        try:
            with open(self._filepath, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            raw_symbols = data.get("symbols", [])
            self._symbols = {str(s).strip().upper() for s in raw_symbols if s}
            self._updated_at = str(data.get("updated_at", ""))
            logger.info(
                "DispositionFilter: loaded %d symbols from %s (updated_at=%s)",
                len(self._symbols),
                self._filepath,
                self._updated_at,
            )
            return len(self._symbols)
        except FileNotFoundError:
            logger.debug("DispositionFilter: %s not found, running with empty list", self._filepath)
            return 0
        except Exception as exc:
            logger.warning("DispositionFilter: failed to load %s: %s", self._filepath, exc)
            return 0

    def is_blocked(self, symbol: str) -> bool:
        """Return True when the symbol exists in the current blocklist."""
        return symbol.strip().upper() in self._symbols

    def add(self, symbol: str) -> None:
        """Add a symbol to the in-memory blocklist."""
        self._symbols.add(symbol.strip().upper())

    def remove(self, symbol: str) -> None:
        """Remove a symbol from the in-memory blocklist."""
        self._symbols.discard(symbol.strip().upper())

    @property
    def count(self) -> int:
        return len(self._symbols)

    @property
    def updated_at(self) -> str:
        return self._updated_at

    def snapshot(self) -> dict[str, Any]:
        """Return a serializable snapshot for logs or UI display."""
        return {
            "count": len(self._symbols),
            "updated_at": self._updated_at,
            "symbols": sorted(self._symbols),
        }
