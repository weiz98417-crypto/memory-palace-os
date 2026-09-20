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
  })
})