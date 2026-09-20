# ADR-0022：前端源码交付、全量定稿与入口切流

状态：已接受（2026-09-20）

现有 V2 前端已经进入代码仓库，但只在部分本机构建和测试中存在；Docker 镜像没有构建或携带 `static/client`，运行时的 `FRONTEND_V2_APPS` 也没有启用，因此交付源码包启动后仍然看到旧页面。我们决定把“代码合并”和“迁移完成”明确分开，并以源码可重建、四入口全量定稿、按入口切流和可回滚为完成条件。

## 决策

- **迁移完成采用完整标准**：四个认证入口都必须由 V2 应用提供，具备功能等价、行为验收、视觉定稿和按入口回滚能力。
- **四个入口全部纳入范围**：`/operations/*`、`/simulator/wecom/`、`/admin/`、`/assistant/`。`/product/` 继续独立，Hatchet 和 Jaeger 继续作为独立技术入口，不嵌入业务 SPA，不改造成统一视觉子系统。
- **功能等价是硬条件**：旧页面的每条路由、动作和用户可见状态都要在 V2 有等价能力，已废弃行为必须显式列入白名单；只覆盖演示主路径不算完成。
- **视觉定稿是硬门禁**：每个入口必须按 `frontend/DESIGN.md` 在桌面端和现场移动端验收，产出截图、Playwright 结果和设计审查记录，由产品负责人签收。
- **源码交付包不依赖预构建前端**：Dockerfile 使用多阶段构建，在 builder 阶段安装 pinned Node/pnpm、执行 `pnpm install --frozen-lockfile` 和 `pnpm build`，runtime 阶段复制构建产物。`node_modules` 和 `static/client` 不提交 Git。
- **可选离线发布包**：默认支持联网构建；对于不能访问公网的交付环境，额外提供带 pnpm store、所需基础镜像或预构建元数据的离线发布包，但不以预构建产物替代源码。
- **默认启用 V2，保留按入口回滚**：四入口全部定稿后，`.env.example` 默认设置 `FRONTEND_V2_APPS=console,field,integration,operations`；运行时仍可覆盖为子集或空值回退旧页面。
- **切流顺序固定为**：`operations → integration → console → field`。四个入口全部达到定稿标准后才开始切流，每个入口独立观察和回滚。
- **旧页面退场采用四条件门禁**：一个 release 观察窗口、V2 功能与视觉验收通过、回滚演练成功、旧入口流量确认为零，缺一不删。

## 影响

- 前端构建必须成为 Docker 交付链的一等步骤；当前的 `.dockerignore` 排除 `static/client` 可以继续保留，但 Docker builder 必须自己生成它。
- `.env.example` 的 V2 默认值只有在四入口全部定稿后才切换，避免再次出现“源码里有新前端、默认启动却仍显示旧页”的情况。
- 迁移验收不再以“V2 能构建”或“页面能打开”为完成标准；功能等价、视觉定稿和回滚证据缺一不可。
- Hatchet dashboard 若需要展示，单独作为技术入口增加；Jaeger 使用官方 UI，仅通过链接和 trace ID 与业务证据关联。
