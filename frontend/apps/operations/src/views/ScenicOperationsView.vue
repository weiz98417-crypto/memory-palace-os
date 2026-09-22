<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge, type StateTone } from '@memory-palace/domain-ui'
import {
  loadScenicSnapshot,
  parseSignalData,
  scenicRunLabel,
  sendScenicCommand,
  type OperationsClient,
  type ScenicSnapshot,
} from '../operations'

const props = defineProps<{ client?: OperationsClient }>()
const client = props.client || createApiClient({ storageKeyPrefix: 'mp_operations_' })
const session = ref<any>(client.auth.read())
const authenticated = computed(() => session.value?.username === 'simulation-ops')
const username = ref('simulation-ops')
const password = ref('')
const snapshot = ref<ScenicSnapshot>({})
const loading = ref(false)
const error = ref('')
const message = ref('')
const busy = ref('')
const speed = ref('1')
const sourceType = ref('DEVICE')
const zone = ref('vehicle-depot')
const signalData = ref('{"label":"人工观察"}')
const signalError = ref('')

async function login() {
  error.value = ''
  try {
    const user = await client.auth.login(username.value, password.value)
    if (user?.username !== 'simulation-ops') {
      client.auth.clear()
      session.value = null
      throw new Error('必须使用 simulation-ops 身份')
    }
    session.value = user
    password.value = ''
    await refresh()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败'
  }
}

async function refresh() {
  if (!authenticated.value) return
  loading.value = true
  error.value = ''
  try {
    snapshot.value = await loadScenicSnapshot(client)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '状态读取失败'
  } finally {
    loading.value = false
  }
}

async function command(kind: string, payload: Record<string, unknown> = {}) {
  if (!authenticated.value || busy.value) return
  busy.value = kind
  message.value = ''
  error.value = ''
  try {
    await sendScenicCommand(client, kind, payload)
    message.value = `${kind} 已记录`
    await refresh()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '命令执行失败'
  } finally {
    busy.value = ''
  }
}

async function injectSignal() {
  signalError.value = ''
  try {
    const data = parseSignalData(signalData.value)
    await command('INJECT_SIGNAL', {
      source_type: sourceType.value,
      source_key: `manual-${Date.now()}`,
      zone_id: zone.value,
      signal_type: 'MANUAL_OBSERVATION',
      data,
    })
  } catch (cause) {
    signalError.value = cause instanceof Error ? cause.message : 'JSON 数据无效'
  }
}

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}
function statusTone(value?: string): StateTone {
  const state = String(value || '').toUpperCase()
  if (!state) return 'neutral'
  if (['PENDING', 'QUEUED', 'WAITING'].includes(state)) return 'primary'
  if (['RUNNING', 'IN_PROGRESS'].includes(state)) return 'info'
  if (['READY', 'DONE', 'SUCCEEDED', 'CLOSED', 'RESOLVED', 'HEALTHY'].includes(state)) return 'success'
  if (['SUPERSEDED', 'WARNING', 'DEGRADED', 'P2', 'OPEN'].includes(state)) return 'warning'
  if (['FAILED', 'ERROR', 'P0', 'P1', 'CRITICAL', 'HIGH'].includes(state)) return 'danger'
  return 'info'
}
function record(value: unknown): Record<string, any> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, any> : null
}
const evidence = computed(() => {
  const groups = [
    ['监测信号', snapshot.value.signals],
    ['态势告警', snapshot.value.alerts],
    ['运营事件', snapshot.value.incidents],
  ] as const
  return groups.flatMap(([group, values]) => (Array.isArray(values) ? values : []).map((item, index) => {
    const source = record(item) || {}
    return {
      key: `${group}:${text(source.id || source.alert_id || source.incident_id || index)}`,
      title: text(source.source_key || source.alert_type || source.business_id || source.title || group),
      detail: text(source.label || source.message || source.summary || source.signal_type || '已记录'),
      status: text(source.status || source.severity || source.event_type).toUpperCase(),
      group,
    }
  }))
})

onMounted(() => {
  if (authenticated.value) void refresh()
})
</script>

