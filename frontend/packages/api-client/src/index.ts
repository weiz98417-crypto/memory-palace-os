import { createParser, type EventSourceMessage } from 'eventsource-parser'
import type { components } from './generated/openapi'

const API_BASE = '/api/v1'
const STORAGE_KEYS = {
  accessToken: 'mp_access_token',
  refreshToken: 'mp_refresh_token',
  user: 'mp_user',
} as const

function storageKeys(prefix: string) {
  return {
    accessToken: `${prefix}access_token`,
    refreshToken: `${prefix}refresh_token`,
    user: `${prefix}user`,
  } as const
}

export type SessionUser = components['schemas']['UserIdentity']
export type SessionPayload = Pick<
  components['schemas']['TokenResponse'],
  'access_token' | 'refresh_token' | 'user'
>

export interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

export interface SseEvent {
  id: string
  event: string
  data: unknown
}

export interface SseSubscription {
  close(): void
  done: Promise<void>
}

export interface ApiClientOptions {
  baseUrl?: string
  storageKeyPrefix?: string
  fetch?: typeof fetch
  storage?: StorageLike
  idempotencyKey?: () => string
  reconnectDelayMs?: number
  maxReconnectDelayMs?: number
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  json?: unknown
  body?: BodyInit | null
  skipAuth?: boolean
  skipRefresh?: boolean
  idempotencyKey?: string | false
  responseType?: 'json' | 'text' | 'blob'
  tenantId?: string
}

export interface SseSubscribeOptions {
  path: string
  onEvent(event: SseEvent): void
  onStateChange?(state: 'CONNECTING' | 'CONNECTED' | 'RECONNECTING' | 'FALLBACK'): void
  snapshot?: () => Promise<unknown>
  onSnapshot?(snapshot: unknown): void
  lastEventId?: string
  signal?: AbortSignal
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly traceId?: string
  readonly retryable: boolean
  readonly action?: unknown
  readonly userMessage: string

  constructor(status: number, payload: unknown) {
    const detail = detailFrom(payload)
    const detailObject = typeof detail === 'object' ? detail : undefined
    const serverMessage =
      typeof detail === 'string'
        ? detail
        : typeof detailObject?.message === 'string'
          ? detailObject.message
          : ''
    const message = serverMessage || defaultMessage(status)
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = typeof detailObject?.code === 'string' ? detailObject.code : undefined
    this.traceId =
      typeof detailObject?.trace_id === 'string' ? detailObject.trace_id : undefined
    this.retryable =
      Boolean(detailObject?.retryable) || status >= 500 || status === 429
    this.action = detailObject?.action
    this.userMessage = message
  }
}

export function createMemoryStorage(seed?: Partial<SessionPayload>, storageKeyPrefix = 'mp_'): StorageLike {
  const values = new Map<string, string>()
  const keys = storageKeys(storageKeyPrefix)
  if (seed?.access_token) values.set(keys.accessToken, seed.access_token)
  if (seed?.refresh_token) values.set(keys.refreshToken, seed.refresh_token)
  if (seed?.user) values.set(keys.user, JSON.stringify(seed.user))
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  }
}

