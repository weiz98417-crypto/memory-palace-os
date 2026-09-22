<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  loadAuditLogs,
  loadDeadLetters,
  loadLlmCalls,
  loadQueueStatus,
  loadRecoveryRuns,
  loadRuntimeDiagnostics,
  loadSkills,
  loadTrace,
  reloadRuntimeConfig,
  reloadSkill,
  runDeepseekProbe,
  type AuditLogRecord,
  type LlmCallRecord,
  type RecoveryRunRecord,
  type RuntimeDiagnostics,
  type SkillRecord,
} from '../administration'
import { retryDeadLetter } from '../operational'

const diagnostics = ref<RuntimeDiagnostics>({})
const queue = ref<Record<string, unknown>>({})
const deadLetters = ref<Array<Record<string, unknown>>>([])
const llmCalls = ref<LlmCallRecord[]>([])
const audits = ref<AuditLogRecord[]>([])
const skills = ref<SkillRecord[]>([])
const recoveryRuns = ref<RecoveryRunRecord[]>([])
const partialErrors = ref<string[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const traceId = ref('')
const traceResult = ref<Record<string, any> | null>(null)

const runtime = computed(() => diagnostics.value.runtime || {})
const deepseek = computed(() => diagnostics.value.deepseek || {})
const modelRuntime = computed(() => diagnostics.value.model_runtime || {})
const tokenQuota = computed(() => diagnostics.value.token_quota || {})
const circuitBreaker = computed(() => diagnostics.value.circuit_breaker || {})
const observability = computed(() => diagnostics.value.observability || {})
const channels = computed(() => diagnostics.value.channels || {})
const agentCoverage = computed(() => diagnostics.value.agent_coverage || {})
const agents = computed(() => diagnostics.value.agents || [])
const jaeger = computed(() => (observability.value.jaeger || {}) as Record<string, any>)
const issues = computed(() => {
  const result: Array<{ title: string; impact: string; recovery: string }> = []
  for (const [key, component] of Object.entries(runtime.value)) {
    if (String((component as any).status || '').toLowerCase() !== 'healthy') result.push({ title: `${key} 异常`, impact: '依赖该组件的业务处理暂停。', recovery: '恢复运行依赖后重新检查。' })
  }
  if (String((deepseek.value as any).status || '') !== 'READY') result.push({ title: 'DeepSeek 未就绪', impact: '生成式环节不可验收。', recovery: '检查模型配置并运行真实探针。' })
  if (String((agentCoverage.value as any).status || '') !== 'healthy') result.push({ title: 'Agent 注册或证据不完整', impact: '缺失 Agent 对应的业务步骤不可用。', recovery: '检查 PostgreSQL、模型调用日志和 Agent 注册。' })
  if (String(((channels.value.wecom_simulator || {}) as any).status || '') !== 'SIMULATOR_READY') result.push({ title: '内部系统接入主数据不完整', impact: '接入会话与通知不可验收。', recovery: '在用户与场地补齐 ACTIVE 用户的接入身份映射。' })
  return result
})
const traceSummary = computed(() => (traceResult.value?.summary || {}) as Record<string, any>)
const traceTimeline = computed(() => (traceResult.value?.timeline || []) as Array<Record<string, any>>)

function format(value?: number | string | null): string {
  if (value === undefined || value === null || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
function text(value: unknown, fallback: string | number = '—'): string {
  return value === undefined || value === null || value === '' ? String(fallback) : String(value)
}
function tone(value?: string | boolean): 'primary' | 'info' | 'success' | 'warning' | 'danger' | 'neutral' {
  if (typeof value === 'boolean') return value ? 'success' : 'danger'
  const state = String(value || '').toUpperCase()
  if (['PENDING', 'QUEUED'].includes(state)) return 'primary'
  if (['RUNNING', 'IN_PROGRESS', 'HALF_OPEN'].includes(state)) return 'info'
  if (['HEALTHY', 'READY', 'LIVE_VERIFIED', 'SUCCEEDED', 'CLOSED', 'SIMULATOR_READY'].includes(state)) return 'success'
  if (['DEGRADED', 'WARNING', 'OPEN', 'OPTIONAL_NOT_CONFIGURED', 'SUPERSEDED', 'REGISTERED_UNVERIFIED'].includes(state)) return 'warning'
  if (['UNHEALTHY', 'BLOCKED', 'FAILED', 'EXHAUSTED', 'DISABLED_BY_POLICY', 'ERROR'].includes(state)) return 'danger'
  return state ? 'info' : 'neutral'
}
function traceLabel(value?: string): string {
  if (!value) return '—'
  return value.length > 18 ? `${value.slice(0, 16)}…` : value
}
async function load() {
  loading.value = true
  error.value = ''
  partialErrors.value = []
  try {
    diagnostics.value = await loadRuntimeDiagnostics(createApiClient())
    const client = createApiClient()
    const [queueResult, deadResult, llmResult, auditResult, skillsResult, recoveryResult] = await Promise.allSettled([
      loadQueueStatus(client),
      loadDeadLetters(client),
      loadLlmCalls(client),
      loadAuditLogs(client),
      loadSkills(client),
      loadRecoveryRuns(client),
    ])
    if (queueResult.status === 'fulfilled') queue.value = queueResult.value
    else partialErrors.value.push('队列诊断')
    if (deadResult.status === 'fulfilled') deadLetters.value = deadResult.value
    else partialErrors.value.push('死信列表')
    if (llmResult.status === 'fulfilled') llmCalls.value = llmResult.value
    else partialErrors.value.push('模型调用证据')
    if (auditResult.status === 'fulfilled') audits.value = auditResult.value
    else partialErrors.value.push('审计日志')
    if (skillsResult.status === 'fulfilled') skills.value = skillsResult.value
    else partialErrors.value.push('Agent 注册表')
    if (recoveryResult.status === 'fulfilled') recoveryRuns.value = recoveryResult.value
    else partialErrors.value.push('恢复记录')
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '运维诊断读取失败'
  } finally {
    loading.value = false
  }
}
async function probe() {
  if (!globalThis.confirm('执行一次真实 DeepSeek 连通性探针并记录脱敏证据？')) return
  busy.value = true
  try {
    await runDeepseekProbe(createApiClient())
    notice.value = 'DeepSeek 真实探针已通过'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'DeepSeek 探针未通过'
  } finally {
    busy.value = false
  }
}
async function reloadConfig() {
  if (!globalThis.confirm('重新读取非敏感运行时配置？当前登录会话保持不变。')) return
  busy.value = true
  try {
    await reloadRuntimeConfig(createApiClient())
    notice.value = '配置已重载'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '配置重载失败'
  } finally {
    busy.value = false
  }
}
async function reloadAgent(name?: string) {
  if (!name || !globalThis.confirm(`热重载 Agent「${name}」？`)) return
  busy.value = true
  try {
    await reloadSkill(createApiClient(), name)
    notice.value = 'Agent 已热重载'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Agent 热重载失败'
  } finally {
    busy.value = false
  }
}
async function retry(item: Record<string, unknown>) {
  const id = String(item.id || item.message_id || item.redis_message_id || '')
  if (!id) return
  busy.value = true
  try {
    await retryDeadLetter(createApiClient(), id)
    notice.value = '死信已重新入队'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '死信重试失败'
  } finally {
    busy.value = false
  }
}
async function searchTrace() {
  const id = traceId.value.trim()
  if (id.length < 6) {
    error.value = 'Trace ID 至少需要 6 个字符'
    return
  }
  busy.value = true
  error.value = ''
  try {
    traceResult.value = await loadTrace(createApiClient(), id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Trace 查询失败'
    traceResult.value = null
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="diagnostics-workspace">
    <header class="workspace-head"><div><p class="eyebrow">RUNTIME EVIDENCE</p><h1>运维诊断</h1><p class="muted">查看健康、队列、死信、模型调用、审计和 Agent 注册；运行时操作均使用正式 API。</p></div><div class="actions"><a v-if="jaeger.ui_url" :href="String(jaeger.ui_url)" target="_blank" rel="noopener">打开 Jaeger</a><button :disabled="busy" @click="probe">验证 DeepSeek</button><button :disabled="busy" @click="reloadConfig">重载配置</button></div></header>
    <StatePanel v-if="loading" state="loading" title="正在读取运维诊断" />
    <StatePanel v-else-if="error" state="error" title="运维诊断操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>
    <p v-if="partialErrors.length" class="partial">部分证据不可用：{{ partialErrors.join('、') }}；其余状态仍来自正式接口。</p>

    <div class="metric-grid">
      <article v-for="(component, key) in runtime" :key="key"><span>{{ key }}</span><StatusBadge :label="text((component as any).status, 'UNKNOWN')" :tone="tone(String((component as any).status || ''))" /><small>{{ text((component as any).version || (component as any).model || (component as any).instance_id) }}</small></article>
      <article><span>DeepSeek</span><StatusBadge :label="text((deepseek as any).status, 'BLOCKED')" :tone="tone(String((deepseek as any).status || ''))" /><small>{{ text((deepseek as any).model) }}</small></article>
      <article><span>模型运行时</span><StatusBadge :label="text((modelRuntime as any).status, 'BLOCKED')" :tone="tone(String((modelRuntime as any).status || ''))" /><small>{{ text((modelRuntime as any).latest_real_call?.model_name, '暂无真实调用') }}</small></article>
      <article><span>每日 Token 配额</span><StatusBadge :label="text((tokenQuota as any).status, 'DISABLED')" :tone="tone(String((tokenQuota as any).status || ''))" /><small>{{ text((tokenQuota as any).used_tokens, 0) }} / {{ text((tokenQuota as any).limit_tokens, 0) }}</small></article>
      <article><span>模型熔断器</span><StatusBadge :label="text((circuitBreaker as any).state, 'CLOSED')" :tone="tone(String((circuitBreaker as any).state || ''))" /><small>连续失败 {{ text((circuitBreaker as any).consecutive_failures, 0) }}</small></article>
      <article><span>Agent 覆盖</span><StatusBadge :label="text((agentCoverage as any).status, 'unknown')" :tone="tone(String((agentCoverage as any).status || ''))" /><small>{{ text((agentCoverage as any).registered_agent_count, 0) }} / {{ text((agentCoverage as any).required_agent_count, 0) }}</small></article>
    </div>

    <section v-if="issues.length" class="blockers"><h2>主旅程阻塞项</h2><article v-for="issue in issues" :key="issue.title"><strong>{{ issue.title }}</strong><p>影响：{{ issue.impact }} 修复：{{ issue.recovery }}</p></article></section>

    <div class="split-grid">
      <article class="panel"><div class="panel-head"><h2>Redis 队列与死信</h2><span class="muted">pending {{ text(queue.pending, 0) }} · dead {{ text(queue.dead_letter_depth, 0) }}</span></div><article v-for="item in deadLetters" :key="String(item.id || item.message_id)" class="feed-item"><strong>{{ text(item.id || item.message_id) }}</strong><StatusBadge label="FAILED" tone="danger" /><p>{{ text(item.error || item.reason, '执行失败') }}</p><button :disabled="busy" @click="retry(item)">重试</button></article><p v-if="!deadLetters.length" class="muted">没有死信，当前队列无需人工恢复。</p></article>
      <article class="panel"><div class="panel-head"><h2>Agent 注册表</h2><span class="muted">{{ agents.length }} 个</span></div><article v-for="agent in agents" :key="agent.id" class="feed-item"><strong>{{ agent.id }}</strong><StatusBadge :label="text(agent.status, 'UNKNOWN')" :tone="tone(agent.status)" /><p>{{ text(skills.find((skill) => skill.name === agent.registry_name)?.description, '运行时 Agent') }}</p><button v-if="agent.registered" :disabled="busy" @click="reloadAgent(agent.registry_name)">热重载</button></article><p v-if="!agents.length" class="muted">没有 Agent 诊断结果。</p></article>
    </div>

    <article class="panel trace-panel">
      <div class="panel-head"><h2>Trace 证据链</h2><form class="trace-search" @submit.prevent="searchTrace"><input v-model="traceId" minlength="6" maxlength="128" placeholder="输入 Trace ID"><button class="primary" :disabled="busy">查询证据链</button></form></div>
      <div v-if="traceResult" class="trace-summary"><article><span>链路状态</span><StatusBadge :label="text(traceResult.status, 'UNKNOWN')" :tone="tone(traceResult.status)" /></article><article><span>模型调用</span><strong>{{ text(traceSummary.model_calls, 0) }}</strong></article><article><span>业务事件</span><strong>{{ text(traceSummary.events, 0) }}</strong></article><article><span>任务 / 审批</span><strong>{{ text(traceSummary.tasks, 0) }} / {{ text(traceSummary.approvals, 0) }}</strong></article><article><span>审计记录</span><strong>{{ text(traceSummary.audits, 0) }}</strong></article></div>
      <div v-if="traceTimeline.length" class="timeline"><article v-for="(item, index) in traceTimeline" :key="`${item.kind}-${index}`"><time>{{ format(item.created_at) }}</time><strong>{{ text(item.kind) }} · {{ text(item.status) }}</strong><p>{{ text(item.summary, '已记录运行证据') }}</p><small>{{ item.agent_id ? `Agent ${item.agent_id}` : '' }}{{ item.resource_id ? ` · 资源 ${item.resource_id}` : '' }}</small></article></div>
      <p v-else class="muted">输入 Trace ID 后显示当前场地有权访问的持久化证据。</p>
    </article>

    <div class="split-grid">
      <article class="panel"><div class="panel-head"><h2>模型调用证据</h2><span class="muted">最近 {{ llmCalls.length }} 条</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>模型</th><th>状态</th><th>真实</th><th>Trace</th></tr></thead><tbody><tr v-for="item in llmCalls" :key="item.id"><td>{{ format(item.created_at) }}</td><td>{{ text(item.model_name) }}</td><td><StatusBadge :label="text(item.status, 'UNKNOWN')" :tone="tone(item.status)" /></td><td><StatusBadge :label="item.is_mock ? '否' : '是'" :tone="item.is_mock ? 'danger' : 'success'" /></td><td class="mono">{{ traceLabel(item.trace_id) }}</td></tr><tr v-if="!llmCalls.length"><td colspan="5" class="empty">暂无模型调用证据。</td></tr></tbody></table></div></article>
      <article class="panel"><div class="panel-head"><h2>审计日志</h2><span class="muted">最近 {{ audits.length }} 条</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>结果</th><th>资源</th><th>Trace</th></tr></thead><tbody><tr v-for="item in audits" :key="item.id"><td>{{ format(item.created_at) }}</td><td>{{ text(item.action) }}</td><td><StatusBadge :label="text(item.outcome, 'UNKNOWN')" :tone="tone(item.outcome)" /></td><td>{{ text(item.resource_type) }} / {{ text(item.resource_id) }}</td><td class="mono">{{ traceLabel(item.trace_id) }}</td></tr><tr v-if="!audits.length"><td colspan="5" class="empty">暂无审计日志。</td></tr></tbody></table></div></article>
    </div>

    <article class="panel"><div class="panel-head"><h2>App 启动与恢复</h2><span class="muted">最近 {{ recoveryRuns.length }} 次</span></div><article v-for="item in recoveryRuns" :key="item.instance_id || item.trace_id" class="feed-item"><strong>{{ format(item.started_at) }} · {{ text(item.status, 'UNKNOWN') }}</strong><p>任务图恢复 {{ item.task_graph_recovered_count || 0 }} · 状态重置 {{ item.task_graph_reset_count || 0 }} · 审批中断 {{ item.approval_interrupted_count || 0 }} · Watcher 中断 {{ item.watcher_interrupted_count || 0 }} · Redis 回收 {{ item.redis_claimed_count || 0 }}</p><small class="mono">{{ item.instance_id || '暂无实例' }} · {{ item.trace_id || '暂无 Trace' }}</small></article><p v-if="!recoveryRuns.length" class="muted">暂无持久化恢复记录。</p></article>
  </section>
</template>

<style scoped>
.diagnostics-workspace { display: grid; gap: 18px; }
.workspace-head, .panel-head, .actions, .trace-search { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-grid article, .panel, .blockers { display: grid; gap: 8px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.metric-grid span, .metric-grid small { color: var(--mp-color-mute); font-size: 12px; }
.blockers { border-color: var(--mp-color-danger); }
.blockers h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.blockers article { display: grid; gap: 4px; padding: 10px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); color: var(--mp-color-body); font-size: 13px; }
.blockers p, .feed-item p { margin: 0; }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.split-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.feed-item { display: grid; gap: 6px; padding: 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); color: var(--mp-color-body); font-size: 13px; }
.feed-item small { color: var(--mp-color-mute); font-size: 12px; }
button, input { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.primary { border-color: var(--mp-color-primary); color: white; background: var(--mp-color-primary); }
button:disabled { opacity: .55; cursor: wait; }
.actions a { display: inline-flex; align-items: center; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); text-decoration: none; }
.trace-search { align-items: center; }
.trace-search input { width: min(360px, 60vw); }
.trace-summary { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
.trace-summary article { display: grid; gap: 6px; padding: 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); }
.trace-summary span { color: var(--mp-color-mute); font-size: 12px; }
.timeline { display: grid; gap: 8px; }
.timeline article { display: grid; grid-template-columns: 160px 1fr; gap: 6px 12px; padding: 10px; border-left: 2px solid var(--mp-color-primary); background: var(--mp-color-surface-elevated); }
.timeline time, .timeline small { color: var(--mp-color-mute); font-size: 12px; }
.timeline p { grid-column: 2; margin: 0; color: var(--mp-color-body); }
.timeline small { grid-column: 2; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.partial { margin: 0; color: var(--mp-color-warning); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .actions, .trace-search { flex-direction: column; } .metric-grid, .split-grid, .trace-summary { grid-template-columns: 1fr; } .timeline article { grid-template-columns: 1fr; } .timeline p, .timeline small { grid-column: 1; } }
</style>
