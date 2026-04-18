from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


class PaperExecutionService:
    """Thin execution boundary around paper trade side effects."""

    def __init__(
        self,
        *,
        buy_executor: Callable[..., Awaitable[None]],
        sell_executor: Callable[..., Awaitable[None]],
        short_executor: Callable[..., Awaitable[None]],
        cover_executor: Callable[..., Awaitable[None]],
    ) -> None:
        self._buy_executor = buy_executor
        self._sell_executor = sell_executor
        self._short_executor = short_executor
        self._cover_executor = cover_executor

    async def execute_buy(self, **kwargs: Any) -> None:
        await self._buy_executor(**kwargs)

    async def execute_sell(self, **kwargs: Any) -> None:
        await self._sell_executor(**kwargs)

    async def execute_short(self, **kwargs: Any) -> None:
        await self._short_executor(**kwargs)

    async def execute_cover(self, **kwargs: Any) -> None:
        await self._cover_executor(**kwargs)
