# ADR-0021：前端应用栈与多入口迁移边界

状态：已接受（2026-09-18）

景区业务链路和 Agent 主干已经稳定到可以重构前端的程度，但现有前端仍是多套原生 HTML/CSS/JS 单体。我们决定把正式客户端迁移为 **Vue 3 + Vite + TypeScript + Vue Router + Pinia + Vue Query + Element Plus**，采用一个 `frontend/` 代码库、多个入口应用、共享 client 和领域 UI module 的结构。

## 决策

- 源码位于同仓库的 `frontend/` workspace，不新建独立前端仓库。
- 使用 pnpm workspace；构建产物不提交 Git，由 Docker builder 或本机启动脚本生成并交给 FastAPI/Nginx 托管。
- 保留四个独立入口：
  - `apps/console` → `/admin/`
  - `apps/field` → `/assistant/`
  - `apps/integration` → `/simulator/wecom/`
  - `apps/operations` → `/operations/scenic/` 和 `/operations/evaluation/`
- `/product/` 继续独立生成单文件，不并入内部 SPA。
- 共享层拆为 `packages/api-client`、`packages/design-tokens`、`packages/domain-ui`。
- 认证、refresh、错误归一化、幂等键和 SSE 全部进入 `api-client`，前端不按 lifecycle 推导流程。
- SSE 使用 fetch-based transport 和 `eventsource-parser`，快照是事实源，SSE 只做增量；重连使用 `Last-Event-ID`，缺口或不可恢复时回退到 snapshot。
- 前端继续渲染后端提供的 `next_actions`、`advice`、`dispatch_draft`、`closure_summary` 和引用/调用证据。
- 视觉以 `raycast/DESIGN.md` 为暗色结构和组件基础，品牌、风险和建议状态映射到 Memory Palace 的 Design Tokens；现场端单独定义浅色映射。
- 迁移按入口使用 `FRONTEND_V2_APPS` feature flag 灰度，旧页面保留一个发布周期作为回滚路径。

## 影响

- ADR-0001 中“继续使用原生 ES Modules 和独立 CSS”的实现约束被本 ADR 取代；品牌、认证、冷静指挥台和信息架构边界不变。
- 前端构建进入 Docker 和本机启动链，但生产运行时仍只托管静态文件。
- 前后端可以在冻结契约后分两条提交序列推进，最后通过汇合提交接入新 Agent 产物。
- 不采用 Next.js、SSR、原生 EventSource、AG-UI 协议或 Vercel AI SDK；这些方案要么不为当前部署模型服务，要么会引入不必要的协议和运行时。
