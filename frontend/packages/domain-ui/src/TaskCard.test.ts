import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import TaskCard from './TaskCard.vue'

describe('TaskCard', () => {
  it('renders task facts and exposes an action slot', () => {
    const wrapper = mount(TaskCard, {
      props: {
        task: {
          id: 't1',
          title: '检修 12 号车',
          status: 'RUNNING',
          assignee_name: '陈雨',
          description: '检查右后轮',
          due_at: 1785283200,
        },
      },
      slots: { actions: '<button class="task-action">提交结果</button>' },
    })
    expect(wrapper.text()).toContain('检修 12 号车')
    expect(wrapper.text()).toContain('RUNNING')
    expect(wrapper.text()).toContain('陈雨')
    expect(wrapper.text()).toContain('检查右后轮')
    expect(wrapper.find('.task-action').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('[object Object]')
  })
})
