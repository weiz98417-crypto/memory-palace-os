import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ApprovalCard from './ApprovalCard.vue'

describe('ApprovalCard', () => {
  it('renders approval facts and exposes decision actions', () => {
    const wrapper = mount(ApprovalCard, {
      props: {
        approval: {
          id: 'a1',
          tool_name: 'send_in_app_alert',
          status: 'PENDING',
          risk_level: 'P1',
          requester_name: '王芳',
          comment: '继续停运并启用备用车',
        },
      },
      slots: { actions: '<button class="approval-action">批准</button>' },
    })
    expect(wrapper.text()).toContain('send_in_app_alert')
    expect(wrapper.text()).toContain('PENDING')
    expect(wrapper.text()).toContain('P1')
    expect(wrapper.text()).toContain('王芳')
    expect(wrapper.text()).toContain('继续停运并启用备用车')
    expect(wrapper.find('.approval-action').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('[object Object]')
  })
})
