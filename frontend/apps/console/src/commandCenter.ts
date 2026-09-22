export interface NextAction {
  code: string
  label: string
  description: string
  enabled?: boolean
  actionType?: string
  kind?: string
  payload?: Record<string, unknown>
  view?: string
  eventId?: string
  incidentId?: string
}

export interface MapZone {
  id: string
  name: string
  capacity: number
  x: number
  y: number
}

export interface MapRoute {
  id: string
  from: string
  to: string
}

export interface CommandCenterMap {
  adapter: string
  coordinateSystem: string
  zones: MapZone[]
  routes: MapRoute[]
  gisConnector: Record<string, any>
}

export interface AdviceSnapshot {
  status: string
  display_status?: string
  evidence_status?: string | null
  advice?: string | null
  citations?: unknown[]
  allowed_actions?: string[]
}

export interface ChartDatum {
  name: string
  value: number
}

export interface ChartSeries {
  key: string
  group: string
  title: string
  subtitle: string
  kind: 'pie' | 'bar'
  data: ChartDatum[]
}

export interface CommandCenterModel {
  runs: any[]
  run: any | null
  alerts: any[]
  map: CommandCenterMap
  nextAction: NextAction | null
  advice: {
    status: string
    title: string
    text: string
    allowedActions: string[]
  } | null
  metrics: {
    events: number
    activeIncidents: number
    activeAlerts: number
    openTasks: number
    pendingApprovals: number
  }
  charts: ChartSeries[]
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
    allowedActions: Array.isArray(advice.allowed_actions) ? advice.allowed_actions.map(String) : [],
  }
}

const STATUS_LABELS: Record<string, string> = {
  PENDING: '待处理',
  RUNNING: '执行中',
  BLOCKED: '已阻塞',
  DONE: '已完成',
  FAILED: '失败',
  APPROVED: '已批准',
  REJECTED: '已拒绝',
  DELIVERED: '已送达',
  RECORDED: '已记录',
  PERSISTED: '已持久化',
  RETRY_REQUIRED: '等待人工重试',
  DEAD_LETTERED: '已进入死信',
  OPEN: '待处理',
  IN_PROGRESS: '处理中',
  CLOSED: '已关闭',
  DRAFT: '草稿',
  IN_REVIEW: '审核中',
  PUBLISHED: '已发布',
  DEPRECATED: '已停用',
  ADOPTED: '已采纳',
  NOT_APPLICABLE: '不适用',
  ACTIVE: '生效中',
  SUCCEEDED: '已成功',
  NOT_STARTED: '未开始',
  CANCELLED: '已取消',
  INVITED: '已邀请',
  PAUSED: '已暂停',
  COMPLETED: '已完成',
  NOT_INDEXED: '未建立索引',
  INDEXED: '已建立索引',
  EXTRACTING: '提取中',
  SUCCESS: '成功',
}

const SEVERITY_LABELS: Record<string, string> = {
  P0: 'P0 特别重大',
  P1: 'P1 重大',
  P2: 'P2 一般',
  P3: 'P3 轻微',
  P4: 'P4 提示',
  'P3/P4': 'P3/P4 轻微',
}

const DELIVERY_LABELS: Record<string, string> = {
  PENDING: '等待回执',
  DELIVERED: '已送达',
  PERSISTED: '已持久化',
  RECORDED: '已记录',
  FAILED: '投递失败',
  RETRY_REQUIRED: '等待重试',
}

const ADOPTION_LABELS: Record<string, string> = {
  PENDING: '待确认',
  ADOPTED: '已采纳',
  REJECTED: '已拒绝',
  NOT_APPLICABLE: '不适用',
}

const CHANNEL_LABELS: Record<string, string> = {
  WECOM_SIMULATOR_OUTBOX: '企业微信模拟器',
  WECOM_SIMULATOR: '企业微信模拟器',
  WECOM: '企业微信',
  WEB_REPLY: 'Web 回复',
  LEGACY: '历史渠道',
}

const SOURCE_LABELS: Record<string, string> = {
  IMPORT: '外部导入',
  SOP: 'SOP 沉淀',
  MANUAL: '人工录入',
  EVENT: '事件巡检',
  WATCHER: '鹰眼巡检',
  KNOWLEDGE: '知识沉淀',
  EXPERIENCE: '专家经验',
}

const PRIORITY_LABELS: Record<string, string> = {
  '1': 'P1 最高',
  '2': 'P2 高',
  '3': 'P3 中',
  '4': 'P4 低',
}

const TOOL_LABELS: Record<string, string> = {
  RECORD_MANAGER_DECISION: '记录管理决策',
}

function normalized(value: unknown): string {
  return String(value ?? '').trim().toUpperCase()
}

function displayLabel(value: unknown, fallback = '未分类', labels: Record<string, string> = {}): string {
  const code = normalized(value)
  if (!code) return fallback
  return labels[code] || SEVERITY_LABELS[code] || STATUS_LABELS[code] || String(value)
}

