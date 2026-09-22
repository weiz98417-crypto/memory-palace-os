import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import LoginShell from './LoginShell.vue'

describe('LoginShell', () => {
  it('keeps credentials controlled by the parent and emits submit', async () => {
    const wrapper = mount(LoginShell, {
      props: {
        title: '现场端',
        subtitle: '测试登录',
        username: '',
        password: '',
        backgroundImage: '/login.webp',
      },
    })

    await wrapper.get('input[autocomplete="username"]').setValue('chenyu')
    await wrapper.get('input[autocomplete="current-password"]').setValue('secret')
    await wrapper.get('form').trigger('submit')

    expect(wrapper.emitted('update:username')?.[0]).toEqual(['chenyu'])
    expect(wrapper.emitted('update:password')?.[0]).toEqual(['secret'])
    expect(wrapper.emitted('submit')).toHaveLength(1)
  })
})
