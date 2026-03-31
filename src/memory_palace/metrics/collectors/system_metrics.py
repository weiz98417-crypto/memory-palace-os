"""
system_metrics.py - 系统级指标收集器
"""
from prometheus_client import Gauge
import os

# CPU 使用率
cpu_usage_percent = Gauge(
    "memory_palace_cpu_usage_percent",
    "CPU usage percentage"
)

# 内存使用
memory_usage_bytes = Gauge(
    "memory_palace_memory_usage_bytes",
    "Memory usage in bytes",
    ["memory_type"]
)

# 线程数
threads_count = Gauge(
    "memory_palace_threads_count",
    "Number of threads",
    ["thread_type"]
)

# 数据库连接
db_connections_active = Gauge(
    "memory_palace_db_connections_active",
    "Active database connections",
    ["db_name"]
)


class SystemMetricsCollector:
    """系统资源指标收集器"""

    @staticmethod
    def update_system_metrics() -> None:
        """采集并更新系统指标（使用 psutil）"""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()

            # CPU
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_usage_percent.set(cpu_percent)

            # 内存
            memory_usage_bytes.labels(memory_type="rss").set(memory_info.rss)
            memory_usage_bytes.labels(memory_type="vms").set(memory_info.vms)
            vm = psutil.virtual_memory()
            memory_usage_bytes.labels(memory_type="available").set(vm.available)

            # 线程
            threads = process.threads()
            threads_count.labels(thread_type="active").set(len(threads))

        except ImportError:
            # psutil 未安装，跳过系统指标采集
            pass
        except Exception:
            pass

    @staticmethod
    def set_db_connections(db_name: str, active_count: int) -> None:
        """设置数据库活跃连接数"""
        db_connections_active.labels(db_name=db_name).set(active_count)


__all__ = ["SystemMetricsCollector"]
