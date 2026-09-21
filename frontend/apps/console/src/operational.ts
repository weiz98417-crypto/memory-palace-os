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


export interface TaskRecord {
  id: string
  business_id?: string
  description?: string
  status?: string
  assigned_user_id?: string
  assigned_agent?: string
  event_id?: string
  session_id?: string
  dependencies?: string[]
  attempts?: number
  max_attempts?: number
  block_reason?: string
  error?: string
  result?: unknown
  due_at?: number
  created_at?: number
  updated_at?: number
}

export interface AssigneeRecord {
  id: string
  display_name?: string
  username?: string
  role?: string
}

export interface ApprovalRecord {
  approval_id: string
  business_id?: string
  tool_name?: string
  args?: Record<string, unknown>
  status?: string
  event_id?: string
  task_id?: string
  session_id?: string
  requested_by?: string
  requested_at?: number
  reviewed_at?: number
  reviewed_by?: string
  comment?: string
  execution_status?: string
  execution_result?: Record<string, unknown>
  execution_error?: string
}

export async function loadTasks(client: RequestClient): Promise<TaskRecord[]> {
  const payload = await client.request<{ tasks?: TaskRecord[] }>('/admin/tasks?limit=200')
  return Array.isArray(payload.tasks) ? payload.tasks : []
}

export async function loadAssignees(client: RequestClient): Promise<AssigneeRecord[]> {
  const payload = await client.request<AssigneeRecord[] | { users?: AssigneeRecord[] }>('/admin/assignees')
  return Array.isArray(payload) ? payload : Array.isArray(payload.users) ? payload.users : []
}

export async function loadTask(client: RequestClient, taskId: string): Promise<{ task?: TaskRecord } & TaskRecord> {
  return client.request(`/admin/tasks/${encodeURIComponent(taskId)}`)
}

export async function createTask(client: RequestClient, body: Record<string, unknown>): Promise<unknown> {
  return client.request('/admin/tasks', { method: 'POST', json: body })
}

export async function decomposeTasks(client: RequestClient, body: Record<string, unknown>): Promise<unknown> {
  return client.request('/admin/tasks/decompose', { method: 'POST', json: body })
}

export async function assignTask(client: RequestClient, taskId: string, body: Record<string, unknown>): Promise<unknown> {
  return client.request(`/admin/tasks/${encodeURIComponent(taskId)}/assignment`, { method: 'PATCH', json: body })
}

export async function taskAction(
  client: RequestClient,
  taskId: string,
  action: 'start' | 'complete' | 'fail' | 'retry' | 'unblock',
  body?: Record<string, unknown>,
): Promise<unknown> {
  const options: Record<string, any> = { method: 'POST' }
  if (body && Object.keys(body).length) options.json = body
  return client.request(`/admin/tasks/${encodeURIComponent(taskId)}/${action}`, options)
}

export async function loadApprovals(client: RequestClient, status = 'PENDING'): Promise<ApprovalRecord[]> {
  return client.request<ApprovalRecord[]>(`/admin/approvals?status=${encodeURIComponent(status)}&limit=200`)
}

export async function loadApproval(client: RequestClient, approvalId: string): Promise<ApprovalRecord> {
  return client.request<ApprovalRecord>(`/admin/approvals/${encodeURIComponent(approvalId)}`)
}

export async function approveApproval(client: RequestClient, approvalId: string, comment = ''): Promise<unknown> {
  return client.request(`/admin/approvals/${encodeURIComponent(approvalId)}/approve`, {
    method: 'POST',
    json: { comment: comment || null },
  })
}

export async function rejectApproval(client: RequestClient, approvalId: string, comment = ''): Promise<unknown> {
  return client.request(`/admin/approvals/${encodeURIComponent(approvalId)}/reject`, {
    method: 'POST',
    json: { comment: comment || null },
  })
}

export async function requestControlledAction(client: RequestClient, body: Record<string, unknown>): Promise<unknown> {
  return client.request('/admin/action-requests', { method: 'POST', json: body })
}
