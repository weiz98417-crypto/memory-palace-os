export type Artifact = 'ADVICE' | 'DISPATCH_DRAFT' | 'CLOSURE_SUMMARY'
export type StateTone = 'neutral' | 'primary' | 'info' | 'success' | 'warning' | 'danger' | 'ai'

export interface AgentRun {
  incident_id: string
  artifact: Artifact
  run_id: string
  status: string
  sequence: number
  payload?: Record<string, any>
  citations?: unknown[]
  model_evidence?: unknown[]
  degradations?: unknown[]
  allowed_actions?: string[]
}

export interface RunFact {
  label: string
  value: string
}

export interface RunList {
  label: string
  items: string[]
}

export interface CitationPresentation {
  sourceId: string
  title: string
  version: string
  excerpt: string
  score: string
}

export interface EvidencePresentation {
  agent: string
  model: string
  tokens: string
  traceId: string
  status: string
}

export interface DegradationPresentation {
  agent: string
  code: string
  message: string
}

export interface AgentRunPresentation {
  title: string
  statusLabel: string
  tone: StateTone
  readOnly: boolean
  summary: string
  facts: RunFact[]
  lists: RunList[]
  citations: CitationPresentation[]
  evidence: EvidencePresentation[]
  degradations: DegradationPresentation[]
  allowedActions: string[]
}

function record(value: unknown): Record<string, any> | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, any>)
    : null
}

function values(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function text(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value)
  }
  return ''
}

function firstText(source: Record<string, any> | null, keys: string[]): string {
  if (!source) return ''
  for (const key of keys) {
    const value = text(source[key])
    if (value) return value
  }
  return ''
}

function runTitle(run: AgentRun, status: string, evidenceStatus: string): string {
  if (status === 'FAILED') return '未获得模型建议'
  if (status === 'SUPERSEDED') return '已过期'
  if (evidenceStatus === 'NO_EVIDENCE') return '没有依据'
  if (run.artifact === 'DISPATCH_DRAFT') return '派单草案'
  if (run.artifact === 'CLOSURE_SUMMARY') return '关闭摘要'
  return '处置建议'
}

function runStatus(status: string, evidenceStatus: string): { label: string; tone: StateTone } {
  if (status === 'PENDING') return { label: '分析中', tone: 'primary' }
  if (status === 'RUNNING') return { label: '分析中', tone: 'info' }
  if (status === 'FAILED') return { label: '未获得模型建议', tone: 'danger' }
  if (status === 'SUPERSEDED') return { label: '已过期', tone: 'warning' }
  if (evidenceStatus === 'NO_EVIDENCE') return { label: '没有依据', tone: 'warning' }
  if (status === 'DEGRADED') return { label: '已降级', tone: 'warning' }
  if (status === 'READY') return { label: '已就绪', tone: 'success' }
  return { label: status || '分析中', tone: 'neutral' }
}

function runSummary(run: AgentRun, status: string, evidenceStatus: string): string {
  if (status === 'FAILED') return '未获得模型建议'
  if (status === 'SUPERSEDED') return '该建议已过期，仅供追溯。'
  if (evidenceStatus === 'NO_EVIDENCE') return '没有依据'
  const payload = run.payload || {}
  if (run.artifact === 'DISPATCH_DRAFT') return firstText(payload, ['summary', 'description'])
  if (run.artifact === 'CLOSURE_SUMMARY') return firstText(payload, ['outcome_summary', 'summary'])
  return firstText(payload, ['advice_text', 'summary', 'message'])
}

function citationPresentation(value: unknown): CitationPresentation | null {
  if (typeof value === 'string') {
    return { sourceId: value, title: '', version: '', excerpt: '', score: '' }
  }
  const source = record(value)
  if (!source) return null
  const sourceId = firstText(source, ['source_id', 'sourceId', 'id'])
  const title = firstText(source, ['title', 'label'])
  const version = firstText(source, ['version'])
  const excerpt = firstText(source, ['excerpt', 'content'])
  const scoreValue = source.rerank_score ?? source.vector_score ?? source.score
  const score = scoreValue === null || scoreValue === undefined ? '' : text(scoreValue)
  if (!sourceId && !title && !excerpt) return null
  return { sourceId, title, version, excerpt, score }
}

function evidencePresentation(value: unknown): EvidencePresentation | null {
  if (typeof value === 'string') {
    return { agent: '', model: value, tokens: '', traceId: '', status: '' }
  }
  const source = record(value)
  if (!source) return null
  const row = {
    agent: firstText(source, ['agent', 'agent_role', 'agent_name']),
    model: firstText(source, ['model', 'model_name']),
    tokens: firstText(source, ['tokens', 'total_tokens']),
    traceId: firstText(source, ['trace_id', 'traceId']),
    status: firstText(source, ['status']),
  }
  return Object.values(row).some(Boolean) ? row : null
}

