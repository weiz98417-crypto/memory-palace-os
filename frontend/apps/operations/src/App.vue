<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createApiClient } from '@memory-palace/api-client'
import { AppShell, LoginShell, NavRail } from '@memory-palace/domain-ui'
import { Calendar, DataAnalysis } from '@element-plus/icons-vue'
import loginBackground from './assets/login-background-1672.webp'

const client = createApiClient()
const session = ref<any>(client.auth.read())
const username = ref('simulation-ops')
const password = ref('')
const error = ref('')
const authenticating = ref(false)
const authenticated = computed(() => String(session.value?.username || '') === 'simulation-ops')
const route = useRoute()
const router = useRouter()
const items = [
  { key: 'scenic', label: '运行准备', icon: Calendar },
  { key: 'evaluation', label: '评测证据', icon: DataAnalysis },
]
const active = computed(() => route.path.includes('/evaluation') ? 'evaluation' : 'scenic')
function select(key: string) {
  router.push(key === 'evaluation' ? '/evaluation' : '/scenic')
}

async function login() {
  authenticating.value = true
  error.value = ''
  try {
    const user = await client.auth.login(username.value, password.value)
    if (String(user?.username || '') !== 'simulation-ops') {
      client.auth.clear()
      throw new Error('必须使用受保护的 simulation-ops 身份')
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
  <LoginShell
    v-if="!authenticated"
    v-model:username="username"
    v-model:password="password"
    title="受保护运行准备"
    subtitle="模拟输入、态势时钟与评测证据入口"
    eyebrow="LOCAL OPERATIONS"
    button-label="进入运行准备"
    busy-label="正在验证"
    scene-label="MEMORY PALACE OS"
    :error="error"
    :busy="authenticating"
    :background-image="loginBackground"
    :footer="['只接受 simulation-ops 身份', '仅限本机或受信入口访问']"
    variant="operations"
    @submit="login"
  />
  <AppShell v-else title="受保护运行准备" venue="云栖山景区" connection="CONNECTED" last-updated="--" :theme="'ops'">
    <template #nav>
      <NavRail :items="items" :active-key="active" @select="select" />
    </template>
    <RouterView />
  </AppShell>
</template>
