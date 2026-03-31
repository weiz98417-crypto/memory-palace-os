"""
工业级大语言模型客户端封装 (LLM Wrapper) - 异步版本

核心变更：
1. OpenAI 客户端从 `OpenAI` 改为 `AsyncOpenAI` (官方原生异步支持)
2. 所有网络 IO 方法添加 `async` 前缀与 `await` 调用
3. 同步的 `time.sleep` 改为异步的 `asyncio.sleep` (防止阻塞事件循环)

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import json
import re
import asyncio  ### CHANGE: 导入 asyncio 用于异步 sleep
import time
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass
from loguru import logger

### CHANGE: 从 openai 导入 AsyncOpenAI 替代 OpenAI
from openai import AsyncOpenAI, APIConnectionError, RateLimitError, APITimeoutError, InternalServerError


@dataclass
class LLMResponse:
    """标准化的 LLM 响应数据传输对象 (DTO)"""
    content: str
    tokens_used: int
    model_name: str
    latency_seconds: float


class LLMClient:
    """大模型核心调度客户端 (异步版本)"""

    def __init__(self):
        ### CHANGE: 类型注解改为 AsyncOpenAI
        self._client: Optional[AsyncOpenAI] = None
        self.default_model = os.environ.get("LLM_DEFAULT_MODEL", "gpt-4o")
        self.max_retries = int(os.environ.get("LLM_MAX_RETRIES", 3))
        self.base_backoff = 2.0

    ### CHANGE: 改为 async 方法，返回 AsyncOpenAI
    async def get_client(self) -> AsyncOpenAI:
        """获取或初始化异步 OpenAI 客户端（单例懒加载）"""
        if self._client is None:
            api_key = os.environ.get("OPENAI_API_KEY")
            base_url = os.environ.get("OPENAI_BASE_URL")
            if not api_key:
                logger.warning("未检测到 OPENAI_API_KEY 环境变量，LLM 调用将会失败。")
            
            ### CHANGE: 使用 AsyncOpenAI 替代 OpenAI
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=float(os.environ.get("LLM_TIMEOUT", 30.0)),
                max_retries=0
            )
        return self._client

    ### CHANGE: 方法添加 async 前缀
    async def ask(self, 
            system_prompt: str, 
            user_prompt: str, 
            model: Optional[str] = None,
            temperature: float = 0.3,
            json_mode: bool = False,
            trace_id: str = "UNKNOWN") -> LLMResponse:
        """
        发起大模型调用，自带指数退避重试与防抖机制 (异步版本)。
        """
        actual_model = model or self.default_model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        kwargs = {
            "model": actual_model,
            "messages": messages,
            "temperature": temperature,
        }
        
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"[Trace-{trace_id}] 开始请求 LLM (Attempt {attempt}/{self.max_retries}) | Model: {actual_model}")
                start_time = time.time()
                
                ### CHANGE: 添加 await，并调用异步客户端方法
                client = await self.get_client()
                response = await client.chat.completions.create(**kwargs)
                
                latency = time.time() - start_time
                content = response.choices[0].message.content or ""
                tokens = response.usage.total_tokens if response.usage else 0
                
                logger.info(f"[Trace-{trace_id}] LLM 响应成功 | 耗时: {latency:.2f}s | Tokens: {tokens}")
                
                return LLMResponse(
                    content=content, 
                    tokens_used=tokens, 
                    model_name=actual_model,
                    latency_seconds=latency
                )

            except RateLimitError as e:
                last_exception = e
                wait_time = self.base_backoff * (2 ** (attempt - 1))
                logger.warning(f"[Trace-{trace_id}] 触发 API 限流 (RateLimit)，{wait_time}秒后重试... 详情: {e}")
                ### CHANGE: time.sleep 改为 asyncio.sleep，避免阻塞事件循环
                await asyncio.sleep(wait_time)
                
            except (APIConnectionError, APITimeoutError) as e:
                last_exception = e
                wait_time = self.base_backoff * attempt
                logger.warning(f"[Trace-{trace_id}] 网络抖动或超时，{wait_time}秒后重试... 详情: {e}")
                await asyncio.sleep(wait_time)  ### CHANGE
                
            except InternalServerError as e:
                last_exception = e
                logger.warning(f"[Trace-{trace_id}] 大模型服务端内部错误 (500)，2秒后重试... 详情: {e}")
                await asyncio.sleep(2.0)  ### CHANGE
                
            except Exception as e:
                logger.error(f"[Trace-{trace_id}] LLM 调用发生未捕获的致命异常: {e}")
                raise RuntimeError(f"LLM 致命异常: {str(e)}") from e

        logger.error(f"[Trace-{trace_id}] LLM 接口历经 {self.max_retries} 次重试后彻底失败。")
        raise last_exception

    ### CHANGE: 解析方法改为 async (虽然纯 CPU 操作，但保持接口一致性)
    async def parse_json(self, content: str, trace_id: str = "UNKNOWN") -> Dict[str, Any]:
        """
        工业级 JSON 解析器 (异步版本)：
        注：JSON 解析本身是 CPU 密集型，但为保持与 ask() 的调用一致性，提供 async 接口。
        实际实现仍使用同步 json.loads，因为 GIL 锁下 json 解析很快，无需线程池。
        """
        if not content or not content.strip():
            logger.error(f"[Trace-{trace_id}] LLM 返回内容为空，无法解析为 JSON。")
            return {}

        content = content.strip()

        # 黄金路径
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass 

        # 银色防线：正则提取 Markdown 代码块
        json_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
        matches = json_pattern.findall(content)
        
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue

        # 青铜防线：暴力查找第一个 { 和最后一个 }
        try:
            start = content.index('{')
            end = content.rindex('}') + 1
            return json.loads(content[start:end])
        except (ValueError, json.JSONDecodeError):
            pass

        logger.error(f"[Trace-{trace_id}] 无法从 LLM 输出中提取有效 JSON。原始内容: {content[:200]}...")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# 全局 LLM 客户端单例
# ─────────────────────────────────────────────────────────────────────────────
llm_client = LLMClient()


def get_llm_client() -> LLMClient:
    """获取 LLM 客户端单例"""
    return llm_client