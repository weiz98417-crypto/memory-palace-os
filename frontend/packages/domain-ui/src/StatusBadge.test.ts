import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import StatusBadge from './StatusBadge.vue'

describe('StatusBadge', () => {
  it('exposes semantic tone for full-badge coloring', () => {
    const wrapper = mount(StatusBadge, { props: { label: 'PENDING', tone: 'primary' } })
    expect(wrapper.text()).toContain('PENDING')
    expect(wrapper.classes()).toContain('status-badge')
    expect(wrapper.attributes('data-tone')).toBe('primary')
  })
})
