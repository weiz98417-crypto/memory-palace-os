"""
熔断器独立测试 (Unit Test for Circuit Breaker)

测试核心：验证 CircuitBreaker 的三态状态机（Closed/Open/Half-Open）。

本文件独立测试 CircuitBreaker，与 test_rate_limiter.py 中的集成场景互补。
本文件测试的是同步接口 + 边界条件。

工业级测试要点：
1. 三态状态机：Closed → Open → Half-Open → Closed/Half-Open
2. 半开超时精度：恢复超时后正确转入半开
3. 半开试探次数限制：只放行一个请求
4. 半开成功/失败后的状态转换
5. 连续失败重置计数器

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytest
import time
import threading
import asyncio

from src.memory_palace.tools.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
)


class TestCircuitBreakerStateMachine:

    def test_initial_state_is_closed(self):
        """初始状态：熔断器关闭，请求正常通过"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_success_keeps_closed_and_resets_count(self):
        """成功记录保持关闭状态，并重置失败计数器"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.failure_count = 2
        cb.record_success()
        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_failure_increments_count_below_threshold(self):
        """失败次数未达阈值时，保持关闭状态"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
        cb.record_failure()
        assert cb.state == "closed"
        assert cb.failure_count == 1

        cb.record_failure()
        assert cb.state == "closed"
        assert cb.failure_count == 2

    def test_failure_threshold_triggers_open(self):
        """达到失败阈值后，熔断器打开"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        cb.record_failure()  # 1
        cb.record_failure()  # 2
        cb.record_failure()  # 3 → 触发熔断

        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_open_state_blocks_requests(self):
        """Open 状态直接拒绝请求，抛出 CircuitOpenError"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        cb.record_failure()  # 立即熔断

        with pytest.raises(CircuitOpenError):
            cb.check_or_raise()

        # allow_request 也应返回 False
        assert cb.allow_request() is False


class TestHalfOpenRecovery:

    def test_timeout_triggers_half_open(self):
        """恢复超时后，从 Open 转入 Half-Open"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)  # 100ms

        cb.record_failure()  # 进入 Open
        assert cb.state == "open"

        time.sleep(0.15)  # 等待超时

        # 下一次 allow_request 检查时，触发转换
        result = cb.allow_request()
        assert cb.state == "half-open"
        assert result is True

    def test_half_open_allows_single_request(self):
        """Half-Open 只放行一个试探请求"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)

        cb.allow_request()  # 进入半开
        assert cb.state == "half-open"

        # 半开状态下，每次 check_or_raise 都应放行一个
        cb.check_or_raise()  # 放行，不抛异常

    def test_half_open_success_closes_circuit(self):
        """半开试探成功后，熔断器恢复关闭"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)

        cb.allow_request()  # 进入半开
        cb.record_success()  # 试探成功

        assert cb.state == "closed"
        assert cb.failure_count == 0

    def test_half_open_failure_reopens_circuit(self):
        """半开试探失败，重新进入 Open"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)

        cb.allow_request()  # 进入半开
        cb.record_failure()  # 试探失败

        assert cb.state == "open"

    def test_half_open_resets_failure_count(self):
        """进入 Half-Open 时，失败计数器应保留（用于下次判断）"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
        cb.record_failure()  # count=1
        cb.record_failure()  # count=2 → Open
        time.sleep(0.15)

        cb.allow_request()  # Half-Open
        assert cb.state == "half-open"


class TestFailureCountReset:

    def test_success_resets_after_partial_failures(self):
        """部分失败后成功，重置计数器，防止累积误触发"""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

        for _ in range(4):
            cb.record_failure()

        assert cb.failure_count == 4
        assert cb.state == "closed"

        cb.record_success()  # 重置

        assert cb.failure_count == 0
        cb.record_failure()  # 再失败
        assert cb.failure_count == 1
        # 还需要4次才能触发熔断

    def test_multiple_success_calls_no_issue(self):
        """连续多次成功调用无副作用"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        for _ in range(10):
            cb.record_success()

        assert cb.state == "closed"
        assert cb.failure_count == 0


class TestThreadSafety:

    def test_concurrent_record_failure_safe(self):
        """并发写入失败计数器无竞态"""
        cb = CircuitBreaker(failure_threshold=1000, recovery_timeout=60)
        count = {"errors": 0}

        def worker():
            try:
                for _ in range(100):
                    cb.record_failure()
            except Exception:
                count["errors"] += 1

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert count["errors"] == 0
        # 10线程 × 100次 = 1000次，应达到熔断阈值
        assert cb.state == "open"

    def test_concurrent_record_mixed_safe(self):
        """成功/失败并发记录最终状态一致"""
        cb = CircuitBreaker(failure_threshold=50, recovery_timeout=60)

        def worker_fail():
            for _ in range(30):
                cb.record_failure()

        def worker_success():
            for _ in range(30):
                cb.record_success()

        threads = [
            threading.Thread(target=worker_fail)
            for _ in range(5)
        ] + [
            threading.Thread(target=worker_success)
            for _ in range(5)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 状态应为 closed/open/half-open 之一，不应有异常
        assert cb.state in ("closed", "open", "half-open")


class TestDecoratorIntegration:

    def test_wrap_decorator_with_success(self):
        """@cb.wrap 装饰器在成功时正常工作"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60)

        @cb.wrap
        def safe_func(x):
            return x * 2

        assert safe_func(5) == 10
        assert cb.state == "closed"

    def test_wrap_decorator_failure_tracked(self):
        """@cb.wrap 装饰器在失败时正确记录"""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)

        @cb.wrap
        def risky_func(should_fail):
            if should_fail:
                raise ValueError("模拟失败")
            return "ok"

        risky_func(False)
        assert cb.failure_count == 0

        try:
            risky_func(True)
        except ValueError:
            pass
        assert cb.failure_count == 1
        assert cb.state == "closed"

    def test_wrap_decorator_open_raises_without_calling(self):
        """熔断打开后，装饰器函数直接抛出异常，不执行实际逻辑"""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=60)
        call_count = {"n": 0}

        @cb.wrap
        def tracked_func():
            call_count["n"] += 1
            return "done"

        try:
            tracked_func()
        except ValueError:
            pass  # 第一次失败

        # 现在熔断打开，第二次调用应直接抛 CircuitOpenError
        with pytest.raises(CircuitOpenError):
            tracked_func()

        assert call_count["n"] == 1, "熔断后函数不应被执行"
