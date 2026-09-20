<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { AgentRunCard } from '@memory-palace/domain-ui'
import { loadCommandCenter, type CommandCenterModel } from '../commandCenter'

const model = ref<CommandCenterModel>({ runs: [], nextAction: null, advice: null })
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    model.value = await loadCommandCenter(createApiClient())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '指挥中心加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section data-testid="command-center">
    <p class="eyebrow">NEXT OPERATIONAL ACTION</p>
    <h1>景区指挥中心</h1>
    <p v-if="loading">正在读取态势快照…</p>
    <p v-else-if="error">{{ error }}</p>
    <article v-else-if="model.nextAction" class="foundation-card">
      <small>下一步处置</small>
      <h2>{{ model.nextAction.label }}</h2>
      <p>{{ model.nextAction.description }}</p>
    </article>
    <AgentRunCard v-for="run in model.runs" :key="`${run.artifact}:${run.run_id}`" :run="run" />\n    <article v-if="model.advice" class="foundation-card">
      <small>处置建议 · {{ model.advice.title }}</small>
      <p>{{ model.advice.text || '建议正在生成。' }}</p>
    </article>
  </section>
</template>