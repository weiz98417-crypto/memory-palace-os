import type { StateTone } from '@memory-palace/domain-ui'

export interface RequestClient {
  request<T>(path: string, options?: Record<string, any>): Promise<T>
}

export interface IntegrationClient extends RequestClient {
  auth: {
    read(): unknown
    login(username: string, password: string): Promise<any>
    clear(): void
  }
}

export interface IntegrationIdentity {
  user_id: string
  username?: string
  display_name?: string
  role?: string
  department?: string
  job_title?: string
  wecom_binding_status?: string
}

export interface IntegrationSession {
  session_id: string
  user_id?: string
  status?: string
  updated_at?: number
  created_at?: number
  last_message?: string
}

export interface IntegrationMessage {
  message_id?: string
  session_id?: string
  role?: string
  content?: string
  text?: string
  status?: string
  created_at?: number
  business_cards?: unknown[]
  attachments?: unknown[]
}

export interface OutboxItem {
  id?: string
  tool_label?: string
  message?: string
  status?: string
  delivery_status?: string
  status_summary?: string
  review_comment?: string
  execution_error?: string
  delivery_error?: string
  updated_at?: number
  created_at?: number
}

export function deliveryStatusLabel(value: string): string {
  const labels: Record<string, string> = {
    DELIVERED: '已送达内部系统接入环境',
    FAILED: '送达失败',
    SENDING: '正在送达',
    PENDING: '等待送达',
    RECORDED: '已写入出站账本',
  }
  return labels[String(value || '').toUpperCase()] || '尚无接入环境送达记录'
}

export function toneForStatus(value: string): StateTone {
  const status = String(value || '').toUpperCase()
  if (['READY', 'SENT', 'DELIVERED', 'SUCCEEDED', 'DONE', 'RECORDED', 'ACTIVE'].includes(status)) return 'success'
  if (['FAILED', 'ERROR', 'DEAD_LETTERED', 'REJECTED'].includes(status)) return 'danger'
  if (['PENDING', 'RUNNING', 'SENDING', 'RETRY_REQUIRED', 'PAUSED'].includes(status)) return 'warning'
  return 'neutral'
}

export async function loadIdentities(client: RequestClient): Promise<IntegrationIdentity[]> {
  const payload = await client.request<{ identities?: IntegrationIdentity[] }>('/channels/simulator-identities')
  return Array.isArray(payload.identities) ? payload.identities : []
}

export async function loadSessions(client: RequestClient, userId: string): Promise<IntegrationSession[]> {
  const query = new URLSearchParams({ channel: 'WECOM_SIMULATOR', acting_user_id: userId, limit: '100' })
  const payload = await client.request<{ sessions?: IntegrationSession[] }>(`/assistant/sessions?${query}`)
  return Array.isArray(payload.sessions) ? payload.sessions : []
}

export async function loadMessages(client: RequestClient, sessionId: string, userId: string): Promise<IntegrationMessage[]> {
  if (!sessionId) return []
  const query = new URLSearchParams({ acting_user_id: userId, limit: '200' })
  const payload = await client.request<{ messages?: IntegrationMessage[] }>(
    `/assistant/sessions/${encodeURIComponent(sessionId)}/messages?${query}`,
  )
  return Array.isArray(payload.messages) ? payload.messages : []
}

export async function sendSimulatorMessage(
  client: RequestClient,
  input: {
    user_id: string
    content: string
    external_message_id?: string
    external_conversation_id?: string
    attachments?: unknown[]
    metadata?: Record<string, unknown>
  },
): Promise<unknown> {
  return client.request('/channels/simulator/messages', {
    method: 'POST',
    json: {
      user_id: input.user_id,
      content: input.content,
      external_message_id: input.external_message_id,
      external_conversation_id: input.external_conversation_id,
      attachments: input.attachments,
      metadata: input.metadata,
    },
  })
}

export async function uploadSimulatorAttachment(
  client: RequestClient,
  userId: string,
  file: File,
): Promise<Record<string, any> | null> {
  const body = new FormData()
  body.append('user_id', userId)
  body.append('file', file)
  const payload = await client.request<{ attachment?: Record<string, any> }>(
    '/channels/simulator/attachments',
    { method: 'POST', body },
  )
  return payload.attachment || null
}

export async function loadOutbox(client: RequestClient, sessionId: string, userId: string): Promise<OutboxItem[]> {
  const query = new URLSearchParams({ user_id: userId })
  const payload = await client.request<{ items?: OutboxItem[]; outbox?: OutboxItem[] }>(
    `/channels/simulator/sessions/${encodeURIComponent(sessionId)}/outbox?${query}`,
    { method: 'GET' },
  )
  return Array.isArray(payload.items) ? payload.items : Array.isArray(payload.outbox) ? payload.outbox : []
}

export async function retrySimulatorMessage(client: RequestClient, messageId: string, userId: string): Promise<unknown> {
  const query = new URLSearchParams({ acting_user_id: userId })
  return client.request(`/assistant/messages/${encodeURIComponent(messageId)}/retry?${query}`, { method: 'POST' })
}

export async function loadExperienceHome(client: RequestClient, userId: string): Promise<Record<string, any>> {
  const query = new URLSearchParams({ acting_user_id: userId })
  return client.request<Record<string, any>>(`/assistant/experience?${query}`)
}

export async function experienceInterviewAction(
  client: RequestClient,
  interviewId: string,
  action: 'accept' | 'pause' | 'resume' | 'complete',
  userId: string,
): Promise<unknown> {
  const query = new URLSearchParams({ acting_user_id: userId })
  return client.request(`/assistant/experience/interviews/${encodeURIComponent(interviewId)}/${action}?${query}`, { method: 'POST' })
}

export async function confirmExperienceCard(
  client: RequestClient,
  cardId: string,
  userId: string,
): Promise<unknown> {
  const query = new URLSearchParams({ acting_user_id: userId })
  return client.request(`/assistant/experience/cards/${encodeURIComponent(cardId)}/confirm?${query}`, { method: 'POST' })
}
