import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppShell from './AppShell.vue'

describe('AppShell', () => {
  it('renders the entry identity, venue, connection, and last update', () => {
    const wrapper = mount(AppShell, {
      props: {
        title: '指挥中心',
        venue: '云栖山景区',
        connection: 'CONNECTED',
        lastUpdated: '23:50',
      },
      slots: {
        default: '<p class="test-slot">next action</p>',
      },
    })

    expect(wrapper.text()).toContain('指挥中心')
    expect(wrapper.text()).toContain('云栖山景区')
    expect(wrapper.text()).toContain('已连接')
    expect(wrapper.text()).toContain('23:50')
    expect(wrapper.find('.test-slot').exists()).toBe(true)
  })
})