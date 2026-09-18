# Memory Palace OS Frontend Design

状态：已接受（2026-09-18）

## 基础来源

本设计以 `VoltAgent/awesome-design-md` 中的 `raycast/DESIGN.md` 为暗色产品结构基础，只借用其表面层级、密度、边框、交互克制和命令面板式布局原则；不复制 Raycast 的商标、图标、文案、营销图形或红色 hero 条纹。

Memory Palace 的正式运营端保持“冷静指挥台”：暗色、低对比、风险状态优先于品牌装饰。现场端使用同一套语义 token 的浅色映射。

## 颜色

### 正式运营端 / 运维端

| Token | 值 | 用途 |
| --- | --- | --- |
| `{colors.canvas}` | `#0D0F1A` | 页面画布 |
| `{colors.surface}` | `#1A1F3C` | 面板与卡片 |
| `{colors.surface-elevated}` | `#22294D` | 抬升表面、抽屉 |
| `{colors.hairline}` | `rgba(213,218,255,.12)` | 1px 分隔线和边框 |
| `{colors.hairline-strong}` | `rgba(213,218,255,.22)` | 聚焦/强调边框 |
| `{colors.ink}` | `#F4F5FF` | 主文字 |
| `{colors.body}` | `#A7AFCA` | 正文 |
| `{colors.mute}` | `#737D9D` | 弱文字、时间戳 |
| `{colors.primary}` | `#5B6EFF` | 主操作、链接、焦点 |
| `{colors.ai}` | `#A06CF9` | AI、处置建议、Agent 运行 |
| `{colors.success}` | `#39C68A` | 已恢复、已完成 |
| `{colors.warning}` | `#FFB020` | 警告、等待、降级 |
| `{colors.danger}` | `#FF5C6C` | P0/P1、失败、阻塞 |
| `{colors.info}` | `#57C1FF` | 信息、连接、SSE 状态 |

Raycast 原色仅作为参考：`#07080A` canvas、`#0D0D0D` surface、`#101111` elevated、`#121212` card、`#242728` hairline、`#F4F4F6` ink、`#CDCDCD` body、`#9C9C9D` mute、`#FFFFFF` primary。Memory Palace 不直接使用其白色主 CTA，而用 `{colors.primary}`。

现场端浅色映射：

| Token | 值 | 用途 |
| --- | --- | --- |
| `{colors.canvas}` | `#F6F8FC` | 页面画布 |
| `{colors.surface}` | `#FFFFFF` | 卡片 |
| `{colors.ink}` | `#172033` | 主文字 |
| `{colors.body}` | `#4E5A70` | 正文 |
| `{colors.primary}` | `#4054E8` | 主操作 |
| `{colors.ai}` | `#7C4DCC` | 建议 |
| `{colors.success}` | `#1F9D6A` | 完成 |
| `{colors.warning}` | `#B66A00` | 等待 |
| `{colors.danger}` | `#D9364A` | 失败/阻塞 |

## 字体与排版

- UI：`Inter, "PingFang SC", "Microsoft YaHei", sans-serif`
- 数据/技术标识：`SFMono-Regular, Menlo, Consolas, monospace`
- 正文 16px / 1.6；表格和密集信息 14px / 1.5；技术 trace 12–13px。
- 标题使用 20/24/32/48px 层级；命令中心的大标题只用于页面级标题，不用于卡片正文。
- 数字型指标使用 tabular numbers；不要在业务密集界面使用夸张 letter-spacing。

## 间距与形状

```text
2 / 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64
rounded: 4 / 6 / 8 / 12 / 16 / pill
```

- 面板、卡片、输入框：6–8px。
- 状态标签：pill。
- 主要媒体卡：最多 16px。
- 运营端不使用大面积圆角卡片堆叠；用 hairline、表面层级和分区组织信息。
- 卡片默认不使用重阴影；抬升通过 `surface-elevated`、hairline 和局部光晕表达。

## 组件原则

### App Shell

- 固定左侧导航，主工作区独立滚动。
- 入口标题、场地、连接状态和最后更新时间必须可见。
- 命令中心必须把“下一步处置”放在统计指标之前。

### 按钮

- 一个视图内最多一个主操作；主操作使用 `{colors.primary}`。
- 高风险动作使用 danger 语义，不使用普通主按钮颜色。
- 取消、返回、查看详情使用 ghost 或 outline。

### 表格与筛选

- 筛选器在表格上方，不使用浮动卡片遮挡数据。
- 状态列使用文本 + 语义色点，不只靠颜色。
- 行内操作不承载高风险决定；高风险进入抽屉或确认对话框。
- 空状态必须解释“为什么为空”和“下一步做什么”。

### 建议卡

- 状态必须显示为 `分析中 / 已就绪 / 未获得建议 / 已过期`。
- 正文、引用、模型证据分区；技术字段默认折叠。
- `NO_EVIDENCE` 必须固定显示“没有依据”，不得用生成文案替换。
- `ADOPT / IGNORE / PROCEED_WITHOUT_WAITING` 由后端 allowed_actions 决定；前端不自行推导。
- IGNORE 必须有 reason code；OTHER 必须有文本。

### 派单草案与关闭摘要

- 派单草案展示风险、立即动作、所需工具、下一步检查、审批要求。
- 关闭摘要展示证据、SOP、任务、审批、告警恢复和未解决风险。
- 草案和摘要是证据，不新增独立审批对象；高风险审批和关闭门禁仍由既有流程决定。

### Agent 运行状态

- `PENDING/RUNNING`：显示分析中和连接状态，不显示假结果。
- `READY`：显示结构化输出和证据。
- `FAILED`：显示“未获得模型建议”，允许依据后端动作继续。
- `SUPERSEDED`：只读，显示已过期原因。
- `DEGRADED`：明确显示降级环节，不把降级结果伪装成完整成功。

### SSE

- 连接状态分为 `CONNECTING / CONNECTED / RECONNECTING / FALLBACK`。
- 断线不弹错误阻塞页面；先保留快照，后台重连。
- `Last-Event-ID` 续传；缺口或无法续传时重新拉取 snapshot。
- 重复事件按 `(incident_id, artifact, run_id, sequence)` 幂等合并。

## 响应式

- 运营端按 1440px 桌面优先设计，支持 1024/768 降级。
- 现场端按 390px 移动优先设计，触控目标至少 44px。
- 表格在窄屏改为卡片行或横向滚动，不压缩成不可读的微型表格。
- 高风险确认在移动端必须保留完整原因输入和二次确认。

## 可访问性

- 文字与背景对比达到 WCAG AA。
- 风险状态同时使用文本、图标和颜色。
- 所有关键操作可键盘到达并可见 focus ring。
- 支持 `prefers-reduced-motion`；品牌动效只在登录首次进入时出现。
- 不使用颜色作为唯一状态表达。

## 禁止

- 不在业务页显示模拟时钟、播放、暂停、倍速或单步。
- 不用营销渐变替代业务状态层级。
- 不用 `is_mock=true` 的模型调用冒充真实模型证据。
- 不用模型输出替代关闭门禁、审批或高风险决定。
- 不把 `/product/` 并进业务 SPA。
- 不把 `/operations/scenic/` 并进指挥中心。
