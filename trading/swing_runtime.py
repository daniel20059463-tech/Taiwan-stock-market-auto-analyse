from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class SwingRuntimeState:
    watch_states: dict[str, str] = field(default_factory=dict)
    previous_watch_states: dict[str, str | None] = field(default_factory=dict)


class SwingRuntimeCoordinator:
    def __init__(self, state: SwingRuntimeState | None = None) -> None:
        self._state = state or SwingRuntimeState()

    @property
    def watch_states(self) -> dict[str, str]:
        return self._state.watch_states

    def classify_entry_state(
        self,
        *,
        symbol: str,
        flow_score: float,
        above_ma10: bool,
        volume_confirmed: bool,
        recent_runup_pct: float,
        consecutive_trust_days: int,
        classifier: Callable[..., str],
    ) -> str:
        previous = self._state.watch_states.get(symbol)
        if previous == "entered":
            self._state.previous_watch_states[symbol] = previous
            return previous
        state = classifier(
            flow_score=flow_score,
            above_ma10=above_ma10,
            volume_confirmed=volume_confirmed,
            recent_runup_pct=recent_runup_pct,
            consecutive_trust_days=consecutive_trust_days,
        )
        self._state.previous_watch_states[symbol] = previous
        self._state.watch_states[symbol] = state
        return state

    def should_trigger_entry(self, symbol: str, watch_state: str) -> bool:
        if watch_state != "ready_to_buy":
            return False
        current = self._state.watch_states.get(symbol)
        if current == "entered":
            return False
        previous = self._state.previous_watch_states.get(
            symbol,
            current,
        )
        return previous not in {"ready_to_buy", "entered"}

    def mark_entered(self, symbol: str) -> None:
        self._state.previous_watch_states[symbol] = self._state.watch_states.get(symbol)
        self._state.watch_states[symbol] = "entered"

    def reset_for_new_day(self) -> None:
        self._state.watch_states.clear()
        self._state.previous_watch_states.clear()
