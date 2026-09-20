# Frontend V2 parity matrix

Status: accepted
Date: 2026-09-20
Source of truth: ADR-0021, ADR-0022, `frontend/DESIGN.md`, `CONTEXT.md`

## Method

The legacy authenticated entries were inventoried from the running static pages and their client code. A behavior counts as migrated only when the corresponding V2 route, action, state, permission boundary, and evidence behavior is present. Missing behavior is not automatically deprecated; every exception must appear in the deprecation whitelist.

The V2 snapshots reviewed here are intentionally early migration shells. They do not satisfy functional equivalence yet. F11 implementation is complete and awaiting product-owner visual sign-off.

## Summary

| Entry | Legacy surface | V2 current surface | Result | Owner ticket |
| --- | --- | --- | --- | --- |
| `/operations/*` | Protected scenic preparation and evaluation evidence | Full V2 implementation; visual sign-off pending | `READY_FOR_REVIEW` | F11 |
| `/simulator/wecom/` | Manager-operated simulator, messages, outbox and experience workflow | Identity count and channel declaration only | `INCOMPLETE` | F12 |
| `/admin/` | 13 workspaces, 45+ actions, gates and audit evidence | Command-center projection only | `INCOMPLETE` | F13 |
| `/assistant/` | Mobile chat, work, experience and profile workflow | Run/task/advice projection only | `INCOMPLETE` | F14 |

## Deprecation whitelist

No legacy authenticated behavior is approved as deprecated. The following are outside this matrix rather than deprecated:

- `/product/` remains an independent artifact.
- Hatchet history remains an independent technical run view.
- Jaeger remains an independent tracing UI.
- External production SMS, voice, and WeCom delivery remain disabled by policy.

## Operations matrix

Legacy surface: `/operations/scenic/` and `/operations/evaluation/`.

| Area | Legacy route/action/state | V2 mapping | Status |
| --- | --- | --- | --- |
| Scenic auth | Login as `simulation-ops` | Protected shell only | `MISSING` |
| Scenario | `PREPARE_SCENARIO` and versioned run display | No command | `MISSING` |
| Clock | `CLOCK_PLAY`, `CLOCK_PAUSE` | No command | `MISSING` |
| Clock | Speed `0.5/1/2/4/8` | No control | `MISSING` |
| Clock | `CLOCK_STEP` 1s/2s/28s/60s | No control | `MISSING` |
| Signals | Manual signal injection with type, zone, JSON | No control | `MISSING` |
| Snapshot | Run, signals, alerts, incidents evidence | No projection | `MISSING` |
| Evaluation | Load runs and tier filter | No API projection | `MISSING` |
| Evaluation | Summary cards and run table | No projection | `MISSING` |
| Evaluation | Open run detail and case filters | No projection | `MISSING` |
| Evaluation | Empty/error states | No equivalent | `MISSING` |

## Integration matrix

Legacy surface: `/simulator/wecom/`.

| Area | Legacy route/action/state | V2 mapping | Status |
| --- | --- | --- | --- |
| Auth | Login and session restore | Shared shell only | `MISSING` |
| Identity | Manager identity list and selection | Count only | `MISSING` |
| Sessions | New, select, refresh, restore employee session | No equivalent | `MISSING` |
| Messages | Send text and attachment, optimistic state, server reconciliation | No equivalent | `MISSING` |
| Messages | Retry persisted message and reclaim/dead-letter state | No equivalent | `MISSING` |
| Outbox | Load outbox, unavailable state, delivery status, retry state | No equivalent | `MISSING` |
| Evidence | Business cards and employee-facing links | No equivalent | `MISSING` |
| Experience | Open interview, accept, pause, resume, close | No equivalent | `MISSING` |
| Experience | Answer/complete/revise/confirm experience card | No equivalent | `MISSING` |
| Recovery | Reload identities/sessions/experience after failure | No equivalent | `MISSING` |
| Logout | End session safely | No equivalent | `MISSING` |

## Console matrix

Legacy surface: `/admin/` with 13 workspaces.

