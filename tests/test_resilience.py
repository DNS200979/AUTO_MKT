import pytest

from market_api.resilience import CircuitBreaker, CircuitOpenError, CircuitState


class TransientFailure(RuntimeError):
    pass


def test_circuit_opens_and_recovers_through_half_open() -> None:
    now = [100.0]
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=10, clock=lambda: now[0])

    def fail() -> None:
        raise TransientFailure("unavailable")

    for _ in range(2):
        with pytest.raises(TransientFailure):
            breaker.call(fail, counts_as_failure=lambda exc: isinstance(exc, TransientFailure))

    assert breaker.snapshot().state == CircuitState.OPEN
    with pytest.raises(CircuitOpenError):
        breaker.call(lambda: "not-called", counts_as_failure=lambda exc: True)

    now[0] += 11
    assert breaker.call(lambda: "recovered", counts_as_failure=lambda exc: True) == "recovered"
    assert breaker.snapshot().state == CircuitState.CLOSED
    assert breaker.snapshot().failures == 0


def test_permanent_failure_does_not_open_circuit() -> None:
    breaker = CircuitBreaker(failure_threshold=1)

    with pytest.raises(ValueError):
        breaker.call(
            lambda: (_ for _ in ()).throw(ValueError("invalid request")),
            counts_as_failure=lambda exc: False,
        )

    assert breaker.snapshot().state == CircuitState.CLOSED
