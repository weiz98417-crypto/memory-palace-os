## ADDED Requirements

### Requirement: 运营事件生命周期
系统 SHALL 只允许合法的运营事件状态转换，并拒绝非法跳转。

#### Scenario: 完整处置
- **WHEN** 事件完成分诊、派发、接单、处置和证据提交
- **THEN** 事件按顺序进入 `TRIAGED`、`DISPATCHED`、`ACKNOWLEDGED`、`MITIGATING`、`RESOLVED`

### Requirement: 任务与现场回执
系统 SHALL 从事件和 SOP 生成带负责人、依赖、截止时间和结构化结果的任务。

#### Scenario: 设备检修
- **WHEN** 经理确认停运和备用车辆任务
- **THEN** 检修员只能在依赖满足后接单并提交检查结果

### Requirement: 高风险审批
系统 SHALL 在停运载客车辆、启用备用车辆和严重通知前阻止工具执行，直到授权审批完成。

### Requirement: 事件关闭
系统 SHALL 在任务、审批、现场回执和必要证据齐全后才允许授权人员关闭事件。

### Requirement: 内部通知
系统 SHALL 将通知写入内部系统接入环境 outbox，并记录送达、接单和回执；生产短信和语音不得被标记为已送达。
