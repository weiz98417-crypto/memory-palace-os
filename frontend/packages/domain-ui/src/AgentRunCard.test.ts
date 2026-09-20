import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AgentRunCard from './AgentRunCard.vue'

describe('AgentRunCard', () => {
  it('renders grounded advice as structured content instead of raw objects', () => {
    const wrapper = mount(AgentRunCard, {
      props: {
        run: {
          incident_id: 'i1',
          artifact: 'ADVICE',
          run_id: 'r1',
          status: 'READY',
          sequence: 1,
          payload: { advice_text: '先停运再检修', evidence_status: 'GROUNDED', confidence: 0.9 },
          citations: [{ source_id: 'sop-1', title: '停运 SOP', version: '1.2', excerpt: '先停运' }],
          model_evidence: [{ agent: 'memory_ops', model: 'deepseek-flash', tokens: 321, trace_id: 'trace-1' }],
          degradations: [{ agent_role: 'memory_ops', code: 'TIMEOUT', public_message: '模型调用超时' }],
        },
      },
    })
    const text = wrapper.text()
    expect(text).toContain('处置建议')
    expect(text).toContain('已就绪')
    expect(text).toContain('先停运再检修')
    expect(text).toContain('停运 SOP')
    expect(text).toContain('deepseek-flash')
    expect(text).toContain('TIMEOUT')
    expect(text).not.toContain('[object Object]')
  })

  it('renders the canonical no-evidence state', () => {
    const wrapper = mount(AgentRunCard, {
      props: {
        run: {
          incident_id: 'i1',
          artifact: 'ADVICE',
          run_id: 'r2',
          status: 'READY',
          sequence: 1,
          payload: { evidence_status: 'NO_EVIDENCE' },
        },
      },
    })
    expect(wrapper.text()).toContain('没有依据')
    expect(wrapper.text()).not.toContain('{')
  })

  it('renders dispatch and closure sections', () => {
    const dispatch = mount(AgentRunCard, {
      props: {
        run: {
          incident_id: 'i1',
          artifact: 'DISPATCH_DRAFT',
          run_id: 'd1',
          status: 'READY',
          sequence: 1,
          payload: {
            summary: '派检修任务',
            priority: 'P1',
            requires_human_approval: true,
            immediate_actions: [{ action_code: 'CREATE_REPAIR_TASK', description: '派检修' }],
            required_tools: ['send_in_app_alert'],
          },
        },
      },
    })
    expect(dispatch.text()).toContain('派单草案')
    expect(dispatch.text()).toContain('CREATE_REPAIR_TASK: 派检修')
    expect(dispatch.text()).toContain('需要人工审批')

    const closure = mount(AgentRunCard, {
      props: {
        run: {
          incident_id: 'i1',
          artifact: 'CLOSURE_SUMMARY',
          run_id: 'c1',
          status: 'READY',
          sequence: 1,
          payload: {
            outcome_summary: '事件已闭环',
            evidence_refs: ['evidence-1'],
            unresolved_risks: ['继续观察'],
            recommended_for_closure: true,
          },
        },
      },
    })
    expect(closure.text()).toContain('关闭摘要')
    expect(closure.text()).toContain('证据引用')
    expect(closure.text()).toContain('未解决风险')
    expect(closure.text()).toContain('继续观察')
  })
})
