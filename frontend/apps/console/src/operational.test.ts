import { describe, expect, it, vi } from 'vitest'
import * as operational from './operational'
import {
  closeEvent,
  closeSession,
  loadEvent,
  loadEvents,
  loadSessions,
  runEventWatcher,
  updateEvent,
} from './operational'

describe('console operational API seam', () => {
  it('loads events and their dossiers', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ events: [{ event_id: 'e1' }] })
      .mockResolvedValueOnce({ event_id: 'e1', dossier: { evidence: [] } })
    expect(await loadEvents({ request })).toHaveLength(1)
    expect(await loadEvent({ request }, 'e1')).toMatchObject({ event_id: 'e1' })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/events?limit=200')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/events/e1')
  })

  it('sends event updates, closure gates and watcher checks', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await updateEvent({ request }, 'e1', { severity: 'P2' })
    await closeEvent({ request }, 'e1')
    await runEventWatcher({ request }, 'e1')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/events/e1', { method: 'PATCH', json: { severity: 'P2' } })
    expect(request).toHaveBeenNthCalledWith(2, '/admin/events/e1/close', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(3, '/admin/events/e1/watcher-check', { method: 'POST' })
  })

  it('loads and closes sessions', async () => {
    const request = vi.fn().mockResolvedValueOnce([{ session_id: 's1' }]).mockResolvedValueOnce({ status: 'ok' })
    expect(await loadSessions({ request })).toHaveLength(1)
    await closeSession({ request }, 's1')
    expect(request).toHaveBeenNthCalledWith(1, '/sessions/?limit=200')
    expect(request).toHaveBeenNthCalledWith(2, '/sessions/s1', { method: 'DELETE' })
  })
})


describe('console task and approval API seam', () => {
  it('loads tasks, assignees and task detail', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ tasks: [{ id: 't1' }] })
      .mockResolvedValueOnce([{ id: 'u1', display_name: '陈雨' }])
      .mockResolvedValueOnce({ task: { id: 't1' } })
    expect(await operational.loadTasks({ request })).toHaveLength(1)
    expect(await operational.loadAssignees({ request })).toHaveLength(1)
    expect(await operational.loadTask({ request }, 't1')).toMatchObject({ task: { id: 't1' } })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/tasks?limit=200')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/assignees')
    expect(request).toHaveBeenNthCalledWith(3, '/admin/tasks/t1')
  })

  it('routes task creation, assignment and lifecycle actions', async () => {
    const request = vi.fn().mockResolvedValue({ ok: true })
    await operational.createTask({ request }, { session_id: 's1', description: '检修' })
    await operational.decomposeTasks({ request }, { session_id: 's1', goal: '闭园检查' })
    await operational.assignTask({ request }, 't1', { assigned_user_id: 'u1' })
    await operational.taskAction({ request }, 't1', 'start')
    await operational.taskAction({ request }, 't1', 'complete', { result: { summary: '完成' } })
    expect(request).toHaveBeenNthCalledWith(1, '/admin/tasks', expect.objectContaining({ method: 'POST' }))
    expect(request).toHaveBeenNthCalledWith(2, '/admin/tasks/decompose', expect.objectContaining({ method: 'POST' }))
    expect(request).toHaveBeenNthCalledWith(3, '/admin/tasks/t1/assignment', { method: 'PATCH', json: { assigned_user_id: 'u1' } })
    expect(request).toHaveBeenNthCalledWith(4, '/admin/tasks/t1/start', { method: 'POST' })
    expect(request).toHaveBeenNthCalledWith(5, '/admin/tasks/t1/complete', { method: 'POST', json: { result: { summary: '完成' } } })
  })

  it('loads approvals and keeps approve/reject as explicit human actions', async () => {
    const request = vi.fn()
      .mockResolvedValueOnce([{ approval_id: 'a1', status: 'PENDING' }])
      .mockResolvedValueOnce({ approval_id: 'a1' })
      .mockResolvedValueOnce({ approved: true })
      .mockResolvedValueOnce({ rejected: true })
    expect(await operational.loadApprovals({ request }, 'PENDING')).toHaveLength(1)
    await operational.loadApproval({ request }, 'a1')
    await operational.approveApproval({ request }, 'a1', '同意')
    await operational.rejectApproval({ request }, 'a1', '风险过高')
    expect(request).toHaveBeenNthCalledWith(1, '/admin/approvals?status=PENDING&limit=200')
    expect(request).toHaveBeenNthCalledWith(2, '/admin/approvals/a1')
    expect(request).toHaveBeenNthCalledWith(3, '/admin/approvals/a1/approve', { method: 'POST', json: { comment: '同意' } })
    expect(request).toHaveBeenNthCalledWith(4, '/admin/approvals/a1/reject', { method: 'POST', json: { comment: '风险过高' } })
  })
})
