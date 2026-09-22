import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import EvidenceTimeline from './EvidenceTimeline.vue'

describe('EvidenceTimeline', () => {
  it('renders evidence entries without exposing raw objects', () => {
    const wrapper = mount(EvidenceTimeline, {
      props: {
        items: [
          { title: '现场照片', detail: '右后轮照片', status: 'RECORDED', created_at: 1785283200 },
          { title: 'SOP 命中', detail: '停运 SOP v1.2', status: 'GROUNDED', created_at: 1785283300 },
        ],
      },
    })
    expect(wrapper.text()).toContain('现场照片')
    expect(wrapper.text()).toContain('右后轮照片')
    expect(wrapper.text()).toContain('停运 SOP v1.2')
    expect(wrapper.text()).toContain('RECORDED')
    expect(wrapper.text()).not.toContain('[object Object]')
    expect(wrapper.text()).not.toContain('1785283200')
    expect(wrapper.text()).toContain('2026')
  })
})
