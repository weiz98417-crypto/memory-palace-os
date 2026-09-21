<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AppShell, NavRail } from '@memory-palace/domain-ui'
import { Calendar, DataAnalysis } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const items = [
  { key: 'scenic', label: '运行准备', icon: Calendar },
  { key: 'evaluation', label: '评测证据', icon: DataAnalysis },
]
const active = computed(() => route.path.includes('/evaluation') ? 'evaluation' : 'scenic')
function select(key: string) {
  router.push(key === 'evaluation' ? '/evaluation' : '/scenic')
}
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
      <NavRail :items="items" :active-key="active" @select="select" />
    </template>
    <RouterView />
  </AppShell>
</template>
