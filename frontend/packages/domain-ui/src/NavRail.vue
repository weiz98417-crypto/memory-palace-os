<script setup lang="ts">
export interface NavItem {
  key: string
  label: string
  icon?: string
  disabled?: boolean
}

const props = withDefaults(defineProps<{
  items: NavItem[]
  activeKey: string
  orientation?: 'vertical' | 'horizontal'
}>(), { orientation: 'vertical' })

const emit = defineEmits<{ select: [key: string] }>()

function select(item: NavItem) {
  if (!item.disabled && item.key !== props.activeKey) emit('select', item.key)
}
</script>

<template>
  <nav class="nav-rail" :data-orientation="orientation" aria-label="主导航">
    <button
      v-for="item in items"
      :key="item.key"
      type="button"
      class="nav-rail__item"
      :class="{ 'is-active': item.key === activeKey }"
      :data-nav-key="item.key"
      :aria-current="item.key === activeKey ? 'page' : undefined"
      :disabled="item.disabled"
      @click="select(item)"
    >
      <span v-if="item.icon" class="nav-rail__icon" aria-hidden="true">{{ item.icon }}</span>
      <span>{{ item.label }}</span>
    </button>
  </nav>
</template>

<style scoped>
.nav-rail {
  display: flex;
  gap: 6px;
  padding: 10px;
}

.nav-rail[data-orientation='vertical'] {
  flex-direction: column;
}

.nav-rail[data-orientation='horizontal'] {
  flex-direction: row;
  align-items: stretch;
  overflow-x: auto;
}

.nav-rail__item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 8px 12px;
  border: 1px solid transparent;
  border-radius: var(--mp-radius-md);
  color: var(--mp-color-body);
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.nav-rail__item:hover:not(:disabled) {
  color: var(--mp-color-ink);
  background: color-mix(in srgb, var(--mp-color-surface-elevated) 76%, transparent);
}

.nav-rail__item.is-active {
  border-color: var(--mp-color-hairline-strong);
  color: var(--mp-color-ink);
  background: var(--mp-color-surface-elevated);
}

.nav-rail__item:disabled {
  color: var(--mp-color-mute);
  cursor: not-allowed;
  opacity: 0.55;
}

.nav-rail__icon {
  width: 20px;
  color: var(--mp-color-ai);
  text-align: center;
}
</style>
