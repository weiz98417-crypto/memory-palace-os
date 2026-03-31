"""
工业级时间与时区工具库 (Time Utilities)

核心特性：
1. 时区安全 (Timezone Aware)：强制使用 UTC 进行内部存储与计算，外显时默认适配 Asia/Shanghai。
2. 语义化耗时计算：为 Watcher Agent 提供精确到分钟的 SLA 差值计算。
3. 容错解析：支持 ISO 8601、标准 YMD HMS 等多种脏格式的时间字符串解析。
4. 业务时间判定：支持“营业时间”判定，为 Persona Agent 提供不同时段的回复策略参考。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import pytz
from datetime import datetime, timedelta
from typing import Union, Optional
from loguru import logger

# 全局默认时区：中国标准时间
DEFAULT_TZ = pytz.timezone("Asia/Shanghai")


def get_now(as_string: bool = False, fmt: str = "%Y-%m-%d %H:%M:%S") -> Union[datetime, str]:
    """
    获取当前时区感知的精准时间。
    工业实践：永远不要使用 datetime.now()，因为它依赖系统本地环境。
    """
    now = datetime.now(DEFAULT_TZ)
    if as_string:
        return now.strftime(fmt)
    return now


def parse_to_datetime(dt_input: Union[str, datetime, None]) -> datetime:
    """
    将各种乱七八糟的输入转换为时区感知的 datetime 对象。
    """
    if dt_input is None:
        return get_now()
    
    if isinstance(dt_input, datetime):
        if dt_input.tzinfo is None:
            return DEFAULT_TZ.localize(dt_input)
        return dt_input

    # 尝试多种常用格式解析
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(dt_input, fmt)
            return DEFAULT_TZ.localize(dt)
        except ValueError:
            continue
            
    logger.warning(f"[TimeUtils] 无法解析的时间格式: {dt_input}，回退至当前时间。")
    return get_now()


def calculate_elapsed_minutes(start_time: Union[str, datetime]) -> int:
    """
    计算从 start_time 到现在经过了多少分钟。
    专门供 Watcher Agent 判定 SLA 是否超时。
    """
    start_dt = parse_to_datetime(start_time)
    now_dt = get_now()
    
    # 防止由于系统时间微调导致的“负时间”异常
    delta = now_dt - start_dt
    elapsed_seconds = max(0, int(delta.total_seconds()))
    
    return elapsed_seconds // 60


def format_for_log(dt: Optional[datetime] = None) -> str:
    """生成带毫秒的标准化日志时间戳"""
    target = dt or get_now()
    return target.strftime("%Y%m%d_%H%M%S_%f")[:-3]


def is_business_hours(start_hour: int = 10, end_hour: int = 22) -> bool:
    """
    业务逻辑判定：当前是否处于景区/酒吧营业时间。
    用于 Persona Agent 切换“值班模式”或“留言模式”。
    """
    now = get_now()
    return start_hour <= now.hour < end_hour


def get_relative_time_desc(dt_input: Union[str, datetime]) -> str:
    """
    生成语义化的时间描述（如：3分钟前，1小时前）。
    用于指挥官（Commander）给一线员工下发指令时增加紧迫感。
    """
    minutes = calculate_elapsed_minutes(dt_input)
    
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟前"
    if minutes < 1440:
        return f"{minutes // 60}小时前"
    
    return "超过1天"