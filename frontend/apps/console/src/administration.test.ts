import { describe, expect, it, vi } from 'vitest'
import * as administration from './administration'

describe('console administration API seam', () => {
  it('loads and mutates users through audited admin endpoints', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await administration.loadUsers({ request })
    await administration.createUser({ request }, { username: 'new.op', display_name: '新操作员', password: 'password123', role: 'operator', venue_id: 'venue-hq' })
    await administration.updateUser({ request }, 'u1', { status: 'DISABLED' })
    await administration.resetUserPassword({ request }, 'u1', 'new-password-123')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/users')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/users', {
      method: 'POST',
      json: { username: 'new.op', display_name: '新操作员', password: 'password123', role: 'operator', venue_id: 'venue-hq' },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/users/u1', { method: 'PATCH', json: { status: 'DISABLED' } })
    expect(request).toHaveBeenNthCalledWith(4, '/admin/users/u1/reset-password', { method: 'POST', json: { password: 'new-password-123' } })
  })

  it('loads and mutates venues and simulator identity mappings', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await administration.loadVenues({ request })
    await administration.createVenue({ request }, { id: 'venue-west', name: '西区运营中心' })
    await administration.updateVenue({ request }, 'venue-west', { status: 'DISABLED' })
    await administration.enableSimulatorIdentity({ request }, { id: 'u1', venue_id: 'venue-hq' })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/venues')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/venues', { method: 'POST', json: { id: 'venue-west', name: '西区运营中心' } })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/venues/venue-west', { method: 'PATCH', json: { status: 'DISABLED' } })
    expect(request).toHaveBeenNthCalledWith(4, '/channels/identities', {
      method: 'POST',
      json: {
        channel: 'WECOM_SIMULATOR',
        external_tenant_id: 'simulator-tenant:venue-hq',
        external_user_id: 'simulator-user:u1',
        user_id: 'u1',
        status: 'ACTIVE',
      },
    })
  })

  it('loads settings, integrations and the release registry', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ settings: [{ key: 'organization_name', value: '示范景区' }] })
      .mockResolvedValueOnce({ integrations: [{ id: 'deepseek', status: 'READY' }] })
      .mockResolvedValueOnce({ summary: { release_gate_passed: true }, items: [] })
    expect(await administration.loadSettings({ request })).toHaveLength(1)
    expect(await administration.loadIntegrations({ request })).toHaveLength(1)
    expect(await administration.loadFeatureRegistry({ request })).toMatchObject({ summary: { release_gate_passed: true } })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/settings')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/integrations')
    expect(request).toHaveBeenNthCalledWith(3, '/admin/feature-registry')
  })

  it('updates settings only through the supported setting key endpoint', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await administration.updateSetting({ request }, 'sla_p0_minutes', 8)
    expect(request).toHaveBeenCalledWith('/admin/settings/sla_p0_minutes', { method: 'PUT', json: { value: 8 } })
  })
})

describe('console diagnostics API seam', () => {
  it('loads diagnostics and operational evidence sections', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ status: 'healthy', runtime: {} })
      .mockResolvedValueOnce({ pending: 0 })
      .mockResolvedValueOnce({ dead_letters: [] })
      .mockResolvedValueOnce({ llm_calls: [{ id: 'c1' }] })
      .mockResolvedValueOnce({ audit_logs: [{ id: 'a1' }] })
      .mockResolvedValueOnce([{ name: 'commander' }])
      .mockResolvedValueOnce({ recovery_runs: [{ instance_id: 'i1' }] })
    expect(await administration.loadRuntimeDiagnostics({ request })).toMatchObject({ status: 'healthy' })
    await administration.loadQueueStatus({ request })
    await administration.loadDeadLetters({ request })
    expect(await administration.loadLlmCalls({ request })).toHaveLength(1)
    expect(await administration.loadAuditLogs({ request })).toHaveLength(1)
    expect(await administration.loadSkills({ request })).toHaveLength(1)
    expect(await administration.loadRecoveryRuns({ request })).toHaveLength(1)
    expect(request).toHaveBeenNthCalledWith(1, '/admin/diagnostics')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/queue')
    expect(request).toHaveBeenNthCalledWith(3, '/admin/dead-letters?limit=50')
    expect(request).toHaveBeenNthCalledWith(4, '/admin/llm-calls?limit=50')
    expect(request).toHaveBeenNthCalledWith(5, '/admin/audit-logs?limit=50')
    expect(request).toHaveBeenNthCalledWith(6, '/skills')
    expect(request).toHaveBeenNthCalledWith(7, '/admin/recovery-runs?limit=20')
  })

  it('queries traces and keeps runtime actions explicit', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await administration.loadTrace({ request }, 'trace-123')
    await administration.runDeepseekProbe({ request })
    await administration.reloadRuntimeConfig({ request })
    await administration.reloadSkill({ request }, 'commander')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/traces/trace-123')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/diagnostics/deepseek-probe', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/config/reload', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(4, '/skills/commander/reload', { method: 'POST' })
  })
})
