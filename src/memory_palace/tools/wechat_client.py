"""Disabled compatibility surface for the real WeCom transport."""

from __future__ import annotations

from typing import NoReturn, Optional

from loguru import logger

from src.memory_palace.config.integration_readiness import REAL_WECOM_BLOCKED_REASON


class WeChatWorkClient:
    """Reject direct construction so no code can reach the real WeCom network."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise RuntimeError(REAL_WECOM_BLOCKED_REASON)

    async def send_text(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError(REAL_WECOM_BLOCKED_REASON)

    async def send_markdown(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError(REAL_WECOM_BLOCKED_REASON)

    async def send_textcard(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError(REAL_WECOM_BLOCKED_REASON)

    async def send_confirm_card(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise RuntimeError(REAL_WECOM_BLOCKED_REASON)


_wechat_client: Optional[WeChatWorkClient] = None


def get_wechat_client() -> Optional[WeChatWorkClient]:
    """Return no transport; all WeCom work belongs to the simulator."""

    logger.info("{}", REAL_WECOM_BLOCKED_REASON)
    return None
