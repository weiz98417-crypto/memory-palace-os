<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel } from '@memory-palace/domain-ui'
import { workspaceByKey } from '../workspaces'

const props = defineProps<{ workspaceKey: string }>()
const workspace = computed(() => workspaceByKey(props.workspaceKey))
const count = ref<number | null>(null)
const loading = ref(false)
const error = ref('')

function countRecords(payload: unknown): number {
  if (Array.isArray(payload)) return payload.length
  if (payload && typeof payload === 'object') {
    const source = payload as Record<string, unknown>
    for (const key of ['items', 'records', 'runs', 'findings', 'policies', 'users', 'venues', 'settings']) {
      if (Array.isArray(source[key])) return source[key].length
    }
    const numeric = source.count ?? source.total
    if (typeof numeric === 'number') return numeric
  }
  return 0
}

onMounted(async () => {
  if (!workspace.value || workspace.value.key === 'dashboard') return
  loading.value = true
  try {
    count.value = countRecords(await createApiClient().request(workspace.value.endpoint))
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '工作区读取失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section v-if="workspace" class="workspace-view">
    <header>
      <p class="eyebrow">CONSOLE WORKSPACE</p>
      <h1>{{ workspace.label }}</h1>
      <p class="muted">该路由已经进入 V2 控制台；完整动作迁移由 {{ workspace.ownerTicket }} 完成。</p>
    </header>
    <StatePanel v-if="loading" state="loading" title="正在读取工作区" />
    <StatePanel v-else-if="error" state="error" title="工作区读取失败" :message="error" />
    <StatePanel v-else state="empty" :title="`${workspace.label} V2 路由已建立`" :message="count === null ? '等待迁移。' : `已从真实 API 读取 ${count} 条记录；结构化操作在 ${workspace.ownerTicket} 接入。`" />
  </section>
  <StatePanel v-else state="error" title="未知工作区" message="该控制台路由没有登记。" />
</template>

<style scoped>
.workspace-view { display: grid; gap: 18px; }
.workspace-view h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
</style>
