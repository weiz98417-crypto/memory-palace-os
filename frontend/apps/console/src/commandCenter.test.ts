import { describe, expect, it } from 'vitest'
import { buildCommandCenter, loadCommandCenter } from './commandCenter'

describe('console command center projection', () => {
  it('puts next action before advice and preserves NO_EVIDENCE wording', () => {
    const model = buildCommandCenter({
      next_actions: [
        { code: 'REVIEW_ADVICE', label: '查看并判断处置建议', description: '核对引用' },
      ],
      advice: { status: 'READY', evidence_status: 'NO_EVIDENCE', advice: 'ignored' },
    })
    expect(model.nextAction?.code).toBe('REVIEW_ADVICE')
    expect(model.advice?.text).toBe('没有依据')
    expect(model.metrics.activeIncidents).toBe(0)
  })

  it('loads the authoritative snapshot through the shared client', async () => {
    const requests: string[] = []
    const model = await loadCommandCenter({
      async request<T>(path: string) {
        requests.push(path)
        return { next_actions: [{ code: 'WAIT', label: '等待', description: '处理中' }] } as T
      },
    })
    expect(requests).toEqual(['/scenic/snapshot'])
    expect(model.nextAction?.label).toBe('等待')
    expect(model.metrics.events).toBe(0)
  })
})

  it('keeps backend-owned allowed actions and exposes snapshot metrics', () => {
    const model = buildCommandCenter({
      incidents: [{ lifecycle: 'OPEN' }, { lifecycle: 'CLOSED' }],
      tasks: [{ status: 'PENDING' }, { status: 'DONE' }],
      approvals: [{ status: 'PENDING' }],
      events: [{ event_id: 'e1' }],
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
