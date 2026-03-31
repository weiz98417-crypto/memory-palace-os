"""
health.py · 健康检查模块
================================================================
职责：
  1. 提供多层次健康检查端点：/health、/ready、/live
  2. 支持依赖服务检测：队列、数据库、Redis、企微API等
  3. 提供健康检查探针钩子，便于扩展检查逻辑
  4. 返回结构化健康状态，便于监控系统集成
"""

import time
import asyncio
import traceback
from typing import Optional, Dict, Any, List, Callable, Awaitable
from dataclasses import dataclass, field, asdict
from enum import Enum
from collections import defaultdict

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from loguru import logger


# ==============================================================================
# 类型定义
# ==============================================================================

class HealthStatus(str, Enum):
    """健康状态枚举"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class CheckStatus(str, Enum):
    """单项检查状态"""
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


# ==============================================================================
# 健康检查配置
# ==============================================================================

@dataclass
class HealthCheckConfig:
    """健康检查配置"""
    # 超时设置 (秒)
    timeout: float = 5.0

    # 检查间隔 (秒)
    interval: float = 30.0

    # 是否在启动时执行检查
    check_on_startup: bool = True

    # 是否在关闭时执行检查
    check_on_shutdown: bool = True

    # 检查失败是否阻止启动
    fail_on_startup: bool = False

    # 不健康状态的重试次数
    retry_count: int = 3

    # 不健康状态的恢复时间 (秒)
    recovery_time: float = 60.0


# ==============================================================================
# 检查结果模型
# ==============================================================================

@dataclass
class DependencyCheckResult:
    """依赖检查结果"""
    name: str
    status: CheckStatus
    latency_ms: float = 0.0
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "latency_ms": round(self.latency_ms, 2),
            "message": self.message,
            "details": self.details,
            "error": self.error,
            "timestamp": self.timestamp
        }


@dataclass
class HealthCheckResponse:
    """健康检查响应"""
    status: HealthStatus
    timestamp: float
    version: str = "1.0.0"
    uptime_seconds: float = 0.0
    checks: List[DependencyCheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "version": self.version,
            "uptime_seconds": round(self.uptime_seconds, 2),
            "checks": [c.to_dict() for c in self.checks]
        }


# ==============================================================================
# 健康检查器基类
# ==============================================================================

class BaseHealthChecker:
    """健康检查器基类"""

    name: str = "base"
    timeout: float = 5.0

    async def check(self) -> DependencyCheckResult:
        """执行检查"""
        raise NotImplementedError


class HealthCheckerRegistry:
    """健康检查器注册表"""

    def __init__(self):
        self._checkers: Dict[str, BaseHealthChecker] = {}
        self._app_start_time: float = time.time()

    def register(self, name: str, checker: BaseHealthChecker):
        """注册检查器"""
        self._checkers[name] = checker
        logger.debug(f"✅ 健康检查器已注册: {name}")

    def unregister(self, name: str):
        """注销检查器"""
        if name in self._checkers:
            del self._checkers[name]

    def get_checker(self, name: str) -> Optional[BaseHealthChecker]:
        """获取检查器"""
        return self._checkers.get(name)

    async def check_all(self) -> List[DependencyCheckResult]:
        """执行所有检查"""
        results = []
        tasks = []

        for name, checker in self._checkers.items():
            tasks.append(self._run_check(name, checker))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        check_results = []
        for result in results:
            if isinstance(result, Exception):
                check_results.append(DependencyCheckResult(
                    name="unknown",
                    status=CheckStatus.FAIL,
                    error=str(result)
                ))
            else:
                check_results.append(result)

        return check_results

    async def _run_check(self, name: str, checker: BaseHealthChecker) -> DependencyCheckResult:
        """运行单个检查"""
        start_time = time.perf_counter()

        try:
            result = await asyncio.wait_for(
                checker.check(),
                timeout=checker.timeout
            )
            result.latency_ms = (time.perf_counter() - start_time) * 1000
            return result

        except asyncio.TimeoutError:
            return DependencyCheckResult(
                name=name,
                status=CheckStatus.FAIL,
                latency_ms=self.timeout * 1000,
                error="检查超时"
            )
        except Exception as e:
            return DependencyCheckResult(
                name=name,
                status=CheckStatus.FAIL,
                latency_ms=(time.perf_counter() - start_time) * 1000,
                error=f"{type(e).__name__}: {str(e)}"
            )

    def get_uptime(self) -> float:
        """获取运行时间"""
        return time.time() - self._app_start_time

    def reset_uptime(self):
        """重置运行时间"""
        self._app_start_time = time.time()


# ==============================================================================
# 内置检查器
# ==============================================================================

class MessageQueueHealthChecker(BaseHealthChecker):
    """消息队列健康检查"""

    name = "message_queue"
    timeout = 2.0

    def __init__(self, get_queue_func: Callable[[], Optional[asyncio.Queue]]):
        self.get_queue_func = get_queue_func

    async def check(self) -> DependencyCheckResult:
        queue = self.get_queue_func()

        if queue is None:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                message="消息队列未初始化"
            )

        try:
            size = queue.qsize()
            max_size = getattr(queue, 'maxsize', 0)
            utilization = (size / max_size * 100) if max_size > 0 else 0

            if utilization > 90:
                status = CheckStatus.WARN
                message = f"队列使用率过高: {utilization:.1f}%"
            elif utilization > 80:
                status = CheckStatus.WARN
                message = f"队列使用率较高: {utilization:.1f}%"
            else:
                status = CheckStatus.PASS
                message = "消息队列正常"

            return DependencyCheckResult(
                name=self.name,
                status=status,
                message=message,
                details={
                    "current_size": size,
                    "max_size": max_size,
                    "utilization_percent": round(utilization, 2),
                    "is_empty": queue.empty(),
                    "is_full": queue.full()
                }
            )

        except Exception as e:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                error=str(e)
            )


class DatabaseHealthChecker(BaseHealthChecker):
    """数据库健康检查"""

    name = "database"
    timeout = 3.0

    def __init__(self, db_check_func: Callable[[], Awaitable[bool]]):
        self.db_check_func = db_check_func

    async def check(self) -> DependencyCheckResult:
        try:
            start_time = time.perf_counter()
            is_connected = await self.db_check_func()
            latency_ms = (time.perf_counter() - start_time) * 1000

            if is_connected:
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.PASS,
                    latency_ms=latency_ms,
                    message="数据库连接正常"
                )
            else:
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.FAIL,
                    message="数据库连接失败"
                )

        except Exception as e:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                error=str(e)
            )


class WeChatCryptoHealthChecker(BaseHealthChecker):
    """企微加解密健康检查"""

    name = "wechat_crypto"
    timeout = 2.0

    def __init__(self, crypto_check_func: Callable[[], bool]):
        self.crypto_check_func = crypto_check_func

    async def check(self) -> DependencyCheckResult:
        try:
            is_available = self.crypto_check_func()

            if is_available:
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.PASS,
                    message="企微加解密可用"
                )
            else:
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.WARN,
                    message="企微加解密未配置，使用 Mock 模式"
                )

        except Exception as e:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                error=str(e)
            )


class RedisHealthChecker(BaseHealthChecker):
    """Redis 健康检查"""

    name = "redis"
    timeout = 2.0

    def __init__(self, redis_check_func: Callable[[], Awaitable[Dict[str, Any]]]):
        self.redis_check_func = redis_check_func

    async def check(self) -> DependencyCheckResult:
        try:
            result = await self.redis_check_func()

            if result.get("connected"):
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.PASS,
                    message="Redis 连接正常",
                    details={
                        "used_memory": result.get("used_memory", 0),
                        "connected_clients": result.get("connected_clients", 0)
                    }
                )
            else:
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.FAIL,
                    message="Redis 连接失败"
                )

        except Exception as e:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                error=str(e)
            )


class VectorStoreHealthChecker(BaseHealthChecker):
    """向量数据库健康检查"""

    name = "vector_store"
    timeout = 3.0

    def __init__(self, vector_check_func: Callable[[], Awaitable[bool]]):
        self.vector_check_func = vector_check_func

    async def check(self) -> DependencyCheckResult:
        try:
            is_ready = await self.vector_check_func()

            if is_ready:
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.PASS,
                    message="向量数据库就绪"
                )
            else:
                return DependencyCheckResult(
                    name=self.name,
                    status=CheckStatus.FAIL,
                    message="向量数据库未就绪"
                )

        except Exception as e:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                error=str(e)
            )


class LLMRuntimeHealthChecker(BaseHealthChecker):
    """LLM 运行时健康检查"""

    name = "llm_runtime"
    timeout = 5.0

    def __init__(self, llm_check_func: Callable[[], Awaitable[Dict[str, Any]]]):
        self.llm_check_func = llm_check_func

    async def check(self) -> DependencyCheckResult:
        try:
            result = await self.llm_check_func()

            status = CheckStatus.PASS if result.get("available") else CheckStatus.FAIL
            message = result.get("message", "LLM 运行时检查完成")

            return DependencyCheckResult(
                name=self.name,
                status=status,
                message=message,
                details={
                    "available": result.get("available", False),
                    "models": result.get("models", []),
                    "active_providers": result.get("active_providers", 0)
                }
            )

        except Exception as e:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                error=str(e)
            )


class SkillsRegistryHealthChecker(BaseHealthChecker):
    """技能注册表健康检查"""

    name = "skills_registry"
    timeout = 2.0

    def __init__(self, skills_check_func: Callable[[], Dict[str, Any]]):
        self.skills_check_func = skills_check_func

    async def check(self) -> DependencyCheckResult:
        try:
            result = self.skills_check_func()

            total = result.get("total", 0)
            enabled = result.get("enabled", 0)
            failed = result.get("failed", 0)

            if failed > 0:
                status = CheckStatus.WARN
                message = f"部分技能加载失败: {failed}/{total}"
            elif enabled == 0:
                status = CheckStatus.WARN
                message = "没有启用的技能"
            else:
                status = CheckStatus.PASS
                message = f"技能注册表正常: {enabled}/{total} 启用"

            return DependencyCheckResult(
                name=self.name,
                status=status,
                message=message,
                details={
                    "total_skills": total,
                    "enabled_skills": enabled,
                    "failed_skills": failed
                }
            )

        except Exception as e:
            return DependencyCheckResult(
                name=self.name,
                status=CheckStatus.FAIL,
                error=str(e)
            )


# ==============================================================================
# 全局注册表
# ==============================================================================

_health_registry: Optional[HealthCheckerRegistry] = None


def get_health_registry() -> HealthCheckerRegistry:
    """获取健康检查注册表"""
    global _health_registry
    if _health_registry is None:
        _health_registry = HealthCheckerRegistry()
    return _health_registry


# ==============================================================================
# 路由器
# ==============================================================================

router = APIRouter(prefix="/health", tags=["Health"])


def create_health_response(
    status: HealthStatus,
    checks: List[DependencyCheckResult],
    version: str = "1.0.0"
) -> HealthCheckResponse:
    """创建健康检查响应"""
    return HealthCheckResponse(
        status=status,
        timestamp=time.time(),
        version=version,
        uptime_seconds=get_health_registry().get_uptime(),
        checks=checks
    )


def aggregate_status(checks: List[DependencyCheckResult]) -> HealthStatus:
    """聚合检查结果为总体状态"""
    if not checks:
        return HealthStatus.UNKNOWN

    has_failure = False
    has_warning = False

    for check in checks:
        if check.status == CheckStatus.FAIL:
            has_failure = True
        elif check.status == CheckStatus.WARN:
            has_warning = True

    if has_failure:
        return HealthStatus.UNHEALTHY
    elif has_warning:
        return HealthStatus.DEGRADED
    else:
        return HealthStatus.HEALTHY


@router.get("/live")
async def liveness_probe():
    """
    存活探针 (Liveness Probe)
    - 仅检查进程是否存活
    - 用于 K8s livenessProbe
    """
    return JSONResponse({
        "status": "alive",
        "timestamp": time.time()
    })


@router.get("/ready", response_model=Dict[str, Any])
async def readiness_probe(request: Request):
    """
    就绪探针 (Readiness Probe)
    - 检查所有依赖服务是否就绪
    - 用于 K8s readinessProbe
    """
    registry = get_health_registry()

    # 检查队列 (从 app.state 获取)
    queue = getattr(request.app.state, 'message_queue', None)

    # 执行所有检查
    checks = await registry.check_all()

    # 聚合状态
    status = aggregate_status(checks)

    response = create_health_response(status, checks)

    # 根据状态返回 HTTP 状态码
    if status == HealthStatus.HEALTHY:
        status_code = 200
    elif status == HealthStatus.DEGRADED:
        status_code = 200  # K8s 仍认为就绪
    else:
        status_code = 503

    return JSONResponse(response.to_dict(), status_code=status_code)


@router.get("/health", response_model=Dict[str, Any])
async def health_check(request: Request):
    """
    完整健康检查
    - 返回详细的健康状态和所有检查结果
    """
    registry = get_health_registry()
    checks = await registry.check_all()
    status = aggregate_status(checks)
    response = create_health_response(status, checks)

    status_code = 200 if status in (HealthStatus.HEALTHY, HealthStatus.DEGRADED) else 503
    return JSONResponse(response.to_dict(), status_code=status_code)


@router.get("/checks/{check_name}")
async def check_specific(check_name: str):
    """执行指定检查"""
    registry = get_health_registry()
    checker = registry.get_checker(check_name)

    if not checker:
        raise HTTPException(status_code=404, detail=f"检查器 '{check_name}' 未找到")

    result = await registry._run_check(check_name, checker)
    return JSONResponse(result.to_dict())


@router.post("/reset-uptime")
async def reset_uptime():
    """重置运行时间计数器"""
    registry = get_health_registry()
    registry.reset_uptime()
    return JSONResponse({
        "status": "success",
        "message": "运行时间已重置"
    })


# ==============================================================================
# 初始化函数
# ==============================================================================

def init_health_checks(app=None):
    """初始化健康检查"""
    registry = get_health_registry()

    # 注册内置检查器
    if app:
        # 队列检查
        registry.register(
            "message_queue",
            MessageQueueHealthChecker(lambda: getattr(app.state, 'message_queue', None))
        )

        # 数据库检查
        try:
            from src.memory_palace.knowledge.db_client import check_connection
            registry.register(
                "database",
                DatabaseHealthChecker(check_connection)
            )
        except ImportError:
            pass

    logger.info("✅ 健康检查模块初始化完成")
    return registry


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    # 类型
    "HealthStatus",
    "CheckStatus",
    "HealthCheckConfig",

    # 模型
    "DependencyCheckResult",
    "HealthCheckResponse",

    # 检查器
    "BaseHealthChecker",
    "HealthCheckerRegistry",
    "MessageQueueHealthChecker",
    "DatabaseHealthChecker",
    "WeChatCryptoHealthChecker",
    "RedisHealthChecker",
    "VectorStoreHealthChecker",
    "LLMRuntimeHealthChecker",
    "SkillsRegistryHealthChecker",

    # 工具
    "get_health_registry",
    "create_health_response",
    "aggregate_status",
    "init_health_checks",

    # 路由
    "router",
]

    