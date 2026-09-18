## ADDED Requirements

### Requirement: 景区指挥中心
系统 SHALL 在正式工作台提供景区作业地图、当前态势、告警、下一步处置、运营事件和响应时间线。

### Requirement: 多角色共享状态
系统 SHALL 让指挥中心、员工现场端和管理端通过同一业务事实源显示同一事件状态，并遵守角色和场地权限。

### Requirement: 作业地图
系统 SHALL 使用离线地图 Adapter 显示四个区域、设备点位、路线、容量阈值、人员和告警。

#### Scenario: GIS 未配置
- **WHEN** 未配置真实 GIS
- **THEN** 页面显示离线地图可用，并显示 GIS 为 `OPTIONAL_CONNECTION / NOT_CONFIGURED` 及接口信息

### Requirement: 业务界面真实性
系统 SHALL 在业务主界面隐藏剧本播放器和模拟控制器；模拟输入只能从受保护运行准备入口或后台脚本产生。
