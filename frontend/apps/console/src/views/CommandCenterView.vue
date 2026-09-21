<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { createApiClient } from '@memory-palace/api-client'
import { AgentRunCard, StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import { loadCommandCenter, type ChartSeries, type CommandCenterModel } from '../commandCenter'

const model = ref<CommandCenterModel>({
  runs: [],
  nextAction: null,
  advice: null,
  metrics: { events: 0, activeIncidents: 0, activeAlerts: 0, openTasks: 0, pendingApprovals: 0 },
  charts: [],
})
use([CanvasRenderer, PieChart, BarChart, GridComponent, LegendComponent, TooltipComponent])

const chartColors = ['#5B6EFF', '#39C68A', '#FFB020', '#FF5C6C', '#A06CF9', '#57C1FF']
const pieOption = (data: Array<{ name: string; value: number }>) => ({
  backgroundColor: 'transparent',
  color: chartColors,
  tooltip: { trigger: 'item', formatter: '{b}<br/>{c} 条' },
  legend: { type: 'scroll', bottom: 0, textStyle: { color: '#A7AFCA' } },
  series: [{
    type: 'pie',
    radius: ['42%', '66%'],
    center: ['50%', '42%'],
    label: { color: '#F4F5FF', formatter: '{b}\n{c} 条' },
    labelLine: { lineStyle: { color: 'rgba(213,218,255,.45)' } },
    data,
  }],
})
const barOption = (data: Array<{ name: string; value: number }>) => ({
  backgroundColor: 'transparent',
  color: ['#5B6EFF'],
  tooltip: { trigger: 'axis', formatter: '{b}<br/>{c} 条' },
  grid: { left: 42, right: 18, top: 18, bottom: data.length > 7 ? 68 : 42, containLabel: true },
  xAxis: {
    type: 'category',
    data: data.map((item) => item.name),
    axisLabel: {
      color: '#A7AFCA',
      interval: 0,
      rotate: data.length > 7 ? 28 : 0,
      overflow: 'truncate',
      width: 72,
    },
    axisLine: { lineStyle: { color: 'rgba(213,218,255,.18)' } },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLabel: { color: '#A7AFCA' },
    splitLine: { lineStyle: { color: 'rgba(213,218,255,.10)' } },
  },
  series: [{ type: 'bar', barMaxWidth: 42, data: data.map((item) => item.value), itemStyle: { borderRadius: [6, 6, 0, 0] } }],
})
const chartOption = (chart: ChartSeries) => chart.kind === 'pie' ? pieOption(chart.data) : barOption(chart.data)
const chartGroups = computed(() => {
  const groups = new Map<string, ChartSeries[]>()
  for (const chart of model.value.charts) {
    const existing = groups.get(chart.group) || []
    existing.push(chart)
    groups.set(chart.group, existing)
  }
  return [...groups.entries()].map(([title, charts]) => ({ title, charts }))
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
        <article><span>事件记录</span><strong>{{ model.metrics.events }}</strong></article>
        <article><span>活跃事件</span><strong>{{ model.metrics.activeIncidents }}</strong></article>
        <article><span>活跃告警</span><strong>{{ model.metrics.activeAlerts }}</strong></article>
        <article><span>待处理任务</span><strong>{{ model.metrics.openTasks }}</strong></article>
        <article><span>待审批</span><strong>{{ model.metrics.pendingApprovals }}</strong></article>
      </div>

      <section v-for="group in chartGroups" :key="group.title" class="chart-section">
        <div class="section-head">
          <div>
            <p class="eyebrow">FORMAL BUSINESS FACTS</p>
            <h2>{{ group.title }}</h2>
          </div>
          <span class="muted">{{ group.charts.length }} 个分类</span>
        </div>
        <div class="chart-grid">
          <article
            v-for="chart in group.charts"
            :key="chart.key"
            class="chart-panel"
            :data-chart-key="chart.key"
            :data-chart-title="chart.title"
          >
            <div class="section-head">
              <h3>{{ chart.title }}</h3>
              <span class="muted">{{ chart.subtitle }}</span>
            </div>
            <VChart v-if="chart.data.length" class="chart" :option="chartOption(chart)" autoresize />
            <p v-else class="chart-empty">暂无该分类的正式业务数据。</p>
          </article>
        </div>
      </section>

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
.command-center { display: grid; gap: 24px; }
.command-center__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.command-center__header h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 30px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.eyebrow { margin: 0; color: var(--mp-color-primary); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.next-action { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; padding: 22px; border: 1px solid color-mix(in srgb, var(--mp-color-primary) 52%, var(--mp-color-hairline)); border-radius: var(--mp-radius-card); background: linear-gradient(135deg, color-mix(in srgb, var(--mp-color-primary) 14%, var(--mp-color-surface)), var(--mp-color-surface)); }
.next-action small, .metric-grid span { color: var(--mp-color-mute); font-size: 12px; }
.next-action h2 { margin: 6px 0 8px; color: var(--mp-color-ink); font-size: 24px; }
.next-action p { margin: 0; color: var(--mp-color-body); font-size: 14px; }
.metric-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.metric-grid article, .advice-panel, .run-list, .chart-panel { padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.metric-grid article { display: grid; gap: 6px; }
.metric-grid strong { color: var(--mp-color-ink); font-size: 28px; font-variant-numeric: tabular-nums; }
.advice-panel, .run-list, .chart-section { display: grid; gap: 12px; }
.chart-section > .section-head h2 { margin: 2px 0 0; color: var(--mp-color-ink); font-size: 20px; }
.chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); gap: 12px; }
.chart-panel { display: grid; align-content: start; gap: 8px; min-height: 310px; }
.chart { width: 100%; height: 250px; }
.chart-empty { display: grid; min-height: 190px; margin: 0; place-items: center; color: var(--mp-color-mute); font-size: 13px; text-align: center; }
.section-head h3 { margin: 0; color: var(--mp-color-ink); font-size: 16px; }
.section-head .muted { max-width: 58%; text-align: right; }
.advice-panel p { margin: 0; color: var(--mp-color-body); font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.section-head h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.allowed-actions { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 1180px) { .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 900px) { .command-center__header, .next-action { flex-direction: column; } .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .chart-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .metric-grid { grid-template-columns: 1fr; } }
</style>