function distribution(
  values: unknown[],
  fallback = '未分类',
  labels: Record<string, string> = {},
): ChartDatum[] {
  const counts = new Map<string, number>()
  for (const value of values) {
    const label = displayLabel(value, fallback, labels)
    counts.set(label, (counts.get(label) || 0) + 1)
  }
  return [...counts.entries()]
    .map(([name, value]) => ({ name, value }))
    .sort((left, right) => right.value - left.value || left.name.localeCompare(right.name, 'zh-CN'))
}

function series(
  key: string,
  group: string,
  title: string,
  subtitle: string,
  kind: 'pie' | 'bar',
  values: unknown[],
  fallback?: string,
  labels: Record<string, string> = {},
): ChartSeries {
  return { key, group, title, subtitle, kind, data: distribution(values, fallback, labels) }
}

function taskSource(item: any): string {
  if (item?.event_id) return '关联事件'
  if (item?.session_id) return '关联会话'
  return '独立任务'
}

export function buildCommandCenter(snapshot: Record<string, any>): CommandCenterModel {
  const actions = Array.isArray(snapshot.next_actions) ? snapshot.next_actions : []
  const action = actions.find((item) => item?.enabled !== false) || actions[0] || null
  const incidentAdvice = Array.isArray(snapshot.incidents)
    ? snapshot.incidents.find((incident) => incident?.advice)?.advice
    : null
  const runs = snapshot.agent_runs || snapshot.incidents?.find((incident: any) => incident?.agent_runs)?.agent_runs || []
  const incidents = Array.isArray(snapshot.incidents) ? snapshot.incidents : []
  const alerts = Array.isArray(snapshot.alerts) ? snapshot.alerts : []
  const tasks = Array.isArray(snapshot.tasks) ? snapshot.tasks : []
  const approvals = Array.isArray(snapshot.approvals) ? snapshot.approvals : []
  const events = Array.isArray(snapshot.events) ? snapshot.events : []
  const pushLogs = Array.isArray(snapshot.push_logs) ? snapshot.push_logs : []
  const knowledge = Array.isArray(snapshot.knowledge) ? snapshot.knowledge : []
  const experienceCards = Array.isArray(snapshot.experience_cards) ? snapshot.experience_cards : []
  const findings = Array.isArray(snapshot.findings) ? snapshot.findings : []
  const sops = Array.isArray(snapshot.sops) ? snapshot.sops : []

  return {
    runs,
    run: snapshot.run || null,
    alerts,
    map: {
      adapter: String(snapshot.map?.adapter || 'OFFLINE_SVG'),
      coordinateSystem: String(snapshot.map?.coordinate_system || 'LOCAL_SCENIC_GRID_V1'),
      zones: Array.isArray(snapshot.map?.zones) ? snapshot.map.zones : [],
      routes: Array.isArray(snapshot.map?.routes) ? snapshot.map.routes : [],
      gisConnector: snapshot.map?.gis_connector && typeof snapshot.map.gis_connector === 'object' ? snapshot.map.gis_connector : {},
    },
    metrics: {
      events: events.length,
      activeIncidents: incidents.filter((item: any) => normalized(item?.lifecycle) !== 'CLOSED').length,
      activeAlerts: alerts.filter((item: any) => normalized(item?.status) === 'ACTIVE').length,
      openTasks: tasks.filter((item: any) => !['DONE', 'FAILED'].includes(normalized(item?.status))).length,
      pendingApprovals: approvals.filter((item: any) => normalized(item?.status) === 'PENDING').length,
    },
    charts: [
      series('eventSeverity', '事件与任务', '事件级别分布', `正式事件库 · ${events.length} 条`, 'pie', events.map((item: any) => item?.severity)),
      series('eventType', '事件与任务', '事件类型分布', `正式事件库 · ${events.length} 条`, 'bar', events.map((item: any) => item?.event_type)),
      series('eventStatus', '事件与任务', '事件状态分布', `正式事件库 · ${events.length} 条`, 'pie', events.map((item: any) => item?.status), '状态未知'),
      series('eventAssignee', '事件与任务', '事件处置人分布', `正式事件库 · ${events.length} 条`, 'bar', events.map((item: any) => item?.assigned_to_name || item?.assigned_user_id), '未分配'),
      series('taskStatus', '事件与任务', '任务状态分布', `当前任务图 · ${tasks.length} 条`, 'bar', tasks.map((item: any) => item?.status)),
      series('taskAgent', '事件与任务', '任务执行方分布', `当前任务图 · ${tasks.length} 条`, 'pie', tasks.map((item: any) => item?.assigned_agent || item?.assigned_user_id), '未分配'),
      series('taskSource', '事件与任务', '任务关联来源分布', `当前任务图 · ${tasks.length} 条`, 'pie', tasks.map(taskSource)),
      series('approvalStatus', '审批与动作', '审批状态分布', `高风险动作 · ${approvals.length} 条`, 'pie', approvals.map((item: any) => item?.status)),
      series('approvalTool', '审批与动作', '审批工具分布', `高风险动作 · ${approvals.length} 条`, 'bar', approvals.map((item: any) => item?.tool_name), '工具未知', TOOL_LABELS),
      series('approvalExecution', '审批与动作', '审批执行状态分布', `高风险动作 · ${approvals.length} 条`, 'pie', approvals.map((item: any) => item?.execution_status), '未记录'),
      series('pushChannel', '审批与动作', '推送渠道分布', `动作记录 · ${pushLogs.length} 条`, 'bar', pushLogs.map((item: any) => item?.channel), '历史渠道', CHANNEL_LABELS),
      series('pushDelivery', '审批与动作', '推送投递状态', `动作记录 · ${pushLogs.length} 条`, 'pie', pushLogs.map((item: any) => item?.delivery_status), '记录缺失', DELIVERY_LABELS),
      series('pushAdoption', '审批与动作', '推送采纳状态', `动作记录 · ${pushLogs.length} 条`, 'pie', pushLogs.map((item: any) => item?.adoption_status), '待确认', ADOPTION_LABELS),
      series('knowledgeCategory', '知识与经验', '知识分类分布', `正式知识库 · ${knowledge.length} 条`, 'bar', knowledge.map((item: any) => item?.category)),
      series('knowledgeSource', '知识与经验', '知识来源类型', `正式知识库 · ${knowledge.length} 条`, 'pie', knowledge.map((item: any) => item?.source_type), '来源未知', SOURCE_LABELS),
      series('experienceStatus', '知识与经验', '经验资产状态', `专家经验 · ${experienceCards.length} 条`, 'pie', experienceCards.map((item: any) => item?.status)),
      series('findingStatus', '巡检与 SOP', '巡检发现状态', `最近 ${findings.length} 条巡检发现`, 'pie', findings.map((item: any) => item?.status), '状态未知'),
      series('findingSeverity', '巡检与 SOP', '巡检严重级别', `最近 ${findings.length} 条巡检发现`, 'pie', findings.map((item: any) => item?.severity)),
      series('findingSource', '巡检与 SOP', '巡检来源类型', `最近 ${findings.length} 条巡检发现`, 'bar', findings.map((item: any) => item?.source_type), '来源未知', SOURCE_LABELS),
      series('sopStatus', '巡检与 SOP', 'SOP 状态分布', `SOP 资产 · ${sops.length} 条`, 'pie', sops.map((item: any) => item?.status)),
      series('sopCategory', '巡检与 SOP', 'SOP 分类分布', `SOP 资产 · ${sops.length} 条`, 'bar', sops.map((item: any) => item?.category)),
      series('sopPriority', '巡检与 SOP', 'SOP 优先级分布', `SOP 资产 · ${sops.length} 条`, 'pie', sops.map((item: any) => item?.priority), '优先级未知', PRIORITY_LABELS),
    ],
    nextAction: action ? (() => {
      const detail = action.action && typeof action.action === 'object' ? action.action : {}
      return {
        code: String(action.code || ''),
        label: String(action.label || ''),
        description: String(action.description || ''),
        enabled: action.enabled !== false,
        actionType: String(detail.type || 'INFO'),
        kind: detail.kind ? String(detail.kind) : undefined,
        payload: detail.payload && typeof detail.payload === 'object' ? detail.payload : undefined,
        view: detail.view ? String(detail.view) : undefined,
        eventId: detail.event_id ? String(detail.event_id) : undefined,
        incidentId: action.incident_id ? String(action.incident_id) : undefined,
      }
    })() : null,
    advice: normalizeAdvice(incidentAdvice || snapshot.advice),
  }
}

