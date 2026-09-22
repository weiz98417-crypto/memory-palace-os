import { describe, expect, it, vi } from 'vitest'
import {
  deliveryStatusLabel,
  loadOutbox,
  sendSimulatorMessage,
  toneForStatus,
} from './integration'

describe('integration API seam', () => {
  it('maps delivery and message states without claiming production delivery', () => {
    expect(deliveryStatusLabel('DELIVERED')).toBe('已送达内部系统接入环境')
    expect(deliveryStatusLabel('RECORDED')).toBe('已写入出站账本')
    expect(deliveryStatusLabel('FAILED')).toBe('送达失败')
    expect(toneForStatus('PENDING')).toBe('primary')
    expect(toneForStatus('RUNNING')).toBe('info')
    expect(toneForStatus('FAILED')).toBe('danger')
    expect(toneForStatus('SENT')).toBe('success')
  })

  it('sends simulator messages through the manager endpoint', async () => {
    const request = vi.fn().mockResolvedValue({ message_id: 'm1' })
    await sendSimulatorMessage({ request }, {
      user_id: 'scenic-liming',
      content: '东门客流分流',
      external_message_id: 'ext-1',
      external_conversation_id: 'conv-1',
    })
    expect(request).toHaveBeenCalledWith('/channels/simulator/messages', {
      method: 'POST',
      json: expect.objectContaining({
        user_id: 'scenic-liming',
        content: '东门客流分流',
        external_message_id: 'ext-1',
        external_conversation_id: 'conv-1',
      }),
    })
  })

  it('loads outbox with the selected employee context', async () => {
    const request = vi.fn().mockResolvedValue({ items: [] })
    await loadOutbox({ request }, 'session-1', 'scenic-liming')
    expect(request).toHaveBeenCalledWith(
      '/channels/simulator/sessions/session-1/outbox?user_id=scenic-liming',
      { method: 'GET' },
    )
  })
})
