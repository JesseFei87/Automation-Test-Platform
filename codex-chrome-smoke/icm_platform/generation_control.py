from __future__ import annotations

import threading


class GenerationCancellationRegistry:
    """Coordinates a client-requested stop with the final draft persistence step."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[str, str] = {}

    def begin(self, generation_id: str) -> bool:
        with self._lock:
            state = self._states.get(generation_id)
            if state is None:
                self._states[generation_id] = "active"
                return True
            if state == "cancelled":
                return False
            raise ValueError(f"generation already active: {generation_id}")

    def request_stop(self, generation_id: str) -> bool:
        with self._lock:
            state = self._states.get(generation_id)
            if state == "committed":
                return False
            self._states[generation_id] = "cancelled"
            return True

    def claim_persistence(self, generation_id: str) -> bool:
        with self._lock:
            if self._states.get(generation_id) != "active":
                return False
            self._states[generation_id] = "committed"
            return True

    def finish(self, generation_id: str) -> None:
        with self._lock:
            self._states.pop(generation_id, None)
