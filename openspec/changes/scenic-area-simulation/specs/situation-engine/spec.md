## ADDED Requirements

### Requirement: 监测信号接收
系统 SHALL 接收天气、设备、客流、定位和人工观察信号，并记录来源、区域、模拟时间、真实写入时间和序号。

#### Scenario: 回放信号
- **WHEN** 运行准备入口启动已版本化故事
- **THEN** 信号按模拟时钟顺序进入正式态势入口

#### Scenario: 人工注入
- **WHEN** 授权运行准备身份注入合法信号
- **THEN** 系统校验区域和字段并记录来源为 `MANUAL_INJECTION`

### Requirement: 告警规则
系统 SHALL 根据信号和区域阈值生成、更新和恢复态势告警。

#### Scenario: 客流越阈值
- **WHEN** 东门客流超过配置容量阈值
- **THEN** 生成带规则、信号引用和区域的态势告警

### Requirement: 运营事件转换
系统 SHALL 支持将一个或多个告警转换为运营事件，并保存转换原因和操作者。

#### Scenario: 设备告警转事件
- **WHEN** 12 号观光车异常告警被确认需要人工处置
- **THEN** 创建 P1 运营事件并进入 `DETECTED`

### Requirement: 模拟时钟
系统 SHALL 支持播放、暂停、单步、倍速和重置，且不删除已写入的业务证据。

### Requirement: 态势订阅
系统 SHALL 通过 SSE 推送有序快照和状态变化，并支持断线后的快照恢复。
