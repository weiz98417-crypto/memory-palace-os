<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { Close, FullScreen } from '@element-plus/icons-vue'
import ScenicMap from '../components/ScenicMap.vue'
import { createApiClient } from '@memory-palace/api-client'
import { AgentRunCard, StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import { loadCommandCenter, type ChartDatum, type ChartSeries, type CommandCenterModel } from '../commandCenter'

const model = ref<CommandCenterModel>({
  runs: [],
  run: null,
  alerts: [],
  map: { adapter: 'OFFLINE_SVG', coordinateSystem: 'LOCAL_SCENIC_GRID_V1', zones: [], routes: [], gisConnector: {} },
  nextAction: null,
  advice: null,
  metrics: { events: 0, activeIncidents: 0, activeAlerts: 0, openTasks: 0, pendingApprovals: 0 },
  charts: [],
})
use([CanvasRenderer, PieChart, BarChart, GridComponent, LegendComponent, TooltipComponent])

const router = useRouter()
const actionBusy = ref(false)
const notice = ref('')
const chartColors = ['#5B6EFF', '#39C68A', '#FFB020', '#FF5C6C', '#A06CF9', '#57C1FF']
const selectedChart = ref<ChartSeries | null>(null)
let previousBodyOverflow = ''
const browser = globalThis as any

function compactData(data: ChartDatum[], limit = 8): ChartDatum[] {
  if (data.length <= limit) return data
  const visible = data.slice(0, limit - 1)
  const hidden = data.slice(limit - 1)
  return [
    ...visible,
    { name: `其他 ${hidden.length} 类`, value: hidden.reduce((sum, item) => sum + item.value, 0) },
  ]
}

const tooltipStyle = {
  backgroundColor: 'rgba(34, 41, 77, .96)',
  borderColor: 'rgba(213, 218, 255, .22)',
  borderWidth: 1,
  textStyle: { color: '#F4F5FF', fontSize: 12 },
  extraCssText: 'box-shadow: 0 12px 34px rgba(0,0,0,.34); border-radius: 8px;',
}

function pieOption(data: ChartDatum[], expanded = false) {
  const chartData = expanded ? data : compactData(data)
  return {
    backgroundColor: 'transparent',
    color: chartColors,
    animationDuration: 360,
    tooltip: { trigger: 'item', formatter: '{b}<br/>正式记录：{c} 条', ...tooltipStyle },
    legend: {
      type: 'scroll',
      bottom: 0,
      textStyle: { color: '#A7AFCA', fontSize: 11 },
      pageTextStyle: { color: '#A7AFCA' },
      pageIconColor: '#5B6EFF',
      pageIconInactiveColor: '#4F5878',
    },
    series: [{
      type: 'pie',
      radius: expanded ? ['40%', '64%'] : ['46%', '68%'],
      center: expanded ? ['50%', '43%'] : ['50%', '42%'],
      minAngle: 3,
      label: {
        color: '#F4F5FF',
        fontSize: expanded ? 12 : 11,
        formatter: '{b}\n{c} 条',
        lineHeight: 16,
      },
      labelLine: { lineStyle: { color: 'rgba(213,218,255,.42)' } },
      emphasis: {
        scale: true,
        scaleSize: expanded ? 10 : 7,
        itemStyle: { shadowBlur: 24, shadowColor: 'rgba(91,110,255,.55)' },
      },
      data: chartData,
    }],
  }
}

function barOption(data: ChartDatum[], expanded = false) {
  const chartData = expanded ? data : compactData(data)
  return {
    backgroundColor: 'transparent',
    color: ['#5B6EFF'],
    animationDuration: 360,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow', shadowStyle: { color: 'rgba(91,110,255,.10)' } },
      formatter: '{b}<br/>正式记录：{c} 条',
      ...tooltipStyle,
    },
    grid: { left: 8, right: 28, top: 10, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: '#A7AFCA', fontSize: 11 },
      splitLine: { lineStyle: { color: 'rgba(213,218,255,.10)' } },
    },
    yAxis: {
      type: 'category',
      inverse: true,
      data: chartData.map((item) => item.name),
      axisLabel: {
        color: '#C7CDE5',
        fontSize: 12,
        width: expanded ? 190 : 116,
        overflow: 'break',
      },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [{
      type: 'bar',
      barMaxWidth: expanded ? 28 : 22,
      data: chartData.map((item) => item.value),
      itemStyle: {
        borderRadius: [0, 7, 7, 0],
        color: {
          type: 'linear',
          x: 0,
          y: 0,
          x2: 1,
          y2: 0,
          colorStops: [
            { offset: 0, color: '#4054E8' },
            { offset: 1, color: '#7E8DFF' },
          ],
        },
      },
      emphasis: { focus: 'series', itemStyle: { color: '#9BA7FF' } },
      blur: { itemStyle: { opacity: .35 } },
    }],
  }
}

