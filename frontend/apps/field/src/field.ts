export interface RequestClient {
  request<T>(path: string, options?: Record<string, any>): Promise<T>
}

export interface AssistantSession {
  session_id: string
  user_id?: string
  display_name?: string
  role?: string
  venue_id?: string
  channel?: string
  external_conversation_id?: string
  stage?: string
  last_message?: string | null
  last_status?: string | null
  message_count?: number
  created_at?: number
  updated_at?: number
}

export interface AssistantConversationMessage {
  id: string
  message_id?: string
  role: 'user' | 'assistant' | string
  content: string
  status?: string
  created_at?: number
  error?: string | null
  attachments?: Array<{ id?: string; filename?: string; mime_type?: string; external_ref?: string; thumbnail_url?: string; size_bytes?: number }>
  business_cards?: Array<Record<string, unknown>>
}

export interface FieldTask {
  id: string
  business_id?: string
  description?: string
  status?: string
  event_id?: string
  session_id?: string
  assigned_user_id?: string
  assigned_agent?: string
  dependencies?: string[]
  attempts?: number
  max_attempts?: number
  block_reason?: string
  result?: Record<string, unknown>
  due_at?: number
  created_at?: number
  updated_at?: number
}

export interface FieldEvent {
  event_id: string
  business_id?: string
  raw_text?: string
  event_type?: string
  severity?: string
  status?: string
  assigned_to?: string
  from_user?: string
  created_at?: number
  updated_at?: number
  dossier?: Record<string, unknown>
  advice?: Record<string, unknown>
  tasks?: FieldTask[]
}

export interface AssistantWork {
  tasks: FieldTask[]
  events: FieldEvent[]
}

export interface AssistantExperienceHome {
  expert?: Record<string, any> | null
  interviews?: Array<Record<string, any>>
  cards?: Array<Record<string, any>>
}

export interface AssistantInterview {
  id: string
  title?: string
  status?: string
  expert_name?: string
  progress?: { answered?: number; total?: number; percent?: number }
  turns?: Array<{ turn_number?: number; question_text?: string; answer_text?: string; source_excerpt?: string }>
  authorization_scopes?: Array<Record<string, unknown>>
}

export interface ExperienceCardUpdate {
  title?: string
  applicable_context?: string
  signals?: string[]
  decision_rule?: string
  recommended_actions?: string[]
  rationale?: string
  prohibitions?: string[]
  exceptions?: string[]
  source_excerpts?: string[]
  change_note: string
}

export async function loadAssistantSessions(client: RequestClient): Promise<AssistantSession[]> {
  const payload = await client.request<{ sessions?: AssistantSession[] }>('/assistant/sessions?limit=100')
  return Array.isArray(payload.sessions) ? payload.sessions : []
}

export async function loadAssistantMessages(client: RequestClient, sessionId: string): Promise<{ session?: AssistantSession; messages: AssistantConversationMessage[] }> {
  const payload = await client.request<{ session?: AssistantSession; messages?: AssistantConversationMessage[] }>(
    `/assistant/sessions/${encodeURIComponent(sessionId)}/messages?limit=200`,
  )
  return { session: payload.session, messages: Array.isArray(payload.messages) ? payload.messages : [] }
}

export async function sendAssistantMessage(
  client: RequestClient,
  body: { content: string; external_message_id: string; external_conversation_id?: string | null; attachments?: Array<Record<string, unknown>>; metadata?: Record<string, unknown> | null },
): Promise<Record<string, any>> {
  return client.request('/assistant/messages', {
    method: 'POST',
    json: { ...body, channel: 'WEB' },
  })
}

export async function retryAssistantMessage(client: RequestClient, messageId: string): Promise<Record<string, any>> {
  return client.request(`/assistant/messages/${encodeURIComponent(messageId)}/retry`, { method: 'POST' })
}

export async function uploadAssistantAttachment(client: RequestClient, file: File): Promise<Record<string, any>> {
  const form = new FormData()
  form.append('file', file)
  return client.request('/assistant/attachments', { method: 'POST', body: form })
}

export async function loadAssistantWork(client: RequestClient): Promise<AssistantWork> {
  const payload = await client.request<{ tasks?: FieldTask[]; events?: FieldEvent[] }>('/assistant/work?limit=100')
  return {
    tasks: Array.isArray(payload.tasks) ? payload.tasks : [],
    events: Array.isArray(payload.events) ? payload.events : [],
  }
}

