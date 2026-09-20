<script setup lang="ts">
import { computed } from 'vue'
import StatusBadge from './StatusBadge.vue'
import type { StateTone } from './agentRun'

const props = withDefaults(defineProps<{
  state: 'loading' | 'empty' | 'error' | 'degraded' | 'unavailable'
  title?: string
  message?: string
}>(), { title: '', message: '' })

const labels: Record<string, string> = {
  loading: '加载中',
  empty: '暂无数据',
  error: '加载失败',
  degraded: '已降级',
  unavailable: '暂不可用',
}
const tones: Record<string, StateTone> = {
  loading: 'info',
  empty: 'neutral',
  error: 'danger',
  degraded: 'warning',
  unavailable: 'warning',
}
const title = computed(() => props.title || labels[props.state])
const tone = computed(() => tones[props.state])
</script>

<template>
  <section class="state-panel" :data-state="state">
    <StatusBadge :label="title" :tone="tone" />
    <p v-if="message">{{ message }}</p>
    <slot />
  </section>
</template>

<style scoped>
.state-panel {
  display: grid;
  justify-items: start;
  gap: 10px;
  padding: 20px;
  border: 1px dashed var(--mp-color-hairline-strong);
  border-radius: var(--mp-radius-card);
  background: var(--mp-color-surface);
}
.state-panel p {
  margin: 0;
  color: var(--mp-color-body);
  font-size: 13px;
  line-height: 1.5;
}
</style>