export function createApiClient(options: ApiClientOptions = {}) {
  const baseUrl = options.baseUrl ?? API_BASE
  const fetchImpl = options.fetch ?? globalThis.fetch.bind(globalThis)
  const storage = options.storage ?? browserStorage()
  const keys = storageKeys(options.storageKeyPrefix ?? 'mp_')
  const reconnectDelayMs = options.reconnectDelayMs ?? 500
  const maxReconnectDelayMs = options.maxReconnectDelayMs ?? 10_000
  let refreshPromise: Promise<boolean> | null = null

  function readSession(): SessionPayload | null {
    const accessToken = storage.getItem(keys.accessToken)
    const refreshToken = storage.getItem(keys.refreshToken)
    const rawUser = storage.getItem(keys.user)
    if (!accessToken || !rawUser) return null
    try {
      return {
        access_token: accessToken,
        refresh_token: refreshToken ?? '',
        user: JSON.parse(rawUser) as SessionUser,
      }
    } catch {
      clear()
      return null
    }
  }

  function setSession(payload: SessionPayload): SessionUser {
    storage.setItem(keys.accessToken, payload.access_token ?? '')
    storage.setItem(keys.refreshToken, payload.refresh_token ?? '')
    storage.setItem(keys.user, JSON.stringify(payload.user ?? null))
    return payload.user
  }

  function clear() {
    storage.removeItem(keys.accessToken)
    storage.removeItem(keys.refreshToken)
    storage.removeItem(keys.user)
  }

  async function refresh(): Promise<boolean> {
    const session = readSession()
    if (!session?.refresh_token) return false
    if (refreshPromise) return refreshPromise
    const refreshToken = session.refresh_token
    refreshPromise = (async () => {
      try {
        const response = await fetchImpl(resolveUrl(baseUrl, '/auth/refresh'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
        if (!response.ok) {
          if (readSession()?.refresh_token === refreshToken) clear()
          return false
        }
        const payload = (await parseResponse(response, 'json')) as SessionPayload
        if (readSession()?.refresh_token === refreshToken) setSession(payload)
        return true
      } catch {
        return false
      }
    })().finally(() => {
      refreshPromise = null
    })
    return refreshPromise
  }

  async function request<T = unknown>(
    path: string,
    requestOptions: RequestOptions = {},
  ): Promise<T> {
    const {
      json,
      skipAuth = false,
      skipRefresh = false,
      idempotencyKey,
      responseType = 'json',
      tenantId,
      ...init
    } = requestOptions
    const method = String(init.method ?? 'GET').toUpperCase()
    const headers = new Headers(init.headers)
    let body = init.body

    if (json !== undefined) {
      headers.set('Content-Type', 'application/json')
      body = JSON.stringify(json)
    }

    const session = readSession()
    if (!skipAuth && session?.access_token) {
      headers.set('Authorization', `Bearer ${session.access_token}`)
    }
    const resolvedTenant = tenantId ?? session?.user.venue_id
    if (resolvedTenant) headers.set('X-Venue-ID', resolvedTenant)

    const resolvedIdempotencyKey =
      idempotencyKey === false
        ? false
        : idempotencyKey || options.idempotencyKey?.() || randomKey()
    if (
      isMutation(method) &&
      resolvedIdempotencyKey &&
      !headers.has('Idempotency-Key')
    ) {
      headers.set('Idempotency-Key', resolvedIdempotencyKey)
    }

    const response = await fetchImpl(resolveUrl(baseUrl, path), {
      ...init,
      method,
      headers,
      body,
      credentials: init.credentials ?? 'same-origin',
    })

    if (response.status === 401 && !skipAuth && !skipRefresh) {
      const refreshed = await refresh()
      if (refreshed) {
        return request<T>(path, {
          ...requestOptions,
          idempotencyKey: resolvedIdempotencyKey,
          skipRefresh: true,
        })
      }
    }

    if (!response.ok) throw new ApiError(response.status, await parseResponse(response, 'json'))
    return (await parseResponse(response, responseType)) as T
  }

  return {
    request,
    auth: {
      read: () => readSession()?.user ?? null,
      set: setSession,
      clear,
      async login(username: string, password: string): Promise<SessionUser> {
        const payload = await request<SessionPayload>('/auth/login', {
          method: 'POST',
          json: { username, password },
          skipAuth: true,
        })
        return setSession(payload)
      },
      async refresh(): Promise<boolean> {
        return refresh()
      },
    },
    sse: {
      subscribe(subscribeOptions: SseSubscribeOptions): SseSubscription {
        const controller = new AbortController()
        const signal = mergeSignals(controller.signal, subscribeOptions.signal)
        const seen = new Set<string>()
        let lastEventId = subscribeOptions.lastEventId ?? ''
        let lastSequence = sequenceFromId(lastEventId)
        let closed = false

        const done = (async () => {
          let attempt = 0
          while (!signal.aborted) {
            await waitUntilVisible(signal)
            if (signal.aborted) break
            subscribeOptions.onStateChange?.(attempt === 0 ? 'CONNECTING' : 'RECONNECTING')
            const connectionController = new AbortController()
            const connectionSignal = mergeSignals(signal, connectionController.signal)
            const stopVisibilityWatch = watchVisibility(connectionController)
            try {
              const session = readSession()
              const headers = new Headers({ Accept: 'text/event-stream' })
              if (session?.access_token) headers.set('Authorization', `Bearer ${session.access_token}`)
              if (session?.user.venue_id) headers.set('X-Venue-ID', session.user.venue_id)
              if (lastEventId) headers.set('Last-Event-ID', lastEventId)

              const response = await fetchImpl(resolveUrl(baseUrl, subscribeOptions.path), {
                method: 'GET',
                headers,
                signal: connectionSignal,
                credentials: 'same-origin',
              })
              if (!response.ok || !response.body) {
                throw new ApiError(response.status, await safeJson(response))
              }

              subscribeOptions.onStateChange?.('CONNECTED')
              attempt = 0
              const pending: Promise<void>[] = []
              const parser = createParser({
                onEvent(message: EventSourceMessage) {
                  pending.push(
                    handleSseMessage(message, {
                      seen,
                      getLastSequence: () => lastSequence,
                      setLastSequence: (sequence) => {
                        lastSequence = sequence
                      },
                      setLastEventId: (id) => {
                        lastEventId = id
                      },
                      options: subscribeOptions,
                    }),
                  )
                },
              })
              const reader = response.body.getReader()
              const decoder = new TextDecoder()
              while (!connectionSignal.aborted) {
                const { done: streamDone, value } = await reader.read()
                if (streamDone) break
                parser.feed(decoder.decode(value, { stream: true }))
                await Promise.all(pending.splice(0))
              }
              await Promise.all(pending.splice(0))
              parser.reset({ consume: true })
              await delay(reconnectDelayMs, signal)
            } catch {
              if (signal.aborted || closed) break
              if (documentHidden()) continue
              subscribeOptions.onStateChange?.('FALLBACK')
              await recoverSnapshot(subscribeOptions)
              attempt += 1
              await delay(
                Math.min(maxReconnectDelayMs, reconnectDelayMs * 2 ** (attempt - 1)),
                signal,
              )
            } finally {
              stopVisibilityWatch()
            }
          }
        })()
          .catch(() => undefined)
          .finally(() => {
            closed = true
          })

        return {
          close() {
            closed = true
            controller.abort()
          },
          done,
        }
      },
    },
  }
}

function browserStorage(): StorageLike {
  if (typeof sessionStorage !== 'undefined') return sessionStorage
  return createMemoryStorage()
}

function isMutation(method: string) {
  return ['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)
}

function randomKey() {
  const randomUUID = globalThis.crypto?.randomUUID?.bind(globalThis.crypto)
  if (randomUUID) return `mp-${randomUUID()}`
  return `mp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
}

function resolveUrl(baseUrl: string, path: string) {
  if (/^https?:\/\//i.test(path)) return path
  return `${baseUrl.replace(/\/$/, '')}/${path.replace(/^\//, '')}`
}

async function parseResponse(response: Response, responseType: 'json' | 'text' | 'blob') {
  if (response.status === 204) return null
  if (responseType === 'blob') return response.blob()
  const contentType = response.headers.get('content-type') ?? ''
  if (responseType === 'text' || !contentType.includes('application/json')) {
    return response.text()
  }
  return response.json().catch(() => ({}))
}

async function safeJson(response: Response) {
  try {
    return await response.clone().json()
  } catch {
    return {}
  }
}

function detailFrom(
  payload: unknown,
): string | Record<string, unknown> | undefined {
  if (!payload || typeof payload !== 'object') return undefined
  const value = payload as Record<string, unknown>
  const detail = value.detail ?? value
  if (typeof detail === 'string' || (detail && typeof detail === 'object')) {
    return detail as string | Record<string, unknown>
  }
  return undefined
}

function defaultMessage(status: number) {
  const messages: Record<number, string> = {
    400: '提交内容未通过校验，请检查后重试。',
    401: '登录状态已失效，请重新登录。',
    403: '当前账号没有执行此操作的权限。',
    404: '请求的资源不存在。',
    409: '当前状态与提交内容冲突，请刷新后重试。',
    422: '提交内容不完整，请检查必填信息。',
    429: '请求较多，系统正在保护服务，请稍后重试。',
    500: '服务处理失败，系统没有生成替代结果。',
    503: '服务暂时不可用，请稍后重试。',
  }
  return messages[status] ?? `请求失败（${status}）`
}

function documentHidden() {
  return typeof document !== 'undefined' && document.hidden
}

function waitUntilVisible(signal: AbortSignal): Promise<void> {
  if (!documentHidden()) return Promise.resolve()
  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      document.removeEventListener('visibilitychange', onVisible)
      clearInterval(poll)
      resolve()
    }
    const onVisible = () => {
      if (!documentHidden()) finish()
    }
    const poll = setInterval(onVisible, 100)
    document.addEventListener('visibilitychange', onVisible)
    signal.addEventListener('abort', finish, { once: true })
  })
}

function watchVisibility(controller: AbortController): () => void {
  if (typeof document === 'undefined') return () => undefined
  const onVisibilityChange = () => {
    if (document.hidden) controller.abort()
  }
  document.addEventListener('visibilitychange', onVisibilityChange)
  return () => document.removeEventListener('visibilitychange', onVisibilityChange)
}

async function recoverSnapshot(options: SseSubscribeOptions) {
  try {
    const snapshot = await options.snapshot?.()
    if (snapshot !== undefined) options.onSnapshot?.(snapshot)
  } catch {
    // Snapshot recovery is best effort; the next reconnect still proceeds.
  }
}

async function handleSseMessage(
  message: EventSourceMessage,
  state: {
    seen: Set<string>
    getLastSequence(): number | null
    setLastSequence(sequence: number): void
    setLastEventId(id: string): void
    options: SseSubscribeOptions
  },
) {
  const sequence = sequenceFromId(message.id)
  const lastSequence = state.getLastSequence()
  if (
    sequence !== null &&
    lastSequence !== null &&
    sequence > lastSequence + 1
  ) {
    state.options.onStateChange?.('FALLBACK')
    await recoverSnapshot(state.options)
  }
  if (message.id) {
    if (state.seen.has(message.id)) return
    if (
      sequence !== null &&
      lastSequence !== null &&
      sequence <= lastSequence
    ) {
      state.seen.add(message.id)
      return
    }
    state.seen.add(message.id)
    state.setLastEventId(message.id)
  }
  if (sequence !== null) state.setLastSequence(sequence)
  state.options.onEvent({
    id: message.id ?? '',
    event: message.event ?? 'message',
    data: parseEventData(message.data),
  })
}

function sequenceFromId(id?: string): number | null {
  if (!id || !/^\d+$/.test(id)) return null
  const sequence = Number(id)
  return Number.isSafeInteger(sequence) ? sequence : null
}

function parseEventData(data: string): unknown {
  if (!data) return null
  try {
    return JSON.parse(data)
  } catch {
    return data
  }
}

function mergeSignals(first: AbortSignal, second?: AbortSignal): AbortSignal {
  if (!second) return first
  const controller = new AbortController()
  const abort = () => controller.abort()
  if (first.aborted || second.aborted) abort()
  first.addEventListener('abort', abort, { once: true })
  second.addEventListener('abort', abort, { once: true })
  return controller.signal
}

function delay(ms: number, signal: AbortSignal) {
  if (signal.aborted) return Promise.resolve()
  return new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer)
        resolve()
      },
      { once: true },
    )
  })
}