export async function loadAssistantTask(client: RequestClient, taskId: string): Promise<FieldTask> {
  const payload = await client.request<{ task: FieldTask }>(`/assistant/work/tasks/${encodeURIComponent(taskId)}`)
  return payload.task
}

export async function loadAssistantEvent(client: RequestClient, eventId: string): Promise<FieldEvent> {
  const payload = await client.request<{ event: FieldEvent }>(`/assistant/work/events/${encodeURIComponent(eventId)}`)
  return payload.event
}

export async function loadAssistantSop(client: RequestClient, sopId: number | string, version = ''): Promise<Record<string, any>> {
  const suffix = version ? `?version=${encodeURIComponent(version)}` : ''
  const payload = await client.request<{ sop: Record<string, any> }>(`/assistant/knowledge/sops/${encodeURIComponent(String(sopId))}${suffix}`)
  return payload.sop
}

export async function startAssistantTask(client: RequestClient, taskId: string): Promise<Record<string, any>> {
  return client.request(`/assistant/work/tasks/${encodeURIComponent(taskId)}/start`, { method: 'POST' })
}

export async function completeAssistantTask(
  client: RequestClient,
  taskId: string,
  summary: string,
  result: Record<string, unknown> = {},
): Promise<Record<string, any>> {
  return client.request(`/assistant/work/tasks/${encodeURIComponent(taskId)}/complete`, {
    method: 'POST',
    json: { summary, result },
  })
}

export async function blockAssistantTask(client: RequestClient, taskId: string, reason: string): Promise<Record<string, any>> {
  return client.request(`/assistant/work/tasks/${encodeURIComponent(taskId)}/block`, {
    method: 'POST',
    json: { reason },
  })
}

export async function loadAssistantExperience(client: RequestClient): Promise<AssistantExperienceHome> {
  return client.request<AssistantExperienceHome>('/assistant/experience')
}

export async function loadAssistantInterview(client: RequestClient, interviewId: string): Promise<AssistantInterview> {
  const payload = await client.request<{ interview: AssistantInterview }>(
    `/assistant/experience/interviews/${encodeURIComponent(interviewId)}`,
  )
  return payload.interview
}

export async function acceptAssistantInterview(client: RequestClient, interviewId: string): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/interviews/${encodeURIComponent(interviewId)}/accept`, { method: 'POST' })
}

export async function answerAssistantInterview(
  client: RequestClient,
  interviewId: string,
  answer: string,
  sourceExcerpt = '',
): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/interviews/${encodeURIComponent(interviewId)}/answers`, {
    method: 'POST',
    json: { answer, source_excerpt: sourceExcerpt || null },
  })
}

export async function pauseAssistantInterview(client: RequestClient, interviewId: string): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/interviews/${encodeURIComponent(interviewId)}/pause`, { method: 'POST' })
}

export async function resumeAssistantInterview(client: RequestClient, interviewId: string): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/interviews/${encodeURIComponent(interviewId)}/resume`, { method: 'POST' })
}

export async function completeAssistantInterview(client: RequestClient, interviewId: string): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/interviews/${encodeURIComponent(interviewId)}/complete`, { method: 'POST' })
}

export async function reviseAssistantExperienceCard(
  client: RequestClient,
  cardId: string,
  body: ExperienceCardUpdate,
): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/cards/${encodeURIComponent(cardId)}`, { method: 'PUT', json: body })
}

export async function confirmAssistantExperienceCard(client: RequestClient, cardId: string): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/cards/${encodeURIComponent(cardId)}/confirm`, { method: 'POST' })
}

export async function recordAssistantExperienceFeedback(
  client: RequestClient,
  cardId: string,
  feedback: 'HELPFUL' | 'NOT_APPLICABLE' | 'NEEDS_EXPERT',
  note = '',
  sessionId = '',
): Promise<Record<string, any>> {
  return client.request(`/assistant/experience/cards/${encodeURIComponent(cardId)}/feedback`, {
    method: 'POST',
    json: { feedback, note: note || null, session_id: sessionId || null },
  })
}

export async function searchAssistantExperience(
  client: RequestClient,
  query: string,
  sessionId = '',
  topK = 5,
  threshold = 0,
): Promise<Array<Record<string, any>>> {
  const payload = await client.request<{ results?: Array<Record<string, any>> }>('/assistant/experience/search', {
    method: 'POST',
    json: { query, session_id: sessionId || null, top_k: topK, threshold },
  })
  return Array.isArray(payload.results) ? payload.results : []
}
