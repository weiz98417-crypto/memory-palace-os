<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createApiClient } from '@memory-palace/api-client'
import { AppShell, NavRail, StatePanel } from '@memory-palace/domain-ui'
import { visibleWorkspaces, workspaceByKey } from './workspaces'

const route = useRoute()
const router = useRouter()
const client = createApiClient()
const storedSession = client.auth.read() as any
const session = ref<any>(storedSession?.user || storedSession)
const username = ref('wangfang')
const password = ref('')
const error = ref('')
const authenticating = ref(false)

const canAccessConsole = computed(() => ['manager', 'admin'].includes(String(session.value?.role || '')))
const items = computed(() => visibleWorkspaces(session.value?.role).map((workspace) => ({
  key: workspace.key,
  label: workspace.label,
  icon: workspace.icon,
})))
const activeKey = computed(() => {
  const match = visibleWorkspaces(session.value?.role).find((workspace) => workspace.path !== '/' && route.path.startsWith(workspace.path))
  return match?.key || 'dashboard'
})
const title = computed(() => workspaceByKey(activeKey.value)?.label || '指挥中心')

function select(key: string) {
  const workspace = visibleWorkspaces(session.value?.role).find((item) => item.key === key)
  if (workspace) router.push(workspace.path)
}

async function login() {
  authenticating.value = true
  error.value = ''
  try {
    const user = await client.auth.login(username.value, password.value)
    if (!['manager', 'admin'].includes(String(user?.role || ''))) {
      client.auth.clear()
      throw new Error('该控制台需要经理或管理员身份')
    }
    session.value = user
    password.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败'
  } finally {
    authenticating.value = false
  }
}
</script>

<template>
  <AppShell
    :title="title"
    :venue="session?.venue_id || '云栖山景区'"
    connection="CONNECTED"
    last-updated="--"
    :theme="'ops'"
  >
    <template #nav>
      <NavRail v-if="canAccessConsole" :items="items" :active-key="activeKey" @select="select" />
    </template>
    <StatePanel v-if="!canAccessConsole" state="empty" title="景区指挥中心登录" message="只接受经理或管理员身份。">
      <form class="console-login" @submit.prevent="login">
        <label>账号<input v-model="username" autocomplete="username"></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password"></label>
        <p v-if="error" class="error-text">{{ error }}</p>
        <button type="submit" :disabled="authenticating">{{ authenticating ? '登录中' : '登录' }}</button>
      </form>
    </StatePanel>
    <RouterView v-else />
  </AppShell>
</template>

<style scoped>
.console-login { display: grid; gap: 12px; width: min(420px, 100%); margin-top: 16px; }
.console-login label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.console-login input { min-height: 40px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
.console-login button { min-height: 40px; border: 1px solid var(--mp-color-primary); border-radius: var(--mp-radius-md); color: white; background: var(--mp-color-primary); cursor: pointer; }
.error-text { margin: 0; color: var(--mp-color-danger); font-size: 13px; }
</style>
