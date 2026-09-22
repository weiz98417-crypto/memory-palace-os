<script setup lang="ts">
import type { StateTone } from './agentRun'
withDefaults(defineProps<{ label: string; tone?: StateTone }>(), { tone: 'neutral' })
</script>

<template>
  <span class="status-badge" :data-tone="tone">{{ label }}</span>
</template>

<style scoped>
.status-badge {
  --status-color: var(--mp-color-body);
  --status-border: var(--mp-color-hairline-strong);
  --status-bg: var(--mp-color-surface-elevated);
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 24px;
  padding: 2px 9px;
  border: 1px solid var(--status-border) !important;
  border-radius: var(--mp-radius-pill);
  color: var(--status-color) !important;
  background: var(--status-bg) !important;
  font-size: 12px;
  font-weight: 650;
  letter-spacing: .01em;
  white-space: nowrap;
}

.status-badge::before {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 8px color-mix(in srgb, currentColor 52%, transparent);
  content: '';
}

.status-badge[data-tone='primary'] {
  --status-color: var(--mp-color-primary);
  --status-border: color-mix(in srgb, var(--mp-color-primary) 52%, var(--mp-color-hairline-strong));
  --status-bg: color-mix(in srgb, var(--mp-color-primary) 13%, var(--mp-color-surface-elevated));
}

.status-badge[data-tone='info'] {
  --status-color: var(--mp-color-info);
  --status-border: color-mix(in srgb, var(--mp-color-info) 52%, var(--mp-color-hairline-strong));
  --status-bg: color-mix(in srgb, var(--mp-color-info) 13%, var(--mp-color-surface-elevated));
}

.status-badge[data-tone='success'] {
  --status-color: var(--mp-color-success);
  --status-border: color-mix(in srgb, var(--mp-color-success) 52%, var(--mp-color-hairline-strong));
  --status-bg: color-mix(in srgb, var(--mp-color-success) 13%, var(--mp-color-surface-elevated));
}

.status-badge[data-tone='warning'] {
  --status-color: var(--mp-color-warning);
  --status-border: color-mix(in srgb, var(--mp-color-warning) 52%, var(--mp-color-hairline-strong));
  --status-bg: color-mix(in srgb, var(--mp-color-warning) 13%, var(--mp-color-surface-elevated));
}

.status-badge[data-tone='danger'] {
  --status-color: var(--mp-color-danger);
  --status-border: color-mix(in srgb, var(--mp-color-danger) 52%, var(--mp-color-hairline-strong));
  --status-bg: color-mix(in srgb, var(--mp-color-danger) 13%, var(--mp-color-surface-elevated));
}

.status-badge[data-tone='ai'] {
  --status-color: var(--mp-color-ai);
  --status-border: color-mix(in srgb, var(--mp-color-ai) 52%, var(--mp-color-hairline-strong));
  --status-bg: color-mix(in srgb, var(--mp-color-ai) 13%, var(--mp-color-surface-elevated));
}
</style>
