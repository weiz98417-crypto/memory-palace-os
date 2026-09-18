import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApiClient, createMemoryStorage } from './index'

function sseResponse(chunks: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
        controller.close()
      },
    }),
    { status: 200, headers: { 'content-type': 'text/event-stream' } },
  )
}

async function waitFor(assertion: () => void, timeoutMs = 1000) {
  const started = Date.now()
  while (true) {
    try {
      assertion()
      return
    } catch (error) {
      if (Date.now() - started >= timeoutMs) throw error
      await new Promise((resolve) => setTimeout(resolve, 10))
    }
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('fetch-based SSE client', () => {
  it('parses events, deduplicates ids, and resumes with Last-Event-ID', async () => {
    const calls: RequestInit[] = []
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(init ?? {})
      if (calls.length === 1) {
        return sseResponse([
          'id: 7\nevent: ADVICE_READY\ndata: {"state":"READY","sequence":7}\n\n',
          'id: 7\nevent: ADVICE_READY\ndata: {"state":"READY","sequence":7}\n\n',
        ])
      }
      return sseResponse([])
    })
    const client = createApiClient({
      fetch: fetchImpl,
      storage: createMemoryStorage({
        access_token: 'access-1',
        refresh_token: '',
        user: {
          id: 'u',
          username: 'm',
          display_name: 'Manager',
          role: 'manager',
          venue_id: 'venue-alpha',
        },
      }),
      reconnectDelayMs: 1,
    })
    const events: unknown[] = []
    const subscription = client.sse.subscribe({
      path: '/scenic/stream',
      onEvent: (event) => events.push(event),
    })

    await waitFor(() => expect(events).toHaveLength(1))
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2))
    expect(new Headers(calls[1]?.headers).get('Last-Event-ID')).toBe('7')
    expect(events[0]).toMatchObject({
      id: '7',
      event: 'ADVICE_READY',
      data: { state: 'READY', sequence: 7 },
    })
    subscription.close()
  })

  it('refreshes the authoritative snapshot when a sequence gap is detected', async () => {
    let attempts = 0
    const fetchImpl = vi.fn(async () => {
      attempts += 1
      if (attempts === 1) {
        return sseResponse([
          'id: 10\nevent: ADVICE_READY\ndata: {"state":"READY","sequence":10}\n\n',
        ])
      }
      return sseResponse([])
    })
    const snapshot = vi.fn(async () => ({ latest_sequence: 10 }))
    const onSnapshot = vi.fn()
    const states: string[] = []
    const client = createApiClient({
      fetch: fetchImpl,
      storage: createMemoryStorage({
        access_token: 'access-1',
        refresh_token: '',
        user: {
          id: 'u',
          username: 'm',
          display_name: 'Manager',
          role: 'manager',
          venue_id: 'venue-alpha',
        },
      }),
      reconnectDelayMs: 1,
    })

    const subscription = client.sse.subscribe({
      path: '/scenic/stream',
      lastEventId: '5',
      snapshot,
      onSnapshot,
      onStateChange: (state) => states.push(state),
      onEvent: vi.fn(),
    })

    await waitFor(() => expect(snapshot).toHaveBeenCalledTimes(1))
    expect(onSnapshot).toHaveBeenCalledWith({ latest_sequence: 10 })
    expect(states).toContain('FALLBACK')
    subscription.close()
  })
  it('pauses while the page is hidden and reconnects when visible again', async () => {
    const descriptor = Object.getOwnPropertyDescriptor(document, 'hidden')
    const fetchImpl = vi.fn(
      async (_input: RequestInfo | URL, _init?: RequestInit) => sseResponse([]),
    )
    const client = createApiClient({
      fetch: fetchImpl,
      storage: createMemoryStorage({
        access_token: 'access-1',
        refresh_token: '',
        user: {
          id: 'u',
          username: 'm',
          display_name: 'Manager',
          role: 'manager',
          venue_id: 'venue-alpha',
        },
      }),
      reconnectDelayMs: 1,
    })
    Object.defineProperty(document, 'hidden', {
      configurable: true,
      value: true,
    })
    const subscription = client.sse.subscribe({
      path: '/scenic/stream',
      lastEventId: '9',
      onEvent: vi.fn(),
    })
    try {
      await new Promise((resolve) => setTimeout(resolve, 20))
      expect(fetchImpl).not.toHaveBeenCalled()

      Object.defineProperty(document, 'hidden', {
        configurable: true,
        value: false,
      })
      expect(document.hidden).toBe(false)
      document.dispatchEvent(new window.Event('visibilitychange'))

      await waitFor(() => expect(fetchImpl).toHaveBeenCalled())
      expect(
        new Headers(fetchImpl.mock.calls[0]?.[1]?.headers).get('Last-Event-ID'),
      ).toBe('9')
    } finally {
      subscription.close()
      if (descriptor) {
        Object.defineProperty(document, 'hidden', descriptor)
      }
    }
  })
  it('falls back to a snapshot when a subscription cannot be established', async () => {
    let attempts = 0
    const fetchImpl = vi.fn(async () => {
      attempts += 1
      if (attempts === 1) throw new TypeError('network down')
      return sseResponse([])
    })
    const snapshot = vi.fn(async () => ({ latest_sequence: 10 }))
    const client = createApiClient({
      fetch: fetchImpl,
      storage: createMemoryStorage({
        access_token: 'access-1',
        refresh_token: '',
        user: {
          id: 'u',
          username: 'm',
          display_name: 'Manager',
          role: 'manager',
          venue_id: 'venue-alpha',
        },
      }),
      reconnectDelayMs: 1,
    })

    const subscription = client.sse.subscribe({
      path: '/scenic/stream',
      snapshot,
      onEvent: vi.fn(),
    })

    await waitFor(() => expect(snapshot).toHaveBeenCalledTimes(1))
    expect(await snapshot.mock.results[0]?.value).toEqual({ latest_sequence: 10 })
    subscription.close()
  })
})