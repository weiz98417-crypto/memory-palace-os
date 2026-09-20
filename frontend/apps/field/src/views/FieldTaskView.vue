<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { buildFieldView } from '../fieldStatus'

const view = ref({ tasks: [] as any[], evidence: [] as any[], advice: null as any })
onMounted(async () => {
  view.value = buildFieldView(await createApiClient().request('/scenic/snapshot'))
})
</script>

<template>
  <section data-testid="field-view">
    <p class="eyebrow">MOBILE FIELD</p>
    <h1>我的现场任务</h1>
    <article v-if="view.advice" class="foundation-card">
      <small>处置建议 · {{ view.advice.evidenceStatus || view.advice.status }}</small>
      <p>{{ view.advice.text }}</p>
    </article>
    <article class="foundation-card">
      <small>任务</small>
      <p>{{ view.tasks.length ? `${view.tasks.length} 项待处理` : '当前没有分配任务' }}</p>
    </article>
  </section>
</template>