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
    ) -> None:
        self._buy_executor = buy_executor
        self._sell_executor = sell_executor

    async def execute_buy(self, **kwargs: Any) -> None:
        await self._buy_executor(**kwargs)

    async def execute_sell(self, **kwargs: Any) -> None:
        await self._sell_executor(**kwargs)

    async def execute_short(self, **kwargs: Any) -> None:
        raise RuntimeError(
            "execute_short called but short execution is not supported in retail_flow_swing mode"
        )

    async def execute_cover(self, **kwargs: Any) -> None:
        raise RuntimeError(
            "execute_cover called but cover execution is not supported in retail_flow_swing mode"
        )
