<script setup lang="ts">
import { computed } from 'vue'
import StatusBadge from './StatusBadge.vue'
import type { StateTone } from './agentRun'

const props = defineProps<{ items: unknown[] }>()
function record(value: unknown): Record<string, any> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, any>)
    : null
}
function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}
function toneFor(status: string): StateTone {
  if (['READY', 'GROUNDED', 'DONE', 'SUCCEEDED', 'RECORDED'].includes(status)) return 'success'
  if (['FAILED', 'ERROR'].includes(status)) return 'danger'
  if (['DEGRADED', 'PENDING', 'RUNNING'].includes(status)) return 'warning'
  return 'neutral'
}
const rows = computed(() => props.items.map((item, index) => {
  if (typeof item === 'string') return { key: `${index}:${item}`, title: item, detail: '', status: '', time: '' }
  const source = record(item) || {}
  return {
    key: text(source.id || source.evidence_id || source.source_id || index),
    title: text(source.title || source.source_id || source.name || '证据'),
    detail: text(source.detail || source.excerpt || source.content || source.summary),
    status: text(source.status || source.evidence_status).toUpperCase(),
    time: text(source.created_at || source.recorded_at || source.occurred_at),
  }
}))
</script>

<template>
  <ol class="evidence-timeline">
    <li v-for="row in rows" :key="row.key">
      <div class="evidence-timeline__head">
        <strong>{{ row.title }}</strong>
        <StatusBadge v-if="row.status" :label="row.status" :tone="toneFor(row.status)" />
      </div>
      <p v-if="row.detail">{{ row.detail }}</p>
      <time v-if="row.time">{{ row.time }}</time>
    </li>
  </ol>
</template>

<style scoped>
.evidence-timeline {
  display: grid;
  gap: 12px;
  margin: 0;
  padding-left: 20px;
}
.evidence-timeline li {
  padding-left: 4px;
  color: var(--mp-color-body);
}
.evidence-timeline__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.evidence-timeline strong {
  color: var(--mp-color-ink);
  font-size: 13px;
}
.evidence-timeline p,
.evidence-timeline time {
  display: block;
  margin: 4px 0 0;
  color: var(--mp-color-mute);
  font-size: 12px;
  line-height: 1.45;
}
</style>
