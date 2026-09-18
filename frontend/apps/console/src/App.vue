<script setup lang="ts">
import { AppShell } from '@memory-palace/domain-ui'
</script>

<template>
  <AppShell
    title="指挥中心"
    venue="云栖山景区"
    connection="CONNECTED"
    last-updated="--"
    :theme="'ops'"
  >
    <template #nav>
      <div class="entry-mark">
        /admin/
      </div>
    </template>
    <RouterView />
  </AppShell>
</template>