export async function loadCommandCenter(client: { request<T>(path: string): Promise<T> }) {
  const [
    snapshot,
    eventPayload,
    taskPayload,
    approvalPayload,
    pushPayload,
    knowledgePayload,
    experiencePayload,
    findingPayload,
    sopPayload,
  ] = await Promise.all([
    client.request<Record<string, any>>('/scenic/snapshot'),
    client.request<{ events?: any[] }>('/admin/events?limit=500'),
    client.request<{ tasks?: any[] }>('/admin/tasks?limit=500'),
    client.request<any[]>('/admin/approvals?status=ALL&limit=500'),
    client.request<{ push_logs?: any[] }>('/admin/push_logs?limit=500'),
    client.request<{ knowledge?: any[] }>('/admin/knowledge?limit=500'),
    client.request<{ experience_cards?: any[] }>('/admin/experience-cards?limit=500'),
    client.request<{ findings?: any[] }>('/admin/watcher/findings?limit=500'),
    client.request<{ sops?: any[] }>('/admin/sops'),
  ])
  return buildCommandCenter({
    ...snapshot,
    events: Array.isArray(eventPayload.events) ? eventPayload.events : [],
    tasks: Array.isArray(taskPayload.tasks) ? taskPayload.tasks : [],
    approvals: Array.isArray(approvalPayload) ? approvalPayload : [],
    push_logs: Array.isArray(pushPayload.push_logs) ? pushPayload.push_logs : [],
    knowledge: Array.isArray(knowledgePayload.knowledge) ? knowledgePayload.knowledge : [],
    experience_cards: Array.isArray(experiencePayload.experience_cards) ? experiencePayload.experience_cards : [],
    findings: Array.isArray(findingPayload.findings) ? findingPayload.findings : [],
    sops: Array.isArray(sopPayload.sops) ? sopPayload.sops : [],
  })
}
