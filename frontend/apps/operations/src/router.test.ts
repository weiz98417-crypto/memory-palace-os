import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import EvaluationOperationsView from './views/EvaluationOperationsView.vue'
import ScenicOperationsView from './views/ScenicOperationsView.vue'

describe('operations routes', () => {
  it('keeps scenic and evaluation entries distinct', async () => {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/scenic', component: ScenicOperationsView },
        { path: '/evaluation', component: EvaluationOperationsView },
      ],
    })
    await router.push('/scenic')
    await router.isReady()
    expect(router.currentRoute.value.path).toBe('/scenic')
    await router.push('/evaluation')
    expect(router.currentRoute.value.path).toBe('/evaluation')
  })
})