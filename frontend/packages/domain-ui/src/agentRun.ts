export type Artifact = 'ADVICE' | 'DISPATCH_DRAFT' | 'CLOSURE_SUMMARY'

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
  const status = String(run.status || 'PENDING')
  if (status === 'FAILED') return { title: '未获得模型建议', readOnly: false }
  if (status === 'SUPERSEDED') return { title: '已过期', readOnly: true }
  if (run.artifact === 'DISPATCH_DRAFT') return { title: '派单草案', readOnly: false }
  if (run.artifact === 'CLOSURE_SUMMARY') return { title: '关闭摘要', readOnly: false }
  if (run.payload?.evidence_status === 'NO_EVIDENCE') return { title: '没有依据', readOnly: false }
  return { title: '处置建议', readOnly: false }
}