const chartOption = (chart: ChartSeries, expanded = false) => chart.kind === 'pie' ? pieOption(chart.data, expanded) : barOption(chart.data, expanded)
const chartGroups = computed(() => {
  const groups = new Map<string, ChartSeries[]>()
  for (const chart of model.value.charts) {
    const existing = groups.get(chart.group) || []
    existing.push(chart)
    groups.set(chart.group, existing)
  }
  return [...groups.entries()].map(([title, charts]) => ({ title, charts }))
})
const expandedChartHeight = computed(() => {
  const chart = selectedChart.value
  if (!chart) return '560px'
  if (chart.kind === 'pie') return `${Math.min(760, Math.max(520, chart.data.length * 26 + 240))}px`
  return `${Math.max(520, chart.data.length * 32 + 96)}px`
})

function openChart(chart: ChartSeries) {
  if (!chart.data.length) return
  previousBodyOverflow = browser.document.body.style.overflow
  browser.document.body.style.overflow = 'hidden'
  selectedChart.value = chart
}

function closeChart() {
  selectedChart.value = null
  browser.document.body.style.overflow = previousBodyOverflow
}

function handleKeydown(event: { key: string }) {
  if (event.key === 'Escape' && selectedChart.value) closeChart()
}

async function executeNextAction() {
  const action = model.value.nextAction
  if (!action || action.enabled === false || actionBusy.value) return
  actionBusy.value = true
  notice.value = ''
  try {
    if (action.actionType === 'NAVIGATE' && action.view) {
      await router.push(`/${action.view}`)
      return
    }
    if (action.actionType === 'OPEN_DOSSIER' && action.eventId) {
      await router.push(`/events?event=${encodeURIComponent(action.eventId)}`)
      return
    }
    if (action.actionType === 'COMMAND' && action.kind) {
      await createApiClient().request('/scenic/commands', {
        method: 'POST',
        json: { kind: action.kind, payload: action.payload || {} },
      })
      notice.value = '动作已提交，正在刷新态势'
      model.value = await loadCommandCenter(createApiClient())
      return
    }
    notice.value = '该动作需要在对应业务页面继续处理'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '下一步动作执行失败'
  } finally {
    actionBusy.value = false
  }
}

const loading = ref(true)
const error = ref<string | null>(null)

onMounted(async () => {
  browser.window.addEventListener('keydown', handleKeydown)
  try {
    model.value = await loadCommandCenter(createApiClient())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '指挥中心加载失败'
  } finally {
    loading.value = false
  }
})

