import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import EvaluationOperationsView from './EvaluationOperationsView.vue'

describe('EvaluationOperationsView', () => {
  it('loads and renders evaluation runs', async () => {
    const request = vi.fn().mockResolvedValue({
      runs: [
        { run_id: 'c1', tier: 'contract', case_set: 'fast', passed_count: 2, case_count: 2, pass_rate: 1, failed_count: 0, elapsed_seconds: 1, created_at: 2 },
      ],
    })
    const wrapper = mount(EvaluationOperationsView, { props: { client: { request } } })
    await flushPromises()
    expect(wrapper.text()).toContain('契约门禁')
    expect(wrapper.text()).toContain('2 / 2')
    expect(wrapper.text()).toContain('查看明细')
  })
})
