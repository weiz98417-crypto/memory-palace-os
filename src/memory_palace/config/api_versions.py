"""
api_versions.py · API 版本路由映射表
================================================================
功能：
1. 定义 API 版本和路由映射
2. 管理版本兼容性
3. 提供 API 文档链接
4. 版本迁移指南
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime


# ==============================================================================
# API 版本状态
# ==============================================================================

class APIVersionStatus(str, Enum):
    """API 版本状态"""
    STABLE = "stable"       # 稳定版
    BETA = "beta"          # 测试版
    DEPRECATED = "deprecated"  # 已弃用
    SUNSET = "sunset"      # 已废弃


# ==============================================================================
# 版本信息模型
# ==============================================================================

@dataclass
class APIEndpoint:
    """API 端点信息"""
    path: str
    method: str
    description: str
    deprecated: bool = False
    sunset_date: Optional[str] = None
    replacement: Optional[str] = None
    since_version: str = "1.0.0"
    responses: Dict[str, str] = field(default_factory=dict)


@dataclass
class APIChange:
    """API 变更记录"""
    version: str
    date: str
    change_type: str  # added, changed, deprecated, removed
    description: str
    breaking: bool = False


@dataclass
class APIVersion:
    """API 版本信息"""
    version: str
    status: APIVersionStatus
    release_date: str
    sunset_date: Optional[str] = None
    base_path: str = "/v1"
    description: str = ""
    endpoints: List[APIEndpoint] = field(default_factory=list)
    changes: List[APIChange] = field(default_factory=list)
    deprecation_message: Optional[str] = None


# ==============================================================================
# API 版本定义
# ==============================================================================

API_VERSIONS: Dict[str, APIVersion] = {
    "v1": APIVersion(
        version="v1",
        status=APIVersionStatus.STABLE,
        release_date="2024-01-01",
        description="Memory Palace OS 初始 API 版本",
        base_path="/v1",
        endpoints=[
            # 健康检查
            APIEndpoint(
                path="/health",
                method="GET",
                description="存活检查",
                responses={"200": "服务存活"}
            ),
            APIEndpoint(
                path="/ready",
                method="GET",
                description="就绪检查",
                responses={"200": "服务就绪", "503": "服务未就绪"}
            ),
            APIEndpoint(
                path="/metrics",
                method="GET",
                description="Prometheus 指标",
                responses={"200": "Prometheus 格式指标"}
            ),

            # 企业微信
            APIEndpoint(
                path="/v1/wechat",
                method="GET",
                description="企微 URL 验签",
                responses={"200": "验签成功", "403": "验签失败"}
            ),
            APIEndpoint(
                path="/v1/wechat",
                method="POST",
                description="接收企微消息",
                responses={"200": "消息接收成功"}
            ),

            # 消息
            APIEndpoint(
                path="/v1/messages",
                method="GET",
                description="获取消息列表",
                responses={"200": "消息列表"}
            ),
            APIEndpoint(
                path="/v1/messages/{msg_id}",
                method="GET",
                description="获取消息详情",
                responses={"200": "消息详情", "404": "消息不存在"}
            ),

            # 技能
            APIEndpoint(
                path="/v1/skills",
                method="GET",
                description="获取技能列表",
                responses={"200": "技能列表"}
            ),
            APIEndpoint(
                path="/v1/skills/{name}",
                method="GET",
                description="获取技能详情",
                responses={"200": "技能详情", "404": "技能不存在"}
            ),
            APIEndpoint(
                path="/v1/skills/{name}/reload",
                method="POST",
                description="热更新技能",
                responses={"200": "更新成功"}
            ),

            # 会话
            APIEndpoint(
                path="/v1/sessions",
                method="GET",
                description="获取会话列表",
                responses={"200": "会话列表"}
            ),
            APIEndpoint(
                path="/v1/sessions/{id}",
                method="GET",
                description="获取会话详情",
                responses={"200": "会话详情", "404": "会话不存在"}
            ),
            APIEndpoint(
                path="/v1/sessions/{id}",
                method="DELETE",
                description="删除会话",
                responses={"200": "删除成功"}
            ),

            # 管理
            APIEndpoint(
                path="/v1/admin/stats",
                method="GET",
                description="获取系统统计",
                responses={"200": "统计信息"}
            ),
            APIEndpoint(
                path="/v1/admin/queue",
                method="GET",
                description="获取队列状态",
                responses={"200": "队列状态"}
            ),

            # 知识库
            APIEndpoint(
                path="/v1/knowledge/query",
                method="POST",
                description="查询知识库",
                responses={"200": "查询结果"}
            ),
            APIEndpoint(
                path="/v1/knowledge/add",
                method="POST",
                description="添加知识",
                responses={"200": "添加成功"}
            ),
        ],
        changes=[
            APIChange(
                version="1.2.0",
                date="2024-03-01",
                change_type="added",
                description="新增知识库查询接口"
            ),
            APIChange(
                version="1.1.0",
                date="2024-02-01",
                change_type="added",
                description="新增会话管理接口"
            ),
            APIChange(
                version="1.0.0",
                date="2024-01-01",
                change_type="added",
                description="初始版本发布"
            ),
        ]
    ),

    "v2": APIVersion(
        version="v2",
        status=APIVersionStatus.BETA,
        release_date="2024-06-01",
        description="增强版 API，支持流式响应和 WebSocket",
        base_path="/v2",
        endpoints=[
            # v2 独有端点
            APIEndpoint(
                path="/v2/chat",
                method="POST",
                description="流式对话 (SSE)",
                responses={"200": "SSE 流"}
            ),
            APIEndpoint(
                path="/v2/chat/ws",
                method="WS",
                description="WebSocket 对话",
                responses={"101": "连接升级"}
            ),
            APIEndpoint(
                path="/v2/batch",
                method="POST",
                description="批量消息处理",
                responses={"202": "批量任务已接收"}
            ),
        ],
        changes=[
            APIChange(
                version="2.0.0-beta",
                date="2024-06-01",
                change_type="added",
                description="Beta 版本发布"
            ),
        ]
    ),
}


# ==============================================================================
# 版本管理工具
# ==============================================================================

class VersionManager:
    """API 版本管理器"""

    @staticmethod
    def get_version(version: str) -> Optional[APIVersion]:
        """获取指定版本信息"""
        return API_VERSIONS.get(version.lower())

    @staticmethod
    def get_all_versions() -> Dict[str, APIVersion]:
        """获取所有版本"""
        return API_VERSIONS

    @staticmethod
    def get_stable_versions() -> List[APIVersion]:
        """获取所有稳定版本"""
        return [v for v in API_VERSIONS.values() if v.status == APIVersionStatus.STABLE]

    @staticmethod
    def is_deprecated(version: str) -> bool:
        """检查版本是否已弃用"""
        v = API_VERSIONS.get(version.lower())
        if not v:
            return False
        return v.status in (APIVersionStatus.DEPRECATED, APIVersionStatus.SUNSET)

    @staticmethod
    def get_deprecation_message(version: str) -> Optional[str]:
        """获取版本弃用消息"""
        v = API_VERSIONS.get(version.lower())
        return v.deprecation_message if v else None

    @staticmethod
    def get_version_endpoints(version: str) -> List[APIEndpoint]:
        """获取版本的端点列表"""
        v = API_VERSIONS.get(version.lower())
        return v.endpoints if v else []

    @staticmethod
    def find_endpoint(path: str, method: str = "GET") -> Optional[APIEndpoint]:
        """查找端点"""
        for version in API_VERSIONS.values():
            for endpoint in version.endpoints:
                if endpoint.path == path and endpoint.method == method:
                    return endpoint
        return None

    @staticmethod
    def generate_openapi_spec(version: str = "v1") -> Dict[str, Any]:
        """生成 OpenAPI 规范片段"""
        v = API_VERSIONS.get(version.lower())
        if not v:
            return {}

        spec = {
            "openapi": "3.0.0",
            "info": {
                "title": f"Memory Palace OS API {version}",
                "description": v.description,
                "version": v.version
            },
            "paths": {}
        }

        for endpoint in v.endpoints:
            if endpoint.path not in spec["paths"]:
                spec["paths"][endpoint.path] = {}

            spec["paths"][endpoint.path][endpoint.method.lower()] = {
                "summary": endpoint.description,
                "responses": {
                    code: {"description": desc}
                    for code, desc in endpoint.responses.items()
                }
            }

        return spec

    @staticmethod
    def get_migration_guide(from_version: str, to_version: str) -> Optional[str]:
        """获取版本迁移指南"""
        guides = {
            ("v1", "v2"): """
# 从 v1 迁移到 v2

## 主要变更

### 1. 认证方式
- v1: API Key 在 Header 中
- v2: Bearer Token + OAuth 2.0

### 2. 响应格式
- v1: JSON 同步响应
- v2: 支持 SSE 流式响应

### 3. 端点变更
- `/v1/chat` → `/v2/chat` (新增流式参数)
- `/v1/messages` → `/v2/messages` (保持兼容)

## 迁移步骤

1. 更新认证方式
2. 测试流式接口
3. 更新客户端代码
4. 切换到 v2
            """
        }

        return guides.get((from_version, to_version))


# ==============================================================================
# 便捷访问
# ==============================================================================

version_manager = VersionManager()


# ==============================================================================
# 导出
# ==============================================================================

__all__ = [
    "APIVersionStatus",
    "APIEndpoint",
    "APIChange",
    "APIVersion",
    "API_VERSIONS",
    "VersionManager",
    "version_manager",
]

    