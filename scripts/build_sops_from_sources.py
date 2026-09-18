"""Turn collected AnySearch material into SOP entries that cite every source.

Each collected query becomes one SOP: the body is a verbatim digest of the retrieved
material with per-source attribution, so nothing is invented. The result is meant as a
source-backed knowledge base for the demo, and is explicitly marked as awaiting the
customer's own procedure review before operational use.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CATEGORY_RULES: tuple[tuple[str, str], ...] = (
    ("消防", "消防与治安"),
    ("森林防火", "消防与治安"),
    ("反恐", "消防与治安"),
    ("治安", "消防与治安"),
    ("客流", "客流与秩序"),
    ("拥挤踩踏", "客流与秩序"),
    ("投诉", "服务与流程"),
    ("医疗", "应急救援"),
    ("急救", "应急救援"),
    ("应急处置", "应急救援"),
    ("应急预案", "应急救援"),
    ("演练", "应急救援"),
    ("暴雨", "天气与防汛"),
    ("强降雨", "天气与防汛"),
    ("防汛", "天气与防汛"),
    ("雷电", "天气与防汛"),
    ("大风", "天气与防汛"),
    ("地质", "地质与边坡"),
    ("边坡", "地质与边坡"),
    ("食品安全", "卫生与防疫"),
    ("防疫", "卫生与防疫"),
    ("特种设备", "设备与安全"),
    ("观光车", "设备与安全"),
    ("游船", "设备与安全"),
    ("索道", "设备与安全"),
    ("游乐", "设备与安全"),
    ("玻璃栈道", "设备与安全"),
    ("漂流", "设备与安全"),
    ("滑索", "设备与安全"),
    ("维保", "设备与安全"),
    ("充电", "设备与安全"),
)

PRIORITY_ONE = ("客流", "消防", "防汛", "暴雨", "强降雨", "特种设备", "观光车", "游船", "索道", "拥挤踩踏")
PRIORITY_TWO = ("应急", "地质", "边坡", "食品", "治安", "反恐", "大型活动", "隐患", "医疗")


def category_for(query: str) -> str:
    for keyword, category in CATEGORY_RULES:
        if keyword in query:
            return category
    return "综合管理"


def priority_for(query: str) -> int:
    if any(keyword in query for keyword in PRIORITY_ONE):
        return 1
    if any(keyword in query for keyword in PRIORITY_TWO):
        return 2
    return 3


def title_for(query: str) -> str:
    cleaned = re.sub(r"\s+", " ", query).strip()
    cleaned = cleaned.replace("旅游景区", "景区")
    return cleaned[:120]


def excerpt(result: dict, limit: int = 320) -> str:
    text = (result.get("content") or result.get("snippet") or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def build_entry(query_record: dict, *, collected_on: str) -> dict:
    query = query_record["query"]
    results = [item for item in query_record.get("results", []) if item.get("url")]
    lines: list[str] = [
        f"【适用场景】{query}",
        f"【整理日期】{collected_on}",
        "【状态】公开来源整理稿，供检索与演示使用；现场执行前须由客户按自身管理制度细化为执行版。",
        "",
        "【来源要点】（逐条摘自公开资料，保留原文与链接）",
    ]
    sources: list[str] = []
    for index, result in enumerate(results[:6], start=1):
        title = (result.get("title") or "未命名来源").strip()
        url = result["url"]
        text = excerpt(result)
        lines.append(f"{index}. {title}")
        lines.append(f"   {text}")
        lines.append(f"   来源：{url}")
        sources.append(f"- {title} {url}")
    lines.append("")
    lines.append("【检索关键词】" + " / ".join(part for part in query.split() if part))
    lines.append("")
    lines.append("【来源清单】")
    lines.extend(sources)
    content = "\n".join(lines)
    return {
        "title": title_for(query),
        "category": category_for(query),
        "priority": priority_for(query),
        "version": "1.0",
        "source_url": results[0]["url"] if results else "",
        "tags": [part for part in query.split() if part][:8],
        "content": content[:29000],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "knowledge" / "anysearch-raw.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "knowledge" / "sops.json",
    )
    parser.add_argument("--min-sources", type=int, default=2, help="skip topics with fewer sources")
    args = parser.parse_args()

    raw = json.loads(args.raw.read_text(encoding="utf-8"))
    collected_on = str(raw.get("collected_at", ""))[:10] or date.today().isoformat()
    entries = [
        build_entry(record, collected_on=collected_on)
        for record in raw.get("queries", [])
        if len(record.get("results", [])) >= args.min_sources
    ]
    document = {
        "note": (
            "由 AnySearch 公开来源整理生成；每条 SOP 内含逐条引用与链接，未编造内容。"
            "正式交付前需客户按自身制度复核并替换为内部执行版。"
        ),
        "generated_from": str(args.raw),
        "collected_on": collected_on,
        "entries": entries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"built {len(entries)} SOP entries -> {args.output}")


if __name__ == "__main__":
    main()
