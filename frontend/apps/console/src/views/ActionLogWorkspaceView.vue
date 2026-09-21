<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  loadApprovals,
  loadDeadLetters,
  loadIntegrations,
  loadPushLogs,
  retryDeadLetter,
  updatePushAdoption,
  type ApprovalRecord,
  type DeadLetterRecord,
  type IntegrationStatusRecord,
  type PushLogRecord,
} from '../operational'

const pushLogs = ref<PushLogRecord[]>([])
const integrations = ref<IntegrationStatusRecord[]>([])
const deadLetters = ref<DeadLetterRecord[]>([])
const controlledActions = ref<ApprovalRecord[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const session = createApiClient().auth.read() as any
const isAdmin = computed(() => String(session?.role || '') === 'admin')
const filter = ref('')
const query = ref('')
const pending = ref<{ item: PushLogRecord; status: 'adopted' | 'rejected' } | null>(null)
const notes = ref('')

const visiblePushLogs = computed(() => pushLogs.value.filter((item) => {
  const q = query.value.trim().toLowerCase()
  const text = [item.channel, item.recipient, item.from_user, item.event_type, item.push_id, (item.hit_keywords || []).join(' ')].join(' ').toLowerCase()
  return !q || text.includes(q)
}))
function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function tone(status: string): 'success' | 'warning' | 'danger' | 'neutral' {
  const value = status.toUpperCase()
  if (['ACTIVE', 'ADOPTED', 'DELIVERED', 'SUCCEEDED', 'RECORDED'].includes(value)) return 'success'
  if (['PENDING', 'RETRYING', 'WAITING'].includes(value)) return 'warning'
  if (['FAILED', 'REJECTED', 'DEAD_LETTERED'].includes(value)) return 'danger'
  return 'neutral'
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const client = createApiClient()
    const [nextPushLogs, nextIntegrations, nextDeadLetters, nextActions] = await Promise.all([
      loadPushLogs(client, filter.value),
      loadIntegrations(client),
      isAdmin.value ? loadDeadLetters(client) : Promise.resolve([]),
      loadApprovals(client, 'ALL'),
    ])
    pushLogs.value = nextPushLogs
    integrations.value = nextIntegrations
    deadLetters.value = nextDeadLetters
    controlledActions.value = nextActions
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '动作日志读取失败'
  } finally {
    loading.value = false
  }
}
function choose(item: PushLogRecord, status: 'adopted' | 'rejected') {
  pending.value = { item, status }
  notes.value = ''
}
async function submitAdoption() {
  if (!pending.value) return
  busy.value = true
  try {
    await updatePushAdoption(createApiClient(), pending.value.item.push_id, pending.value.status, notes.value)
    notice.value = pending.value.status === 'adopted' ? '推送已采纳' : '推送已拒绝'
    pending.value = null
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '动作日志更新失败'
  } finally {
    busy.value = false
  }
}
async function retry(item: DeadLetterRecord) {
  busy.value = true
  try {
    await retryDeadLetter(createApiClient(), item.id)
    notice.value = 'Dead Letter 已重新入队'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Dead Letter 重试失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="action-workspace">
    <header class="workspace-head"><div><p class="eyebrow">ACTION LEDGER</p><h1>推送与动作日志</h1><p class="muted">内部系统接入通知、受控动作执行和失败队列均来自真实记录。</p></div><div class="actions"><select v-model="filter" @change="load"><option value="">全部采纳状态</option><option value="pending">待处理</option><option value="adopted">已采纳</option><option value="rejected">已拒绝</option></select><button :disabled="loading" @click="load">刷新</button></div></header>
    <StatePanel v-if="loading" state="loading" title="正在读取动作日志" />
    <StatePanel v-else-if="error" state="error" title="动作日志读取失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <div class="integration-grid">
      <article v-for="item in integrations" :key="item.key || item.name" class="integration-card">
        <div class="card-head"><strong>{{ item.name || item.key }}</strong><StatusBadge :label="item.status || 'UNKNOWN'" :tone="tone(item.status || '')" /></div>
        <p>{{ item.live_verified ? '已有真实 Live 证据' : item.blocked_reason || `缺少：${(item.missing || []).join(', ') || '无'}` }}</p>
        <small>已配置：{{ item.configured ? '是' : '否' }}</small>
      </article>
    </div>

    <article class="panel">
      <div class="panel-head"><h2>推送与动作</h2><input v-model="query" placeholder="搜索动作日志"><span class="muted">{{ visiblePushLogs.length }} 条</span></div>
      <div class="table-wrap"><table><thead><tr><th>时间</th><th>渠道</th><th>上报人</th><th>事件类型</th><th>风险</th><th>送达</th><th>采纳</th><th></th></tr></thead><tbody>
        <tr v-for="item in visiblePushLogs" :key="item.push_id">
          <td class="mono">{{ format(item.pushed_at) }}</td>
          <td><strong>{{ item.channel === 'WECOM_SIMULATOR_OUTBOX' ? '内部系统接入环境（联调）' : item.channel === 'in_app' ? '站内' : item.channel || '历史记录' }}</strong><small>{{ item.recipient || '—' }}</small></td>
          <td>{{ item.from_user || '—' }}</td>
          <td>{{ item.event_type || '—' }}</td>
          <td><StatusBadge :label="item.severity || '—'" :tone="tone(item.severity || '')" /></td>
          <td><StatusBadge :label="item.delivery_status || 'RECORDED'" :tone="tone(item.delivery_status || 'RECORDED')" /><small v-if="item.delivery_error">{{ item.delivery_error }}</small></td>
          <td><StatusBadge :label="item.adoption_status || 'pending'" :tone="tone(item.adoption_status || 'PENDING')" /></td>
          <td><button v-if="(item.adoption_status || 'pending') === 'pending'" @click="choose(item, 'adopted')">采纳</button><button v-if="(item.adoption_status || 'pending') === 'pending'" class="danger" @click="choose(item, 'rejected')">拒绝</button></td>
        </tr>
        <tr v-if="!visiblePushLogs.length"><td colspan="8" class="empty">暂无推送记录。</td></tr>
      </tbody></table></div>
    </article>

    <div class="split-grid">
      <article class="panel">
        <div class="panel-head"><h2>受控动作</h2><span class="muted">{{ controlledActions.length }} 条</span></div>
        <div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>状态</th><th>执行</th></tr></thead><tbody>
          <tr v-for="item in controlledActions" :key="item.approval_id"><td class="mono">{{ format(item.requested_at) }}</td><td>{{ item.tool_name }}<small>{{ item.business_id || item.approval_id }}</small></td><td><StatusBadge :label="item.status || 'PENDING'" :tone="tone(item.status || 'PENDING')" /></td><td>{{ item.execution_status || '—' }}</td></tr>
          <tr v-if="!controlledActions.length"><td colspan="4" class="empty">暂无受控动作。</td></tr>
        </tbody></table></div>
      </article>

      <article v-if="isAdmin" class="panel">
        <div class="panel-head"><h2>Dead Letter</h2><span class="muted">{{ deadLetters.length }} 条</span></div>
        <article v-for="item in deadLetters" :key="item.id" class="dead-letter"><div class="card-head"><strong>{{ item.id }}</strong><StatusBadge :label="`重试 ${item.retries || 0}`" tone="danger" /></div><p>{{ item.error || '未提供错误信息' }}</p><button :disabled="busy" @click="retry(item)">重新入队</button></article>
        <p v-if="!deadLetters.length" class="muted">没有 Dead Letter。</p>
      </article>
    </div>

    <form v-if="pending" class="panel adoption-dialog" @submit.prevent="submitAdoption">
      <h2>{{ pending.status === 'adopted' ? '采纳推送' : '拒绝推送' }}</h2>
      <label>处理说明<textarea v-model="notes" rows="3"></textarea></label>
      <button type="submit" :disabled="busy">确认</button>
      <button type="button" @click="pending = null">取消</button>
    </form>
  </section>
</template>

<style scoped>
.action-workspace { display: grid; gap: 18px; }
.workspace-head, .actions, .panel-head, .card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.integration-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.integration-card, .panel, .dead-letter { display: grid; gap: 10px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.integration-card p, .dead-letter p { margin: 0; color: var(--mp-color-body); font-size: 13px; }
.integration-card small, td small { display: block; color: var(--mp-color-mute); font-size: 12px; }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
input, select, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.danger { border-color: var(--mp-color-danger); }
button:disabled { opacity: 0.55; cursor: wait; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
.split-grid { display: grid; grid-template-columns: 1.2fr 1fr; gap: 14px; }
.adoption-dialog { position: sticky; bottom: 16px; max-width: 560px; }
.adoption-dialog label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .actions { flex-direction: column; } .split-grid { grid-template-columns: 1fr; } }
</style>
