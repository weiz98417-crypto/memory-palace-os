import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppShell from './AppShell.vue'

describe('AppShell', () => {
  it('exposes a global logout action when enabled', async () => {
    const wrapper = mount(AppShell, {
      props: {
        title: '指挥中心',
        venue: 'venue-hq',
        connection: 'CONNECTED',
        lastUpdated: '--',
        showLogout: true,
      },
    })

    const logout = wrapper.get('button.mp-shell__logout')
    expect(logout.text()).toContain('退出登录')
    await logout.trigger('click')
    expect(wrapper.emitted('logout')).toHaveLength(1)
  })
})
