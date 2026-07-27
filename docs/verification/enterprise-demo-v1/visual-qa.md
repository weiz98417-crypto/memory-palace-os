# 企业指挥中心视觉 QA

## 视口结果

| 视口 | 结果 | 说明 |
|---|---|---|
| 1366x768 | 通过 | 三栏高密度桌面布局，无横向滚动 |
| 1440x900 | 通过 | 时间线、结果区和证据栏完整可见 |
| 1920x1080 | 通过 | 宽屏信息层级稳定，无不必要拉伸 |
| 1179x900 | 通过 | 左侧场景栏常驻，右侧证据栏抽屉化 |
| 899x900 | 通过 | 左右栏均抽屉化，主时间线无重叠 |

自动检查包含 `documentElement.scrollWidth <= innerWidth`、可见按钮边界和控件文本裁切。人工复核确认无元素重叠、异常截断和过渡帧残留。

## 截图

- [1366x768](screenshots/console-1366x768-verified.png)
- [1440x900](screenshots/console-1440x900-verified.png)
- [1920x1080](screenshots/console-1920x1080-verified.png)
- [1179x900](screenshots/console-1179x900-verified.png)
- [899x900](screenshots/console-899x900-verified.png)

## 修复记录

- IDLE 当前步骤显示“待开始”，不再误报“处理中”。
- 失败 run 开放重试、单步、停止和 Reset。
- 场景切换保留每个场景的最新快照和证据。
- 同一 step 多 attempt 时展示最新 evidence，恢复次数按 step 去重。
- 1179px 只显示证据抽屉按钮；场景抽屉按钮在 899px 才出现，与 PRD 一致。
- 服务重启后原 run 显示“运行已中断”，Play/Step 禁用，Reset 后生成新 run 并恢复 IDLE。
- 前端只接受同一 `run_id` 且版本不低于当前状态的轮询快照，避免旧响应覆盖新状态。
