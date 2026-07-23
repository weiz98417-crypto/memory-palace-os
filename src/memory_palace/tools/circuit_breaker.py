"""
circuit_breaker.py · LLM 调用熔断器
=====================================
实现经典三态熔断器（Circuit Breaker Pattern）：

  CLOSED  → 正常状态，请求正常通过
     ↓ 连续失败次数 >= failure_threshold
  OPEN    → 熔断状态，直接拒绝请求，不访问 LLM
     ↓ 冷却时间 recovery_timeout 到期后，放行一个探测请求
  HALF_OPEN → 探测状态，成功则回 CLOSED，失败则回 OPEN

           失败次数达阈值
  CLOSED ──────────────→ OPEN
    ↑                      ↓ 冷却到期
    │                   HALF_OPEN
    └─── 探测成功 ──────────┘
              探测失败 → OPEN（重新计时）

使用方式（在 llm_wrapper.py 中）：
  from src.memory_palace.tools.circuit_breaker import CircuitBreaker, CircuitOpenError

  breaker = CircuitBreaker(name="llm_main", failure_threshold=5, recovery_timeout=60)

  try:
      result = await breaker.call(your_llm_async_func, prompt=prompt)
  except CircuitOpenError:
      # 熔断中：走降级逻辑
      result = fallback_response()

装饰器方式：
  @breaker.protect
  async def call_llm(prompt: str) -> str:
      ...
"""

import asyncio
import functools
import time
from enum import Enum
from typing import Any, Callable, Optional

from loguru import logger


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 状态枚举 & 异常
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CircuitState(Enum):
    CLOSED    = "CLOSED"      # 正常
    OPEN      = "OPEN"        # 熔断中
    HALF_OPEN = "HALF_OPEN"   # 探测中


class CircuitOpenError(Exception):
    """
    熔断器处于 OPEN 状态时抛出。
    llm_wrapper.py 捕获此异常后走降级逻辑，不重试。
    """
    def __init__(self, name: str, retry_after: float):
        self.name        = name
        self.retry_after = retry_after
        super().__init__(
            f"熔断器 [{name}] 当前熔断中，"
            f"距离下次探测还有 {retry_after:.1f}s"
        )


