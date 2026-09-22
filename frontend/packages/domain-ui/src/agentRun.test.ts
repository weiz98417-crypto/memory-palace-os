import { describe, expect, it } from 'vitest'
import { artifactDisplay, mergeAgentRuns, presentAgentRun } from './agentRun'

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

describe('AgentRun presentation', () => {
  it('maps every advice lifecycle state to the canonical label and color tone', () => {
    const base = { incident_id: 'i', artifact: 'ADVICE' as const, run_id: 'r', sequence: 1 }
    expect(presentAgentRun({ ...base, status: 'PENDING' })).toMatchObject({ statusLabel: '分析中', tone: 'primary' })
    expect(presentAgentRun({ ...base, status: 'RUNNING' })).toMatchObject({ statusLabel: '分析中', tone: 'info' })
    expect(presentAgentRun({ ...base, status: 'READY', payload: { evidence_status: 'GROUNDED' } })).toMatchObject({ statusLabel: '已就绪', tone: 'success' })
    expect(presentAgentRun({ ...base, status: 'READY', payload: { evidence_status: 'NO_EVIDENCE' } })).toMatchObject({ statusLabel: '没有依据', tone: 'warning' })
    expect(presentAgentRun({ ...base, status: 'FAILED' })).toMatchObject({ statusLabel: '未获得模型建议', tone: 'danger' })
    expect(presentAgentRun({ ...base, status: 'SUPERSEDED' })).toMatchObject({ statusLabel: '已过期', tone: 'warning' })
  })

  it('renders dispatch and closure payloads as structured facts and lists', () => {
    const dispatch = presentAgentRun({
      incident_id: 'i',
      artifact: 'DISPATCH_DRAFT',
      run_id: 'd1',
      status: 'READY',
      sequence: 1,
      payload: {
        summary: '检修 12 号车',
        priority: 'P1',
        risk_reason: '制动异常',
        requires_human_approval: true,
        required_tools: ['send_in_app_alert'],
        next_step_check: '检查备用车',
        immediate_actions: [{ action_code: 'CREATE_REPAIR_TASK', description: '派检修', preconditions: ['停运'] }],
      },
    })
    expect(dispatch.title).toBe('派单草案')
    expect(dispatch.summary).toBe('检修 12 号车')
    expect(dispatch.facts).toContainEqual({ label: '优先级', value: 'P1' })
    expect(dispatch.facts).toContainEqual({ label: '需要人工审批', value: '是' })
    expect(dispatch.lists.find((item) => item.label === '立即动作')?.items[0]).toContain('CREATE_REPAIR_TASK')

    const closure = presentAgentRun({
      incident_id: 'i',
      artifact: 'CLOSURE_SUMMARY',
      run_id: 'c1',
      status: 'READY',
      sequence: 1,
      payload: {
        outcome_summary: '事件已闭环',
        evidence_refs: ['e1'],
        sop_refs: ['sop1'],
        completed_task_refs: ['t1'],
        approval_refs: ['a1'],
        alert_recovery_refs: ['alert1'],
        unresolved_risks: ['后续复查'],
        recommended_for_closure: true,
      },
    })
    expect(closure.title).toBe('关闭摘要')
    expect(closure.summary).toBe('事件已闭环')
    expect(closure.facts).toContainEqual({ label: '建议关闭', value: '是' })
    expect(closure.lists.find((item) => item.label === '证据引用')?.items).toEqual(['e1'])
    expect(closure.lists.find((item) => item.label === '未解决风险')?.items).toEqual(['后续复查'])
  })

  it('normalizes citations, model evidence and degradations without exposing raw objects', () => {
    const presentation = presentAgentRun({
      incident_id: 'i',
      artifact: 'ADVICE',
      run_id: 'r1',
      status: 'READY',
      sequence: 1,
      payload: { advice_text: '按 SOP 执行', evidence_status: 'GROUNDED' },
      citations: [{ source_id: 'sop-1', title: '停运 SOP', version: '1.2', excerpt: '先停运' }],
      model_evidence: [{ agent: 'memory_ops', model: 'deepseek-flash', tokens: 321, trace_id: 'trace-1' }],
      degradations: [{ agent_role: 'memory_ops', code: 'TIMEOUT', public_message: '模型调用超时' }],
    })
    expect(presentation.citations[0]).toEqual({ sourceId: 'sop-1', title: '停运 SOP', version: '1.2', excerpt: '先停运', score: '' })
    expect(presentation.evidence[0]).toEqual({ agent: 'memory_ops', model: 'deepseek-flash', tokens: '321', traceId: 'trace-1', status: '' })
    expect(presentation.degradations[0]).toEqual({ agent: 'memory_ops', code: 'TIMEOUT', message: '模型调用超时' })
    expect(JSON.stringify(presentation)).not.toContain('[object Object]')
  })
})
