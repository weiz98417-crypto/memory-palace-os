import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, createApiClient, createMemoryStorage } from './index'

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function session(venueId = 'venue-alpha', accessToken = 'access-1') {
  return {
    access_token: accessToken,
    refresh_token: 'refresh-1',
    user: {
      id: 'user-1',
      username: 'manager',
      display_name: 'Manager',
      role: 'manager',
      venue_id: venueId,
    },
  }
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('api-client session seam', () => {
  it('reads the current user without exposing tokens to views', () => {
    const client = createApiClient({ storage: createMemoryStorage(session()) })
    expect(client.auth.read()).toEqual(session().user)
    expect(client.auth.read()).not.toHaveProperty('access_token')
  })

  it('isolates sessions by storage key prefix', () => {
    const storage = createMemoryStorage(session(), 'mp_operations_')
    const client = createApiClient({ storage, storageKeyPrefix: 'mp_operations_' })

    expect(client.auth.read()).toEqual(session().user)
    client.auth.clear()
    expect(storage.getItem('mp_operations_user')).toBeNull()
  })
})

describe('api-client request behaviour', () => {
  it('adds auth, tenant, and idempotency headers and returns JSON', async () => {
    const fetchImpl = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ ok: true }))
    const client = createApiClient({
      fetch: fetchImpl,
      storage: createMemoryStorage(session()),
      idempotencyKey: () => 'idem-1',
    })

    const result = await client.request<{ ok: boolean }>('/scenic/commands', {
      method: 'POST',
      json: { kind: 'RETRIEVE_SOP' },
    })

    expect(result).toEqual({ ok: true })
    const [, init] = fetchImpl.mock.calls[0]
    const headers = new Headers(init?.headers)
    expect(headers.get('Authorization')).toBe('Bearer access-1')
    expect(headers.get('X-Venue-ID')).toBe('venue-alpha')
    expect(headers.get('Idempotency-Key')).toBe('idem-1')
    expect(init?.body).toBe(JSON.stringify({ kind: 'RETRIEVE_SOP' }))
  })

  it('deduplicates refresh and retries a 401 only once', async () => {
    let refreshed = false
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/auth/refresh')) {
        refreshed = true
        return jsonResponse(session('venue-alpha', 'access-2'))
      }
      const headers = new Headers(init?.headers)
      if (headers.get('Authorization') === 'Bearer access-1') {
        return jsonResponse({ detail: { code: 'EXPIRED' } }, 401)
      }
      return jsonResponse({ ok: true })
    })
    const client = createApiClient({
      fetch: fetchImpl,
      storage: createMemoryStorage(session()),
    })

    const [first, second] = await Promise.all([
      client.request('/one'),
      client.request('/two'),
    ])

    expect(first).toEqual({ ok: true })
    expect(second).toEqual({ ok: true })
    expect(refreshed).toBe(true)
    expect(fetchImpl.mock.calls.filter(([input]) => String(input).endsWith('/auth/refresh'))).toHaveLength(1)
  })

  it('preserves a generated idempotency key across a refresh retry', async () => {
    const idempotencyKeys: Array<string | null> = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/auth/refresh')) {
        return jsonResponse(session('venue-alpha', 'access-2'))
      }
      const headers = new Headers(init?.headers)
      idempotencyKeys.push(headers.get('Idempotency-Key'))
      if (headers.get('Authorization') === 'Bearer access-1') {
        return jsonResponse({ detail: { code: 'EXPIRED' } }, 401)
      }
      return jsonResponse({ ok: true })
    })
    const client = createApiClient({
      fetch: fetchImpl,
      storage: createMemoryStorage(session()),
      idempotencyKey: (() => {
        let sequence = 0
        return () => `idem-${++sequence}`
      })(),
    })

    await client.request('/commands', { method: 'POST', json: { kind: 'X' } })

    expect(idempotencyKeys).toEqual(['idem-1', 'idem-1'])
  })
  it('normalizes server errors for UI consumption', async () => {
    const client = createApiClient({
      fetch: vi.fn(async () =>
        jsonResponse(
          {
            detail: {
              code: 'SCENIC_CONFLICT',
              message: 'concurrent update',
              trace_id: 'trace-1',
              retryable: true,
            },
          },
          409,
        ),
      ),
      storage: createMemoryStorage(session()),
    })

    await expect(client.request('/conflict')).rejects.toMatchObject({
      status: 409,
      code: 'SCENIC_CONFLICT',
      traceId: 'trace-1',
      retryable: true,
      userMessage: 'concurrent update',
    })
    await expect(client.request('/conflict')).rejects.toBeInstanceOf(ApiError)
  })
})