<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  createUser,
  createVenue,
  enableSimulatorIdentity,
  loadUsers,
  loadVenues,
  resetUserPassword,
  updateUser,
  updateVenue,
  type AccountRole,
  type UserRecord,
  type VenueRecord,
} from '../administration'

const users = ref<UserRecord[]>([])
const venues = ref<VenueRecord[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const userFormOpen = ref(false)
const venueFormOpen = ref(false)
const userForm = ref({ username: '', display_name: '', password: '', role: 'operator' as AccountRole, venue_id: '' })
const venueForm = ref({ id: '', name: '' })

const adminCount = computed(() => users.value.filter((item) => item.role === 'admin').length)
const activeUserCount = computed(() => users.value.filter((item) => item.status === 'ACTIVE').length)
const activeVenueCount = computed(() => venues.value.filter((item) => item.status === 'ACTIVE').length)

function roleLabel(value?: string): string {
  const labels: Record<string, string> = { admin: '系统管理员', manager: '值班经理', operator: '现场操作员', api: 'API 客户端' }
  return labels[String(value || '').toLowerCase()] || value || '—'
}
function tone(value?: string): 'success' | 'danger' | 'neutral' {
  const state = String(value || '').toUpperCase()
  if (state === 'ACTIVE') return 'success'
  if (state === 'DISABLED') return 'danger'
  return 'neutral'
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const client = createApiClient()
    const [nextUsers, nextVenues] = await Promise.all([loadUsers(client), loadVenues(client)])
    users.value = nextUsers
    venues.value = nextVenues
    if (!userForm.value.venue_id) userForm.value.venue_id = nextVenues.find((item) => item.status === 'ACTIVE')?.id || ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '用户与场地读取失败'
  } finally {
    loading.value = false
  }
}
async function saveUser() {
  busy.value = true
  error.value = ''
  try {
    await createUser(createApiClient(), { ...userForm.value, username: userForm.value.username.trim(), display_name: userForm.value.display_name.trim() })
    notice.value = '用户已创建'
    userFormOpen.value = false
    userForm.value = { username: '', display_name: '', password: '', role: 'operator', venue_id: venues.value.find((item) => item.status === 'ACTIVE')?.id || '' }
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '用户创建失败'
  } finally {
    busy.value = false
  }
}
async function toggleUser(item: UserRecord) {
  const next = item.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE'
  if (!globalThis.confirm(`${next === 'ACTIVE' ? '启用' : '停用'}用户「${item.display_name || item.username}」？`)) return
  busy.value = true
  try {
    await updateUser(createApiClient(), item.id, { status: next })
    notice.value = '用户状态已更新'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '用户状态更新失败'
  } finally {
    busy.value = false
  }
}
async function resetPassword(item: UserRecord) {
  const password = globalThis.prompt(`为「${item.display_name || item.username}」设置新密码（至少 8 位）`, '') || ''
  if (password.length < 8) {
    error.value = '新密码至少需要 8 个字符'
    return
  }
  busy.value = true
  try {
    await resetUserPassword(createApiClient(), item.id, password)
    notice.value = '密码已重置，旧刷新令牌已撤销'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '密码重置失败'
  } finally {
    busy.value = false
  }
}
async function mapSimulatorIdentity(item: UserRecord) {
  if (!globalThis.confirm('仅为该用户创建内部系统接入身份映射；不会调用任何真实外部渠道。')) return
  busy.value = true
  try {
    await enableSimulatorIdentity(createApiClient(), item)
    notice.value = '内部系统接入身份已启用'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '接入身份启用失败'
  } finally {
    busy.value = false
  }
}
async function saveVenue() {
  busy.value = true
  error.value = ''
  try {
    await createVenue(createApiClient(), { id: venueForm.value.id.trim(), name: venueForm.value.name.trim() })
    notice.value = '场地已创建'
    venueFormOpen.value = false
    venueForm.value = { id: '', name: '' }
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '场地创建失败'
  } finally {
    busy.value = false
  }
}
async function toggleVenue(item: VenueRecord) {
  const next = item.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE'
  if (!globalThis.confirm(`${next === 'ACTIVE' ? '启用' : '停用'}场地「${item.name || item.id}」？`)) return
  busy.value = true
  try {
    await updateVenue(createApiClient(), item.id, { status: next })
    notice.value = '场地状态已更新'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '场地状态更新失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="management-workspace">
    <header class="workspace-head"><div><p class="eyebrow">IDENTITY & TENANCY</p><h1>用户与场地</h1><p class="muted">管理员维护正式账号、角色、密码、状态和 venue_id；敏感密码不会被页面读取或回显。</p></div><div class="actions"><button :disabled="busy" @click="venueFormOpen = true">新增场地</button><button class="primary" :disabled="busy" @click="userFormOpen = true">新增用户</button></div></header>
    <StatePanel v-if="loading" state="loading" title="正在读取用户与场地" />
    <StatePanel v-else-if="error" state="error" title="管理操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <div class="metrics"><article><span>用户</span><strong>{{ users.length }}</strong><small>在岗 {{ activeUserCount }}</small></article><article><span>管理员</span><strong>{{ adminCount }}</strong><small>含当前账号</small></article><article><span>场地</span><strong>{{ venues.length }}</strong><small>启用 {{ activeVenueCount }}</small></article></div>

    <div class="split-grid">
      <article class="panel">
        <div class="panel-head"><h2>用户</h2><span class="muted">{{ users.length }} 个</span></div>
        <div class="table-wrap"><table><thead><tr><th>用户</th><th>角色</th><th>场地</th><th>状态</th><th>操作</th></tr></thead><tbody>
          <tr v-for="item in users" :key="item.id"><td><strong>{{ item.display_name || item.username }}</strong><small>{{ item.username }}</small></td><td>{{ roleLabel(item.role) }}</td><td class="mono">{{ item.venue_id || '—' }}</td><td><StatusBadge :label="item.status || 'UNKNOWN'" :tone="tone(item.status)" /></td><td class="row-actions"><button v-if="item.status === 'ACTIVE'" :disabled="busy" @click="mapSimulatorIdentity(item)">启用接入身份</button><button :disabled="busy" @click="toggleUser(item)">{{ item.status === 'ACTIVE' ? '停用' : '启用' }}</button><button :disabled="busy" @click="resetPassword(item)">重置密码</button></td></tr>
          <tr v-if="!users.length"><td colspan="5" class="empty">暂无用户。</td></tr>
        </tbody></table></div>
      </article>

      <article class="panel">
        <div class="panel-head"><h2>场地</h2><span class="muted">{{ venues.length }} 个</span></div>
        <div class="table-wrap"><table><thead><tr><th>场地</th><th>标识</th><th>状态</th><th>操作</th></tr></thead><tbody>
          <tr v-for="item in venues" :key="item.id"><td>{{ item.name || '未命名场地' }}</td><td class="mono">{{ item.id }}</td><td><StatusBadge :label="item.status || 'UNKNOWN'" :tone="tone(item.status)" /></td><td><button :disabled="busy" @click="toggleVenue(item)">{{ item.status === 'ACTIVE' ? '停用' : '启用' }}</button></td></tr>
          <tr v-if="!venues.length"><td colspan="4" class="empty">暂无场地。</td></tr>
        </tbody></table></div>
      </article>
    </div>

    <form v-if="userFormOpen" class="panel form-panel" @submit.prevent="saveUser">
      <div class="panel-head"><h2>新增用户</h2><button type="button" class="ghost" @click="userFormOpen = false">取消</button></div>
      <label>用户名<input v-model="userForm.username" required minlength="2" maxlength="64" pattern="[A-Za-z0-9._-]+"></label>
      <label>显示名称<input v-model="userForm.display_name" required maxlength="80"></label>
      <label>初始密码<input v-model="userForm.password" type="password" required minlength="8" maxlength="128" autocomplete="new-password"></label>
      <label>角色<select v-model="userForm.role"><option value="manager">值班经理</option><option value="operator">现场操作员</option><option value="admin">系统管理员</option></select></label>
      <label>场地<select v-model="userForm.venue_id" required><option v-for="venue in venues.filter((item) => item.status === 'ACTIVE')" :key="venue.id" :value="venue.id">{{ venue.name || venue.id }}</option></select></label>
      <button type="submit" :disabled="busy">创建用户</button>
    </form>

    <form v-if="venueFormOpen" class="panel form-panel" @submit.prevent="saveVenue">
      <div class="panel-head"><h2>新增场地</h2><button type="button" class="ghost" @click="venueFormOpen = false">取消</button></div>
      <label>场地标识<input v-model="venueForm.id" required minlength="2" maxlength="64" pattern="[A-Za-z0-9._-]+"></label>
      <label>场地名称<input v-model="venueForm.name" required minlength="2" maxlength="120"></label>
      <button type="submit" :disabled="busy">创建场地</button>
    </form>
  </section>
</template>

<style scoped>
.management-workspace { display: grid; gap: 18px; }
.workspace-head, .actions, .panel-head, .row-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.metrics { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.metrics article, .panel { display: grid; gap: 8px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.metrics span, .metrics small { color: var(--mp-color-mute); font-size: 12px; }
.metrics strong { color: var(--mp-color-ink); font-size: 26px; }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.split-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { display: block; color: var(--mp-color-mute); font-size: 12px; }
input, select, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.primary { border-color: var(--mp-color-primary); color: white; background: var(--mp-color-primary); }
button.ghost { border-color: transparent; background: transparent; }
button:disabled { opacity: .55; cursor: wait; }
.form-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-panel label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.form-panel .panel-head, .form-panel > button { grid-column: 1 / -1; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .actions, .row-actions { flex-direction: column; } .metrics, .split-grid, .form-panel { grid-template-columns: 1fr; } }
</style>
