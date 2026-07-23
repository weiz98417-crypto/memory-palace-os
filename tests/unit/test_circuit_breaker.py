"""
熔断器独立测试 (Unit Test for Circuit Breaker)

测试核心：验证 CircuitBreaker 的三态状态机（CLOSED / OPEN / HALF_OPEN）。

当前 API（async call + protect 装饰器）：
  breaker.call(func, *args, **kwargs)
  breaker.protect(func)  → 装饰器
  breaker.state          → CircuitState enum
  breaker.is_open        → bool
  breaker.stats()        → dict
  breaker.reset()        → 手动重置

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""
import pytest
import time
import asyncio

from src.memory_palace.tools.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    CircuitOpenError,
)


# ── helpers ─────────────────────────────────────────────────────────────────

async def _ok():
    return "ok"

async def _fail(msg="boom"):
    raise RuntimeError(msg)

async def _fail_val():
    raise ValueError("business")


class TestCircuitBreakerStateMachine:

    @pytest.mark.asyncio
    async def test_initial_state_is_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_success_keeps_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(5):
            result = await cb.call(_ok)
            assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_increments_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(_fail)
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 2

    @pytest.mark.asyncio
    async def test_failure_threshold_triggers_open(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(_fail)
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True

    @pytest.mark.asyncio
    async def test_open_state_blocks_requests(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        with pytest.raises(RuntimeError):
            await cb.call(_fail)  # triggers OPEN

        with pytest.raises(CircuitOpenError):
            await cb.call(_ok)

    @pytest.mark.asyncio
    async def test_excluded_exception_does_not_count(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60, excluded_exceptions=(ValueError,))
        with pytest.raises(ValueError):
            await cb.call(_fail_val)
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0


class TestHalfOpenRecovery:

    @pytest.mark.asyncio
    async def test_timeout_triggers_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(RuntimeError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.1)  # wait past recovery
        # _get_current_state lazily transitions during call()
        result = await cb.call(_ok)
        assert result == "ok"
        # 1 success in HALF_OPEN → still HALF_OPEN (success_threshold=2 by default)
        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(RuntimeError):
            await cb.call(_fail)
        await asyncio.sleep(0.1)

        # success_threshold=2 (default), need 2 successes
        await cb.call(_ok)  # 1st success in HALF_OPEN
        assert cb.state == CircuitState.HALF_OPEN
        await cb.call(_ok)  # 2nd success → CLOSED
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        with pytest.raises(RuntimeError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN
        await asyncio.sleep(0.1)

        with pytest.raises(RuntimeError):
            await cb.call(_fail)  # HALF_OPEN + failure → back to OPEN
        assert cb.state == CircuitState.OPEN
        assert cb.is_open is True


class TestFailureCountReset:

    @pytest.mark.asyncio
    async def test_success_resets_counter(self):
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
        for _ in range(4):
            with pytest.raises(RuntimeError):
                await cb.call(_fail)
        assert cb._failure_count == 4

        await cb.call(_ok)  # success resets failure count
        assert cb._failure_count == 0

    @pytest.mark.asyncio
    async def test_stats_reflects_state(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, recovery_timeout=60)
        s = cb.stats()
        assert s["name"] == "test"
        assert s["state"] == "CLOSED"
        assert s["failure_count"] == 0


class TestManualReset:

    @pytest.mark.asyncio
    async def test_reset_from_open(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
        with pytest.raises(RuntimeError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb._failure_count == 0
        assert cb._success_count == 0

    @pytest.mark.asyncio
    async def test_reset_restores_functional(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=999)
        with pytest.raises(RuntimeError):
            await cb.call(_fail)
        cb.reset()
        result = await cb.call(_ok)
        assert result == "ok"


class TestDecoratorIntegration:

    @pytest.mark.asyncio
    async def test_protect_decorator_success(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        @cb.protect
        async def double(x):
            return x * 2

        result = await double(5)
        assert result == 10
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_protect_tracks_failure(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        @cb.protect
        async def maybe(should_fail):
            if should_fail:
                raise RuntimeError("fail")
            return "ok"

        assert await maybe(False) == "ok"
        assert cb._failure_count == 0

        with pytest.raises(RuntimeError):
            await maybe(True)
        assert cb._failure_count == 1
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_protect_open_raises_without_calling(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        calls = []

        @cb.protect
        async def tracked():
            calls.append(1)
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            await tracked()

        with pytest.raises(CircuitOpenError):
            await tracked()

        assert len(calls) == 1, "function should not be called while OPEN"


class TestExcludedExceptions:

    @pytest.mark.asyncio
    async def test_excluded_passthrough(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60, excluded_exceptions=(ValueError,))
        with pytest.raises(ValueError):
            await cb.call(_fail_val)

        # excluded exception should NOT open the breaker
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_excluded_then_real_failure(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60, excluded_exceptions=(ValueError,))
        with pytest.raises(ValueError):
            await cb.call(_fail_val)
        assert cb.state == CircuitState.CLOSED

        with pytest.raises(RuntimeError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN
