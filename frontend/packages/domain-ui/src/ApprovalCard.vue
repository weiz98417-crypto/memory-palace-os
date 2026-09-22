<script setup lang="ts">
import { computed } from 'vue'
import StatusBadge from './StatusBadge.vue'
import type { StateTone } from './agentRun'

const props = defineProps<{ approval: Record<string, any> }>()
function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}
function toneFor(status: string): StateTone {
  if (status === 'PENDING') return 'primary'
  if (status === 'APPROVED') return 'success'
  if (status === 'REJECTED' || status === 'FAILED') return 'danger'
  return 'neutral'
}
const title = computed(() => text(props.approval.tool_name || props.approval.action_code || props.approval.request_type || props.approval.title || '审批请求'))
const status = computed(() => text(props.approval.status || 'PENDING').toUpperCase())
const comment = computed(() => text(props.approval.comment || props.approval.review_comment || props.approval.reason))
const facts = computed(() => [
  { label: '风险', value: text(props.approval.risk_level || props.approval.risk_reason) },
  { label: '发起人', value: text(props.approval.requester_name || props.approval.requested_by) },
  { label: '业务编号', value: text(props.approval.business_id || props.approval.business_code) },
].filter((item) => item.value))
</script>

<template>
  <article class="approval-card">
    <header>
      <div>
        <small>高风险审批</small>
        <h3>{{ title }}</h3>
      </div>
      <StatusBadge :label="status" :tone="toneFor(status)" />
    </header>
    <p v-if="comment">{{ comment }}</p>
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
.approval-card {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--mp-color-hairline);
  border-radius: var(--mp-radius-card);
  background: var(--mp-color-surface);
}
.approval-card header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.approval-card h3,
.approval-card p,
.approval-card dl {
  margin: 0;
}
.approval-card small,
.approval-card dt {
  color: var(--mp-color-mute);
  font-size: 12px;
}
.approval-card h3 {
  margin-top: 4px;
  color: var(--mp-color-ink);
  font-size: 16px;
}
.approval-card p,
.approval-card dd {
  color: var(--mp-color-body);
  font-size: 13px;
}
.approval-card dl {
  display: grid;
  gap: 6px;
}
.approval-card dl div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 8px;
}
.approval-card footer {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
</style>
