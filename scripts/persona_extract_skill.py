#!/usr/bin/env python3
"""
persona_extract_skill.py · 老员工经验萃取调试工具

用法示例：
    cd memory-palace-os
    python scripts/persona_extract_skill.py --start "安保组长"
    python scripts/persona_extract_skill.py --continue <interview_id> "游客突然晕倒了..."
    python scripts/persona_extract_skill.py --finalize <interview_id>
    python scripts/persona_extract_skill.py --list
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 添加 src 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class PersonaExtractTester:
    """PersonaExtract 调试工具"""

    def __init__(self):
        self._skill = None
        self._state: Dict[str, str] = {}  # interview_id -> job_title

    def _get_skill(self):
        if self._skill is None:
            from memory_palace.skills.persona_extract import PersonaExtractSkill
            self._skill = PersonaExtractSkill()
        return self._skill

    async def start_interview(self, job_title: str, venue_id: str = "default_venue") -> Dict:
        """开始访谈"""
        skill = self._get_skill()
        context = {
            "action": "start",
            "job_title": job_title,
            "venue_id": venue_id,
        }
        result = await skill.run(context, trace_id="test")
        return result

    async def continue_interview(self, interview_id: str, answer: str) -> Dict:
        """继续访谈"""
        skill = self._get_skill()
        context = {
            "action": "continue",
            "interview_id": interview_id,
            "answer": answer,
        }
        result = await skill.run(context, trace_id="test")
        return result

    async def finalize(self, interview_id: str) -> Dict:
        """完成访谈"""
        skill = self._get_skill()
        context = {
            "action": "finalize",
            "interview_id": interview_id,
        }
        result = await skill.run(context, trace_id="test")
        return result

    def print_result(self, result, label: str):
        """打印结果"""
        print(f"\n{'='*60}")
        print(f"{label}")
        print(f"{'='*60}")
        print(f"success: {result.success}")
        if result.reply_text:
            print(f"\n[回复文本]\n{result.reply_text[:500]}")
        if result.structured_data:
            import json
            print(f"\n[结构化数据]")
            print(json.dumps(result.structured_data, ensure_ascii=False, indent=2))
        print(f"action_taken: {result.action_taken}")


async def main():
    parser = argparse.ArgumentParser(description="PersonaExtract 调试工具")
    parser.add_argument("--start", type=str, help="开始访谈，参数为岗位名称")
    parser.add_argument("--next", nargs=2, type=str, metavar=("INTERVIEW_ID", "ANSWER"),
                        help="继续访谈")
    parser.add_argument("--finalize", type=str, metavar="INTERVIEW_ID",
                        help="完成访谈")
    parser.add_argument("--venue-id", type=str, default="default_venue",
                        help="景区ID（默认: default_venue）")

    args = parser.parse_args()

    tester = PersonaExtractTester()

    if args.start:
        print(f"\n开始访谈: 岗位={args.start}, 景区={args.venue_id}")
        result = await tester.start_interview(args.start, args.venue_id)
        tester.print_result(result, "访谈已开始")
        if result.structured_data and result.structured_data.get("interview_id"):
            print(f"\n[记录] interview_id = {result.structured_data.get('interview_id')}")

    elif args.next:
        interview_id, answer = args.next
        print(f"\n继续访谈: id={interview_id}")
        print(f"员工回答: {answer[:50]}...")
        result = await tester.continue_interview(interview_id, answer)
        tester.print_result(result, "继续访谈结果")

    elif args.finalize:
        print(f"\n完成访谈: id={args.finalize}")
        result = await tester.finalize(args.finalize)
        tester.print_result(result, "访谈完成")
        if result.structured_data and result.structured_data.get("persona_id"):
            print(f"\n[成功] persona_id = {result.structured_data.get('persona_id')}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
