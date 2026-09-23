# SPEC-04：显式建议执行模式与 Hatchet 就绪

## Problem Statement

默认部署设置 Hatchet token 文件路径，但相应服务属于可选 profile。系统可能仅凭路径字符串误启用 Hatchet，或在完整部署中同时启动两条消费者，导致无法启动、长期排队或重复执行。

## Solution

提供明确且可诊断的默认队列模式和 Hatchet 模式；启用条件、依赖健康与消费者归属保持一致，错误配置明确失败。

## User Stories

1. 作为部署管理员，我希望默认栈不依赖未启用的 Hatchet，以便按默认文档启动。
2. 作为部署管理员，我希望显式启用 Hatchet 后验证 token 和服务，以免请求进入无人消费的队列。
3. 作为运维人员，我希望诊断显示实际执行模式，以便定位建议延迟。
4. 作为经理，我希望任何模式下人工采纳门禁相同，以便业务行为不随部署变化。
5. 作为运维人员，我希望缺 worker 时就绪失败，以免把只能接收请求的系统当成健康。
6. 作为审计员，我希望模式切换不改变业务事实源，以便卷宗始终一致。
7. 作为部署管理员，我希望错误模式不静默回退，以便及时发现配置问题。
8. 作为运维人员，我希望切换模式前处理在途工作，以免两条执行路径同时运行。

## Implementation Decisions

- 复用既有 dispatcher、Hatchet workflow 与生命周期，不增加第三种编排实现。
- 默认正式模式使用 Redis 持久建议队列；测试内存队列不进入正式运行。
- 启用 Hatchet 必须是显式运行配置，不能仅凭非空 token 文件路径推断。完整 profile 启动脚本同步设置模式并检查可读非空 token、服务和 worker。
- 显式启用后 token 缺失/空/不可读、服务不可达或 worker 不可用时返回清楚的启动/就绪诊断；不得默默回到默认队列。
- 每个 run 只有一个派发所有者；默认队列消费者与 Hatchet worker 的执行边界明确，复用 SPEC-03 的幂等与执行权。
- 活跃 run 存在时禁止未经处置的模式切换；先排空或按持久归属继续恢复，不重新路由已在途业务。
- 模式不改变建议采纳、忽略、不等待及人工中断语义，Hatchet 历史不替代业务数据库。
- 健康/就绪报告实际启用能力；关闭的可选服务不造成默认栈假失败，已启用服务故障不能被隐藏。

## Testing Decisions

- 测试边界是部署启动命令、健康/就绪查询和正式建议请求/决定，不以 token 路径字符串存在作为成功。
- 复用 Hatchet 工作流测试、运行诊断测试、建议 API 测试和 Compose 配置检查。
- 覆盖默认 profile、完整 profile、残留 token 卷、空文件、错误 token、worker 缺失、服务中断及在途切换。
- 两种模式执行相同业务合同，验证建议结果与人工决定的持久状态一致。

## Out of Scope

替换 Hatchet、引入新编排框架、自动故障转移、运行历史作为业务真相。

## Further Notes

映射 R2 的运行时选择部分；集成依赖 SPEC-03，部署验收依赖 SPEC-02/05。规格可预先实现配置契约，但不能绕过持久队列发布。

## ADDED Requirements

### Requirement: 默认部署不误启用可选运行时
系统 SHALL 显式选择执行模式，MUST NOT 将 token 路径字符串当作 Hatchet 就绪证明。

#### Scenario: 默认栈有残留 token 配置
- **WHEN** 默认模式启动且 Hatchet profile 未启用，即使存在旧 token 卷或路径配置
- **THEN** 建议仍由默认 Redis 模式处理，诊断显示默认模式，不尝试派发到未启用 Hatchet

### Requirement: 显式 Hatchet 依赖完整
系统 SHALL 在显式 Hatchet 模式校验秘密、服务与 worker，MUST NOT 静默回退。

#### Scenario: Hatchet worker 不可用
- **WHEN** Hatchet 模式已启用但 worker 不可用
- **THEN** 就绪检查失败并报告缺失组件，不把建议服务宣告就绪

### Requirement: 执行归属与人工门禁稳定
系统 SHALL 保持一个 run 的唯一执行归属并保留同样的人工决定门禁。

#### Scenario: 有在途运行时切换模式
- **WHEN** 管理员请求更换执行模式但仍有在途 run
- **THEN** 系统要求排空或保留原归属恢复，不将同一 run 同时交给两条消费者
