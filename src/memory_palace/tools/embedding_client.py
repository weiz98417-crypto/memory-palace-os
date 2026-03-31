"""
embedding_client.py · 统一 Embedding 接口
==========================================
职责：
  - 对上层（vector_store.py）暴露唯一接口：embed_text() / embed_batch()
  - 优先使用本地 bge-m3（sentence-transformers），零网络依赖，隐私安全
  - 本地加载失败时自动降级到远程 API（兼容 OpenAI embedding 协议）
  - 自动检测 CUDA / MPS / CPU，无需手动配置
  - 单例模式：模型只加载一次，避免重复占用显存/内存

依赖：
  pip install sentence-transformers torch
  （降级模式额外需要：openai 或 httpx）

使用示例：
  from src.memory_palace.tools.embedding_client import get_embedding_client
  client = get_embedding_client()
  vec = await client.embed_text("景区厕所被投诉")
  vecs = await client.embed_batch(["文本1", "文本2"])
"""

import asyncio
import os
import time
from functools import lru_cache
from typing import Optional

from loguru import logger


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT_LOCAL_MODEL  = "BAAI/bge-m3"
EMBEDDING_DIMENSION  = 1024          # bge-m3 输出维度
LOCAL_BATCH_SIZE     = 32            # 本地推理批次大小（显存不足时调小）
MAX_TEXT_LENGTH      = 8192          # bge-m3 最大 token 数（超出截断）


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 设备检测
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _detect_device() -> str:
    """
    自动检测最优推理设备：CUDA > MPS (Apple Silicon) > CPU
    """
    try:
        import torch
        if torch.cuda.is_available():
            device = "cuda"
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb  = torch.cuda.get_device_properties(0).total_memory / 1e9
            logger.info(f"🎮 检测到 CUDA GPU: {gpu_name} ({vram_gb:.1f}GB 显存)")
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device = "mps"
            logger.info("🍎 检测到 Apple MPS (Apple Silicon)")
        else:
            device = "cpu"
            logger.info("🖥️  未检测到 GPU，使用 CPU 推理（bge-m3 约 1-3s/条）")
        return device
    except ImportError:
        logger.warning("⚠️  torch 未安装，无法检测设备，默认 CPU")
        return "cpu"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 本地 Embedding 后端（sentence-transformers）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LocalEmbeddingBackend:
    """
    使用 sentence-transformers 在本地加载 bge-m3。
    首次调用时懒加载模型（避免 import 时就占用资源）。
    """

    def __init__(self, model_name: str = DEFAULT_LOCAL_MODEL):
        self.model_name = model_name
        self._model     = None          # 懒加载
        self._device    = _detect_device()

    def _load_model(self):
        """懒加载模型（线程安全由调用方保证——asyncio 单线程）"""
        if self._model is not None:
            return

        logger.info(f"⏳ 正在加载本地 embedding 模型: {self.model_name} ...")
        t0 = time.time()

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise RuntimeError(
                "sentence-transformers 未安装。\n"
                "请执行: pip install sentence-transformers"
            )

        self._model = SentenceTransformer(
            self.model_name,
            device=self._device,
        )
        elapsed = time.time() - t0
        logger.info(
            f"✅ 模型加载完成 [{self.model_name}] "
            f"设备={self._device} 耗时={elapsed:.1f}s"
        )

    def embed_batch_sync(self, texts: list[str]) -> list[list[float]]:
        """
        同步批量 embedding（在线程池中调用，不阻塞事件循环）。
        bge-m3 推荐加前缀 "Represent this sentence: " 提升召回质量。
        """
        self._load_model()

        # bge 系列对查询/文档前缀敏感，统一加通用前缀
        processed = [f"Represent this sentence: {t[:MAX_TEXT_LENGTH]}" for t in texts]

        vectors = self._model.encode(
            processed,
            batch_size=LOCAL_BATCH_SIZE,
            show_progress_bar=False,
            normalize_embeddings=True,   # 归一化，便于余弦相似度计算
            convert_to_numpy=True,
        )
        return [v.tolist() for v in vectors]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 远程 API 降级后端（OpenAI 协议兼容）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class RemoteEmbeddingBackend:
    """
    调用兼容 OpenAI embedding 协议的远程接口（硅基流动、智谱、本地 Ollama 等）。
    仅在本地模型加载失败时作为降级兜底。
    """

    def __init__(self):
        from src.memory_palace.config.app_settings import settings
        self.api_key  = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        # 远程 embedding 模型名（可在 settings 中单独配置，默认复用 LLM 的 base_url）
        self.model    = os.environ.get("EMBED_REMOTE_MODEL", "BAAI/bge-m3")
        logger.warning(
            f"⚠️  本地模型不可用，已切换至远程 embedding API: "
            f"{self.base_url} [{self.model}]"
        )

    async def embed_batch_async(self, texts: list[str]) -> list[list[float]]:
        """异步批量调用远程 embedding 接口"""
        import httpx

        url     = f"{self.base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {"model": self.model, "input": texts}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # OpenAI 协议返回格式：data[].embedding
        return [item["embedding"] for item in data["data"]]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 统一客户端（对外暴露的唯一入口）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class EmbeddingClient:
    """
    统一 Embedding 客户端。
    - 优先本地 bge-m3（sentence-transformers）
    - 本地失败自动降级远程 API
    - 所有对外接口均为 async，内部用线程池跑同步推理
    """

    def __init__(self):
        from src.memory_palace.config.app_settings import settings
        model_name = settings.EMBED_MODEL or DEFAULT_LOCAL_MODEL

        self._local:  Optional[LocalEmbeddingBackend]  = None
        self._remote: Optional[RemoteEmbeddingBackend] = None
        self._use_remote = False

        # 尝试初始化本地后端
        try:
            self._local = LocalEmbeddingBackend(model_name)
            logger.info(f"📦 Embedding 后端: 本地模式 [{model_name}]")
        except Exception as e:
            logger.error(f"❌ 本地 embedding 初始化失败: {e}，将使用远程 API")
            self._use_remote = True
            self._remote = RemoteEmbeddingBackend()

    # ── 核心接口 ──────────────────────────────────────────────────────────────

    async def embed_text(self, text: str) -> list[float]:
        """
        单条文本 embedding。
        返回长度为 1024 的 float 列表（bge-m3 维度）。
        """
        if not text or not text.strip():
            raise ValueError("embed_text: 输入文本不能为空")

        results = await self.embed_batch([text])
        return results[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        批量文本 embedding。
        自动过滤空字符串，保持返回顺序与输入一致。
        """
        if not texts:
            return []

        # 过滤并记录空文本位置，最后补零向量还原顺序
        valid_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        valid_texts   = [texts[i] for i in valid_indices]

        if not valid_texts:
            return [[0.0] * EMBEDDING_DIMENSION] * len(texts)

        t0 = time.time()

        if self._use_remote:
            vectors = await self._remote.embed_batch_async(valid_texts)
        else:
            # 本地推理是同步阻塞的，放到线程池避免阻塞 asyncio 事件循环
            loop    = asyncio.get_event_loop()
            vectors = await loop.run_in_executor(
                None,
                self._local.embed_batch_sync,
                valid_texts,
            )

        elapsed_ms = (time.time() - t0) * 1000
        logger.debug(
            f"🔢 Embedding 完成 {len(valid_texts)} 条 "
            f"耗时={elapsed_ms:.0f}ms "
            f"后端={'远程API' if self._use_remote else '本地'}"
        )

        # 还原完整结果（空文本位置补零向量）
        zero_vec = [0.0] * EMBEDDING_DIMENSION
        result   = [zero_vec] * len(texts)
        for idx, vec in zip(valid_indices, vectors):
            result[idx] = vec

        return result

    # ── 便捷属性 ──────────────────────────────────────────────────────────────

    @property
    def dimension(self) -> int:
        """返回向量维度，供 ChromaDB 初始化时使用"""
        return EMBEDDING_DIMENSION

    @property
    def backend_mode(self) -> str:
        return "remote_api" if self._use_remote else "local_bge_m3"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 单例工厂
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@lru_cache(maxsize=1)
def get_embedding_client() -> EmbeddingClient:
    """
    全局单例，模型只加载一次。
    测试时可通过 get_embedding_client.cache_clear() 重置。
    """
    return EmbeddingClient()

    