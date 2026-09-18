<script setup lang="ts">
import { AppShell } from '@memory-palace/domain-ui'
</script>

<template>
  <AppShell
    title="受保护运行准备"
    venue="云栖山景区"
    connection="CONNECTED"
    last-updated="--"
    :theme="'ops'"
  >
    <template #nav>
      <div class="entry-mark">
        /operations/
      </div>
    </template>
    <RouterView />
  </AppShell>
</template>