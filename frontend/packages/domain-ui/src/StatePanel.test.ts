import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatePanel from './StatePanel.vue'

describe('StatePanel', () => {
  it('renders loading, empty, degraded and error states as text', () => {
    const loading = mount(StatePanel, { props: { state: 'loading', title: '正在同步' } })
    expect(loading.text()).toContain('正在同步')
    expect(loading.attributes('data-state')).toBe('loading')

    const degraded = mount(StatePanel, { props: { state: 'degraded', title: '建议已降级', message: '未获得模型建议' } })
    expect(degraded.text()).toContain('建议已降级')
    expect(degraded.text()).toContain('未获得模型建议')

    const error = mount(StatePanel, { props: { state: 'error', title: '加载失败', message: '请刷新后重试' } })
    expect(error.text()).toContain('加载失败')
    expect(error.text()).toContain('请刷新后重试')
  })
})
