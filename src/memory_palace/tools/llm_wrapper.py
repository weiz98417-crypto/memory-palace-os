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

    def _demo_json(self, system_prompt: str) -> str:
        """DEMO_MODE 下根据 system_prompt 推断并返回合法的 JSON 响应"""
        import json as _json
        sp = system_prompt.lower()
        # ContextTrigger Stage2: 触发判断
        if "trigger" in sp and "severity" in sp and "event_type" in sp:
            return _json.dumps({
                "trigger": False,
                "severity": "P3",
                "event_type": "其他",
                "confidence": 0.1,
                "reason": "DEMO_MODE mock",
            }, ensure_ascii=False)
        # Router: 意图识别
        if "intent" in sp and ("chitchat" in sp or "incident" in sp or "emergency" in sp):
            return _json.dumps({
                "intent": "chitchat",
                "severity": "P3",
                "confidence": 0.5,
            }, ensure_ascii=False)
        # Persona: 人设回复
        if "reply_text" in sp or "persona" in sp or "回复" in sp:
            return _json.dumps({
                "reply_text": "[DEMO] 这是模拟的文旅助手回复。在实际部署中，这里会由 LLM 生成个性化的游客服务回复。",
                "reply_type": "text",
                "tokens_used": 0,
            }, ensure_ascii=False)
        # Commander/TODO: 任务分解
        if "task" in sp and "dependency" in sp:
            return _json.dumps({
                "tasks": [{"title": "DEMO 示例任务", "description": "模拟任务", "priority": "P3", "dependencies": []}],
            }, ensure_ascii=False)
        # Fallback: generic JSON
        return _json.dumps({"status": "ok", "message": "DEMO_MODE mock"}, ensure_ascii=False)

    ### CHANGE: 方法添加 async 前缀
    async def ask(self,
            system_prompt: str,
            user_prompt: str,
            model: Optional[str] = None,
            temperature: float = 0.3,
            max_tokens: Optional[int] = None,
            json_mode: bool = False,
            trace_id: str = "UNKNOWN") -> LLMResponse:
        """
        发起大模型调用，自带指数退避重试与防抖机制 (异步版本)。
        """
        # MOCK_LLM: 独立控制 LLM mock（DEMO_MODE 不再强制 mock LLM）
        if os.environ.get("MOCK_LLM", "").lower() == "true":
            logger.info(f"[Trace-{trace_id}] MOCK_LLM: 返回 Mock 响应 (json={json_mode})")
            if json_mode:
                # 根据 system_prompt 推断 skill 类型，返回合法的 JSON
                mock_content = self._demo_json(system_prompt)
            else:
                mock_content = f"[DEMO] 模拟回复: {user_prompt[:40]}..."
            return LLMResponse(
                content=mock_content,
                tokens_used=0,
                model_name="demo",
                latency_seconds=0.0,
            )

        env_model = os.environ.get("LLM_DEFAULT_MODEL", "")
        actual_model = env_model or model or self.default_model
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        kwargs = {
            "model": actual_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        
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

    async def ask_with_reference_context(
        self,
        system_prompt: str,
        context_messages: list,
        user_prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.3,
        trace_id: str = "UNKNOWN"
    ) -> LLMResponse:
        """
        [新] 带参考上下文的 LLM 调用

        用于三层上下文压缩系统:
        - context_messages: 从 Cold -> Warm -> Hot 组装的消息列表
        - system_prompt: 系统提示词
        - user_prompt: 当前用户输入

        Args:
            system_prompt: 系统提示词
            context_messages: 格式化的上下文消息 [{"role": "...", "content": "..."}]
            user_prompt: 当前用户输入
            model: 模型名称
            temperature: 温度参数
            trace_id: 追踪 ID

        Returns:
            LLMResponse
        """
        if os.environ.get("MOCK_LLM", "").lower() == "true":
            logger.info(f"[Trace-{trace_id}] MOCK_LLM: 返回 Mock 响应 (with context)")
            return LLMResponse(
                content=f"[DEMO] Mock response with {len(context_messages)} context messages",
                tokens_used=0,
                model_name="demo",
                latency_seconds=0.0,
            )

        env_model = os.environ.get("LLM_DEFAULT_MODEL", "")
        actual_model = env_model or model or self.default_model

        messages = [
            {"role": "system", "content": system_prompt}
        ]

        # 添加上下文消息 (通常是 system 角色)
        messages.extend(context_messages)

        # 添加当前用户输入
        messages.append({"role": "user", "content": user_prompt})

        kwargs = {
            "model": actual_model,
            "messages": messages,
            "temperature": temperature,
        }

        last_exception = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(f"[Trace-{trace_id}] 开始请求 LLM (Attempt {attempt}/{self.max_retries}) | Model: {actual_model}")
                start_time = time.time()

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
                await asyncio.sleep(wait_time)

            except (APIConnectionError, APITimeoutError) as e:
                last_exception = e
                wait_time = self.base_backoff * attempt
                logger.warning(f"[Trace-{trace_id}] 网络抖动或超时，{wait_time}秒后重试... 详情: {e}")
                await asyncio.sleep(wait_time)

            except InternalServerError as e:
                last_exception = e
                logger.warning(f"[Trace-{trace_id}] 大模型服务端内部错误 (500)，2秒后重试... 详情: {e}")
                await asyncio.sleep(2.0)

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


# =============================================================================
# LLM Output Sanitization Utility
# =============================================================================

INJECTION_TOKENS = [
    "<|im_start|>", "<|im_end|>", "<|im_sep|>",
    "[system]", "[/system]", "[INST]", "[/INST]",
    "<system>", "</system>", "<|system|>",
]

_SANITIZE_SCHEMAS: Dict[str, Dict[str, Any]] = {}


def register_sanitize_schema(name: str, schema: Dict[str, Any]) -> None:
    """注册一个消毒 schema，供 sanitize_llm_output 按名称调用。"""
    _SANITIZE_SCHEMAS[name] = schema


def sanitize_llm_output(
    data: Any,
    schema_name: str,
    *,
    trace_id: str = "UNKNOWN",
) -> tuple:
    """
    消毒 LLM 生成的输出数据，返回 (cleaned_data, warnings)。

    schema_name 指向预注册的 schema dict，结构：
        {
            "fields": {
                "field_name": {"type": "str", "max_len": 500, "required": True},
                ...
            },
            "allow_unknown": False,
        }

    消毒规则：
    1. required 字段必须存在且非空（str 时）
    2. type 不匹配 → 尝试强制转换，失败则设为默认值
    3. 字符串超过 max_len → 截断
    4. 删除控制字符（ASCII 0-31 除 \\n \\r \\t）
    5. 检测并移除注入 token → 记录警告
    """
    schema = _SANITIZE_SCHEMAS.get(schema_name)
    if not schema:
        logger.warning(f"[Trace-{trace_id}] 消毒 schema '{schema_name}' 未注册，跳过消毒")
        return data, [f"schema '{schema_name}' not found — bypassed"]

    warnings: list[str] = []
    fields = schema.get("fields", {})
    allow_unknown = schema.get("allow_unknown", False)

    if not isinstance(data, dict):
        return {}, ["input is not a dict — rejected"]

    cleaned: Dict[str, Any] = {}

    for field_name, field_spec in fields.items():
        required = field_spec.get("required", False)
        expected_type = field_spec.get("type", "str")
        max_len = field_spec.get("max_len")

        value = data.get(field_name)

        if required and (value is None or (isinstance(value, str) and not value.strip())):
            warnings.append(f"required field '{field_name}' missing or empty — rejected")
            continue

        if value is None:
            cleaned[field_name] = field_spec.get("default")
            continue

        if expected_type == "str":
            if not isinstance(value, str):
                value = str(value)
            value = _strip_control_chars(value)
            value = _remove_injection_tokens(value, field_name, warnings)
            if max_len is not None and len(value) > max_len:
                value = value[:max_len]
                warnings.append(f"'{field_name}' truncated to {max_len} chars")

        elif expected_type == "int":
            try:
                value = int(value)
            except (ValueError, TypeError):
                warnings.append(f"'{field_name}' expected int, got {type(value).__name__} — set to 0")
                value = 0

        elif expected_type == "float":
            try:
                value = float(value)
            except (ValueError, TypeError):
                warnings.append(f"'{field_name}' expected float, got {type(value).__name__} — set to 0.0")
                value = 0.0

        elif expected_type == "bool":
            if not isinstance(value, bool):
                value = bool(value)

        elif expected_type == "list":
            if not isinstance(value, list):
                warnings.append(f"'{field_name}' expected list, got {type(value).__name__} — set to []")
                value = []

        elif expected_type == "dict":
            if not isinstance(value, dict):
                warnings.append(f"'{field_name}' expected dict, got {type(value).__name__} — set to {{}}")
                value = {}

        cleaned[field_name] = value

    if not allow_unknown:
        extra_keys = set(data.keys()) - set(fields.keys())
        if extra_keys:
            warnings.append(f"unknown keys stripped: {extra_keys}")

    if warnings:
        logger.info(f"[Trace-{trace_id}] sanitize '{schema_name}': {len(warnings)} warning(s) — {warnings}")

    return cleaned, warnings


def _strip_control_chars(s: str) -> str:
    """移除控制字符（保留 \\n \\r \\t）。"""
    return ''.join(ch for ch in s if ch not in '\x00\x01\x02\x03\x04\x05\x06\x07\x08\x0b\x0c\x0e\x0f\x10\x11\x12\x13\x14\x15\x16\x17\x18\x19\x1a\x1b\x1c\x1d\x1e\x1f\x7f')


def _remove_injection_tokens(s: str, field_name: str, warnings: list[str]) -> str:
    """检测并移除注入 token。"""
    result = s
    for token in INJECTION_TOKENS:
        if token.lower() in result.lower():
            result = result.replace(token, '').replace(token.upper(), '').replace(token.lower(), '')
            warnings.append(f"'{field_name}' contained injection token '{token}' — removed")
    return result


# ── 预注册 schema ────────────────────────────────────────────────────────────

register_sanitize_schema("logic_entry", {
    "fields": {
        "trigger":  {"type": "str", "max_len": 500, "required": True},
        "behavior": {"type": "str", "max_len": 500, "required": True},
        "reason":   {"type": "str", "max_len": 500, "required": False},
    },
    "allow_unknown": False,
})

register_sanitize_schema("stage2_result", {
    "fields": {
        "trigger":    {"type": "bool", "required": True},
        "severity":   {"type": "str", "max_len": 10, "required": True},
        "event_type": {"type": "str", "max_len": 200, "required": True},
        "confidence": {"type": "float", "required": True},
    },
    "allow_unknown": True,
})

ALLOWED_SEVERITIES = frozenset({"P0", "P1", "P2", "P3", "P4"})

register_sanitize_schema("task_spec", {
    "fields": {
        "description": {"type": "str", "max_len": 500, "required": True},
        "depends_on":  {"type": "list", "required": False, "default": []},
    },
    "allow_unknown": True,
})

register_sanitize_schema("write_memory", {
    "fields": {
        "content":  {"type": "str", "max_len": 10000, "required": True},
        "metadata": {"type": "dict", "required": False, "default": {}},
    },
    "allow_unknown": True,
})

register_sanitize_schema("push_event", {
    "fields": {
        "event_type": {"type": "str", "max_len": 200, "required": True},
        "raw_text":   {"type": "str", "max_len": 5000, "required": True},
        "severity":   {"type": "str", "max_len": 10, "required": False, "default": "P3"},
    },
    "allow_unknown": True,
})