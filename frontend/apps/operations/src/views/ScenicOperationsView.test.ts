import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import ScenicOperationsView from './ScenicOperationsView.vue'

function client(overrides: Record<string, any> = {}) {
  return {
    auth: { read: () => null, login: vi.fn(), clear: vi.fn() },
    request: vi.fn().mockResolvedValue({ run: { scenario_key: 'rain_vehicle_east_gate', scenario_version: '1.0.0', status: 'PAUSED', simulated_at: 1785283200 } }),
    ...overrides,
  }
}

describe('ScenicOperationsView', () => {
  it('requires the protected simulation identity', async () => {
    const fake = client()
    const wrapper = mount(ScenicOperationsView, { props: { client: fake } })
    expect(wrapper.text()).toContain('运行准备身份验证')
  })

  it('shows the prepared run and clock controls after authentication', async () => {
    const fake = client({ auth: { read: () => ({ username: 'simulation-ops' }), login: vi.fn(), clear: vi.fn() } })
    const wrapper = mount(ScenicOperationsView, { props: { client: fake } })
    await flushPromises()
    expect(wrapper.text()).toContain('rain_vehicle_east_gate v1.0.0 · PAUSED')
    expect(wrapper.text()).toContain('播放')
    expect(wrapper.text()).toContain('单步 2 秒')
  })
})
