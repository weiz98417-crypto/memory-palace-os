<script setup lang="ts">
import { computed } from 'vue'
import StatusBadge from './StatusBadge.vue'
import type { StateTone } from './agentRun'

const props = defineProps<{ task: Record<string, any> }>()
function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}
function toneFor(status: string): StateTone {
  if (status === 'PENDING') return 'primary'
  if (status === 'RUNNING') return 'info'
  if (status === 'BLOCKED') return 'warning'
  if (status === 'DONE') return 'success'
  if (status === 'FAILED' || status === 'RETRY_REQUIRED') return 'danger'
  return 'neutral'
}
const title = computed(() => text(props.task.title || props.task.name || '任务'))
const status = computed(() => text(props.task.status || 'PENDING').toUpperCase())
const description = computed(() => text(props.task.description || props.task.summary || props.task.task_description))
const facts = computed(() => [
  { label: '负责人', value: text(props.task.assignee_name || props.task.assignee || props.task.assigned_to) },
  { label: '优先级', value: text(props.task.priority) },
  { label: '截止时间', value: text(props.task.due_at || props.task.due_date) },
].filter((item) => item.value))
</script>

<template>
  <article class="task-card">
    <header>
      <div>
        <small>任务</small>
        <h3>{{ title }}</h3>
      </div>
      <StatusBadge :label="status" :tone="toneFor(status)" />
    </header>
    <p v-if="description">{{ description }}</p>
    <dl v-if="facts.length">
      <div v-for="fact in facts" :key="fact.label">
        <dt>{{ fact.label }}</dt>
        <dd>{{ fact.value }}</dd>
      </div>
    </dl>
    <footer v-if="$slots.actions"><slot name="actions" /></footer>
  </article>
</template>

<style scoped>
.task-card,
.approval-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--mp-color-hairline);
  border-radius: var(--mp-radius-card);
  background: var(--mp-color-surface);
}
.task-card header,
.approval-card header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.task-card h3,
.approval-card h3,
.task-card p,
.approval-card p,
.task-card dl,
.approval-card dl {
  margin: 0;
}
.task-card small,
.approval-card small,
.task-card dt,
.approval-card dt {
  color: var(--mp-color-mute);
  font-size: 12px;
}
.task-card h3,
.approval-card h3 {
  margin-top: 4px;
  color: var(--mp-color-ink);
  font-size: 16px;
}
.task-card p,
.approval-card p,
.task-card dd,
.approval-card dd {
  color: var(--mp-color-body);
  font-size: 13px;
}
.task-card dl,
.approval-card dl {
  display: grid;
  gap: 6px;
}
.task-card dl div,
.approval-card dl div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
}
.task-card footer,
.approval-card footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