<template>
  <section class="operations-view">
    <StatePanel v-if="!authenticated" state="empty" title="运行准备身份验证" message="只接受预置的 simulation-ops 身份，并限制为本机/受信入口访问。">
      <form class="login-form" @submit.prevent="login">
        <label>账号<input v-model="username" autocomplete="username"></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password"></label>
        <button type="submit">登录</button>
      </form>
    </StatePanel>

    <template v-else>
      <header class="operations-header">
        <div>
          <p class="eyebrow">PROTECTED OPERATIONS</p>
          <h1>景区模拟控制</h1>
          <p class="muted">仅控制外部模拟输入与模拟时钟；事件、任务、审批和关闭必须在正式业务入口完成。</p>
        </div>
        <StatusBadge label="本地运维身份已验证" tone="success" />
      </header>

      <StatePanel v-if="loading" state="loading" title="正在读取运行状态" />
      <StatePanel v-else-if="error" state="error" title="运行状态读取失败" :message="error" />
      <p v-else-if="message" class="notice">{{ message }}</p>

      <div class="operations-grid">
        <article class="panel">
          <div class="panel-head"><h2>版本化故事</h2><StatusBadge :label="snapshot.run?.status || '未准备'" :tone="snapshot.run ? 'info' : 'neutral'" /></div>
          <p>雨后观光车异常 → 东门客流上升</p>
          <p class="run-label">{{ scenicRunLabel(snapshot) }}</p>
          <button class="primary" :disabled="!!busy" @click="command('PREPARE_SCENARIO')">准备新运行</button>
        </article>

        <article class="panel">
          <div class="panel-head"><h2>模拟时钟</h2><span class="mono">{{ snapshot.latest_sequence ? `seq ${snapshot.latest_sequence}` : '—' }}</span></div>
          <label class="field">倍速
            <select v-model="speed">
              <option>0.5</option><option selected>1</option><option>2</option><option>4</option><option>8</option>
            </select>
          </label>
          <div class="button-row">
            <button :disabled="!!busy" @click="command('CLOCK_PLAY', { speed: Number(speed) })">播放</button>
            <button :disabled="!!busy" @click="command('CLOCK_PAUSE')">暂停</button>
            <button :disabled="!!busy" @click="command('CLOCK_STEP', { seconds: 1 })">单步 1 秒</button>
            <button :disabled="!!busy" @click="command('CLOCK_STEP', { seconds: 2 })">单步 2 秒</button>
            <button :disabled="!!busy" @click="command('CLOCK_STEP', { seconds: 28 })">单步 28 秒</button>
            <button :disabled="!!busy" @click="command('CLOCK_STEP', { seconds: 60 })">单步 60 秒</button>
          </div>
        </article>

        <article class="panel wide">
          <h2>人工监测信号注入</h2>
          <form class="signal-form" @submit.prevent="injectSignal">
            <label>类型<select v-model="sourceType"><option>WEATHER</option><option>DEVICE</option><option>CROWD</option><option>LOCATION</option><option>OBSERVATION</option></select></label>
            <label>区域<select v-model="zone"><option value="east-gate">东门集散区</option><option value="vehicle-depot">观光车场站</option><option value="mountain-road">山地游线</option><option value="lake-zone">镜湖游览区</option></select></label>
            <label class="grow">JSON 数据<textarea v-model="signalData" rows="3"></textarea></label>
            <button type="submit" :disabled="!!busy">注入正式态势入口</button>
          </form>
          <p v-if="signalError" class="error-text">{{ signalError }}</p>
        </article>

        <article class="panel wide">
          <h2>运行证据</h2>
          <p v-if="!evidence.length" class="muted">等待状态。运行准备和时钟操作不会直接改变事件闭环。</p>
          <ul v-else class="evidence-list">
            <li v-for="item in evidence" :key="item.key">
              <span class="evidence-group">{{ item.group }}</span>
              <strong>{{ item.title }}</strong>
              <span>{{ item.detail }}</span>
              <StatusBadge v-if="item.status" :label="item.status" :tone="statusTone(item.status)" />
            </li>
          </ul>
        </article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.operations-view { display: grid; gap: 20px; }
.operations-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.operations-header h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.login-form { display: grid; gap: 12px; width: min(420px, 100%); margin-top: 16px; }
.login-form label, .field, .signal-form label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
input, select, textarea { min-height: 40px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
.operations-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.panel { display: grid; align-content: start; gap: 12px; padding: 18px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel.wide { grid-column: 1 / -1; }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.run-label { color: var(--mp-color-body); font-family: var(--mp-font-mono); font-size: 13px; }
.button-row { display: flex; flex-wrap: wrap; gap: 8px; }
.button-row button, .panel button { min-height: 38px; padding: 8px 12px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); cursor: pointer; }
.panel button.primary { border-color: var(--mp-color-primary); background: var(--mp-color-primary); }
.panel button:disabled { cursor: wait; opacity: 0.6; }
.signal-form { display: grid; grid-template-columns: 160px 180px 1fr auto; gap: 12px; align-items: end; }
.grow { min-width: 240px; }
.notice, .error-text { color: var(--mp-color-success); font-size: 13px; }
.error-text { color: var(--mp-color-danger); }
.evidence-list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.evidence-list li { display: grid; grid-template-columns: 90px minmax(160px, .5fr) 1fr auto; gap: 10px; align-items: center; padding: 9px 0; border-top: 1px solid var(--mp-color-hairline); color: var(--mp-color-body); font-size: 13px; }
.evidence-group { color: var(--mp-color-mute); }
.mono { font-family: var(--mp-font-mono); font-size: 12px; }
@media (max-width: 900px) {
  .operations-header { flex-direction: column; }
  .operations-grid { grid-template-columns: 1fr; }
  .signal-form { grid-template-columns: 1fr; }
  .evidence-list li { grid-template-columns: 1fr; }
}
</style>
