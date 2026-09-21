<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { EvidenceTimeline, StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  closeEvent,
  eventLabel,
  eventTimestamp,
  loadEvent,
  loadEvents,
  retryEventExperienceCandidate,
  runEventWatcher,
  updateEvent,
  type EventRecord,
} from '../operational'

const events = ref<EventRecord[]>([])
const selected = ref<EventRecord | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const edit = ref({ event_type: '', severity: 'P3', assigned_to: '' })
const resolution = ref('')

const isClosed = computed(() => String(selected.value?.status || selected.value?.lifecycle || '').toUpperCase() === 'CLOSED')
const evidence = computed(() => {
  const dossier = selected.value?.dossier || {}
  const items = dossier.evidence || dossier.timeline || dossier.activities
  return Array.isArray(items) ? items : []
})

function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function tone(value: string): 'success' | 'warning' | 'danger' | 'neutral' {
  const status = value.toUpperCase()
  if (status === 'CLOSED' || status === 'RESOLVED') return 'success'
  if (status === 'P0' || status === 'P1' || status === 'FAILED') return 'danger'
  if (status === 'OPEN' || status === 'P2') return 'warning'
  return 'neutral'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    events.value = await loadEvents(createApiClient())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '事件读取失败'
  } finally {
    loading.value = false
  }
}

async function open(item: EventRecord) {
  busy.value = true
  error.value = ''
  try {
    selected.value = await loadEvent(createApiClient(), item.event_id)
    edit.value = {
      event_type: selected.value.event_type || '',
      severity: selected.value.severity || 'P3',
      assigned_to: '',
    }
    resolution.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '事件卷宗读取失败'
  } finally {
    busy.value = false
  }
}

async function saveEvent() {
  if (!selected.value || busy.value) return
  busy.value = true
  try {
    const body: Record<string, unknown> = { event_type: edit.value.event_type, severity: edit.value.severity }
    if (edit.value.assigned_to) body.assigned_to = edit.value.assigned_to
    await updateEvent(createApiClient(), selected.value.event_id, body)
    notice.value = '事件已更新'
    await open(selected.value)
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '事件更新失败'
  } finally {
    busy.value = false
  }
}

