import { describe, expect, it, vi } from 'vitest'
import * as governance from './governance'

describe('console knowledge API seam', () => {
  it('loads and reads knowledge records', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ knowledge: [{ id: 'k1', title: '闭园检查' }] })
      .mockResolvedValueOnce({ knowledge: { id: 'k1', title: '闭园检查' } })
    expect(await governance.loadKnowledge({ request })).toHaveLength(1)
    expect(await governance.loadKnowledgeEntry({ request }, 'k1')).toMatchObject({ id: 'k1' })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/knowledge?limit=200')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/knowledge/k1')
  })

  it('keeps knowledge writes and index maintenance explicit', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    const body = { title: '闭园检查', content: '闭园前完成设备巡检', category: '安全', tags: ['闭园'] }
    await governance.createKnowledge({ request }, body)
    await governance.updateKnowledge({ request }, 'k1', { ...body, content: '更新后的巡检要求' })
    await governance.deleteKnowledge({ request }, 'k1')
    await governance.rebuildKnowledgeIndex({ request })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/knowledge', { method: 'POST', json: body })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/knowledge/k1', {
      method: 'PUT',
      json: { ...body, content: '更新后的巡检要求' },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/knowledge/k1', { method: 'DELETE' })
    expect(request).toHaveBeenNthCalledWith(4, '/admin/knowledge/rebuild-index', { method: 'POST' })
  })

  it('searches and batch imports through the formal knowledge endpoints', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ results: [{ id: 'k1', document: '闭园检查', similarity: 0.82 }] })
      .mockResolvedValueOnce({ imported: 2 })
    expect(await governance.searchKnowledge({ request }, '闭园风险')).toHaveLength(1)
    await governance.importKnowledge({ request }, [{ title: '入口秩序', content: '入口人流超过阈值时分流', category: '秩序', tags: [] }])
    expect(request).toHaveBeenNthCalledWith(1, '/admin/knowledge/search', {
      method: 'POST',
      json: { query: '闭园风险', top_k: 10, threshold: 0.3 },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/knowledge/import', {
      method: 'POST',
      json: { entries: [{ title: '入口秩序', content: '入口人流超过阈值时分流', category: '秩序', tags: [] }] },
    })
  })
})

describe('console experience API seam', () => {
  it('loads experts, interviews and experience cards', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ experts: [{ id: 'x1' }] })
      .mockResolvedValueOnce({ interviews: [{ id: 'i1' }] })
      .mockResolvedValueOnce({ experience_cards: [{ id: 'c1' }] })
      .mockResolvedValueOnce({ interview: { id: 'i1', turns: [] } })
      .mockResolvedValueOnce({ experience_card: { id: 'c1', versions: [] } })
    expect(await governance.loadExperts({ request })).toHaveLength(1)
    expect(await governance.loadInterviews({ request })).toHaveLength(1)
    expect(await governance.loadExperienceCards({ request })).toHaveLength(1)
    expect(await governance.loadInterview({ request }, 'i1')).toMatchObject({ id: 'i1' })
    expect(await governance.loadExperienceCard({ request }, 'c1')).toMatchObject({ id: 'c1' })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/experts?limit=200')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/experience-interviews?limit=200')
    expect(request).toHaveBeenNthCalledWith(3, '/admin/experience-cards?limit=200')
    expect(request).toHaveBeenNthCalledWith(4, '/admin/experience-interviews/i1')
    expect(request).toHaveBeenNthCalledWith(5, '/admin/experience-cards/c1')
  })

  it('creates experts and interviews with explicit authorization', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    const expert = {
      user_id: 'u1',
      display_name: '陈雨',
      job_title: '安保值班长',
      department: '运营保障部',
      years_experience: 8,
      expertise: ['客流疏导'],
      authorization_status: 'SIGNED' as const,
      authorization_statement: '同意在授权范围内使用经验。',
    }
    const interview = {
      expert_id: 'x1',
      title: '节假日高峰疏导',
      authorization_scopes: [{ scope_type: 'VENUE' as const, scope_value: 'venue-hq' }],
    }
    await governance.createExpert({ request }, expert)
    await governance.createInterview({ request }, interview)
    expect(request).toHaveBeenNthCalledWith(1, '/admin/experts', { method: 'POST', json: expert })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/experience-interviews', { method: 'POST', json: interview })
  })

  it('submits and reviews experience cards only through lifecycle endpoints', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await governance.submitExperienceCard({ request }, 'c1')
    await governance.rejectExperienceCard({ request }, 'c1', '补充适用边界')
    await governance.publishExperienceCard({ request }, 'c1', '审核通过')
    await governance.deprecateExperienceCard({ request }, 'c1', '业务规则已变更')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/experience-cards/c1/submit', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/experience-cards/c1/reject', {
      method: 'POST',
      json: { comment: '补充适用边界' },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/experience-cards/c1/publish', {
      method: 'POST',
      json: { comment: '审核通过' },
    })
    expect(request).toHaveBeenNthCalledWith(4, '/admin/experience-cards/c1/deprecate', {
      method: 'POST',
      json: { comment: '业务规则已变更' },
    })
  })
})

