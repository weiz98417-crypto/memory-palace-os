<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { buildIntegrationView } from '../integrationStatus'

const view = ref(buildIntegrationView({}))
onMounted(async () => {
  view.value = buildIntegrationView(await createApiClient().request('/channels/simulator-identities'))
})
</script>

<template>
  <section data-testid="integration-view">
    <p class="eyebrow">WECOM SIMULATOR</p>
    <h1>接入环境</h1>
    <p>使用真实 API 与 outbox；不声明已送达外部生产渠道。</p>
    <p>{{ view.identities.length }} 个模拟身份可用</p>
  </section>
</template>