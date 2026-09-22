<script setup lang="ts">
import { computed, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { AppShell, LoginShell } from '@memory-palace/domain-ui'
const loginBackground = '/shared/login-backgrounds/integration.webp'

const client = createApiClient()
const session = ref<any>(client.auth.read())
const username = ref('wangfang')
const password = ref('')
const error = ref('')
const authenticating = ref(false)
const canAccessIntegration = computed(() => ['manager', 'admin'].includes(String(session.value?.role || '')))

async function login() {
  authenticating.value = true
  error.value = ''
  try {
    const user = await client.auth.login(username.value, password.value)
    if (!['manager', 'admin'].includes(String(user?.role || ''))) {
      client.auth.clear()
      throw new Error('该入口需要经理或管理员身份')
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
    v-if="!canAccessIntegration"
    v-model:username="username"
    v-model:password="password"
    title="内部通知接入环境"
    subtitle="经理操作的通知联调控制台"
    eyebrow="INTEGRATION ACCESS"
    button-label="进入接入环境"
    busy-label="正在验证"
    scene-label="MEMORY PALACE OS"
    :error="error"
    :busy="authenticating"
    :background-image="loginBackground"
    :footer="['只读取正式 API 与内部系统 outbox', '未配置的外部渠道不会伪造送达']"
    variant="integration"
    @submit="login"
  />
  <AppShell v-else title="接入环境" venue="云栖山景区" connection="CONNECTED" last-updated="--" :theme="'field'">
    <template #nav><div class="entry-mark">/simulator/wecom/</div></template>
    <RouterView />
  </AppShell>
</template>
