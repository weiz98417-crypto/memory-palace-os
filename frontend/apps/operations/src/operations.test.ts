import { describe, expect, it, vi } from 'vitest'
import {
  filterEvaluationCases,
  parseSignalData,
  scenicRunLabel,
  sendScenicCommand,
  summarizeEvaluationRuns,
} from './operations'

describe('operations projections', () => {
  it('formats the current scenic run without exposing raw objects', () => {
    expect(scenicRunLabel({ run: { scenario_key: 'rain_vehicle_east_gate', scenario_version: '1.0.0', status: 'PAUSED', simulated_at: 1785283200 } }))
      .toContain('rain_vehicle_east_gate v1.0.0 · PAUSED')
  })

  it('parses signal JSON and rejects invalid input', () => {
    expect(parseSignalData('{"label":"人工观察"}')).toEqual({ label: '人工观察' })
    expect(() => parseSignalData('{bad json')).toThrow('JSON 数据无效')
  })

  it('summarizes evaluation runs and filters cases', () => {
    const runs = [
      { run_id: 'c1', tier: 'contract', case_set: 'fast', passed_count: 2, case_count: 2, pass_rate: 1, failed_count: 0, elapsed_seconds: 1, created_at: 1, results: [] },
      { run_id: 'd1', tier: 'deep', case_set: 'deep', passed_count: 1, case_count: 2, pass_rate: 0.5, failed_count: 1, elapsed_seconds: 2, created_at: 2, results: [] },
    ]
    const summary = summarizeEvaluationRuns(runs)
    expect(summary.total).toBe(2)
    expect(summary.contract).toBe(1)
    expect(summary.deep).toBe(1)
    expect(summary.latestContract?.run_id).toBe('c1')

    const cases = [
      { case_id: 'a', success: true, evidence_status: 'GROUNDED' },
      { case_id: 'b', success: false, evidence_status: 'NO_EVIDENCE' },
    ]
    expect(filterEvaluationCases(cases, 'failed').map((item) => item.case_id)).toEqual(['b'])
    expect(filterEvaluationCases(cases, 'NO_EVIDENCE').map((item) => item.case_id)).toEqual(['b'])
  })

  it('sends protected scenic commands through the shared client', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await sendScenicCommand({ request }, 'CLOCK_STEP', { seconds: 2 })
    expect(request).toHaveBeenCalledWith('/operations/scenic/commands', {
      method: 'POST',
      json: { kind: 'CLOCK_STEP', payload: { seconds: 2 } },
    })
  })
})
