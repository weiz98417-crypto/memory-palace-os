#!/usr/bin/env python3
"""
context_trigger_skill.py · 情境触发专家调试工具

对应 docx 中描述的测试命令：

    # 测试单条消息是否触发
    python scripts/context_trigger_skill.py --test "游客在B区突然晕倒了"

    # 批量测试一组消息（每行一条）
    python scripts/context_trigger_skill.py --batch test_messages.txt

    # 查看某次推送的完整上下文
    python scripts/context_trigger_skill.py --explain-push <push_log_id>

用法示例：
    cd memory-palace-os
    python scripts/context_trigger_skill.py --test "游客在B区突然晕倒了"
    python scripts/context_trigger_skill.py --batch test_messages.txt
    python scripts/context_trigger_skill.py --explain-push abc123
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

# 添加 src 到 path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# 直接导入 keywords 模块，避免触发整个 skills.__init__.py 的导入链
import importlib.util
keywords_spec = importlib.util.spec_from_file_location(
    "context_trigger_keywords",
    Path(__file__).parent.parent / "src" / "memory_palace" / "skills" / "context_trigger" / "keywords.py"
)
keywords_mod = importlib.util.module_from_spec(keywords_spec)
keywords_spec.loader.exec_module(keywords_mod)

KeywordMatcher = keywords_mod.KeywordMatcher
TRIGGER_KEYWORDS = keywords_mod.TRIGGER_KEYWORDS
EXCLUDE_KEYWORDS = keywords_mod.EXCLUDE_KEYWORDS


class ContextTriggerTester:
    """
    ContextTrigger 调试工具

    提供以下功能：
    1. 单条消息测试 (--test)
    2. 批量消息测试 (--batch)
    3. 推送上下文解释 (--explain-push)
    """

    def __init__(self, scenic_types: List[str] = None):
        self.matcher = KeywordMatcher(
            include_scenic_types=scenic_types or [],
            enable_extended=True
        )

    def test_single(self, message: str) -> Dict:
        """
        测试单条消息

        Returns:
            {
                "message": str,
                "stage1": {
                    "excluded": bool,
                    "triggered": bool,
                    "hit_keywords": List[str],
                    "hit_categories": List[str],
                    "should_process": bool
                },
                "stage2": {...} or null,
                "should_trigger": bool
            }
        """
        print(f"\n{'='*60}")
        print(f"测试消息: {message}")
        print(f"{'='*60}")

        # Stage1 关键词匹配
        stage1_result = self.matcher.match(message)
        print(f"\n[Stage1 关键词匹配结果]")
        print(f"  排除: {stage1_result['excluded']}")
        print(f"  触发: {stage1_result['triggered']}")
        print(f"  命中关键词: {stage1_result['hit_keywords']}")
        print(f"  命中分类: {stage1_result['hit_categories']}")
        print(f"  应进入Stage2: {stage1_result['should_process']}")

        result = {
            "message": message,
            "stage1_result": stage1_result,
            "stage2_result": None,
            "should_trigger": False
        }

        # 如果被排除，跳过 Stage2
        if stage1_result["excluded"]:
            print(f"\n[结论] 消息被 Stage1 EXCLUDE 规则排除，不进入 Stage2")
            return result

        # Stage2 提示（不实际调用 LLM）
        if stage1_result["triggered"]:
            print(f"\n[Stage2 提示] Stage1 触发，应进入 LLM 语义判断")
            print(f"  LLM 应判断为: trigger=true（关键词命中 + 语义明确）")
            result["should_trigger"] = True
        else:
            print(f"\n[Stage2 提示] Stage1 未触发，但 fallback_to_llm=true 会进入 LLM")
            print(f"  LLM 判断结果不确定，取决于语义分析")

        return result

    def test_batch(self, file_path: str) -> List[Dict]:
        """
        批量测试

        Args:
            file_path: 每行一条消息的文本文件路径
        """
        path = Path(file_path)
        if not path.exists():
            print(f"错误: 文件不存在 {file_path}")
            return []

        messages = path.read_text(encoding="utf-8").strip().split("\n")
        messages = [m.strip() for m in messages if m.strip()]

        print(f"\n{'='*60}")
        print(f"批量测试: {len(messages)} 条消息")
        print(f"{'='*60}")

        results = []
        stats = {
            "total": len(messages),
            "excluded": 0,
            "triggered": 0,
            "no_trigger": 0
        }

        for idx, msg in enumerate(messages, 1):
            print(f"\n[{idx}/{len(messages)}] ", end="")
            result = self.test_single(msg)
            results.append(result)

            if result["stage1_result"]["excluded"]:
                stats["excluded"] += 1
            elif result["stage1_result"]["triggered"]:
                stats["triggered"] += 1
            else:
                stats["no_trigger"] += 1

        # 打印统计
        print(f"\n{'='*60}")
        print(f"批量测试统计")
        print(f"{'='*60}")
        print(f"  总消息数: {stats['total']}")
        print(f"  被排除 (EXCLUDE): {stats['excluded']} ({stats['excluded']/stats['total']*100:.1f}%)")
        print(f"  触发关键词: {stats['triggered']} ({stats['triggered']/stats['total']*100:.1f}%)")
        print(f"  未触发关键词: {stats['no_trigger']} ({stats['no_trigger']/stats['total']*100:.1f}%)")
        print(f"\n  预估 Stage2 LLM 调用量: {stats['triggered'] + stats['no_trigger']} 条")
        print(f"  相比全量 LLM 调用节省: {stats['excluded']/stats['total']*100:.1f}%")

        return results

    def explain_push(self, push_log_id: str):
        """
        查看某次推送的完整上下文

        Args:
            push_log_id: 推送日志 ID
        """
        import asyncio
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

        async def _fetch_and_print():
            try:
                # 懒加载避免触发无依赖模块
                from memory_palace.knowledge.push_logger import get_push_log
                log = await get_push_log(push_log_id)
                if log:
                    self._print_push_context(log)
                else:
                    print(f"\n[ERROR] 未找到 push_id={push_log_id} 的推送日志")
            except Exception as e:
                print(f"\n[ERROR] 查询推送日志失败: {e}")

        asyncio.run(_fetch_and_print())

    def _print_push_context(self, log: Dict):
        """打印推送上下文详情"""
        print(f"\n{'='*60}")
        print(f"推送日志详情: {log.get('push_id', 'N/A')}")
        print(f"{'='*60}")
        print(f"  原始消息: {log.get('original_message', 'N/A')}")
        print(f"  触发关键词: {log.get('trigger_keywords', [])}")
        print(f"  Stage2 判断: {log.get('stage2_result', {})}")
        print(f"  推送时间: {log.get('push_time', 'N/A')}")
        print(f"  员工响应: {log.get('employee_response', 'N/A')}")

    def print_keyword_library(self):
        """打印关键词库汇总"""
        print(f"\n{'='*60}")
        print(f"关键词库汇总")
        print(f"{'='*60}")

        print(f"\n[TRIGGER_KEYWORDS 触发词库]")
        for cat_name, cat in TRIGGER_KEYWORDS.items():
            print(f"\n  {cat_name} ({cat.name}):")
            print(f"    描述: {cat.description}")
            print(f"    关键词: {', '.join(cat.keywords)}")

        print(f"\n\n[EXCLUDE_KEYWORDS 排除词库]")
        for cat_name, cat in EXCLUDE_KEYWORDS.items():
            print(f"\n  {cat_name} ({cat.name}):")
            print(f"    描述: {cat.description}")
            print(f"    关键词: {', '.join(cat.keywords)}")


def main():
    parser = argparse.ArgumentParser(
        description="ContextTrigger 调试工具 - 对应 docx 中的关键词调参流程"
    )

    parser.add_argument(
        "--test",
        type=str,
        help="测试单条消息是否触发。例如: --test \"游客在B区突然晕倒了\""
    )

    parser.add_argument(
        "--batch",
        type=str,
        help="批量测试消息文件（每行一条）。例如: --batch test_messages.txt"
    )

    parser.add_argument(
        "--explain-push",
        type=str,
        help="查看某次推送的完整上下文。例如: --explain-push abc123"
    )

    parser.add_argument(
        "--scenic-type",
        type=str,
        nargs="+",
        choices=["ancient_town", "museum", "theme_park", "mountain"],
        help="启用景区扩展关键词。例如: --scenic-type ancient_town museum"
    )

    parser.add_argument(
        "--print-keywords",
        action="store_true",
        help="打印完整的关键词库"
    )

    args = parser.parse_args()

    # 初始化测试器
    tester = ContextTriggerTester(scenic_types=args.scenic_type)

    # 执行
    if args.print_keywords:
        tester.print_keyword_library()
    elif args.test:
        tester.test_single(args.test)
    elif args.batch:
        tester.test_batch(args.batch)
    elif args.explain_push:
        tester.explain_push(args.explain_push)
    else:
        parser.print_help()
        print("\n\n[示例]")
        print("  python scripts/context_trigger_skill.py --test \"游客在B区突然晕倒了\"")
        print("  python scripts/context_trigger_skill.py --batch test_messages.txt")
        print("  python scripts/context_trigger_skill.py --print-keywords")


if __name__ == "__main__":
    main()
