<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import { loadAssignees, type AssigneeRecord } from '../operational'
import {
  assignWatcherFinding,
  closeWatcherFinding,
  createWatcherPolicy,
  loadWatcherFindings,
  loadWatcherPolicies,
  loadWatcherRuns,
  runWatcherPolicy,
  toggleWatcherPolicy,
  updateWatcherPolicy,
  type WatcherFindingRecord,
  type WatcherPolicyRecord,
  type WatcherPolicyUpsert,
  type WatcherRunRecord,
} from '../governance'

const policies = ref<WatcherPolicyRecord[]>([])
const findings = ref<WatcherFindingRecord[]>([])
const runs = ref<WatcherRunRecord[]>([])
const assignees = ref<AssigneeRecord[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const policyOpen = ref(false)
const editingId = ref('')
const assignments = reactive<Record<string, string>>({})
const form = ref<WatcherPolicyUpsert>({ name: '', description: '', schedule_cron: '0 10 * * *', enabled: true, check_types: ['SLA', 'TASK', 'SOP'], config: { max_targets: 200 } })
const assigneeMap = computed(() => Object.fromEntries(assignees.value.map((item) => [item.id, item.display_name || item.username || item.id])))

function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function tone(value?: string): 'success' | 'warning' | 'danger' | 'neutral' | 'info' {
  const status = String(value || '').toUpperCase()
  if (['ACTIVE', 'SUCCEEDED', 'CLOSED', 'HEALTHY'].includes(status)) return 'success'
  if (['OPEN', 'IN_PROGRESS', 'RUNNING', 'PENDING'].includes(status)) return 'warning'
  if (['FAILED', 'CRITICAL', 'HIGH', 'ERROR'].includes(status)) return 'danger'
  if (status === 'DISABLED') return 'neutral'
  return 'info'
}
function resetForm() {
  editingId.value = ''
  form.value = { name: '', description: '', schedule_cron: '0 10 * * *', enabled: true, check_types: ['SLA', 'TASK', 'SOP'], config: { max_targets: 200 } }
}
function openCreate() {
  resetForm()
  policyOpen.value = true
}
function openEdit(item: WatcherPolicyRecord) {
  editingId.value = item.id
  form.value = {
    name: item.name || '',
    description: item.description || '',
    schedule_cron: item.schedule_cron || '0 10 * * *',
    enabled: Boolean(item.enabled),
    check_types: item.check_types || [],
    config: item.config || { max_targets: 200 },
  }
  policyOpen.value = true
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const client = createApiClient()
    const [nextPolicies, nextFindings, nextRuns, nextAssignees] = await Promise.all([
      loadWatcherPolicies(client),
      loadWatcherFindings(client),
      loadWatcherRuns(client),
      loadAssignees(client),
    ])
    policies.value = nextPolicies
    findings.value = nextFindings
    runs.value = nextRuns
    assignees.value = nextAssignees
    for (const item of nextFindings) assignments[item.id] = item.assigned_to || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '巡检数据读取失败'
  } finally {
    loading.value = false
  }
}
async function savePolicy() {
  busy.value = true
  error.value = ''
  try {
    const body: WatcherPolicyUpsert = {
      ...form.value,
      name: form.value.name.trim(),
      description: form.value.description.trim(),
      schedule_cron: form.value.schedule_cron.trim(),
      check_types: form.value.check_types.map((item) => item.trim().toUpperCase()).filter(Boolean),
      config: { ...form.value.config, max_targets: Number(form.value.config.max_targets || 200) },
    }
    if (editingId.value) await updateWatcherPolicy(createApiClient(), editingId.value, body)
    else await createWatcherPolicy(createApiClient(), body)
    notice.value = '巡检策略已保存'
    policyOpen.value = false
    resetForm()
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '巡检策略保存失败'
  } finally {
    busy.value = false
  }
}
async function toggle(item: WatcherPolicyRecord) {
  busy.value = true
  try {
    await toggleWatcherPolicy(createApiClient(), item.id, !item.enabled)
    notice.value = item.enabled ? '策略已停用' : '策略已启用'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '巡检策略状态更新失败'
  } finally {
    busy.value = false
  }
}
async function run(item: WatcherPolicyRecord) {
  busy.value = true
  try {
    const result = await runWatcherPolicy(createApiClient(), item.id) as { finding_count?: number }
    notice.value = `巡检完成，发现 ${result.finding_count ?? 0} 项`
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '巡检运行失败'
  } finally {
    busy.value = false
  }
}
async function assign(item: WatcherFindingRecord) {
  const assignedTo = assignments[item.id]
  if (!assignedTo) {
    error.value = '请选择负责人'
    return
  }
  busy.value = true
  try {
    await assignWatcherFinding(createApiClient(), item.id, assignedTo)
    notice.value = '巡检发现已分配'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '巡检发现分配失败'
  } finally {
    busy.value = false
  }
}
async function close(item: WatcherFindingRecord) {
  const resolution = globalThis.prompt('填写实际处理结果后关闭该发现', '')?.trim() || ''
  if (resolution.length < 3) {
    error.value = '处理结果至少需要 3 个字符'
    return
  }
  busy.value = true
  try {
    await closeWatcherFinding(createApiClient(), item.id, resolution)
    notice.value = '巡检发现已关闭'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '巡检发现关闭失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="watcher-workspace">
    <header class="workspace-head"><div><p class="eyebrow">EYE OF THE VENUE</p><h1>鹰眼巡检</h1></div><button class="primary" :disabled="busy" @click="openCreate">创建巡检策略</button></header>
    <StatePanel v-if="loading" state="loading" title="正在读取巡检数据" />
    <StatePanel v-else-if="error" state="error" title="巡检操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <article class="panel">
      <div class="panel-head"><h2>巡检策略</h2><span class="muted">{{ policies.length }} 条</span></div>
      <div v-if="policies.length" class="policy-grid">
        <article v-for="item in policies" :key="item.id" class="policy-card">
          <div class="card-head"><strong>{{ item.name }}</strong><StatusBadge :label="item.enabled ? '已启用' : '已停用'" :tone="item.enabled ? 'success' : 'neutral'" /></div>
          <p>{{ item.description || '无说明' }}</p>
          <div class="badges"><StatusBadge :label="`Cron ${item.schedule_cron || '—'}`" tone="info" /><StatusBadge :label="`v${item.version || 1}`" tone="neutral" /><StatusBadge v-for="type in item.check_types || []" :key="type" :label="type" tone="neutral" /></div>
          <div class="row-actions"><button :disabled="busy" @click="openEdit(item)">编辑</button><button :disabled="busy" @click="toggle(item)">{{ item.enabled ? '停用' : '启用' }}</button><button class="primary" :disabled="busy || !item.enabled" :title="item.enabled ? '立即运行' : '先启用策略'" @click="run(item)">立即运行</button></div>
        </article>
      </div>
      <p v-else class="muted">暂无巡检策略。创建 SLA、任务或 SOP 巡检策略。</p>
    </article>

    <div class="split-grid">
      <article class="panel">
        <div class="panel-head"><h2>巡检发现</h2><span class="muted">{{ findings.length }} 条</span></div>
        <div class="table-wrap"><table><thead><tr><th>发现</th><th>级别</th><th>状态</th><th>负责人</th><th>操作</th></tr></thead><tbody>
          <tr v-for="item in findings" :key="item.id"><td><strong>{{ item.title || item.finding_type || '巡检发现' }}</strong><small>{{ item.description || item.details || '' }}</small></td><td><StatusBadge :label="item.severity || '—'" :tone="tone(item.severity)" /></td><td><StatusBadge :label="item.status || 'OPEN'" :tone="tone(item.status)" /></td><td><span v-if="item.assigned_to">{{ assigneeMap[item.assigned_to] || item.assigned_to }}</span><select v-else v-model="assignments[item.id]"><option value="">选择负责人</option><option v-for="user in assignees" :key="user.id" :value="user.id">{{ user.display_name || user.username }}</option></select></td><td class="row-actions"><button v-if="item.status !== 'CLOSED'" :disabled="busy" @click="assign(item)">处理</button><button v-if="item.status !== 'CLOSED'" class="danger" :disabled="busy" @click="close(item)">关闭</button><span v-else class="muted">{{ item.resolution || '已关闭' }}</span></td></tr>
          <tr v-if="!findings.length"><td colspan="5" class="empty">暂无巡检发现。运行启用的策略后查看真实发现。</td></tr>
        </tbody></table></div>
      </article>
      <article class="panel">
        <div class="panel-head"><h2>运行记录</h2><span class="muted">最近 50 次</span></div>
        <div class="table-wrap"><table><thead><tr><th>时间</th><th>来源</th><th>状态</th><th>发现</th><th>Trace</th></tr></thead><tbody>
          <tr v-for="item in runs" :key="item.id"><td class="mono">{{ format(item.started_at) }}</td><td>{{ item.trigger_source || '—' }}</td><td><StatusBadge :label="item.status || 'UNKNOWN'" :tone="tone(item.status)" /></td><td>{{ item.finding_count || 0 }}</td><td class="mono">{{ item.trace_id || '—' }}</td></tr>
          <tr v-if="!runs.length"><td colspan="5" class="empty">暂无运行记录。手动运行策略或等待 Scheduler 触发。</td></tr>
        </tbody></table></div>
      </article>
    </div>

    <form v-if="policyOpen" class="panel form-panel" @submit.prevent="savePolicy">
      <div class="panel-head"><h2>{{ editingId ? '编辑巡检策略' : '创建巡检策略' }}</h2><button type="button" class="ghost" @click="policyOpen = false">取消</button></div>
      <label>策略名称<input v-model="form.name" required minlength="2" maxlength="120"></label>
      <label>执行计划<input v-model="form.schedule_cron" required placeholder="0 10 * * *"></label>
      <label>检查类型<input :value="form.check_types.join(', ')" @input="form.check_types = ($event.target as HTMLInputElement).value.split(',').map((item) => item.trim().toUpperCase()).filter(Boolean)"></label>
      <label>状态<select v-model="form.enabled"><option :value="true">启用</option><option :value="false">停用</option></select></label>
      <label>最大检查对象<input v-model.number="form.config.max_targets" type="number" min="1" max="1000" required></label>
      <label class="wide">说明<textarea v-model="form.description" maxlength="1000" rows="3"></textarea></label>
      <button type="submit" :disabled="busy">保存策略</button>
    </form>
  </section>
</template>

<style scoped>
.watcher-workspace { display: grid; gap: 18px; }
.workspace-head, .card-head, .panel-head, .row-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.panel, .policy-card { display: grid; gap: 10px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.policy-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; }
.policy-card p { margin: 0; color: var(--mp-color-body); font-size: 13px; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; }
input, select, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.primary { border-color: var(--mp-color-primary); color: white; background: var(--mp-color-primary); }
button.danger { border-color: var(--mp-color-danger); color: var(--mp-color-danger); }
button.ghost { border-color: transparent; background: transparent; }
button:disabled { opacity: .55; cursor: wait; }
.split-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: 14px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { display: block; color: var(--mp-color-mute); font-size: 12px; }
.form-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-panel label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.form-panel .panel-head, .form-panel .wide, .form-panel > button { grid-column: 1 / -1; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .row-actions { flex-direction: column; } .split-grid, .form-panel { grid-template-columns: 1fr; } }
</style>
