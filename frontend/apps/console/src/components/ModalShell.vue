<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

defineProps<{ label: string }>()
const emit = defineEmits<{ close: [] }>()

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" role="presentation">
      <section class="modal-surface" role="dialog" aria-modal="true" :aria-label="label">
        <header class="modal-shell__bar">
          <strong>{{ label }}</strong>
          <button class="modal-close" type="button" aria-label="关闭弹窗" @click="emit('close')">关闭</button>
        </header>
        <div class="modal-body"><slot /></div>
      </section>
    </div>
  </Teleport>
</template>
