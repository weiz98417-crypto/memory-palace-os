<script setup lang="ts">
import { computed, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { AppShell, LoginShell } from '@memory-palace/domain-ui'
import FieldWorkspace from './views/FieldTaskView.vue'

const loginBackground = '/shared/login-backgrounds/field.webp'

const client = createApiClient()
const session = ref<any>(client.auth.read())
const username = ref('chenyu')
const password = ref('')
const error = ref('')
const authenticating = ref(false)
const canAccessField = computed(() => ['admin', 'manager', 'operator'].includes(String(session.value?.role || '')))

async function login() {
  authenticating.value = true
  error.value = ''
  try {
    const user = await client.auth.login(username.value, password.value)
    if (!['admin', 'manager', 'operator'].includes(String(user?.role || ''))) {
      client.auth.clear()
      throw new Error('该入口需要现场员工、经理或管理员身份')
    }
    session.value = user
    password.value = ''
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败'
  } finally {
    authenticating.value = false
  }
}
function logout() {
  client.auth.clear()
  session.value = null
}
</script>

<template>
  <LoginShell
    v-if="!canAccessField"
    v-model:username="username"
    v-model:password="password"
    title="企业运营助手"
    subtitle="登录现场端，处理分配给自己的任务与证据"
    eyebrow="FIELD ACCESS"
    button-label="登录助手"
    busy-label="正在登录"
    scene-label="MEMORY PALACE OS"
    :error="error"
    :busy="authenticating"
    :background-image="loginBackground"
    :footer="['仅限景区运营、设备与管理人员', '任务、证据和回执均进入正式审计链路']"
    variant="field"
    @submit="login"
  />
  <AppShell v-else title="企业运营助手" :venue="session?.venue_id || '云栖山景区'" connection="CONNECTED" last-updated="--" :theme="'field'">
    <template #nav><div class="entry-mark">/assistant/</div></template>
    <FieldWorkspace @logout="logout" />
  </AppShell>
</template>
