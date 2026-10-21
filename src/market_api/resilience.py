from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    pass


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    state: CircuitState
    failures: int


class CircuitBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        recovery_seconds: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1 or recovery_seconds <= 0:
            raise ValueError("invalid circuit breaker policy")
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self.clock = clock
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def snapshot(self) -> CircuitSnapshot:
        with self._lock:
            return CircuitSnapshot(self._state, self._failures)

    def call(
        self, operation: Callable[[], T], *, counts_as_failure: Callable[[Exception], bool]
    ) -> T:
        with self._lock:
            if self._state == CircuitState.OPEN:
                assert self._opened_at is not None
                if self.clock() - self._opened_at < self.recovery_seconds:
                    raise CircuitOpenError("integration circuit is open")
                self._state = CircuitState.HALF_OPEN
            elif self._state == CircuitState.HALF_OPEN:
                raise CircuitOpenError("integration circuit is testing recovery")
        try:
            result = operation()
        except Exception as exc:
            if counts_as_failure(exc):
                self._record_failure()
            else:
                self._record_success()
            raise
        self._record_success()
        return result

    def _record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = self.clock()

    def _record_success(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failures = 0
            self._opened_at = None
