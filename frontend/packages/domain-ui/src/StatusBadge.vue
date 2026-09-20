<script setup lang="ts">
import type { StateTone } from './agentRun'
withDefaults(defineProps<{ label: string; tone?: StateTone }>(), { tone: 'neutral' })
</script>

<template>
  <span class="status-badge" :data-tone="tone">{{ label }}</span>
</template>

<style scoped>
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 2px 9px;
  border: 1px solid var(--mp-color-hairline-strong);
  border-radius: var(--mp-radius-pill);
  color: var(--mp-color-body);
  background: var(--mp-color-surface-elevated);
  font-size: 12px;
  white-space: nowrap;
}

.status-badge::before {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--mp-color-mute);
  content: '';
}

.status-badge[data-tone='info']::before { background: var(--mp-color-info); }
.status-badge[data-tone='success']::before { background: var(--mp-color-success); }
.status-badge[data-tone='warning']::before { background: var(--mp-color-warning); }
.status-badge[data-tone='danger']::before { background: var(--mp-color-danger); }
.status-badge[data-tone='ai']::before { background: var(--mp-color-ai); }
</style>
