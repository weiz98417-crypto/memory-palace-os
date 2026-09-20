import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import NavRail from './NavRail.vue'

describe('NavRail', () => {
  it('renders navigation items and emits the selected key', async () => {
    const wrapper = mount(NavRail, {
      props: {
        activeKey: 'dashboard',
        items: [
          { key: 'dashboard', label: '指挥中心' },
          { key: 'events', label: '事件处置' },
          { key: 'disabled', label: '暂不可用', disabled: true },
        ],
      },
    })
    expect(wrapper.text()).toContain('指挥中心')
    expect(wrapper.find('[data-nav-key="dashboard"]').attributes('aria-current')).toBe('page')
    await wrapper.find('[data-nav-key="events"]').trigger('click')
    expect(wrapper.emitted('select')?.[0]).toEqual(['events'])
    await wrapper.find('[data-nav-key="disabled"]').trigger('click')
    expect(wrapper.emitted('select')).toHaveLength(1)
  })

  it('supports horizontal navigation for the field entry', () => {
    const wrapper = mount(NavRail, {
      props: { activeKey: 'chat', orientation: 'horizontal', items: [{ key: 'chat', label: '助手' }] },
    })
    expect(wrapper.find('nav').attributes('data-orientation')).toBe('horizontal')
  })
})