CircuitBreakerOpen = CircuitOpenError  # 别名，兼容旧导入


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 熔断器主体
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class CircuitBreaker:
    """
    异步安全的三态熔断器。

    参数说明：
      name               — 熔断器名称，用于日志区分（如 "llm_main" / "llm_fallback"）
      failure_threshold  — CLOSED 状态下，连续失败多少次触发熔断（默认 5）
      recovery_timeout   — OPEN 状态持续多少秒后进入 HALF_OPEN 探测（默认 60s）
      success_threshold  — HALF_OPEN 状态下，连续成功多少次才恢复 CLOSED（默认 2）
      timeout            — 单次调用的超时秒数，超时视为失败（默认 30s）
      excluded_exceptions— 这些异常不计入失败次数（如业务级 ValueError）
    """

    def __init__(
        self,
        name: str                   = "default",
        failure_threshold: int      = 5,
        recovery_timeout: float     = 60.0,
        success_threshold: int      = 2,
        timeout: float              = 30.0,
        excluded_exceptions: tuple  = (),
    ):
        self.name                = name
        self.failure_threshold   = failure_threshold
        self.recovery_timeout    = recovery_timeout
        self.success_threshold   = success_threshold
        self.timeout             = timeout
        self.excluded_exceptions = excluded_exceptions

        self._state              = CircuitState.CLOSED
        self._failure_count      = 0
        self._success_count      = 0
        self._opened_at: Optional[float] = None

        # asyncio 锁：防止并发请求同时修改状态
        self._lock = asyncio.Lock()

    # ── 对外接口 ──────────────────────────────────────────────────────────────

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        通过熔断器调用异步函数。

        CLOSED    → 正常调用，记录成功/失败
        OPEN      → 直接抛 CircuitOpenError，不调用 func
        HALF_OPEN → 放行一次探测，成功则恢复，失败则重新熔断
        """
        async with self._lock:
            state = self._get_current_state()

            if state == CircuitState.OPEN:
                retry_after = self.recovery_timeout - (time.time() - self._opened_at)
                raise CircuitOpenError(self.name, max(0.0, retry_after))

            if state == CircuitState.HALF_OPEN:
                logger.info(f"[熔断器:{self.name}] 进入探测模式，放行一次请求")

        # 实际调用在锁外执行，不阻塞其他协程
        try:
            result = await asyncio.wait_for(func(*args, **kwargs), timeout=self.timeout)
            await self._on_success()
            return result

        except CircuitOpenError:
            raise

        except asyncio.TimeoutError as e:
            await self._on_failure(e)
            raise

        except self.excluded_exceptions:
            raise   # 业务异常不触发熔断，直接透传

        except Exception as e:
            await self._on_failure(e)
            raise

    def protect(self, func: Callable) -> Callable:
        """
        装饰器写法。
        用法：
          @breaker.protect
          async def call_llm(prompt): ...
        """
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            return await self.call(func, *args, **kwargs)
        return wrapper

    # ── 状态读取 ──────────────────────────────────────────────────────────────

    @property
    def state(self) -> CircuitState:
        return self._get_current_state()

    @property
    def is_open(self) -> bool:
        return self._get_current_state() == CircuitState.OPEN

    def stats(self) -> dict:
        """返回当前统计，供 /health 端点和管理大屏使用"""
        state = self._get_current_state()
        retry_after = None
        if state == CircuitState.OPEN and self._opened_at:
            retry_after = max(
                0.0,
                self.recovery_timeout - (time.time() - self._opened_at)
            )
        return {
            "name":            self.name,
            "state":           state.value,
            "failure_count":   self._failure_count,
            "success_count":   self._success_count,
            "retry_after_sec": retry_after,
        }

    def reset(self):
        """手动重置（运维干预，管理大屏可调用）"""
        self._state         = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._opened_at     = None
        logger.info(f"[熔断器:{self.name}] 已手动重置为 CLOSED")

    # ── 内部状态机 ────────────────────────────────────────────────────────────

    def _get_current_state(self) -> CircuitState:
        """OPEN 冷却到期时自动迁移至 HALF_OPEN。调用方负责加锁。"""
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and time.time() - self._opened_at >= self.recovery_timeout
        ):
            self._state         = CircuitState.HALF_OPEN
            self._success_count = 0
            logger.info(
                f"[熔断器:{self.name}] 冷却到期，OPEN → HALF_OPEN，开始探测"
            )
        return self._state

    async def _on_success(self):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state         = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    self._opened_at     = None
                    logger.info(
                        f"[熔断器:{self.name}] 探测成功 "
                        f"({self.success_threshold} 次)，HALF_OPEN → CLOSED ✅"
                    )
                else:
                    logger.debug(
                        f"[熔断器:{self.name}] 探测中 "
                        f"({self._success_count}/{self.success_threshold})"
                    )
            elif self._state == CircuitState.CLOSED:
                if self._failure_count > 0:
                    self._failure_count = 0

    async def _on_failure(self, exc: Exception):
        async with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._state     = CircuitState.OPEN
                self._opened_at = time.time()
                logger.warning(
                    f"[熔断器:{self.name}] 探测失败 [{type(exc).__name__}: {exc}]，"
                    f"HALF_OPEN → OPEN，重新冷却 {self.recovery_timeout}s"
                )
            elif self._state == CircuitState.CLOSED:
                self._failure_count += 1
                logger.warning(
                    f"[熔断器:{self.name}] 调用失败 "
                    f"[{self._failure_count}/{self.failure_threshold}] "
                    f"[{type(exc).__name__}: {exc}]"
                )
                if self._failure_count >= self.failure_threshold:
                    self._state     = CircuitState.OPEN
                    self._opened_at = time.time()
                    logger.error(
                        f"[熔断器:{self.name}] 连续失败 {self._failure_count} 次，"
                        f"CLOSED → OPEN 🔴，冷却 {self.recovery_timeout}s"
                    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 全局预置实例（llm_wrapper.py 直接 import 使用）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 主 LLM：5次失败触发，60秒冷却，单次超时30秒
llm_breaker = CircuitBreaker(
    name                = "llm_main",
    failure_threshold   = 5,
    recovery_timeout    = 60.0,
    success_threshold   = 2,
    timeout             = 30.0,
    excluded_exceptions = (ValueError, KeyError),
)

# 降级备用模型：阈值更宽松
llm_fallback_breaker = CircuitBreaker(
    name              = "llm_fallback",
    failure_threshold = 3,
    recovery_timeout  = 30.0,
    success_threshold = 1,
    timeout           = 20.0,
)