## ADDED Requirements

### Requirement: 运行准备权限
系统 SHALL 仅允许受保护的本地运维身份准备剧本、控制模拟时钟和注入信号，并为每个动作记录审计。

### Requirement: 业务账号
系统 SHALL 使用预置业务账号和真实角色权限；客户端不得通过请求参数修改用户或场地身份。

### Requirement: 证据包
系统 SHALL 为每次垂直切片记录输入来源、模拟时间、事件编号、任务、审批、通知、SSE 序号、向量命中、真实墙上时间和最终状态。

### Requirement: 恢复
系统 SHALL 在 SSE 断线、App 重启、Redis 重试和单步骤失败后保留原始失败证据，并恢复到唯一最终业务结果。
