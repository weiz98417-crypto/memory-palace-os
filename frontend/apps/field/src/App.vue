<script setup lang="ts">
import { computed, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { AppShell, StatePanel } from '@memory-palace/domain-ui'

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
  <AppShell title="企业运营助手" :venue="session?.venue_id || '云栖山景区'" connection="CONNECTED" last-updated="--" :theme="'field'">
    <template #nav><div class="entry-mark">/assistant/</div></template>
    <StatePanel v-if="!canAccessField" state="empty" title="企业运营助手登录" message="使用组织分配的正式账号继续。">
      <form class="login-form" @submit.prevent="login">
        <label>用户名<input v-model="username" autocomplete="username" required></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password" required></label>
        <p v-if="error" class="error-text">{{ error }}</p>
        <button type="submit" :disabled="authenticating">{{ authenticating ? '登录中' : '登录助手' }}</button>
      </form>
    </StatePanel>
    <FieldWorkspace v-else @logout="logout" />
  </AppShell>
</template>

<script lang="ts">
import FieldWorkspace from './views/FieldTaskView.vue'
export default { components: { FieldWorkspace } }
</script>

<style scoped>
.login-form { display: grid; gap: 14px; width: min(420px, 100%); margin-top: 16px; }
.login-form label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 14px; }
.login-form input { min-height: 44px; padding: 10px 12px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
.login-form button { min-height: 44px; border: 1px solid var(--mp-color-primary); border-radius: var(--mp-radius-md); color: white; background: var(--mp-color-primary); cursor: pointer; }
.error-text { margin: 0; color: var(--mp-color-danger); font-size: 13px; }
</style>
