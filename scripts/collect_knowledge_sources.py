"""Collect source material for knowledge/SOP authoring through the AnySearch API.

Results are stored verbatim (title, url, snippet, content) so every imported SOP can be
traced back to what was actually retrieved. Set ``ANYSEARCH_API_KEY`` for higher rate
limits; anonymous access works with lower limits.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://api.anysearch.com/v1/search"

DEFAULT_QUERIES = [
    "场（厂）内专用机动车辆 观光车 安全技术规程 日常检查 制动 轮胎",
    "旅游景区 观光车 雨后 复运 检查 要求",
    "旅游景区 客流 高峰 分流 限流 管理规范",
    "暴雨 强降雨 景区 设施 检查 恢复运营 要求",
    "旅游景区 突发事件 应急预案 设备故障 处置",
    "景区 观光车 驾驶员 资质 培训 限速 载客 规定",
    "景区 观光车 充电 电池 安全 管理",
    "景区 游船 安全 检查 救生衣 载客 定额",
    "景区 索道 缆车 安全检查 应急救援",
    "大型游乐设施 安全检查 定期检验 运营要求",
    "玻璃栈道 高空项目 安全管理 检查",
    "漂流 项目 安全 管理 检查 规范",
    "滑索 滑道 安全检查 规范",
    "景区 消防 安全 检查 灭火器 疏散通道",
    "森林防火 景区 管理 火源管控",
    "景区 防汛 应急预案 边坡 落石 排查",
    "地质灾害 隐患 排查 景区 巡查",
    "雷电 大风 天气 景区 安全 防护",
    "景区 最大承载量 核定 限流 措施",
    "景区 拥挤踩踏 预防 疏散 通道",
    "景区 医疗急救 救援站 配置 要求",
    "景区 食品安全 管理 检查",
    "景区 卫生 防疫 消杀 要求",
    "景区 夜游 照明 安全 管理",
    "景区 票务系统 闸机 故障 应急 处置",
    "景区 广播 监控 系统 管理 要求",
    "景区 反恐 防暴 治安 管理",
    "景区 大型活动 安全 管理 审批",
    "景区 特种设备 安全 管理 制度 台账",
    "景区 设备 维保 外包 单位 管理",
    "景区 隐患 排查 治理 闭环 管理",
    "景区 应急预案 演练 要求",
    "景区 游客 投诉 处理 流程",
    "景区 临时 闭园 恢复 开放 程序",
    "景区 安全生产 责任制 岗位职责",
    "旅游景区 智慧 监测 客流 预警 系统",
]


def search(client: httpx.Client, query: str, max_results: int) -> dict:
    """Search once, retrying politely when the service throttles anonymous traffic."""
    headers = {"Content-Type": "application/json", "X-Anysearch-Client": "mcp/1.0.0"}
    api_key = os.environ.get("ANYSEARCH_API_KEY", "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    delay = 5.0
    for attempt in range(4):
        response = client.post(
            ENDPOINT,
            json={"query": query, "max_results": max_results},
            headers=headers,
        )
        if response.status_code == 429 or response.status_code >= 500 or "rate" in response.text.lower():
            if attempt == 3:
                raise SystemExit(f"anysearch rate limited on {query!r}; set ANYSEARCH_API_KEY")
            time.sleep(delay)
            delay *= 2
            continue
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise SystemExit(f"anysearch error for {query!r}: {payload.get('message')}")
        return payload
    raise SystemExit(f"anysearch failed for {query!r}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", dest="queries", default=[])
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "knowledge" / "anysearch-raw.json",
    )
    parser.add_argument("--pause", type=float, default=1.5, help="seconds between queries")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip queries already present in the output file and append new ones",
    )
    args = parser.parse_args()

    queries = args.queries or DEFAULT_QUERIES
    document = {
        "endpoint": ENDPOINT,
        "authenticated": bool(os.environ.get("ANYSEARCH_API_KEY", "").strip()),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "queries": [],
    }
    if args.resume and args.output.is_file():
        document = json.loads(args.output.read_text(encoding="utf-8"))
        document["authenticated"] = bool(os.environ.get("ANYSEARCH_API_KEY", "").strip())
    done = {item["query"] for item in document["queries"]}
    with httpx.Client(timeout=60.0) as client:
        pending = [query for query in queries if query not in done]
        for index, query in enumerate(pending):
            payload = search(client, query, args.max_results)
            document["queries"].append(
                {"query": query, "request_id": payload.get("request_id"), "results": payload["data"]["results"]}
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{index + 1}/{len(pending)}] {query}: {len(payload['data']['results'])} results")
            if index < len(pending) - 1:
                time.sleep(args.pause)
    print(f"saved {args.output} ({len(document['queries'])} queries total)")


if __name__ == "__main__":
    main()
