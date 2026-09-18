<script setup lang="ts">
import { AppShell } from '@memory-palace/domain-ui'
</script>

<template>
  <AppShell
    title="接入环境"
    venue="云栖山景区"
    connection="CONNECTED"
    last-updated="--"
    :theme="'field'"
  >
    <template #nav>
      <div class="entry-mark">
        /simulator/wecom/
      </div>
    </template>
    <RouterView />
  </AppShell>
</template>