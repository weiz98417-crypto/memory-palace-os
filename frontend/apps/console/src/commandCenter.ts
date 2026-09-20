export interface NextAction {
  code: string
  label: string
  description: string
  enabled?: boolean
}

export interface AdviceSnapshot {
  status: string
  display_status?: string
  evidence_status?: string | null
  advice?: string | null
  citations?: unknown[]
}

export interface CommandCenterModel {
  runs: any[]
  nextAction: NextAction | null
  advice: {
    status: string
    title: string
    text: string
    allowedActions: string[]
  } | null
}

export function normalizeAdvice(advice?: AdviceSnapshot | null) {
  if (!advice) return null
  const status = String(advice.status || 'PENDING')
  let title = String(advice.display_status || '分析中')
  let text = String(advice.advice || '')
  if (advice.evidence_status === 'NO_EVIDENCE') {
    title = '已就绪'
    text = '没有依据'
  } else if (status === 'FAILED') {
    title = '未获得模型建议'
    text = '未获得模型建议'
  } else if (status === 'SUPERSEDED') {
    title = '已过期'
  }
  return {
    status,
    title,
    text,
    allowedActions: [],
  }
}

export function buildCommandCenter(snapshot: Record<string, any>): CommandCenterModel {
  const actions = Array.isArray(snapshot.next_actions) ? snapshot.next_actions : []
  const action = actions.find((item) => item?.enabled !== false) || actions[0] || null
  const incidentAdvice = Array.isArray(snapshot.incidents)
    ? snapshot.incidents.find((incident) => incident?.advice)?.advice
    : null
  const runs = snapshot.agent_runs || snapshot.incidents?.find((incident: any) => incident?.agent_runs)?.agent_runs || []
  return {
    runs,
    nextAction: action ? {
      code: String(action.code || ''),
      label: String(action.label || ''),
      description: String(action.description || ''),
      enabled: action.enabled !== false,
    } : null,
    advice: normalizeAdvice(incidentAdvice || snapshot.advice),
  }
}

export async function loadCommandCenter(client: { request<T>(path: string): Promise<T> }) {
  const snapshot = await client.request<Record<string, any>>('/scenic/snapshot')
  return buildCommandCenter(snapshot)
}