<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createApiClient } from '@memory-palace/api-client'
import { AppShell, NavRail } from '@memory-palace/domain-ui'
import ConsoleLoginView from './views/ConsoleLoginView.vue'
import consoleBackground from './assets/console-background-1672.webp'
import { visibleWorkspaces, workspaceByKey } from './workspaces'

const route = useRoute()
const router = useRouter()
const client = createApiClient()
const session = ref<any>(client.auth.read())

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
watch(canAccessConsole, (allowed) => {
  if (!allowed && route.path !== '/') router.replace('/')
})

function select(key: string) {
  const workspace = visibleWorkspaces(session.value?.role).find((item) => item.key === key)
  if (workspace) router.push(workspace.path)
}
function authenticated(user: any) {
  session.value = user
}
</script>

<template>
  <ConsoleLoginView
    v-if="!canAccessConsole"
    :client="client"
    @authenticated="authenticated"
  />
  <AppShell
    v-else
    :title="title"
    :venue="session?.venue_id || '云栖山景区'"
    connection="CONNECTED"
    last-updated="--"
    :theme="'ops'"
    :background-image="consoleBackground"
  >
    <template #nav>
      <NavRail :items="items" :active-key="activeKey" @select="select" />
    </template>
    <RouterView />
  </AppShell>
</template>
