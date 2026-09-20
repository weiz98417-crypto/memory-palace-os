<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { AgentRunCard, StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import { loadCommandCenter, type CommandCenterModel } from '../commandCenter'

const model = ref<CommandCenterModel>({
  runs: [],
  nextAction: null,
  advice: null,
  metrics: { events: 0, activeIncidents: 0, openTasks: 0, pendingApprovals: 0 },
})
const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  try {
    model.value = await loadCommandCenter(createApiClient())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '指挥中心加载失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="command-center" data-testid="command-center">
    <header class="command-center__header">
      <div>
        <p class="eyebrow">NEXT OPERATIONAL ACTION</p>
        <h1>景区指挥中心</h1>
        <p class="muted">监测信号、态势告警、运营事件、任务与审批均来自当前场地正式业务事实。</p>
      </div>
      <StatusBadge label="快照已连接" tone="success" />
    </header>

    <StatePanel v-if="loading" state="loading" title="正在读取态势快照" />
    <StatePanel v-else-if="error" state="error" title="指挥中心加载失败" :message="error" />

    <template v-else>
      <article v-if="model.nextAction" class="next-action">
        <div>
          <small>下一步处置</small>
          <h2>{{ model.nextAction.label }}</h2>
          <p>{{ model.nextAction.description }}</p>
        </div>
        <StatusBadge :label="model.nextAction.enabled === false ? '暂不可用' : '已解锁'" :tone="model.nextAction.enabled === false ? 'warning' : 'info'" />
      </article>
      <StatePanel v-else state="empty" title="当前没有下一步动作" message="事件、任务和审批都已处于稳定状态。" />

      <div class="metric-grid">
        <article><span>活跃事件</span><strong>{{ model.metrics.activeIncidents }}</strong></article>
        <article><span>待处理任务</span><strong>{{ model.metrics.openTasks }}</strong></article>
        <article><span>待审批</span><strong>{{ model.metrics.pendingApprovals }}</strong></article>
        <article><span>事件记录</span><strong>{{ model.metrics.events }}</strong></article>
      </div>

      <section v-if="model.advice" class="advice-panel">
        <div class="section-head"><div><h2>处置建议</h2><p class="muted">{{ model.advice.title }}</p></div><StatusBadge :label="model.advice.status" tone="ai" /></div>
        <p>{{ model.advice.text || '建议正在生成。' }}</p>
        <div v-if="model.advice.allowedActions.length" class="allowed-actions">
          <StatusBadge v-for="action in model.advice.allowedActions" :key="action" :label="action" tone="neutral" />
        </div>
      </section>

      <section v-if="model.runs.length" class="run-list">
        <div class="section-head"><h2>Agent 运行</h2><span class="muted">{{ model.runs.length }} 条</span></div>
        <AgentRunCard v-for="run in model.runs" :key="`${run.artifact}:${run.run_id}`" :run="run" />
      </section>
    </template>
  </section>
</template>

<style scoped>
.command-center { display: grid; gap: 18px; }
.command-center__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.command-center__header h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 30px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.next-action { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 22px; border: 1px solid color-mix(in srgb, var(--mp-color-primary) 52%, var(--mp-color-hairline)); border-radius: var(--mp-radius-card); background: linear-gradient(135deg, color-mix(in srgb, var(--mp-color-primary) 14%, var(--mp-color-surface)), var(--mp-color-surface)); }
.next-action small, .metric-grid span { color: var(--mp-color-mute); font-size: 12px; }
.next-action h2 { margin: 6px 0 8px; color: var(--mp-color-ink); font-size: 24px; }
.next-action p { margin: 0; color: var(--mp-color-body); font-size: 14px; }
.metric-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.metric-grid article, .advice-panel, .run-list { padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.metric-grid article { display: grid; gap: 6px; }
.metric-grid strong { color: var(--mp-color-ink); font-size: 28px; font-variant-numeric: tabular-nums; }
.advice-panel, .run-list { display: grid; gap: 12px; }
.advice-panel p { margin: 0; color: var(--mp-color-body); font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.section-head h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.allowed-actions { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 900px) { .command-center__header, .next-action { flex-direction: column; } .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
