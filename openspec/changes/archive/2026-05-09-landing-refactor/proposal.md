## Why

核心链路跑不通：8 个 P0/P1 bug 阻塞企微消息→应急识别→SOP下发的 30 秒闭环。模块级副作用导致 import 即崩溃，DB 初始化顺序错误导致 Phase 恢复报错，Agent 名称不匹配导致路由失败。约 60% 代码（Phase 2-4）未跑通但在启动时挡路。需要一次落地级重构，交付干净可迭代的基底。

## What Changes

- 修复 requirements.txt（缺 pytz、httpx 重复）
- 修复 Windows GBK 控制台下 emoji 日志崩溃
- DB 路径从相对路径改为项目根目录绝对路径
- 消除模块级副作用：vector_store、embedding_client、wechat_client、scheduler 全部改为懒加载
- 修复 DB 初始化顺序：lifespan 中先 init_db() 再做 Phase 恢复
- 修复 orchestrator 默认路由 Agent 名称错误（`deep_interview` → `persona_extract`）
- 清理 gateway.py 与 main.py 的重复路由定义
- 修复 config 模块命名冲突（`init.py` → `config_manager.py`）
- 修复 context_trigger 硬编码 URL（`example.com` → 环境变量）
- 处理 tools/ 和 knowledge/ 下重复的 db_client
- Phase 2-4 半成品代码（permissions、task_graph、workspace）退回 stub，保留接口不报错
- skills 注册去重（`_auto_register_skills()` 只在 lifespan 调一次）
- 新增 5 个核心链路集成测试
- Demo 模式全链路可验证

## Capabilities

### New Capabilities
- `lazy-init`: 所有外部依赖（vector_store、embedding_client、wechat_client、scheduler）统一懒加载，消除 import 时副作用
- `core-pipeline`: 企微消息→入队→ContextTrigger→Router→Agent 的全链路可验证运行
- `windows-compat`: Windows GBK 控制台下日志正常输出，不崩溃

### Modified Capabilities
_（无需修改已有 spec，本项目无已有 spec）_

## Impact

- 影响文件：~20 个，涉及 core/、tools/、knowledge/、skills/、config/、main.py、requirements.txt
- 不影响：Agent 业务逻辑不变，API 端点不变，外部接口不变
- Phase 2-4 代码退回 stub 后，相关 API 仍返回空数据（不报错），等后续里程碑逐一激活
