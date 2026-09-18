<script setup lang="ts">
import { AppShell } from '@memory-palace/domain-ui'
</script>

<template>
  <AppShell
    title="移动现场端"
    venue="云栖山景区"
    connection="CONNECTED"
    last-updated="--"
    :theme="'field'"
  >
    <template #nav>
      <div class="entry-mark">
        /assistant/
      </div>
    </template>
    <RouterView />
  </AppShell>
</template>