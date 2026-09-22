<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  evaluationStatusLabel,
  filterEvaluationCases,
  formatPercent,
  formatSeconds,
  formatTimestamp,
  loadEvaluationRun,
  loadEvaluationRuns,
  summarizeEvaluationRuns,
  tierLabel,
  type EvaluationCase,
  type EvaluationRun,
  type RequestClient,
} from '../operations'

const props = defineProps<{ client?: RequestClient }>()
const client = props.client || createApiClient({ storageKeyPrefix: 'mp_operations_' })
const runs = ref<EvaluationRun[]>([])
const selected = ref<EvaluationRun | null>(null)
const tier = ref('')
const filter = ref<'all' | 'failed' | 'GROUNDED' | 'NO_EVIDENCE'>('all')
const loading = ref(false)
const error = ref('')
const summary = computed(() => summarizeEvaluationRuns(runs.value))
const cases = computed(() => filterEvaluationCases(selected.value?.results || [], filter.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    runs.value = await loadEvaluationRuns(client, tier.value)
    selected.value = null
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '评测记录读取失败'
  } finally {
    loading.value = false
  }
}

async function open(runId: string) {
  try {
    selected.value = await loadEvaluationRun(client, runId)
    filter.value = 'all'
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '评测明细读取失败'
  }
}

function caseStatus(item: EvaluationCase): string {
  return evaluationStatusLabel(String(item.actual || item.evidence_status || item.expected_status || ''))
}

onMounted(load)
</script>

<template>
  <section class="evaluation-view">
    <header class="evaluation-header">
      <div>
        <p class="eyebrow">EVALUATION EVIDENCE</p>
        <h1>Agent 评测运行</h1>
        <p class="muted">共用正式 client 与视觉 token，但保持独立权限和证据入口。</p>
      </div>
      <div class="header-actions">
        <label>层级<select v-model="tier" @change="load"><option value="">全部</option><option value="contract">契约门禁</option><option value="deep">深度评分</option></select></label>
        <button :disabled="loading" @click="load">刷新</button>
      </div>
    </header>

    <StatePanel v-if="loading" state="loading" title="正在读取评测记录" />
    <StatePanel v-else-if="error" state="error" title="评测证据加载失败" :message="error" />
    <StatePanel v-else-if="!runs.length" state="empty" title="尚无评估记录" message="运行 contract 或 DeepEval 门禁后，结果会出现在这里。" />

    <template v-else>
      <div class="summary-grid">
        <article class="summary-card"><span>评估运行总数</span><strong>{{ summary.total }}</strong><small>契约 {{ summary.contract }} 次 · 深度 {{ summary.deep }} 次</small></article>
        <article v-if="summary.latestContract" class="summary-card"><span>契约门禁 · 最新</span><strong>{{ summary.latestContract.passed_count || 0 }} / {{ summary.latestContract.case_count || 0 }}</strong><small>通过率 {{ formatPercent(summary.latestContract.pass_rate) }} · {{ formatSeconds(summary.latestContract.elapsed_seconds) }}</small></article>
        <article v-if="summary.latestDeep" class="summary-card"><span>深度评分 · 最新</span><strong>{{ summary.latestDeep.passed_count || 0 }} / {{ summary.latestDeep.case_count || 0 }}</strong><small>通过率 {{ formatPercent(summary.latestDeep.pass_rate) }} · {{ formatSeconds(summary.latestDeep.elapsed_seconds) }}</small></article>
      </div>

      <article class="panel">
        <div class="panel-head"><h2>运行记录</h2><span class="muted">共 {{ runs.length }} 次</span></div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>时间</th><th>层级</th><th>用例集</th><th>通过</th><th>通过率</th><th>判官</th><th>耗时</th><th></th></tr></thead>
            <tbody>
              <tr v-for="run in runs" :key="run.run_id">
                <td class="mono">{{ formatTimestamp(run.created_at) }}</td>
                <td>{{ tierLabel(String(run.tier || '')) }}</td>
                <td>{{ run.case_set || '—' }}</td>
                <td>{{ run.passed_count || 0 }} / {{ run.case_count || 0 }}</td>
                <td><StatusBadge :label="formatPercent(run.pass_rate)" :tone="(run.pass_rate || 0) >= 1 ? 'success' : 'warning'" /></td>
                <td>{{ run.judge_model || '—' }}</td>
                <td>{{ formatSeconds(run.elapsed_seconds) }}</td>
                <td><button @click="open(run.run_id)">查看明细</button></td>
              </tr>
            </tbody>
          </table>
        </div>
      </article>

      <article v-if="selected" class="panel">
        <div class="panel-head"><h2>{{ selected.case_set }} · {{ formatTimestamp(selected.created_at) }}</h2><span class="muted">通过 {{ selected.passed_count || 0 }}/{{ selected.case_count || 0 }}</span></div>
        <div class="chips">
          <button v-for="option in [{key:'all',label:'全部'},{key:'failed',label:'仅失败'},{key:'GROUNDED',label:'有依据'},{key:'NO_EVIDENCE',label:'没有依据'}]" :key="option.key" :class="{ active: filter === option.key }" @click="filter = option.key as typeof filter">{{ option.label }}</button>
        </div>
        <div class="table-wrap">
          <table>
            <thead><tr><th>用例</th><th>场景</th><th>期望</th><th>实际</th><th>引用</th><th>分数</th><th>耗时</th></tr></thead>
            <tbody>
              <tr v-for="item in cases" :key="item.case_id">
                <td class="mono">{{ item.case_id }}</td><td>{{ item.scenario_type || '—' }}</td><td>{{ evaluationStatusLabel(String(item.expected_status || item.evidence_status || '')) }}</td><td>{{ caseStatus(item) }}<small v-if="item.reason">{{ item.reason }}</small></td><td class="mono">{{ (item.citations || []).join(', ') || '—' }}</td><td>{{ item.score == null ? '—' : Number(item.score).toFixed(3) }}</td><td>{{ item.latency == null ? '—' : formatSeconds(item.latency) }}</td>
              </tr>
              <tr v-if="!cases.length"><td colspan="7" class="empty">没有符合条件的用例。</td></tr>
            </tbody>
          </table>
        </div>
      </article>
    </template>
  </section>
</template>

<style scoped>
.evaluation-view { display: grid; gap: 18px; }
.evaluation-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.evaluation-header h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.header-actions { display: flex; align-items: end; gap: 10px; }
.header-actions label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
select, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
.summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.summary-card { display: grid; gap: 6px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.summary-card span, .summary-card small { color: var(--mp-color-mute); font-size: 12px; }
.summary-card strong { color: var(--mp-color-ink); font-size: 24px; }
.panel { display: grid; gap: 12px; padding: 18px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.panel-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; white-space: nowrap; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { display: block; margin-top: 4px; color: var(--mp-color-mute); white-space: normal; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chips button.active { border-color: var(--mp-color-primary); background: var(--mp-color-primary); }
.mono { font-family: var(--mp-font-mono); font-size: 12px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .evaluation-header { flex-direction: column; } .header-actions { width: 100%; } }
</style>
