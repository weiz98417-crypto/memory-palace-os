import { describe, expect, it } from 'vitest'
import { buildCommandCenter, loadCommandCenter } from './commandCenter'

describe('console command center projection', () => {
  it('puts next action before advice and preserves NO_EVIDENCE wording', () => {
    const model = buildCommandCenter({
      next_actions: [{ code: 'REVIEW_ADVICE', label: '查看并判断处置建议', description: '核对引用', action: { type: 'COMMAND', kind: 'RETRIEVE_SOP', payload: { incident_id: 'incident-1' } } }],
      advice: { status: 'READY', evidence_status: 'NO_EVIDENCE', advice: 'ignored' },
      map: {
        adapter: 'OFFLINE_SVG',
        coordinate_system: 'LOCAL_SCENIC_GRID_V1',
        zones: [{ id: 'east-gate', name: '东门集散区', capacity: 1200, x: 82, y: 51 }],
        routes: [],
        gis_connector: { status: 'OPTIONAL_CONNECTION / NOT_CONFIGURED', interface: 'ScenicMapAdapter/v1' },
      },
    })
    expect(model.nextAction?.code).toBe('REVIEW_ADVICE')
    expect(model.nextAction?.kind).toBe('RETRIEVE_SOP')
    expect(model.nextAction?.actionType).toBe('COMMAND')
    expect(model.map.zones).toHaveLength(1)
    expect(model.advice?.text).toBe('没有依据')
    expect(model.metrics.activeIncidents).toBe(0)
    expect(model.charts).toHaveLength(22)
    expect(model.charts.every((chart) => chart.data.length === 0)).toBe(true)
  })

  it('loads all formal business distributions and renders Chinese labels', async () => {
    const requests: string[] = []
    const model = await loadCommandCenter({
      async request<T>(path: string) {
        requests.push(path)
        if (path === '/scenic/snapshot') return {
          next_actions: [{ code: 'WAIT', label: '等待', description: '处理中' }],
          incidents: [{ lifecycle: 'OPEN' }, { lifecycle: 'CLOSED' }],
          alerts: [{ status: 'ACTIVE' }, { status: 'RECOVERED' }],
        } as T
        if (path.startsWith('/admin/events')) return {
          events: [
            { severity: 'P1', event_type: '设备安全', status: 'OPEN' },
            { severity: 'P1', event_type: '设备安全', status: 'CLOSED' },
            { severity: 'P2', event_type: '客流管理', status: 'OPEN' },
          ],
        } as T
        if (path.startsWith('/admin/tasks')) return {
          tasks: [
            { status: 'PENDING', assigned_agent: 'field-technician', event_id: 'e1' },
            { status: 'DONE', assigned_agent: 'field-operator' },
          ],
        } as T
        if (path.startsWith('/admin/approvals')) return [
          { status: 'PENDING', tool_name: 'record_manager_decision', execution_status: 'NOT_STARTED' },
          { status: 'APPROVED', tool_name: 'record_manager_decision', execution_status: 'SUCCEEDED' },
        ] as T
        if (path.startsWith('/admin/push_logs')) return {
          push_logs: [
            { channel: 'WECOM_SIMULATOR_OUTBOX', delivery_status: 'DELIVERED', adoption_status: 'pending' },
          ],
        } as T
        if (path.startsWith('/admin/knowledge')) return {
          knowledge: [{ category: '设备与安全', source_type: 'SOP' }],
        } as T
        if (path.startsWith('/admin/experience-cards')) return {
          experience_cards: [{ status: 'DRAFT' }],
        } as T
        if (path.startsWith('/admin/watcher/findings')) return {
          findings: [
            { status: 'OPEN', severity: 'P0', source_type: 'event' },
            { status: 'OPEN', severity: 'P1', source_type: 'event' },
          ],
        } as T
        if (path.startsWith('/admin/sops')) return {
          sops: [{ status: 'PUBLISHED', category: '设备与安全', priority: 1 }],
        } as T
        throw new Error(`unexpected path: ${path}`)
      },
    })

    expect(requests).toEqual([
      '/scenic/snapshot',
      '/admin/events?limit=500',
      '/admin/tasks?limit=500',
      '/admin/approvals?status=ALL&limit=500',
      '/admin/push_logs?limit=500',
      '/admin/knowledge?limit=500',
      '/admin/experience-cards?limit=500',
      '/admin/watcher/findings?limit=500',
      '/admin/sops',
    ])
    expect(model.metrics).toEqual({ events: 3, activeIncidents: 1, activeAlerts: 1, openTasks: 1, pendingApprovals: 1 })
    expect(model.charts).toHaveLength(22)
    expect(model.charts.filter((chart) => chart.data.length > 0)).toHaveLength(22)
    expect(model.charts.find((chart) => chart.key === 'eventSeverity')?.data).toEqual([
      { name: 'P1 重大', value: 2 },
      { name: 'P2 一般', value: 1 },
    ])
    expect(model.charts.find((chart) => chart.key === 'taskStatus')?.data).toEqual(expect.arrayContaining([
      { name: '待处理', value: 1 },
      { name: '已完成', value: 1 },
    ]))
    expect(model.charts.find((chart) => chart.key === 'pushChannel')?.data).toEqual([
      { name: '企业微信模拟器', value: 1 },
    ])
    expect(model.charts.find((chart) => chart.key === 'pushAdoption')?.data).toEqual([
      { name: '待确认', value: 1 },
    ])
    expect(model.charts.find((chart) => chart.key === 'sopPriority')?.data).toEqual([
      { name: 'P1 最高', value: 1 },
    ])
  })

  it('groups event, task, approval, knowledge, experience, watcher and SOP facts', () => {
    const model = buildCommandCenter({
      incidents: [{ lifecycle: 'OPEN' }, { lifecycle: 'CLOSED' }],
      alerts: [{ status: 'ACTIVE' }],
      tasks: [{ status: 'PENDING', assigned_agent: 'field-technician' }, { status: 'DONE', assigned_agent: 'field-operator' }],
      approvals: [{ status: 'PENDING', tool_name: 'record_manager_decision', execution_status: 'NOT_STARTED' }],
      events: [{ event_id: 'e1', severity: 'P2', event_type: '设备安全', status: 'OPEN' }],
      push_logs: [{ channel: 'WEB_REPLY', delivery_status: 'PERSISTED', adoption_status: 'not_applicable' }],
      knowledge: [{ category: '设备与安全', source_type: 'IMPORT' }],
      experience_cards: [{ status: 'DRAFT' }],
      findings: [{ status: 'OPEN', severity: 'P1', source_type: 'event' }],
      sops: [{ status: 'PUBLISHED', category: '设备与安全', priority: 2 }],
      advice: {
        status: 'READY',
        evidence_status: 'GROUNDED',
        advice: '按 SOP 执行',
        allowed_actions: ['ADOPT', 'IGNORE'],
      },
    })
    expect(model.metrics).toEqual({ events: 1, activeIncidents: 1, activeAlerts: 1, openTasks: 1, pendingApprovals: 1 })
    expect(model.advice?.allowedActions).toEqual(['ADOPT', 'IGNORE'])
    expect(new Set(model.charts.map((chart) => chart.group))).toEqual(new Set(['事件与任务', '审批与动作', '知识与经验', '巡检与 SOP']))
    expect(model.charts.find((chart) => chart.key === 'knowledgeSource')?.data).toEqual([{ name: '外部导入', value: 1 }])
    expect(model.charts.find((chart) => chart.key === 'findingSource')?.data).toEqual([{ name: '事件巡检', value: 1 }])
  })
})
