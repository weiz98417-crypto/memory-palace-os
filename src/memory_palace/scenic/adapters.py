"""Deterministic external-input Adapters for the first scenic-area story."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MonitoringSignal:
    offset_seconds: int
    source_type: str
    source_adapter: str
    source_key: str
    zone_id: str
    signal_type: str
    payload: dict[str, Any]


class WeatherAdapter:
    def story_signals(self) -> tuple[MonitoringSignal, ...]:
        return (
            MonitoringSignal(
                1,
                "WEATHER",
                "LOCAL_WEATHER_ADAPTER",
                "weather-main",
                "mountain-road",
                "RAIN_STATUS",
                {
                    "rainfall_mm_6h": 38.0,
                    "is_raining": False,
                    "condition": "POST_RAIN_RECHECK",
                    "label": "连续降雨结束，进入雨后复检窗口",
                },
            ),
        )


class DeviceAdapter:
    def story_signals(self) -> tuple[MonitoringSignal, ...]:
        return (
            MonitoringSignal(
                2,
                "DEVICE",
                "LOCAL_DEVICE_ADAPTER",
                "vehicle-12",
                "vehicle-depot",
                "VEHICLE_HEALTH",
                {
                    "vehicle_no": "12",
                    "status": "FAULT",
                    "fault_code": "RIGHT_REAR_WHEEL_ABNORMAL",
                    "vibration_mm_s": 9.4,
                    "threshold_mm_s": 6.0,
                    "label": "12 号观光车右后轮异常",
                },
            ),
            MonitoringSignal(
                90,
                "DEVICE",
                "LOCAL_DEVICE_ADAPTER",
                "vehicle-12",
                "vehicle-depot",
                "VEHICLE_HEALTH",
                {
                    "vehicle_no": "12",
                    "status": "ISOLATED",
                    "fault_code": None,
                    "vibration_mm_s": 0.0,
                    "threshold_mm_s": 6.0,
                    "label": "12 号观光车已隔离，设备风险解除",
                },
            ),
        )


class CrowdAdapter:
    def story_signals(self) -> tuple[MonitoringSignal, ...]:
        return (
            MonitoringSignal(
                30,
                "CROWD",
                "LOCAL_CROWD_ADAPTER",
                "east-gate-counter",
                "east-gate",
                "ZONE_OCCUPANCY",
                {
                    "people": 1360,
                    "capacity_threshold": 1200,
                    "trend": "RISING",
                    "label": "东门客流上升并超过容量阈值",
                },
            ),
            MonitoringSignal(
                90,
                "CROWD",
                "LOCAL_CROWD_ADAPTER",
                "east-gate-counter",
                "east-gate",
                "ZONE_OCCUPANCY",
                {
                    "people": 820,
                    "capacity_threshold": 1200,
                    "trend": "FALLING",
                    "label": "东门客流恢复安全范围",
                },
            ),
        )


class FirstScenicStory:
    key = "rain_vehicle_east_gate"
    version = "1.0.0"
    start_time = 1789437600.0

    def __init__(self) -> None:
        self.adapters = (WeatherAdapter(), DeviceAdapter(), CrowdAdapter())

    def due(self, previous_elapsed: int, current_elapsed: int) -> list[MonitoringSignal]:
        signals = [
            signal
            for adapter in self.adapters
            for signal in adapter.story_signals()
            if previous_elapsed < signal.offset_seconds <= current_elapsed
        ]
        return sorted(signals, key=lambda item: item.offset_seconds)


STORY = FirstScenicStory()
