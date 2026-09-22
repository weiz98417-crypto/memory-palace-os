<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    title: string
    venue: string
    connection: 'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'FALLBACK'
    lastUpdated: string
    theme?: 'ops' | 'field'
    backgroundImage?: string
  }>(),
  { theme: 'ops' },
)

const connectionLabel = computed(
  () =>
    ({
      CONNECTING: '连接中',
      CONNECTED: '已连接',
      RECONNECTING: '重连中',
      FALLBACK: '快照回退',
    })[props.connection],
)
</script>

<template>
  <div
    class="mp-shell"
    :data-theme="theme"
    :data-background="Boolean(backgroundImage)"
    :style="backgroundImage ? { '--mp-shell-background-image': `url(${backgroundImage})` } : undefined"
  >
    <header class="mp-shell__header">
      <div class="mp-shell__identity">
        <span class="mp-shell__brand">记忆宫殿 · Memory Palace OS</span>
        <strong>{{ title }}</strong>
      </div>
      <div class="mp-shell__meta">
        <span>{{ venue }}</span>
        <span
          class="mp-shell__connection"
          :data-connection="connection"
        >
          {{ connectionLabel }}
        </span>
        <time>{{ lastUpdated }}</time>
      </div>
    </header>
    <div class="mp-shell__body">
      <nav
        v-if="$slots.nav"
        class="mp-shell__nav"
        aria-label="主导航"
      >
        <slot name="nav" />
      </nav>
      <main class="mp-shell__main">
        <slot />
      </main>
    </div>
  </div>
</template>

<style scoped>
.mp-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  min-height: 0;
  position: relative;
  isolation: isolate;
  overflow: hidden;
  background: var(--mp-color-canvas);
  color: var(--mp-color-body);
  font-family: var(--mp-font-ui);
}

.mp-shell[data-background='true']::before,
.mp-shell[data-background='true']::after {
  position: absolute;
  inset: -24px;
  z-index: -2;
  content: '';
  pointer-events: none;
}

.mp-shell[data-background='true']::before {
  background-image: var(--mp-shell-background-image, none);
  background-position: center;
  background-size: cover;
  filter: blur(10px) saturate(1.04) brightness(.78);
  transform: scale(1.06);
}

.mp-shell[data-background='true']::after {
  z-index: -1;
  background: radial-gradient(circle at 24% 22%, rgba(64, 138, 220, .10), transparent 42%), linear-gradient(180deg, rgba(5, 12, 29, .14), rgba(5, 12, 29, .56));
}

.mp-shell[data-background='true'] {
  --mp-color-canvas: #0a1024;
  --mp-color-surface: rgba(16, 24, 48, .62);
  --mp-color-surface-elevated: rgba(29, 39, 74, .76);
  --mp-color-body: #dce7f4;
  --mp-color-mute: #b8c8dc;
  --mp-color-ink: #ffffff;
}

.mp-shell[data-background='true'] .mp-shell__header {
  background: rgba(7, 14, 32, .66);
  backdrop-filter: blur(18px) saturate(125%);
}

.mp-shell[data-background='true'] .mp-shell__nav {
  background: rgba(8, 15, 34, .72);
  backdrop-filter: blur(18px) saturate(120%);
}

@media (prefers-reduced-transparency: reduce) {
  .mp-shell[data-background='true'] .mp-shell__header,
  .mp-shell[data-background='true'] .mp-shell__nav {
    background: #0b1228;
    backdrop-filter: none;
  }
}

.mp-shell__header {
  flex: 0 0 auto;
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 64px;
  padding: 0 24px;
  border-bottom: 1px solid var(--mp-color-hairline);
  background: color-mix(in srgb, var(--mp-color-canvas) 92%, transparent);
  backdrop-filter: blur(12px);
}

.mp-shell__identity,
.mp-shell__meta {
  display: flex;
  align-items: center;
  gap: 16px;
}

.mp-shell__identity strong {
  color: var(--mp-color-ink);
  font-size: 16px;
  font-weight: 650;
}

.mp-shell__brand {
  color: var(--mp-color-ai);
  font-size: 12px;
  letter-spacing: 0.02em;
}

.mp-shell__meta {
  color: var(--mp-color-mute);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.mp-shell__connection::before {
  display: inline-block;
  width: 6px;
  height: 6px;
  margin-right: 6px;
  border-radius: var(--mp-radius-pill);
  background: var(--mp-color-info);
  content: '';
  vertical-align: 1px;
}

.mp-shell__connection[data-connection='CONNECTED']::before {
  background: var(--mp-color-success);
}

.mp-shell__connection[data-connection='FALLBACK']::before,
.mp-shell__connection[data-connection='RECONNECTING']::before {
  background: var(--mp-color-warning);
}

.mp-shell__body {
  flex: 1 1 auto;
  display: grid;
  grid-template-columns: 224px minmax(0, 1fr);
  min-height: 0;
}

.mp-shell__nav {
  min-height: 0;
  overflow: auto;
  border-right: 1px solid var(--mp-color-hairline);
  background: var(--mp-color-surface);
}

.mp-shell__main {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  padding: 24px;
}

@media (max-width: 900px) {
  .mp-shell__header {
    align-items: flex-start;
    flex-direction: column;
    gap: 8px;
    padding: 12px 16px;
  }

  .mp-shell__body {
    grid-template-columns: 1fr;
  }

  .mp-shell__nav {
    border-right: 0;
    border-bottom: 1px solid var(--mp-color-hairline);
  }
}
</style>