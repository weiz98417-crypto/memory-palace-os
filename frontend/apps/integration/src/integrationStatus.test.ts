import { describe, expect, it } from 'vitest'
import { buildIntegrationView } from './integrationStatus'

describe('integration entry projection', () => {
  it('keeps simulator channel semantics and does not claim production delivery', () => {
    const view = buildIntegrationView({ identities: [{ id: 'u1' }] })
    expect(view.channel).toBe('WECOM_SIMULATOR_OUTBOX')
    expect(view.productionDeliveryClaim).toBe(false)
    expect(view.identities).toHaveLength(1)
  })
})