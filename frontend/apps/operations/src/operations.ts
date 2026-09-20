export interface RequestClient {
  request<T>(path: string, options?: Record<string, any>): Promise<T>
}

export interface OperationsClient extends RequestClient {
  auth: {
    read(): unknown
    login(username: string, password: string): Promise<any>
    clear(): void
  }
}

export interface ScenicRun {
  scenario_key?: string
  scenario_version?: string
  status?: string
  simulated_at?: number
}

export interface ScenicSnapshot {
  run?: ScenicRun | null
  latest_sequence?: number
  signals?: unknown[]
  alerts?: unknown[]
  incidents?: unknown[]
}

export interface EvaluationRun {
  run_id: string
  tier?: string
  case_set?: string
  passed_count?: number
  case_count?: number
  pass_rate?: number
  failed_count?: number
  elapsed_seconds?: number
  created_at?: number
  judge_model?: string
  results?: EvaluationCase[]
}

export interface EvaluationCase {
  case_id?: string
  scenario_type?: string
  expected_status?: string
  evidence_status?: string
  actual?: string
  success?: boolean
  passed?: boolean
  score?: number
  citations?: string[]
  reason?: string
  advice_text?: string
  latency?: number
}

export function parseSignalData(value: string): Record<string, unknown> {
  let parsed: unknown
  try {
    parsed = JSON.parse(value)
  } catch {
    throw new Error('JSON 数据无效')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('JSON 数据无效')
  }
  return parsed as Record<string, unknown>
}

export function scenicRunLabel(snapshot: ScenicSnapshot): string {
  const run = snapshot.run
  if (!run?.scenario_key) return '尚未准备'
  const version = run.scenario_version ? ` v${run.scenario_version}` : ''
  const status = run.status ? ` · ${run.status}` : ''
  const simulated = run.simulated_at ? ` · ${new Date(run.simulated_at * 1000).toLocaleString('zh-CN')}` : ''
  return `${run.scenario_key}${version}${status}${simulated}`
}

export async function loadScenicSnapshot(client: RequestClient): Promise<ScenicSnapshot> {
  return client.request<ScenicSnapshot>('/scenic/snapshot')
}

export async function sendScenicCommand(
  client: RequestClient,
  kind: string,
  payload: Record<string, unknown> = {},
): Promise<unknown> {
  return client.request('/operations/scenic/commands', {
    method: 'POST',
    json: { kind, payload },
  })
}

export async function loadEvaluationRuns(
  client: RequestClient,
  tier = '',
): Promise<EvaluationRun[]> {
  const query = tier ? `?tier=${encodeURIComponent(tier)}` : ''
  const payload = await client.request<{ runs?: EvaluationRun[] }>(`/operations/scenic/evaluation-runs${query}`)
  return Array.isArray(payload.runs) ? payload.runs : []
}

export async function loadEvaluationRun(
  client: RequestClient,
  runId: string,
): Promise<EvaluationRun> {
  return client.request<EvaluationRun>(`/operations/scenic/evaluation-runs/${encodeURIComponent(runId)}`)
}

export function summarizeEvaluationRuns(runs: EvaluationRun[]) {
  const sorted = [...runs].sort((a, b) => Number(b.created_at || 0) - Number(a.created_at || 0))
  const contract = sorted.filter((run) => run.tier === 'contract')
  const deep = sorted.filter((run) => run.tier === 'deep')
  return {
    total: sorted.length,
    contract: contract.length,
    deep: deep.length,
    latestContract: contract[0] || null,
    latestDeep: deep[0] || null,
  }
}

export function filterEvaluationCases(
  cases: EvaluationCase[],
  filter: 'all' | 'failed' | 'GROUNDED' | 'NO_EVIDENCE',
): EvaluationCase[] {
  if (filter === 'all') return cases
  if (filter === 'failed') return cases.filter((item) => !(item.passed || item.success))
  return cases.filter((item) => (item.expected_status || item.evidence_status) === filter)
}

export function tierLabel(value: string): string {
  if (value === 'contract') return '契约门禁'
  if (value === 'deep') return '深度评分'
  return value || '—'
}

export function evaluationStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    GROUNDED: '有依据',
    NO_EVIDENCE: '没有依据',
    RETRIEVAL_FAILED: '未获得模型建议',
    READY: '已就绪',
    DEGRADED: '已降级',
    FAILED: '失败',
    ERROR: '运行异常',
  }
  return labels[value] || value || '—'
}

export function formatTimestamp(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}

export function formatPercent(value?: number): string {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

export function formatSeconds(value?: number): string {
  return value === null || value === undefined ? '—' : `${Number(value).toFixed(1)}s`
}
