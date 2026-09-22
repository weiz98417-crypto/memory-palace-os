<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { ApprovalCard, StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  approveApproval,
  loadApproval,
  loadApprovals,
  rejectApproval,
  requestControlledAction,
  type ApprovalRecord,
} from '../operational'
import ModalShell from '../components/ModalShell.vue'

const approvals = ref<ApprovalRecord[]>([])
const selected = ref<ApprovalRecord | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const statusFilter = ref('PENDING')
const comment = ref('')
const showRequest = ref(false)
const request = ref({
  tool_name: 'send_in_app_alert',
  session_id: '',
  event_id: '',
  task_id: '',
  message: '',
  priority: 'normal',
})
const filtered = computed(() => approvals.value)

function resultRows(value?: Record<string, unknown>): Array<{ label: string; value: string }> {
  if (!value || typeof value !== 'object') return []
  return Object.entries(value).map(([label, item]) => ({ label, value: typeof item === 'object' ? JSON.stringify(item) : String(item) }))
}
function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function tone(status: string): 'success' | 'warning' | 'danger' | 'neutral' {
  const value = status.toUpperCase()
  if (value === 'APPROVED') return 'success'
  if (value === 'PENDING') return 'warning'
  if (value === 'REJECTED') return 'danger'
  return 'neutral'
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    approvals.value = await loadApprovals(createApiClient(), statusFilter.value)
    selected.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '审批读取失败'
  } finally {
    loading.value = false
  }
}
async function open(item: ApprovalRecord) {
  busy.value = true
  try {
    selected.value = await loadApproval(createApiClient(), item.approval_id)
    comment.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '审批详情读取失败'
  } finally {
    busy.value = false
  }
}
async function review(action: 'approve' | 'reject') {
  if (!selected.value) return
  busy.value = true
  try {
    if (action === 'approve') await approveApproval(createApiClient(), selected.value.approval_id, comment.value)
    else await rejectApproval(createApiClient(), selected.value.approval_id, comment.value)
    notice.value = action === 'approve' ? '审批已批准并执行' : '审批已拒绝'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '审批处理失败'
  } finally {
    busy.value = false
  }
}
async function submitRequest() {
  busy.value = true
  try {
    await requestControlledAction(createApiClient(), request.value)
    notice.value = '受控动作已提交审批'
    showRequest.value = false
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '受控动作提交失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="approval-workspace">
    <header class="workspace-head">
      <div><p class="eyebrow">HUMAN-IN-THE-LOOP</p><h1>审批中心</h1><p class="muted">高风险动作必须由人批准或拒绝；执行结果和错误来自真实审批链。</p></div>
      <div class="actions"><button @click="showRequest = !showRequest">发起受控动作</button><select v-model="statusFilter" @change="load"><option value="PENDING">待审批</option><option value="APPROVED">已批准</option><option value="REJECTED">已拒绝</option><option value="ALL">全部</option></select><button :disabled="loading" @click="load">刷新</button></div>
    </header>
    <StatePanel v-if="loading" state="loading" title="正在读取审批" />
    <StatePanel v-else-if="error" state="error" title="审批读取失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <ModalShell v-if="showRequest" label="发起受控动作" @close="showRequest = false">
      <form class="panel request-form" @submit.prevent="submitRequest">
      <h2>发起受控动作</h2>
      <label>工具<select v-model="request.tool_name"><option>send_in_app_alert</option><option>send_alert</option><option>send_sms</option><option>record_manager_decision</option></select></label>
      <label>会话 ID<input v-model="request.session_id" required></label>
      <label>事件 ID<input v-model="request.event_id" required></label>
      <label>任务 ID<input v-model="request.task_id" required></label>
      <label class="wide">动作内容<textarea v-model="request.message" rows="3" required></textarea></label>
      <button type="submit" :disabled="busy">提交审批</button>
    </form>
    </ModalShell>

    <article class="panel">
      <div class="table-wrap"><table><thead><tr><th>时间</th><th>审批</th><th>工具</th><th>状态</th><th>事件 / 任务</th><th>执行</th><th></th></tr></thead><tbody>
        <tr v-for="item in filtered" :key="item.approval_id">
          <td class="mono">{{ format(item.requested_at) }}</td>
          <td><strong>{{ item.business_id || item.approval_id }}</strong><small>{{ item.comment || '暂无审核意见' }}</small></td>
          <td>{{ item.tool_name }}</td>
          <td><StatusBadge :label="item.status || 'PENDING'" :tone="tone(item.status || 'PENDING')" /></td>
          <td>{{ item.event_id || '—' }} / {{ item.task_id || '—' }}</td>
          <td>{{ item.execution_status || '—' }}</td>
          <td><button @click="open(item)">查看详情</button></td>
        </tr>
        <tr v-if="!filtered.length"><td colspan="7" class="empty">没有符合条件的审批。</td></tr>
      </tbody></table></div>
    </article>

    <ModalShell v-if="selected" label="审批详情" @close="selected = null">
      <article class="panel detail">
      <ApprovalCard :approval="selected">
        <template #actions>
          <textarea v-model="comment" rows="2" placeholder="审批意见"></textarea>
          <button :disabled="busy || selected.status !== 'PENDING'" @click="review('approve')">批准并执行</button>
          <button class="danger" :disabled="busy || selected.status !== 'PENDING'" @click="review('reject')">拒绝</button>
        </template>
      </ApprovalCard>
      <div class="execution-grid">
        <div><span>请求人</span><strong>{{ selected.requested_by || '—' }}</strong></div>
        <div><span>执行状态</span><strong>{{ selected.execution_status || '—' }}</strong></div>
        <div class="execution-result"><span>执行结果</span><dl v-if="resultRows(selected.execution_result).length"><div v-for="row in resultRows(selected.execution_result)" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl><strong v-else>—</strong></div>
        <div><span>执行错误</span><strong>{{ selected.execution_error || '—' }}</strong></div>
      </div>
    </article>
    </ModalShell>
  </section>
</template>

<style scoped>
.approval-workspace { display: grid; gap: 18px; }
.workspace-head, .actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.panel { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.request-form { grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: end; }
.request-form h2, .request-form .wide { grid-column: 1 / -1; }
.request-form label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
input, select, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.danger { border-color: var(--mp-color-danger); background: color-mix(in srgb, var(--mp-color-danger) 18%, var(--mp-color-surface-elevated)); }
button:disabled { opacity: 0.55; cursor: wait; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { display: block; margin-top: 3px; color: var(--mp-color-mute); }
.detail { max-width: 980px; }
.execution-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.execution-grid div { display: grid; gap: 4px; }
.execution-grid span { color: var(--mp-color-mute); font-size: 12px; }
.execution-grid strong { color: var(--mp-color-body); font-size: 13px; word-break: break-word; }
.execution-result dl { display: grid; gap: 4px; margin: 0; }
.execution-result dl div { display: grid; grid-template-columns: 90px 1fr; gap: 8px; }
.execution-result dt { color: var(--mp-color-mute); font-size: 12px; }
.execution-result dd { margin: 0; color: var(--mp-color-body); font-size: 13px; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .actions { flex-direction: column; } .request-form, .execution-grid { grid-template-columns: 1fr; } }
</style>