onBeforeUnmount(() => {
  browser.window.removeEventListener('keydown', handleKeydown)
  browser.document.body.style.overflow = previousBodyOverflow
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
      <div class="overview-grid">
        <article v-if="model.map.zones.length" class="map-panel">
          <div class="section-head">
            <div>
              <p class="eyebrow">OFFLINE SCENIC MAP</p>
              <h2>景区作业地图</h2>
            </div>
            <span class="map-status">{{ model.map.adapter }} · {{ model.map.coordinateSystem }}</span>
          </div>
          <div class="map-canvas">
            <ScenicMap :zones="model.map.zones" :routes="model.map.routes" :alerts="model.alerts" />
          </div>
          <div class="map-legend-row" aria-label="地图图例">
            <span><i class="legend-dot legend-dot--alert"></i>告警区域</span>
            <span><i class="legend-dot legend-dot--normal"></i>正常区域</span>
            <span><i class="legend-flow"></i>处置流向</span>
          </div>
          <p class="map-footer">真实 GIS 可选连接器：{{ model.map.gisConnector.status || 'OPTIONAL_CONNECTION / NOT_CONFIGURED' }} · {{ model.map.gisConnector.interface || 'ScenicMapAdapter/v1' }} · 图层 {{ (model.map.gisConnector.layers || []).join(' / ') || 'zones / routes / equipment / staff / alerts' }}</p>
        </article>

        <aside class="overview-side">
          <article v-if="model.nextAction" class="next-action">
            <div>
              <small>下一步处置</small>
              <h2>{{ model.nextAction.label }}</h2>
              <p>{{ model.nextAction.description }}</p>
            </div>
            <StatusBadge :label="model.nextAction.enabled === false ? '暂不可用' : '已解锁'" :tone="model.nextAction.enabled === false ? 'warning' : 'info'" />
            <button class="next-action__button" :disabled="actionBusy || model.nextAction.enabled === false" @click="executeNextAction">
              {{ actionBusy ? '正在处理' : model.nextAction.label }}
            </button>
            <p v-if="notice" class="notice">{{ notice }}</p>
          </article>
          <StatePanel v-else state="empty" title="当前没有下一步动作" message="事件、任务和审批都已处于稳定状态。" />

          <article class="alert-panel">
            <div class="section-head"><h2>当前告警与事件</h2><span class="muted">{{ model.alerts.length }} 条</span></div>
            <ul v-if="model.alerts.length">
              <li v-for="item in model.alerts" :key="item.id || item.alert_id || item.rule_code">
                <strong>{{ item.title || item.rule_code || item.alert_id }}</strong>
                <span>{{ item.zone_id || '全场' }} · {{ item.severity || '未分级' }} · {{ item.status || 'ACTIVE' }}</span>
              </li>
            </ul>
            <p v-else class="muted">当前没有活跃告警。</p>
          </article>
        </aside>
      </div>

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
            <div class="section-head chart-panel__head">
              <div>
                <h3>{{ chart.title }}</h3>
                <span class="muted">{{ chart.subtitle }}</span>
              </div>
              <button
                v-if="chart.data.length"
                class="chart-panel__expand"
                type="button"
                :aria-label="`放大查看${chart.title}`"
                @click="openChart(chart)"
              >
                <FullScreen aria-hidden="true" />
                <span>放大</span>
              </button>
            </div>
            <div v-if="chart.data.length" class="chart-panel__plot" @click="openChart(chart)">
              <VChart class="chart" :option="chartOption(chart)" autoresize />
              <span class="chart-panel__hint">悬停查看数值 · 点击放大</span>
            </div>
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

  <Teleport to="body">
    <div v-if="selectedChart" class="chart-modal" @click.self="closeChart">
      <section class="chart-modal__panel" role="dialog" aria-modal="true" :aria-label="`${selectedChart.title}放大视图`">
        <header class="chart-modal__header">
          <div>
            <p class="eyebrow">CHART DETAIL</p>
            <h2>{{ selectedChart.title }}</h2>
            <p class="muted">{{ selectedChart.subtitle }} · 共 {{ selectedChart.data.length }} 个分类</p>
          </div>
          <button class="chart-modal__close" type="button" aria-label="关闭图表放大" @click="closeChart">
            <Close aria-hidden="true" />
          </button>
        </header>
        <div class="chart-modal__plot" :style="{ height: expandedChartHeight }">
          <VChart class="chart-modal__chart" :option="chartOption(selectedChart, true)" autoresize />
        </div>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.command-center { display: grid; gap: 24px; }
.command-center__header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.command-center__header h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 30px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.eyebrow { margin: 0; color: var(--mp-color-primary); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.overview-grid { display: grid; grid-template-columns: minmax(0, 1.55fr) minmax(310px, .75fr); gap: 14px; align-items: stretch; }
.overview-side { display: grid; gap: 12px; align-content: start; }
.next-action { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: flex-start; gap: 14px; padding: 22px; border: 1px solid color-mix(in srgb, var(--mp-color-primary) 52%, var(--mp-color-hairline)); border-radius: var(--mp-radius-card); background: linear-gradient(135deg, color-mix(in srgb, var(--mp-color-primary) 14%, var(--mp-color-surface)), var(--mp-color-surface)); }
.next-action > div { min-width: 0; }
.next-action__button { grid-column: 1 / -1; justify-self: start; min-height: 40px; padding: 9px 14px; border: 1px solid color-mix(in srgb, var(--mp-color-primary) 74%, white); border-radius: var(--mp-radius-md); color: #fff; background: var(--mp-color-primary); font: inherit; font-weight: 650; cursor: pointer; }
.next-action__button:hover:not(:disabled) { filter: brightness(1.1); }
.next-action__button:disabled { cursor: not-allowed; opacity: .48; }
.notice { margin: 0; color: var(--mp-color-success); font-size: 13px; }
.map-panel, .alert-panel { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.map-panel .section-head h2, .alert-panel h2 { margin: 3px 0 0; color: var(--mp-color-ink); font-size: 20px; }
.map-status { color: var(--mp-color-mute); font-family: var(--mp-font-mono); font-size: 10px; letter-spacing: .06em; }
.map-canvas { position: relative; aspect-ratio: 16 / 9; overflow: hidden; border: 1px solid rgba(104, 214, 255, .16); border-radius: 14px; background: #081827; }
.map-canvas svg { display: block; width: 100%; height: 100%; }
.map-zone { fill: rgba(23, 77, 112, .82); stroke: #65a7cb; stroke-width: .55; stroke-dasharray: 1.2 1; }
.map-zone.is-alert { fill: rgba(180, 45, 59, .74); stroke: #ff7d86; stroke-width: .8; }
.map-alert-ring { fill: none; stroke: #ff7d86; stroke-width: .65; opacity: .6; animation: map-pulse 1.8s ease-out infinite; }
.map-zone-name { fill: #f4f9ff; font-size: 3.25px; font-weight: 700; text-anchor: middle; paint-order: stroke; stroke: rgba(4, 12, 25, .85); stroke-width: .8; }
.map-zone-meta { fill: #b9d9ec; font-size: 2.25px; text-anchor: middle; paint-order: stroke; stroke: rgba(4, 12, 25, .78); stroke-width: .65; }
.map-north circle { fill: rgba(6, 18, 30, .8); stroke: #55748f; stroke-width: .35; }
.map-north path { fill: #e8f4ff; }
.map-north text { fill: #d9edff; font-size: 3px; text-anchor: middle; }
.map-footer { margin: 0; color: var(--mp-color-mute); font-size: 11px; line-height: 1.6; }
.map-legend-row { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; color: var(--mp-color-mute); font-size: 11px; }
.map-legend-row > span { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.legend-dot { display: inline-block; width: 9px; height: 9px; border-radius: 50%; }
.legend-dot--alert { background: #f06b73; box-shadow: 0 0 8px rgba(240, 107, 115, .6); }
.legend-dot--normal { border: 2px dashed #65a7cb; }
.legend-flow { display: inline-block; width: 26px; height: 3px; border-radius: 999px; background: linear-gradient(90deg, transparent, #68d6ff 35%, #68d6ff 65%, transparent); background-size: 200% 100%; animation: legend-flow 1.6s linear infinite; }
@keyframes legend-flow { to { background-position: -200% 0; } }
.alert-panel ul { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.alert-panel li { display: grid; gap: 3px; padding: 10px 12px; border: 1px solid var(--mp-color-hairline); border-radius: 9px; background: color-mix(in srgb, var(--mp-color-danger) 6%, transparent); }
.alert-panel li strong { color: var(--mp-color-ink); font-size: 13px; }
.alert-panel li span { color: var(--mp-color-mute); font-size: 12px; }
@keyframes map-pulse { from { opacity: .72; transform: scale(.9); transform-origin: center; } to { opacity: 0; transform: scale(1.45); transform-origin: center; } }
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
.chart-panel { display: grid; align-content: start; gap: 8px; min-height: 330px; transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease, background .18s ease; }
.chart-panel:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--mp-color-primary) 55%, var(--mp-color-hairline)); background: color-mix(in srgb, var(--mp-color-primary) 7%, var(--mp-color-surface)); box-shadow: 0 14px 34px rgba(5, 10, 32, .22); }
.chart-panel__head { align-items: flex-start; }
.chart-panel__head h3 { margin: 0 0 3px; color: var(--mp-color-ink); font-size: 16px; }
.chart-panel__head .muted { display: block; max-width: none; text-align: left; }
.chart-panel__expand { display: inline-flex; align-items: center; gap: 5px; padding: 5px 8px; border: 1px solid var(--mp-color-hairline); border-radius: 6px; background: rgba(255,255,255,.025); color: var(--mp-color-mute); font: inherit; font-size: 11px; cursor: pointer; transition: color .18s ease, border-color .18s ease, background .18s ease; }
.chart-panel__expand svg { width: 13px; height: 13px; }
.chart-panel__expand:hover { border-color: var(--mp-color-primary); background: color-mix(in srgb, var(--mp-color-primary) 13%, transparent); color: var(--mp-color-ink); }
.chart-panel__plot { position: relative; cursor: zoom-in; border-radius: 7px; }
.chart-panel__plot:focus-within { outline: 2px solid var(--mp-color-primary); outline-offset: 2px; }
.chart-panel__hint { position: absolute; right: 8px; bottom: 1px; padding: 3px 7px; border-radius: 999px; background: rgba(13,15,26,.72); color: var(--mp-color-mute); font-size: 10px; opacity: 0; transform: translateY(3px); transition: opacity .18s ease, transform .18s ease; pointer-events: none; }
.chart-panel__plot:hover .chart-panel__hint { opacity: 1; transform: translateY(0); }
.chart { width: 100%; height: 250px; }
.chart-empty { display: grid; min-height: 190px; margin: 0; place-items: center; color: var(--mp-color-mute); font-size: 13px; text-align: center; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.section-head h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.advice-panel p { margin: 0; color: var(--mp-color-body); font-size: 14px; line-height: 1.6; white-space: pre-wrap; }
.allowed-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.chart-modal { position: fixed; z-index: 3000; inset: 0; display: grid; overflow: auto; padding: 28px; place-items: center; background: rgba(5, 8, 22, .76); backdrop-filter: blur(12px); }
.chart-modal__panel { width: min(1180px, 96vw); max-height: 92vh; overflow: auto; border: 1px solid var(--mp-color-hairline-strong); border-radius: 12px; background: var(--mp-color-surface-elevated); box-shadow: 0 30px 90px rgba(0,0,0,.55); }
.chart-modal__header { position: sticky; z-index: 1; top: 0; display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; padding: 20px 22px; border-bottom: 1px solid var(--mp-color-hairline); background: color-mix(in srgb, var(--mp-color-surface-elevated) 94%, transparent); backdrop-filter: blur(12px); }
.chart-modal__header h2 { margin: 5px 0 4px; color: var(--mp-color-ink); font-size: 23px; }
.chart-modal__header .muted { margin: 0; }
.chart-modal__close { display: grid; flex: 0 0 auto; width: 36px; height: 36px; border: 1px solid var(--mp-color-hairline); border-radius: 8px; background: rgba(255,255,255,.03); color: var(--mp-color-body); cursor: pointer; place-items: center; transition: color .18s ease, border-color .18s ease, background .18s ease; }
.chart-modal__close svg { width: 18px; height: 18px; }
.chart-modal__close:hover { border-color: var(--mp-color-primary); background: color-mix(in srgb, var(--mp-color-primary) 14%, transparent); color: var(--mp-color-ink); }
.chart-modal__plot { width: 100%; min-height: 520px; padding: 12px 14px 18px; }
.chart-modal__chart { width: 100%; height: 100%; }
@media (max-width: 1180px) { .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); } .overview-grid { grid-template-columns: 1fr; } .map-canvas { min-height: 0; } }
@media (max-width: 900px) { .command-center__header, .next-action { flex-direction: column; } .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } .chart-grid { grid-template-columns: 1fr; } .chart-modal { padding: 12px; } .chart-modal__panel { width: 100%; max-height: 96vh; } }
@media (max-width: 560px) { .metric-grid { grid-template-columns: 1fr; } .chart-modal__header { padding: 16px; } .chart-modal__header h2 { font-size: 20px; } .chart-modal__plot { min-height: 480px; padding-inline: 6px; } }
</style>
