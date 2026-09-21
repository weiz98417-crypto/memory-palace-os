<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  loadFeatureRegistry,
  loadIntegrations,
  loadSettings,
  updateSetting,
  type FeatureRegistry,
  type IntegrationRecord,
  type SettingRecord,
} from '../administration'

const settings = ref<SettingRecord[]>([])
const integrations = ref<IntegrationRecord[]>([])
const registry = ref<FeatureRegistry>({})
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const session = createApiClient().auth.read() as { role?: string } | null
const isAdmin = computed(() => session?.role === 'admin')
const registrySummary = computed(() => registry.value.summary || {})
const registryCounts = computed(() => registrySummary.value.by_status || {})

function format(value?: number | string | null): string {
  if (value === undefined || value === null || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}
function tone(value?: string | boolean): 'success' | 'warning' | 'danger' | 'neutral' | 'info' {
  if (typeof value === 'boolean') return value ? 'success' : 'danger'
  const state = String(value || '').toUpperCase()
  if (['HEALTHY', 'READY', 'LIVE_VERIFIED', 'ACTIVE', 'PASSED', 'PUBLISHED'].includes(state)) return 'success'
  if (['DEGRADED', 'WARNING', 'CONFIGURED', 'REGISTERED_UNVERIFIED', 'IN_REVIEW'].includes(state)) return 'warning'
  if (['BLOCKED', 'UNHEALTHY', 'DISABLED', 'EXHAUSTED'].includes(state)) return 'danger'
  return state ? 'info' : 'neutral'
}
function displayValue(item: SettingRecord): string {
  if (typeof item.value === 'boolean') return item.value ? '启用' : '停用'
  return item.value === null || item.value === undefined || item.value === '' ? '—' : String(item.value)
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const client = createApiClient()
    const [nextSettings, nextIntegrations, nextRegistry] = await Promise.all([
      loadSettings(client),
      loadIntegrations(client),
      loadFeatureRegistry(client),
    ])
    settings.value = nextSettings
    integrations.value = nextIntegrations
    registry.value = nextRegistry
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '系统设置读取失败'
  } finally {
    loading.value = false
  }
}
async function edit(item: SettingRecord) {
  const raw = globalThis.prompt(`修改 ${item.key}（类型：${item.type}）`, displayValue(item))
  if (raw === null) return
  let value: unknown = raw.trim()
  if (item.type === 'integer') {
    value = Number(value)
    if (!Number.isFinite(value)) {
      error.value = '配置值必须是整数'
      return
    }
  }
  if (item.type === 'boolean') value = value === 'true' || value === '启用'
  busy.value = true
  error.value = ''
  try {
    await updateSetting(createApiClient(), item.key, value)
    notice.value = '设置已更新'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '设置更新失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="settings-workspace">
    <header class="workspace-head"><div><p class="eyebrow">GOVERNED CONFIGURATION</p><h1>系统设置</h1><p class="muted">只允许修改后端白名单中的非敏感配置；模型与外部渠道仅显示真实配置和 Live 证据。</p></div><StatusBadge :label="isAdmin ? '管理员可编辑' : '经理只读'" :tone="isAdmin ? 'success' : 'neutral'" /></header>
    <StatePanel v-if="loading" state="loading" title="正在读取系统设置" />
    <StatePanel v-else-if="error" state="error" title="系统设置操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <div class="split-grid">
      <article class="panel">
        <div class="panel-head"><h2>非敏感配置</h2><span class="muted">{{ settings.length }} 项</span></div>
        <div class="settings-list"><article v-for="item in settings" :key="item.key" class="setting-item"><div><strong>{{ item.key }}</strong><small>类型 {{ item.type }} · 更新 {{ format(item.updated_at) }}</small></div><StatusBadge :label="displayValue(item)" tone="neutral" /><button v-if="isAdmin" :disabled="busy" @click="edit(item)">修改</button></article><p v-if="!settings.length" class="muted">暂无配置项。</p></div>
      </article>

      <article class="panel">
        <div class="panel-head"><h2>外部集成</h2><span class="muted">配置不等于可用</span></div>
        <div class="settings-list"><article v-for="item in integrations" :key="item.id || item.key || item.name" class="setting-item"><div><strong>{{ item.name || item.id || item.key }}</strong><small>已配置 {{ item.configured ? '是' : '否' }} · Live {{ item.live_verified ? '通过' : '未通过' }}{{ item.model ? ` · ${item.model}` : '' }}</small></div><StatusBadge :label="item.status || 'UNKNOWN'" :tone="tone(item.status)" /><p>{{ item.blocked_reason || ((item.missing || []).length ? `缺少 ${item.missing?.join(', ')}` : '已就绪') }}</p></article></div>
      </article>
    </div>

    <article class="panel registry-panel">
      <div class="panel-head"><div><h2>功能验收注册表</h2><small class="muted">PRD 交付门禁</small></div><StatusBadge :label="registrySummary.release_gate_passed ? '发布门禁通过' : '发布门禁阻塞'" :tone="tone(Boolean(registrySummary.release_gate_passed))" /></div>
      <div v-if="registry.collection_errors?.length" class="registry-error">证据采集异常：{{ registry.collection_errors.map((item) => `${item.source || 'unknown'} / ${item.error_type || 'unknown'}`).join('；') }}</div>
      <div class="metric-grid"><article><span>业务功能</span><strong>{{ registrySummary.business_total || 0 }}</strong></article><article><span>已 READY</span><strong>{{ registrySummary.business_ready || 0 }}</strong></article><article><span>BLOCKED</span><strong>{{ registryCounts.BLOCKED || 0 }}</strong></article><article><span>发布门禁</span><strong>{{ registrySummary.release_gate_passed ? 'PASS' : 'BLOCK' }}</strong></article></div>
      <div class="journey-list"><article v-for="journey in registry.uat_journeys || []" :key="journey.id"><strong>{{ journey.id }} · {{ journey.name }}</strong><StatusBadge :label="journey.status || 'UNKNOWN'" :tone="tone(journey.status)" /><p>覆盖：{{ (journey.covers || []).join(', ') || '—' }}</p><small v-if="journey.acceptance?.missing?.length">阻塞：{{ journey.acceptance.missing.join(' · ') }}</small><small v-else>覆盖项证据已齐全</small></article></div>
      <div class="table-wrap"><table><thead><tr><th>功能 / 责任域</th><th>状态</th><th>验收证据</th><th>Trace</th></tr></thead><tbody>
        <tr v-for="item in registry.items || []" :key="item.id"><td><strong>{{ item.id }} · {{ item.name }}</strong><small>{{ item.category }} · {{ item.owner || '—' }}</small></td><td><StatusBadge :label="item.status || 'UNKNOWN'" :tone="tone(item.status)" /></td><td>{{ item.acceptance?.satisfied?.length || 0 }} / {{ item.acceptance?.required?.length || 0 }}<small v-if="item.acceptance?.missing?.length">缺失：{{ item.acceptance.missing.join(' · ') }}</small><small v-else>运行证据已齐全</small></td><td class="mono">{{ item.runtime_evidence?.[0]?.trace_id || '—' }}</td></tr>
        <tr v-if="!registry.items?.length"><td colspan="4" class="empty">暂无功能注册表条目。</td></tr>
      </tbody></table></div>
    </article>
  </section>
</template>

<style scoped>
.settings-workspace { display: grid; gap: 18px; }
.workspace-head, .panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.panel { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.split-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.settings-list, .journey-list { display: grid; gap: 8px; }
.setting-item, .journey-list article { display: grid; grid-template-columns: 1fr auto auto; align-items: start; gap: 10px; padding: 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); color: var(--mp-color-body); font-size: 13px; }
.setting-item p { grid-column: 1 / -1; margin: 0; color: var(--mp-color-mute); font-size: 12px; }
.setting-item small, td small { display: block; color: var(--mp-color-mute); font-size: 12px; }
.setting-item button { min-height: 34px; padding: 6px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); cursor: pointer; }
.registry-panel { overflow: hidden; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.metric-grid article { display: grid; gap: 4px; padding: 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); }
.metric-grid span { color: var(--mp-color-mute); font-size: 12px; }
.metric-grid strong { color: var(--mp-color-ink); font-size: 22px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
.registry-error { padding: 10px 12px; border: 1px solid var(--mp-color-danger); border-radius: var(--mp-radius-md); color: var(--mp-color-danger); font-size: 13px; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head { flex-direction: column; } .split-grid, .metric-grid { grid-template-columns: 1fr; } }
</style>
