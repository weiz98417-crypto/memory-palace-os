export interface RequestClient {
  request<T>(path: string, options?: Record<string, any>): Promise<T>
}

export interface EventRecord {
  event_id: string
  business_id?: string
  raw_text?: string
  event_type?: string
  severity?: string
  status?: string
  lifecycle?: string
  assigned_to_name?: string
  reporter_name?: string
  created_at?: number
  updated_at?: number
  confirmed_at?: number
  dossier?: Record<string, any>
}

export interface SessionRecord {
  session_id: string
  user_id?: string
  stage?: string
  status?: string
  history_summary?: string
  active_agent?: string
  agent_name?: string
  current_intent?: string
  current_severity?: string
  created_at?: number
  updated_at?: number
}

export async function loadEvents(client: RequestClient): Promise<EventRecord[]> {
  const payload = await client.request<{ events?: EventRecord[] }>('/admin/events?limit=200')
  return Array.isArray(payload.events) ? payload.events : []
}

export async function loadEvent(client: RequestClient, eventId: string): Promise<EventRecord> {
  return client.request<EventRecord>(`/admin/events/${encodeURIComponent(eventId)}`)
}

export async function updateEvent(
  client: RequestClient,
  eventId: string,
  body: Record<string, unknown>,
): Promise<unknown> {
  return client.request(`/admin/events/${encodeURIComponent(eventId)}`, { method: 'PATCH', json: body })
}

export async function runEventWatcher(client: RequestClient, eventId: string): Promise<Record<string, any>> {
  return client.request<Record<string, any>>(`/admin/events/${encodeURIComponent(eventId)}/watcher-check`, { method: 'POST' })
}

export async function closeEvent(client: RequestClient, eventId: string): Promise<unknown> {
  return client.request(`/admin/events/${encodeURIComponent(eventId)}/close`, { method: 'POST' })
}

export async function retryEventExperienceCandidate(client: RequestClient, eventId: string): Promise<Record<string, any>> {
  return client.request<Record<string, any>>(
    `/admin/events/${encodeURIComponent(eventId)}/experience-candidate/retry`,
    { method: 'POST' },
  )
}

export async function loadSessions(client: RequestClient): Promise<SessionRecord[]> {
  return client.request<SessionRecord[]>('/sessions/?limit=200')
}

export async function closeSession(client: RequestClient, sessionId: string): Promise<unknown> {
  return client.request(`/sessions/${encodeURIComponent(sessionId)}`, { method: 'DELETE' })
}

export function eventLabel(event: EventRecord): string {
  return event.business_id || event.event_id
}

export function eventTimestamp(event: EventRecord): number {
  return Number(event.updated_at || event.created_at || event.confirmed_at || 0)
}

export function sessionLabel(session: SessionRecord): string {
  return session.history_summary || session.current_intent || session.session_id
}
