import { describe, expect, it } from 'vitest'
import { buildCommandCenter, loadCommandCenter } from './commandCenter'

describe('console command center projection', () => {
  it('puts next action before advice and preserves NO_EVIDENCE wording', () => {
    const model = buildCommandCenter({
      next_actions: [{ code: 'REVIEW_ADVICE', label: '查看并判断处置建议', description: '核对引用' }],
      advice: { status: 'READY', evidence_status: 'NO_EVIDENCE', advice: 'ignored' },
    })
    expect(model.nextAction?.code).toBe('REVIEW_ADVICE')
    expect(model.advice?.text).toBe('没有依据')
    expect(model.metrics.activeIncidents).toBe(0)
  })

  it('loads snapshot metrics and chart distributions through formal list APIs', async () => {
    const requests: string[] = []
    const model = await loadCommandCenter({
      async request<T>(path: string) {
        requests.push(path)
        if (path === '/scenic/snapshot') return { next_actions: [{ code: 'WAIT', label: '等待', description: '处理中' }] } as T
        if (path.startsWith('/admin/events')) return { events: [{ severity: 'P1' }, { severity: 'P1' }, { severity: 'P2' }] } as T
        if (path.startsWith('/admin/tasks')) return { tasks: [{ status: 'PENDING' }, { status: 'DONE' }] } as T
        return [{ status: 'PENDING' }, { status: 'APPROVED' }] as T
      },
    })
    expect(requests).toEqual([
      '/scenic/snapshot',
      '/admin/events?limit=200',
      '/admin/tasks?limit=200',
      '/admin/approvals?status=ALL&limit=200',
    ])
    expect(model.metrics).toEqual({ events: 3, activeIncidents: 0, openTasks: 1, pendingApprovals: 1 })
    expect(model.charts.eventSeverity).toEqual([{ name: 'P1', value: 2 }, { name: 'P2', value: 1 }])
    expect(model.charts.taskStatus).toEqual([{ name: 'PENDING', value: 1 }, { name: 'DONE', value: 1 }])
    expect(model.charts.approvalStatus).toEqual([{ name: 'PENDING', value: 1 }, { name: 'APPROVED', value: 1 }])
  })

  it('keeps backend-owned allowed actions and exposes snapshot metrics', () => {
    const model = buildCommandCenter({
      incidents: [{ lifecycle: 'OPEN' }, { lifecycle: 'CLOSED' }],
      tasks: [{ status: 'PENDING' }, { status: 'DONE' }],
      approvals: [{ status: 'PENDING' }],
      events: [{ event_id: 'e1', severity: 'P2' }],
      advice: {
        status: 'READY',
        evidence_status: 'GROUNDED',
        advice: '按 SOP 执行',
        allowed_actions: ['ADOPT', 'IGNORE'],
      },
    })
    expect(model.metrics.activeIncidents).toBe(1)
    expect(model.metrics.openTasks).toBe(1)
    expect(model.metrics.pendingApprovals).toBe(1)
    expect(model.metrics.events).toBe(1)
    expect(model.advice?.allowedActions).toEqual(['ADOPT', 'IGNORE'])
  })
})