describe('console watcher API seam', () => {
  it('loads policies, findings and recent runs', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ policies: [{ id: 'w1' }] })
      .mockResolvedValueOnce({ findings: [{ id: 'f1' }] })
      .mockResolvedValueOnce({ runs: [{ id: 'r1' }] })
    expect(await governance.loadWatcherPolicies({ request })).toHaveLength(1)
    expect(await governance.loadWatcherFindings({ request })).toHaveLength(1)
    expect(await governance.loadWatcherRuns({ request })).toHaveLength(1)
    expect(request).toHaveBeenNthCalledWith(1, '/admin/watcher/policies')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/watcher/findings?limit=200')
    expect(request).toHaveBeenNthCalledWith(3, '/admin/watcher/runs?limit=50')
  })

  it('creates, edits, toggles and runs a policy explicitly', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    const body = { name: 'SLA 巡检', description: '检查超时', schedule_cron: '0 10 * * *', enabled: true, check_types: ['SLA'], config: { max_targets: 200 } }
    await governance.createWatcherPolicy({ request }, body)
    await governance.updateWatcherPolicy({ request }, 'w1', body)
    await governance.toggleWatcherPolicy({ request }, 'w1', false)
    await governance.runWatcherPolicy({ request }, 'w1')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/watcher/policies', { method: 'POST', json: body })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/watcher/policies/w1', { method: 'PUT', json: body })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/watcher/policies/w1', { method: 'PUT', json: { enabled: false } })
    expect(request).toHaveBeenNthCalledWith(4, '/admin/watcher/policies/w1/run', { method: 'POST' })
  })

  it('assigns and closes findings through the governed endpoints', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await governance.assignWatcherFinding({ request }, 'f1', 'u1')
    await governance.closeWatcherFinding({ request }, 'f1', '已更换老化部件')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/watcher/findings/f1', {
      method: 'PATCH',
      json: { assigned_to: 'u1', status: 'IN_PROGRESS' },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/watcher/findings/f1/close', {
      method: 'POST',
      json: { resolution: '已更换老化部件' },
    })
  })
})

describe('console SOP display seam', () => {
  it('formats PostgreSQL ISO timestamps without Invalid Date', () => {
    const formatted = governance.formatSopTimestamp('2026-09-21T06:00:00Z')
    expect(formatted).not.toBe('Invalid Date')
    expect(formatted).toContain('2026')
  })
})

describe('console SOP API seam', () => {
  it('loads the SOP list and a versioned detail', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ sops: [{ id: 1, title: '闭园流程' }] })
      .mockResolvedValueOnce({ sop: { id: 1, title: '闭园流程' }, versions: [{ version: '1.0' }] })
    expect(await governance.loadSops({ request })).toHaveLength(1)
    expect(await governance.loadSop({ request }, 1)).toMatchObject({ id: 1 })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/sops')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/sops/1')
  })

  it('creates and updates SOP drafts with change notes', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    const createBody = { title: '闭园流程', category: '安全', priority: 2, source_event_id: null, content: '闭园前完成设备巡检', version: '1.0' }
    const updateBody = { title: '闭园流程', category: '安全', priority: 2, source_event_id: null, content: '闭园前完成设备巡检和入口封闭', change_note: '补充入口动作' }
    await governance.createSop({ request }, createBody)
    await governance.updateSop({ request }, 1, updateBody)
    expect(request).toHaveBeenNthCalledWith(1, '/admin/sops', { method: 'POST', json: createBody })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/sops/1', { method: 'PUT', json: updateBody })
  })

  it('submits, publishes and rejects through governed lifecycle actions', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await governance.submitSop({ request }, 1)
    await governance.publishSop({ request }, 1, '审核通过')
    await governance.rejectSop({ request }, 1, '补充设备检查步骤')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/sops/1/submit', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/sops/1/publish', { method: 'POST', json: { comment: '审核通过' } })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/sops/1/reject', { method: 'POST', json: { comment: '补充设备检查步骤' } })
  })
})
