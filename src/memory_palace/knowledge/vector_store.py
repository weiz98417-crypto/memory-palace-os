"""
向量检索接口 (ChromaDB Vector Store)

核心特性：
1. Embedding 抽象：统一封装文本转向量过程。
2. 余弦相似度检索：精准定位历史经验片段。
3. 持久化防护：支持本地 SQLite 存储向量数据，保障重启不丢失。

Copyright (c) 2026 ZhouWei & Team. All Rights Reserved.
"""

import os
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Dict, Any, Optional
from loguru import logger

class PalaceVectorStore:
    def __init__(self):
        # 工业路径：数据持久化到 data/ 目录
        self.db_path = os.environ.get("VECTOR_DB_PATH", "data/vector_db")
        
        # 1. 选用 OpenAI 工业级 Embedding 模型 (text-embedding-3-small)
        self.emb_fn = embedding_functions.OpenAIEmbeddingFunction(
            api_key=os.environ.get("OPENAI_API_KEY"),
            model_name="text-embedding-3-small"
        )

        # 2. 建立持久化客户端
        self._client = chromadb.PersistentClient(path=self.db_path)
        
        # 3. 初始化集合，指定余弦空间 (cosine)
        self.collection = self._client.get_or_create_collection(
            name="memory_palace_vdb",
            embedding_function=self.emb_fn,
            metadata={"hnsw:space": "cosine"}
        )
        logger.info(f"向量知识库初始化完成，挂载点: {self.db_path}")

    def upsert_experience(self, content: str, metadata: Dict[str, Any], doc_id: str):
        """插入或更新一条经验碎片"""
        try:
            self.collection.upsert(
                documents=[content],
                metadatas=[metadata],
                ids=[doc_id]
            )
            logger.debug(f"[VectorStore] 数据上云: {doc_id}")
        except Exception as e:
            logger.error(f"[VectorStore] Upsert 失败: {e}")

    def query_experience(self, text: str, top_k: int = 3, threshold: float = 0.75) -> List[Dict[str, Any]]:
        """
        语义检索逻辑：带相似度阈值过滤，防止召回毫无相关的噪音。
        """
        try:
            results = self.collection.query(
                query_texts=[text],
                n_results=top_k,
                include=["documents", "metadatas", "distances"]
            )
            
            clean_results = []
            if not results or not results['documents']:
                return []

            for i in range(len(results['documents'][0])):
                # Chroma 的 cosine distance = 1 - similarity
                similarity = 1 - results['distances'][0][i]
                
                # 工业级过滤：低于阈值的通通丢弃，宁可不给建议也不乱给建议
                if similarity >= threshold:
                    clean_results.append({
                        "content": results['documents'][0][i],
                        "metadata": results['metadatas'][0][i],
                        "score": round(similarity, 3)
                    })
            
            return clean_results
        except Exception as e:
            logger.error(f"[VectorStore] 检索过程中断: {e}")
            return []

# 单例工厂（懒加载，避免 import 时触发 ChromaDB/OpenAI 初始化）
_vector_client = None


def get_vector_client() -> Optional[PalaceVectorStore]:
    """返回 PalaceVectorStore 单例，首次调用时初始化。初始化失败返回 None。"""
    global _vector_client
    if _vector_client is None:
        try:
            _vector_client = PalaceVectorStore()
        except Exception as e:
            logger.warning(f"[VectorStore] 初始化失败（将以降级模式运行）: {e}")
            _vector_client = None
    return _vector_client