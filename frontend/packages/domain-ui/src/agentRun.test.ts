import { describe, expect, it } from 'vitest'
import { artifactDisplay, mergeAgentRuns } from './agentRun'

describe('AgentRun reducer', () => {
  it('merges by incident/artifact/run and keeps latest sequence', () => {
    const merged = mergeAgentRuns(
      [{ incident_id: 'i1', artifact: 'ADVICE', run_id: 'r1', status: 'PENDING', sequence: 1 }],
      [{ incident_id: 'i1', artifact: 'ADVICE', run_id: 'r1', status: 'READY', sequence: 2 }],
    )
    expect(merged).toHaveLength(1)
    expect(merged[0].status).toBe('READY')
  })

  it('renders no-evidence and failed states explicitly', () => {
    expect(artifactDisplay({ incident_id: 'i', artifact: 'ADVICE', run_id: 'r', status: 'READY', sequence: 1, payload: { evidence_status: 'NO_EVIDENCE' } }).title).toBe('没有依据')
    expect(artifactDisplay({ incident_id: 'i', artifact: 'DISPATCH_DRAFT', run_id: 'r', status: 'FAILED', sequence: 2 }).title).toBe('未获得模型建议')
  })
})