## ADDED Requirements

### Requirement: Knowledge entry management
系统 SHALL 提供 REST API 管理知识库条目。

#### Scenario: List knowledge entries
- **WHEN** GET /api/v1/admin/knowledge/entries
- **THEN** 返回分页的知识库条目列表

#### Scenario: Delete knowledge entry
- **WHEN** DELETE /api/v1/admin/knowledge/entries/{id}
- **THEN** 该条目从 ChromaDB 中删除

#### Scenario: Re-index knowledge base
- **WHEN** POST /api/v1/admin/knowledge/reindex
- **THEN** ChromaDB 全量重建索引

### Requirement: Admin UI knowledge tab
系统 SHALL 在 admin_frontend.html 中提供知识库管理标签页。

#### Scenario: View knowledge entries
- **WHEN** 用户打开知识库标签页
- **THEN** 显示条目表格，支持搜索和分类过滤