| Legacy workspace | V2 route | Status |
| --- | --- | --- |
| 指挥中心 (`dashboard`) | `/admin/` and `/admin/command-center` partial projection | `PARTIAL` |
| 事件处置 (`events`) | No dedicated V2 route | `MISSING` |
| 消息与会话 (`sessions`) | No dedicated V2 route | `MISSING` |
| 任务与审批 (`tasks`) | No dedicated V2 route | `MISSING` |
| 审批中心 (`approvals`) | No dedicated V2 route | `MISSING` |
| 推送与动作日志 (`actions`) | No dedicated V2 route | `MISSING` |
| 组织记忆 (`knowledge`) | No dedicated V2 route | `MISSING` |
| 专家经验 (`experience`) | No dedicated V2 route | `MISSING` |
| 鹰眼巡检 (`watcher`) | No dedicated V2 route | `MISSING` |
| SOP 中心 (`sops`) | No dedicated V2 route | `MISSING` |
| 用户与场地 (`management`) | No dedicated V2 route | `MISSING` |
| 系统设置 (`settings`) | No dedicated V2 route | `MISSING` |
| 运维诊断 (`diagnostics`) | No dedicated V2 route | `MISSING` |

### Console actions

| Action family | Legacy actions | V2 status |
| --- | --- | --- |
| Shell | menu, refresh, logout, event-mode | `MISSING` |
| Events | open/edit/close event | `MISSING` |
| Sessions | open/close session | `MISSING` |
| Tasks | new-task, decompose-task, recover/cancel decomposition, view/open task, start/complete/fail/retry task, assign task, unblock task | `MISSING` |
| Approvals | new controlled action, open approval, approve/reject | `MISSING` |
| Actions | mark push adopted/rejected, retry dead letter | `MISSING` |
| Knowledge | new/edit/delete knowledge, import, rebuild index | `MISSING` |
| Experience | new expert, start interview, view card/interview, submit/publish/reject/deprecate card, retry candidate | `MISSING` |
| Watcher | new/edit/toggle/run policy, assign/close finding, run event watcher | `MISSING` |
| SOP | new/edit/open SOP, submit/publish/reject SOP | `MISSING` |
| Management | new/toggle user, reset password, enable simulator identity, new/toggle venue | `MISSING` |
| Settings | reload config, update setting | `MISSING` |
| Diagnostics | DeepSeek probe, reload skill, health/traces/calls/dead letters | `MISSING` |

## Field matrix

Legacy surface: `/assistant/` with four sections: chat, work, experience, me.

| Area | Legacy route/action/state | V2 mapping | Status |
| --- | --- | --- | --- |
| Chat | New/open/close sessions, refresh current, send message, attachment note/file | No equivalent | `MISSING` |
| Chat | Optimistic sending, retry, delivered/failed states | No equivalent | `MISSING` |
| Work | Task list and task detail | Counts only | `PARTIAL` |
| Work | Start task | No action | `MISSING` |
| Work | Complete task with structured result | No action | `MISSING` |
| Work | Block task and recovery state | No action | `MISSING` |
| Events | Open event detail and evidence | No equivalent | `MISSING` |
| SOP | Open SOP detail and published knowledge link | No equivalent | `MISSING` |
| Advice | Read-only advice projection | AgentRunCard partial | `PARTIAL` |
| Experience | Open interview, accept/pause/resume/close | No equivalent | `MISSING` |
| Experience | Confirm/revise experience card | No equivalent | `MISSING` |
| Me | Session/profile/logout surface | No equivalent | `MISSING` |

## State and permission parity

The following state boundaries must be represented in V2 before an entry is complete:

- `NO_EVIDENCE` must display exactly `没有依据`.
- `RETRIEVAL_FAILED` must display `未获得模型建议`.
- Advice, dispatch, closure and task states must remain backend-owned.
- High-risk approval and closure gates cannot be bypassed by frontend behavior.
- Field advice remains read-only; manager decisions remain manager/admin-only.
- Simulator outbox must not claim production external delivery.
- Simulation controls remain only in protected operations entries.
- Loading, empty, degraded, failed, unavailable, superseded, recovery and completed states require explicit UI treatment.

## Ticket mapping

- F11 closes the operations matrix.
- F12 closes the integration matrix.
- F13 closes the console matrix.
- F14 closes the field matrix.
- F10 supplies the shared UI primitives required by all four tickets.

## Sign-off

Product-owner sign-off: accepted 2026-09-20 by user confirmation.

No entry may be marked migrated while it still depends on this matrix having unresolved `MISSING` behavior.
