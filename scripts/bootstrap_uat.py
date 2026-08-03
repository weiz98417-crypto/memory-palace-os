"""Initialize the frozen enterprise UAT baseline through the running API."""

from __future__ import annotations

import asyncio
import sys

from src.memory_palace.operations.uat_bootstrap import (
    UATBootstrapConfig,
    UATBootstrapError,
    bootstrap_uat_master_data,
)


async def _run() -> int:
    try:
        config = UATBootstrapConfig.from_environment()
        result = await bootstrap_uat_master_data(config)
    except UATBootstrapError as exc:
        print(f"UAT 主数据初始化失败：{exc}", file=sys.stderr)
        return 1
    print(
        f"UAT 主数据已就绪：{result.organization_name} / {result.venue_name}，"
        f"{result.user_count} 名角色、{result.identity_count} 个企微映射、"
        f"SOP {result.sop_version}、专家 {result.expert_name}。"
    )
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
