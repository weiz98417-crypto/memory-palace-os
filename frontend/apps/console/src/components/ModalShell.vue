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
    <div class="modal-backdrop" role="presentation" @click.self="emit('close')">
      <section class="modal-surface" role="dialog" aria-modal="true" :aria-label="label">
        <slot />
      </section>
    </div>
  </Teleport>
</template>
