import { describe, expect, it, vi } from 'vitest'
import * as field from './field'

describe('field assistant API seam', () => {
  it('loads sessions, messages and work context', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ sessions: [{ session_id: 's1' }] })
      .mockResolvedValueOnce({ session: { session_id: 's1' }, messages: [{ id: 'm1' }] })
      .mockResolvedValueOnce({ tasks: [{ id: 't1' }], events: [{ event_id: 'e1' }] })
    expect(await field.loadAssistantSessions({ request })).toHaveLength(1)
    expect(await field.loadAssistantMessages({ request }, 's1')).toMatchObject({ messages: [{ id: 'm1' }] })
    expect(await field.loadAssistantWork({ request })).toMatchObject({ tasks: [{ id: 't1' }] })
    expect(request).toHaveBeenNthCalledWith(1, '/assistant/sessions?limit=100')
    expect(request).toHaveBeenNthCalledWith(2, '/assistant/sessions/s1/messages?limit=200')
    expect(request).toHaveBeenNthCalledWith(3, '/assistant/work?limit=100')
  })

  it('sends, retries and uploads assistant messages through formal endpoints', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await field.sendAssistantMessage({ request }, { content: '需要支援', external_message_id: 'ext-1' })
    await field.retryAssistantMessage({ request }, 'm1')
    const file = new File(['evidence'], 'evidence.png', { type: 'image/png' })
    await field.uploadAssistantAttachment({ request }, file)
    expect(request).toHaveBeenNthCalledWith(1, '/assistant/messages', {
      method: 'POST',
      json: { content: '需要支援', external_message_id: 'ext-1', channel: 'WEB' },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/assistant/messages/m1/retry', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(3, '/assistant/attachments', {
      method: 'POST',
      body: expect.any(FormData),
    })
  })

  it('executes task lifecycle and detail reads', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await field.loadAssistantTask({ request }, 't1')
    await field.loadAssistantEvent({ request }, 'e1')
    await field.loadAssistantSop({ request }, 7, '1.0')
    await field.startAssistantTask({ request }, 't1')
    await field.completeAssistantTask({ request }, 't1', '已更换部件', { checked: true })
    await field.blockAssistantTask({ request }, 't1', '等待备件')
    expect(request).toHaveBeenNthCalledWith(1, '/assistant/work/tasks/t1')
    expect(request).toHaveBeenNthCalledWith(2, '/assistant/work/events/e1')
    expect(request).toHaveBeenNthCalledWith(3, '/assistant/knowledge/sops/7?version=1.0')
    expect(request).toHaveBeenNthCalledWith(4, '/assistant/work/tasks/t1/start', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(5, '/assistant/work/tasks/t1/complete', {
      method: 'POST',
      json: { summary: '已更换部件', result: { checked: true } },
    })
    expect(request).toHaveBeenNthCalledWith(6, '/assistant/work/tasks/t1/block', {
      method: 'POST',
      json: { reason: '等待备件' },
    })
  })
})

describe('field experience API seam', () => {
  it('loads experience home, interviews and card revisions', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ expert: { id: 'x1' }, interviews: [], cards: [] })
      .mockResolvedValueOnce({ interview: { id: 'i1', turns: [] } })
    expect(await field.loadAssistantExperience({ request })).toMatchObject({ expert: { id: 'x1' } })
    expect(await field.loadAssistantInterview({ request }, 'i1')).toMatchObject({ id: 'i1' })
    expect(request).toHaveBeenNthCalledWith(1, '/assistant/experience')
    expect(request).toHaveBeenNthCalledWith(2, '/assistant/experience/interviews/i1')
  })

  it('accepts, answers, pauses, resumes and completes an interview', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await field.acceptAssistantInterview({ request }, 'i1')
    await field.answerAssistantInterview({ request }, 'i1', '先确认现场风险', '现场原话')
    await field.pauseAssistantInterview({ request }, 'i1')
    await field.resumeAssistantInterview({ request }, 'i1')
    await field.completeAssistantInterview({ request }, 'i1')
    expect(request).toHaveBeenNthCalledWith(1, '/assistant/experience/interviews/i1/accept', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(2, '/assistant/experience/interviews/i1/answers', {
      method: 'POST',
      json: { answer: '先确认现场风险', source_excerpt: '现场原话' },
    })
    expect(request).toHaveBeenNthCalledWith(3, '/assistant/experience/interviews/i1/pause', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(4, '/assistant/experience/interviews/i1/resume', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(5, '/assistant/experience/interviews/i1/complete', { method: 'POST' })
  })

  it('revises, confirms, searches and records experience feedback', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await field.reviseAssistantExperienceCard({ request }, 'c1', { title: '新标题', change_note: '补充边界' })
    await field.confirmAssistantExperienceCard({ request }, 'c1')
    await field.searchAssistantExperience({ request }, '客流疏导', 's1')
    await field.recordAssistantExperienceFeedback({ request }, 'c1', 'HELPFUL', '有效', 's1')
    expect(request).toHaveBeenNthCalledWith(1, '/assistant/experience/cards/c1', {
      method: 'PUT',
      json: { title: '新标题', change_note: '补充边界' },
    })
    expect(request).toHaveBeenNthCalledWith(2, '/assistant/experience/cards/c1/confirm', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(3, '/assistant/experience/search', {
      method: 'POST',
      json: { query: '客流疏导', session_id: 's1', top_k: 5, threshold: 0 },
    })
    expect(request).toHaveBeenNthCalledWith(4, '/assistant/experience/cards/c1/feedback', {
      method: 'POST',
      json: { feedback: 'HELPFUL', note: '有效', session_id: 's1' },
    })
  })
})
