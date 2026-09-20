import { describe, expect, it } from 'vitest'
import { buildFieldView } from './fieldStatus'

describe('field snapshot projection', () => {
  it('keeps advice read-only and preserves no-evidence wording', () => {
    const view = buildFieldView({
      incidents: [{
        tasks: [{ id: 'task-1' }],
        evidence: [{ id: 'evidence-1' }],
        advice: { status: 'READY', evidence_status: 'NO_EVIDENCE' },
      }],
    })
    expect(view.advice?.text).toBe('没有依据')
    expect(view.advice?.readOnly).toBe(true)
    expect(view.tasks).toHaveLength(1)
  })
})