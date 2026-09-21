import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ConsoleLoginView from './views/ConsoleLoginView.vue'

function clientWithLogin(login: ReturnType<typeof vi.fn>) {
  return { auth: { login, clear: vi.fn() } }
}

describe('ConsoleLoginView', () => {
  it('authenticates a manager and emits the session user', async () => {
    const login = vi.fn().mockResolvedValue({ role: 'manager', username: 'wangfang' })
    const wrapper = mount(ConsoleLoginView, { props: { client: clientWithLogin(login) } })
    await wrapper.find('form').trigger('submit')
    expect(login).toHaveBeenCalledWith('wangfang', '')
    expect(wrapper.emitted('authenticated')?.[0]?.[0]).toMatchObject({ role: 'manager' })
  })

  it('rejects non-console roles and clears the local session', async () => {
    const clear = vi.fn()
    const client = { auth: { login: vi.fn().mockResolvedValue({ role: 'operator' }), clear } }
    const wrapper = mount(ConsoleLoginView, { props: { client } })
    await wrapper.find('form').trigger('submit')
    expect(clear).toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain('经理或管理员')
  })

  it('toggles password visibility through the public icon button', async () => {
    const wrapper = mount(ConsoleLoginView, { props: { client: clientWithLogin(vi.fn()) } })
    const input = wrapper.get('input[autocomplete="current-password"]')
    expect(input.attributes('type')).toBe('password')
    await wrapper.get('button[aria-label="显示密码"]').trigger('click')
    expect(input.attributes('type')).toBe('text')
  })
})
