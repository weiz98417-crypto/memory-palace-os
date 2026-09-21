import { describe, expect, it, vi } from 'vitest'
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
