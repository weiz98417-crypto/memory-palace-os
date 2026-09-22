<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge, TaskCard } from '@memory-palace/domain-ui'
import {
  assignTask,
  createTask,
  decomposeTasks,
  loadAssignees,
  loadEvents,
  loadSessions,
  loadTask,
  loadTasks,
  taskAction,
  type AssigneeRecord,
  type EventRecord,
  type SessionRecord,
  type TaskRecord,
} from '../operational'
import ModalShell from '../components/ModalShell.vue'

const tasks = ref<TaskRecord[]>([])
const assignees = ref<AssigneeRecord[]>([])
const events = ref<EventRecord[]>([])
const sessions = ref<SessionRecord[]>([])
const selected = ref<TaskRecord | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const statusFilter = ref('')
const query = ref('')
const showCreate = ref(false)
const showDecompose = ref(false)
const createForm = ref({ session_id: '', event_id: '', description: '', assigned_user_id: '', max_attempts: 3 })
const decomposeForm = ref({ session_id: '', event_id: '', goal: '', assigned_user_id: '', max_attempts: 3 })
const completeSummary = ref('')
const failureReason = ref('')
const assignTo = ref('')

const visibleTasks = computed(() => tasks.value.filter((task) => {
  const statusOk = !statusFilter.value || String(task.status || '').toUpperCase() === statusFilter.value
  const q = query.value.trim().toLowerCase()
  const text = [task.description, task.business_id, task.assigned_user_id, task.block_reason].join(' ').toLowerCase()
  return statusOk && (!q || text.includes(q))
}))
function assigneeName(userId?: string): string {
  return assignees.value.find((item) => item.id === userId)?.display_name || userId || '未分配'
}
function statusTone(status: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'DONE') return 'success'
  if (status === 'RUNNING') return 'warning'
  if (status === 'FAILED') return 'danger'
  return 'neutral'
}
function resultRows(value: unknown): Array<{ label: string; value: string }> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>).map(([label, item]) => ({
    label,
    value: typeof item === 'object' ? JSON.stringify(item) : String(item),
  }))
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const client = createApiClient()
    const [nextTasks, nextAssignees, nextEvents, nextSessions] = await Promise.all([
      loadTasks(client), loadAssignees(client), loadEvents(client), loadSessions(client),
    ])
    tasks.value = nextTasks
    assignees.value = nextAssignees
    events.value = nextEvents
    sessions.value = nextSessions
    if (!createForm.value.session_id && nextSessions[0]) createForm.value.session_id = nextSessions[0].session_id
    if (!decomposeForm.value.session_id && nextSessions[0]) decomposeForm.value.session_id = nextSessions[0].session_id
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务读取失败'
  } finally {
    loading.value = false
  }
}
async function open(task: TaskRecord) {
  busy.value = true
  try {
    const result = await loadTask(createApiClient(), task.id)
    selected.value = result.task || result
    completeSummary.value = ''
    failureReason.value = ''
    assignTo.value = selected.value?.assigned_user_id || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务详情读取失败'
  } finally {
    busy.value = false
  }
}
async function submitCreate() {
  busy.value = true
  try {
    await createTask(createApiClient(), { ...createForm.value, event_id: createForm.value.event_id || null, assigned_user_id: createForm.value.assigned_user_id || null })
    notice.value = '任务已创建'
    showCreate.value = false
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务创建失败'
  } finally {
    busy.value = false
  }
}
async function submitDecompose() {
  busy.value = true
  try {
    await decomposeTasks(createApiClient(), { ...decomposeForm.value, event_id: decomposeForm.value.event_id || null, assigned_user_id: decomposeForm.value.assigned_user_id || null })
    notice.value = '任务拆解已提交'
    showDecompose.value = false
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务拆解失败'
  } finally {
    busy.value = false
  }
}
async function action(task: TaskRecord, name: 'start' | 'complete' | 'fail' | 'retry' | 'unblock') {
  busy.value = true
  try {
    const body = name === 'complete' ? { result: { summary: completeSummary.value.trim() } } : name === 'fail' ? { error: failureReason.value.trim() } : undefined
    await taskAction(createApiClient(), task.id, name, body)
    notice.value = `任务 ${name} 已提交`
    await load()
    await open(task)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务操作失败'
  } finally {
    busy.value = false
  }
}
async function saveAssignment() {
  if (!selected.value) return
  busy.value = true
  try {
    await assignTask(createApiClient(), selected.value.id, { assigned_user_id: assignTo.value || null })
    notice.value = '任务负责人已更新'
    await load()
    await open(selected.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '任务分配失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="task-workspace">
    <header class="workspace-head">
      <div><p class="eyebrow">TASK & APPROVAL</p><h1>任务与审批</h1><p class="muted">任务由人工执行；开始、完成、失败和恢复都经过服务端状态校验与审计。</p></div>
      <div class="actions"><button @click="showCreate = !showCreate">创建单项任务</button><button @click="showDecompose = !showDecompose">AI 拆解任务</button><button :disabled="loading" @click="load">刷新</button></div>
    </header>
    <StatePanel v-if="loading" state="loading" title="正在读取任务" />
    <StatePanel v-else-if="error" state="error" title="任务读取失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <ModalShell v-if="showCreate" label="创建单项任务" @close="showCreate = false">
      <form class="panel form-grid" @submit.prevent="submitCreate">
      <h2>创建单项任务</h2>
      <label>会话<select v-model="createForm.session_id"><option v-for="item in sessions" :key="item.session_id" :value="item.session_id">{{ item.session_id }}</option></select></label>
      <label>关联事件<select v-model="createForm.event_id"><option value="">通用待办</option><option v-for="item in events" :key="item.event_id" :value="item.event_id">{{ item.business_id || item.raw_text }}</option></select></label>
      <label>负责人<select v-model="createForm.assigned_user_id"><option value="">未分配</option><option v-for="item in assignees" :key="item.id" :value="item.id">{{ item.display_name || item.username }}</option></select></label>
      <label class="wide">任务内容<textarea v-model="createForm.description" rows="3" required></textarea></label>
      <button type="submit" :disabled="busy">创建任务</button>
    </form>
    </ModalShell>

    <ModalShell v-if="showDecompose" label="AI 拆解任务" @close="showDecompose = false">
      <form class="panel form-grid" @submit.prevent="submitDecompose">
      <h2>AI 拆解任务</h2>
      <label>会话<select v-model="decomposeForm.session_id"><option v-for="item in sessions" :key="item.session_id" :value="item.session_id">{{ item.session_id }}</option></select></label>
      <label>关联事件<select v-model="decomposeForm.event_id"><option value="">通用待办</option><option v-for="item in events" :key="item.event_id" :value="item.event_id">{{ item.business_id || item.raw_text }}</option></select></label>
      <label>负责人<select v-model="decomposeForm.assigned_user_id"><option value="">未分配</option><option v-for="item in assignees" :key="item.id" :value="item.id">{{ item.display_name || item.username }}</option></select></label>
      <label class="wide">目标<textarea v-model="decomposeForm.goal" rows="3" required></textarea></label>
      <button type="submit" :disabled="busy">提交拆解</button>
    </form>
    </ModalShell>

    <article class="panel">
      <div class="filters"><input v-model="query" placeholder="搜索任务"><select v-model="statusFilter"><option value="">全部状态</option><option>PENDING</option><option>RUNNING</option><option>BLOCKED</option><option>DONE</option><option>FAILED</option></select><span class="muted">{{ visibleTasks.length }} 条</span></div>
      <div class="table-wrap"><table><thead><tr><th>任务</th><th>状态</th><th>负责人</th><th>依赖</th><th>尝试</th><th></th></tr></thead><tbody>
        <tr v-for="task in visibleTasks" :key="task.id">
          <td><strong>{{ task.description }}</strong><small>{{ task.business_id || task.id }}</small></td>
          <td><StatusBadge :label="task.status || 'PENDING'" :tone="statusTone(String(task.status || ''))" /></td>
          <td>{{ assigneeName(task.assigned_user_id) }}</td>
          <td>{{ (task.dependencies || []).length || '无' }}</td>
          <td>{{ task.attempts || 0 }} / {{ task.max_attempts || 3 }}</td>
          <td><button @click="open(task)">详情</button><button v-if="task.status === 'PENDING'" :disabled="busy" @click="action(task, 'start')">开始</button><button v-if="task.status === 'FAILED'" :disabled="busy" @click="action(task, 'retry')">恢复</button></td>
        </tr>
      </tbody></table></div>
    </article>

    <article v-if="selected" class="panel detail">
      <TaskCard :task="selected">
        <template #actions>
          <select v-model="assignTo"><option value="">未分配</option><option v-for="item in assignees" :key="item.id" :value="item.id">{{ item.display_name || item.username }}</option></select>
          <button :disabled="busy" @click="saveAssignment">保存负责人</button>
          <button v-if="selected.status === 'PENDING'" :disabled="busy" @click="action(selected, 'start')">开始</button>
          <button v-if="selected.status === 'RUNNING'" :disabled="busy" @click="action(selected, 'complete')">完成</button>
          <button v-if="selected.status === 'RUNNING'" :disabled="busy" @click="action(selected, 'fail')">标记失败</button>
          <button v-if="selected.status === 'BLOCKED' && selected.block_reason" :disabled="busy" @click="action(selected, 'unblock')">解除阻塞</button>
          <button v-if="selected.status === 'FAILED'" :disabled="busy" @click="action(selected, 'retry')">恢复</button>
        </template>
      </TaskCard>
      <div v-if="selected.status === 'RUNNING'" class="action-inputs">
        <textarea v-model="completeSummary" rows="2" placeholder="完成结果"></textarea>
        <textarea v-model="failureReason" rows="2" placeholder="失败原因"></textarea>
      </div>
      <dl v-if="resultRows(selected.result).length" class="result-grid"><div v-for="row in resultRows(selected.result)" :key="row.label"><dt>{{ row.label }}</dt><dd>{{ row.value }}</dd></div></dl>
    </article>
  </section>
</template>

<style scoped>
.task-workspace { display: grid; gap: 18px; }
.workspace-head, .actions, .filters { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.panel { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.form-grid { grid-template-columns: 1fr 1fr 1fr; align-items: end; }
.form-grid h2, .form-grid .wide { grid-column: 1 / -1; }
.form-grid label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
input, select, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button:disabled { opacity: 0.55; cursor: wait; }
.filters { justify-content: flex-start; }
.filters input { min-width: 240px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { display: block; margin-top: 3px; color: var(--mp-color-mute); font-family: var(--mp-font-mono); }
.detail { max-width: 900px; }
.action-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 8px; }
.result-grid div { display: grid; gap: 3px; }
dt { color: var(--mp-color-mute); font-size: 12px; }
dd { margin: 0; color: var(--mp-color-body); font-size: 13px; }
.notice { color: var(--mp-color-success); font-size: 13px; }
@media (max-width: 900px) { .workspace-head, .actions { flex-direction: column; } .form-grid, .action-inputs { grid-template-columns: 1fr; } }
</style>
