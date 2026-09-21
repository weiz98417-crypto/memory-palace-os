<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import { closeSession, loadSessions, sessionLabel, type SessionRecord } from '../operational'

const sessions = ref<SessionRecord[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busyId = ref('')

function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function tone(stage: string): 'success' | 'warning' | 'neutral' {
  if (stage === 'CLOSED') return 'success'
  if (stage === 'ACTIVE' || stage === 'RUNNING') return 'warning'
  return 'neutral'
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    sessions.value = await loadSessions(createApiClient())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '会话读取失败'
  } finally {
    loading.value = false
  }
}
async function close(item: SessionRecord) {
  if (busyId.value || ['CLOSED'].includes(String(item.stage || item.status || '').toUpperCase())) return
  busyId.value = item.session_id
  try {
    await closeSession(createApiClient(), item.session_id)
    notice.value = '会话已关闭'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '会话关闭失败'
  } finally {
    busyId.value = ''
  }
}
onMounted(load)
</script>

<template>
  <section class="session-workspace">
    <header class="workspace-head"><div><p class="eyebrow">MESSAGE SESSIONS</p><h1>消息与会话</h1><p class="muted">会话由现场事件进入 Agent 链路后生成；关闭后不再接收新的处理结果。</p></div><button :disabled="loading" @click="load">刷新</button></header>
    <StatePanel v-if="loading" state="loading" title="正在读取会话" />
    <StatePanel v-else-if="error" state="error" title="会话读取失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>
    <article class="panel">
      <div class="table-wrap">
        <table>
          <thead><tr><th>更新时间</th><th>会话</th><th>员工</th><th>状态</th><th>当前 Agent</th><th>意图 / 风险</th><th></th></tr></thead>
          <tbody>
            <tr v-for="item in sessions" :key="item.session_id">
              <td class="mono">{{ format(item.updated_at || item.created_at) }}</td>
              <td><strong>{{ sessionLabel(item) }}</strong><small>{{ item.session_id }}</small></td>
              <td class="mono">{{ item.user_id || '—' }}</td>
              <td><StatusBadge :label="item.stage || item.status || '—'" :tone="tone(String(item.stage || item.status || ''))" /></td>
              <td>{{ item.active_agent || item.agent_name || '—' }}</td>
              <td>{{ item.current_intent || '—' }} / {{ item.current_severity || '—' }}</td>
              <td><button v-if="(item.stage || item.status || '').toUpperCase() !== 'CLOSED'" :disabled="busyId === item.session_id" @click="close(item)">关闭</button></td>
            </tr>
            <tr v-if="!sessions.length"><td colspan="7" class="empty">暂无会话。</td></tr>
          </tbody>
        </table>
      </div>
    </article>
  </section>
</template>

<style scoped>
.session-workspace { display: grid; gap: 18px; }
.workspace-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.panel { display: grid; gap: 14px; padding: 18px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { display: block; margin-top: 3px; color: var(--mp-color-mute); font-family: var(--mp-font-mono); }
button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; cursor: pointer; }
button:disabled { opacity: 0.55; cursor: wait; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head { flex-direction: column; } }
</style>