function degradationPresentation(value: unknown): DegradationPresentation | null {
  if (typeof value === 'string') return { agent: '', code: value, message: '' }
  const source = record(value)
  if (!source) return null
  const row = {
    agent: firstText(source, ['agent_role', 'agent', 'agent_id']),
    code: firstText(source, ['code', 'error_code']),
    message: firstText(source, ['public_message', 'message', 'reason']),
  }
  return Object.values(row).some(Boolean) ? row : null
}

function plannedAction(value: unknown): string {
  if (typeof value === 'string') return value
  const source = record(value) || {}
  const code = firstText(source, ['action_code', 'code'])
  const description = firstText(source, ['description', 'label'])
  if (code && description) return `${code}: ${description}`
  return code || description
}

function stringList(value: unknown): string[] {
  return values(value).map((item) => typeof item === 'string' ? item : plannedAction(item)).filter(Boolean)
}

export function presentAgentRun(run: AgentRun): AgentRunPresentation {
  const payload = run.payload || {}
  const status = String(run.status || 'PENDING').toUpperCase()
  const evidenceStatus = String(payload.evidence_status || '').toUpperCase()
  const title = runTitle(run, status, evidenceStatus)
  const statusView = runStatus(status, evidenceStatus)
  const facts: RunFact[] = []
  const lists: RunList[] = []

  if (run.artifact === 'ADVICE') {
    const confidence = text(payload.confidence)
    if (confidence) facts.push({ label: '置信度', value: confidence })
    const absenceReason = firstText(payload, ['absence_reason'])
    if (absenceReason) facts.push({ label: '无依据原因', value: absenceReason })
  }

  if (run.artifact === 'DISPATCH_DRAFT') {
    const priority = firstText(payload, ['priority'])
    const riskReason = firstText(payload, ['risk_reason'])
    const nextCheck = firstText(payload, ['next_step_check'])
    if (priority) facts.push({ label: '优先级', value: priority })
    if (riskReason) facts.push({ label: '风险原因', value: riskReason })
    if (nextCheck) facts.push({ label: '下一步检查', value: nextCheck })
    if (typeof payload.requires_human_approval === 'boolean') {
      facts.push({ label: '需要人工审批', value: payload.requires_human_approval ? '是' : '否' })
    }
    const actions = stringList(payload.immediate_actions)
    if (actions.length) lists.push({ label: '立即动作', items: actions })
    const tools = stringList(payload.required_tools)
    if (tools.length) lists.push({ label: '所需工具', items: tools })
  }

  if (run.artifact === 'CLOSURE_SUMMARY') {
    if (typeof payload.recommended_for_closure === 'boolean') {
      facts.push({ label: '建议关闭', value: payload.recommended_for_closure ? '是' : '否' })
    }
    const mapping: Array<[string, string]> = [
      ['证据引用', 'evidence_refs'],
      ['SOP 引用', 'sop_refs'],
      ['已完成任务', 'completed_task_refs'],
      ['审批引用', 'approval_refs'],
      ['告警恢复', 'alert_recovery_refs'],
      ['未解决风险', 'unresolved_risks'],
    ]
    for (const [label, key] of mapping) {
      const items = stringList(payload[key])
      if (items.length) lists.push({ label, items })
    }
  }

  return {
    title,
    statusLabel: statusView.label,
    tone: statusView.tone,
    readOnly: status === 'SUPERSEDED',
    summary: runSummary(run, status, evidenceStatus),
    facts,
    lists,
    citations: values(run.citations).map(citationPresentation).filter((item): item is CitationPresentation => Boolean(item)),
    evidence: values(run.model_evidence).map(evidencePresentation).filter((item): item is EvidencePresentation => Boolean(item)),
    degradations: values(run.degradations).map(degradationPresentation).filter((item): item is DegradationPresentation => Boolean(item)),
    allowedActions: values(run.allowed_actions).map(text).filter(Boolean),
  }
}

export function mergeAgentRuns(current: AgentRun[], incoming: AgentRun[]): AgentRun[] {
  const byKey = new Map(current.map((run) => [`${run.incident_id}:${run.artifact}:${run.run_id}`, run]))
  for (const run of incoming) {
    const key = `${run.incident_id}:${run.artifact}:${run.run_id}`
    const previous = byKey.get(key)
    if (!previous || run.sequence >= previous.sequence) byKey.set(key, run)
  }
  return [...byKey.values()].sort((a, b) => a.sequence - b.sequence)
}

export function artifactDisplay(run: AgentRun) {
  const presentation = presentAgentRun(run)
  return { title: presentation.title, readOnly: presentation.readOnly }
}
