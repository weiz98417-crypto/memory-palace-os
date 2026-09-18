## ADDED Requirements

### Requirement: pgvector 检索
系统 SHALL 使用 PostgreSQL pgvector 作为唯一知识向量后端，向量维度固定为 1024。

### Requirement: bge-m3
系统 SHALL 使用本地 bge-m3 生成向量，CPU 可运行、GPU 可选加速，模型缓存持久化在本机且不进入 Git 或应用镜像。

### Requirement: 发布一致性
系统 SHALL 将已发布 SOP 和批准经验的版本、场地、模型、维度和向量索引状态关联保存；索引失败不得显示发布成功。

### Requirement: 向量数据契约
系统 SHALL 只把来自正式业务事实表的数据写入 pgvector（已发布 `sop_documents`、已发布经验卡、关闭事件生成的 CASE 记忆），并 SHALL 通过 `scripts/verify_vector_data.py` 校验索引版本、维度与"每条已发布 SOP 都有向量"。

### Requirement: 无其他向量后端
系统 SHALL 只使用 PostgreSQL pgvector。系统 SHALL NOT 依赖任何第二套实体向量库，SHALL NOT 保留影子向量后端，也 SHALL NOT 提供其他向量库的迁移工具；客户历史旧库不在本变更范围内（见 ADR-0007 修订）。