async function watcherCheck() {
  if (!selected.value || busy.value) return
  busy.value = true
  try {
    const result = await runEventWatcher(createApiClient(), selected.value.event_id)
    notice.value = String(result.summary || (result.ready_to_close ? '证据完整，可闭环' : 'Watcher 已发现待处理问题'))
    await open(selected.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'Watcher 检查失败'
  } finally {
    busy.value = false
  }
}

async function close() {
  if (!selected.value || !resolution.value.trim() || busy.value) return
  busy.value = true
  try {
    const result: any = await closeEvent(createApiClient(), selected.value.event_id)
    notice.value = String(result.experience_candidate?.outcome || '事件已闭环')
    await load()
    await open(selected.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '事件闭环失败'
  } finally {
    busy.value = false
  }
}

async function retryCandidate() {
  if (!selected.value || busy.value) return
  busy.value = true
  try {
    await retryEventExperienceCandidate(createApiClient(), selected.value.event_id)
    notice.value = '经验候选已重新生成'
    await open(selected.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '经验候选重试失败'
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="event-workspace">
    <header class="workspace-head">
      <div><p class="eyebrow">EVENT DOSSIER</p><h1>事件处置</h1><p class="muted">事件卷宗、证据、Watcher 检查和闭环门禁来自正式业务事实。</p></div>
      <button :disabled="loading" @click="load">刷新</button>
    </header>
    <StatePanel v-if="loading" state="loading" title="正在读取事件" />
    <StatePanel v-else-if="error" state="error" title="事件读取失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>
    <article class="panel">
      <div class="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>事件</th><th>类型</th><th>风险</th><th>状态</th><th>负责人</th><th></th></tr></thead>
          <tbody>
            <tr v-for="item in events" :key="item.event_id">
              <td class="mono">{{ format(eventTimestamp(item)) }}</td>
              <td><strong>{{ item.raw_text || '暂无事件说明' }}</strong><small>{{ eventLabel(item) }}</small></td>
              <td>{{ item.event_type || '待确认' }}</td>
              <td><StatusBadge :label="item.severity || '—'" :tone="tone(item.severity || '')" /></td>
              <td><StatusBadge :label="item.status || item.lifecycle || 'OPEN'" :tone="tone(item.status || item.lifecycle || 'OPEN')" /></td>
              <td>{{ item.assigned_to_name || '未分配' }}</td>
              <td><button @click="open(item)">查看卷宗</button></td>
            </tr>
            <tr v-if="!events.length"><td colspan="7" class="empty">暂无事件。</td></tr>
          </tbody>
        </table>
      </div>
    </article>

    <article v-if="selected" class="panel detail">
      <div class="panel-head"><div><h2>{{ selected.raw_text || '事件卷宗' }}</h2><p class="muted">{{ eventLabel(selected) }} · {{ selected.event_type || '待确认' }} · {{ selected.severity || '—' }}</p></div><StatusBadge :label="selected.status || selected.lifecycle || 'OPEN'" :tone="tone(selected.status || selected.lifecycle || 'OPEN')" /></div>
      <div class="fact-grid">
        <div><span>事件编号</span><strong>{{ eventLabel(selected) }}</strong></div>
        <div><span>负责人</span><strong>{{ selected.assigned_to_name || '未分配' }}</strong></div>
        <div><span>上报人</span><strong>{{ selected.reporter_name || '—' }}</strong></div>
        <div><span>更新时间</span><strong>{{ format(eventTimestamp(selected)) }}</strong></div>
      </div>
      <div v-if="evidence.length"><h3>卷宗证据</h3><EvidenceTimeline :items="evidence" /></div>
      <div class="edit-grid">
        <label>事件类型<input v-model="edit.event_type"></label>
        <label>风险等级<select v-model="edit.severity"><option>P0</option><option>P1</option><option>P2</option><option>P3</option><option>P4</option></select></label>
        <button :disabled="busy" @click="saveEvent">更新事件</button>
        <button :disabled="busy" @click="watcherCheck">闭环前合规检查</button>
        <button :disabled="busy" @click="retryCandidate">重试经验候选</button>
      </div>
      <div v-if="!isClosed" class="closure-grid">
        <label>闭环结果<textarea v-model="resolution" rows="3" placeholder="记录现场处置结果，闭环后不可继续修改。"></textarea></label>
        <button class="danger" :disabled="busy || !resolution.trim()" @click="close">提交闭环</button>
      </div>
    </article>
  </section>
</template>

<style scoped>
.event-workspace { display: grid; gap: 18px; }
.workspace-head, .panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.panel { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2, .panel h3 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { display: block; margin-top: 3px; color: var(--mp-color-mute); font-family: var(--mp-font-mono); }
input, select, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.danger { border-color: var(--mp-color-danger); background: color-mix(in srgb, var(--mp-color-danger) 18%, var(--mp-color-surface-elevated)); }
button:disabled { opacity: 0.55; cursor: wait; }
.fact-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.fact-grid div { display: grid; gap: 4px; padding: 10px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); }
.fact-grid span { color: var(--mp-color-mute); font-size: 12px; }
.fact-grid strong { color: var(--mp-color-ink); font-size: 13px; }
.edit-grid { display: grid; grid-template-columns: 1fr 160px auto auto auto; gap: 10px; align-items: end; }
.edit-grid label, .closure-grid label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.closure-grid { display: grid; gap: 10px; justify-items: start; }
.closure-grid label { width: 100%; }
.notice, .empty { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .panel-head { flex-direction: column; } .fact-grid, .edit-grid { grid-template-columns: 1fr; } }
</style>
