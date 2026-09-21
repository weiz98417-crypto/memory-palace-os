import type { RequestClient } from './operational'

export interface KnowledgeRecord {
  id: string
  title: string
  content: string
  category?: string
  source_type?: string
  source_id?: string | null
  version?: number | string
  tags?: string[]
  status?: string
  created_at?: number
  updated_at?: number
}

export interface KnowledgeUpsert {
  title: string
  content: string
  category: string
  tags: string[]
  source_type?: 'MANUAL' | 'EVENT' | 'SOP' | 'IMPORT'
  source_id?: string | null
}

export interface KnowledgeSearchResult {
  id?: string
  document?: string
  content?: string
  similarity?: number
  score?: number
  metadata?: {
    title?: string
    source_type?: string
    version?: number | string
    [key: string]: unknown
  }
}

export async function loadKnowledge(client: RequestClient, query = ''): Promise<KnowledgeRecord[]> {
  const suffix = query ? `&query=${encodeURIComponent(query)}` : ''
  const payload = await client.request<{ knowledge?: KnowledgeRecord[] }>(`/admin/knowledge?limit=200${suffix}`)
  return Array.isArray(payload.knowledge) ? payload.knowledge : []
}

export async function loadKnowledgeEntry(client: RequestClient, knowledgeId: string): Promise<KnowledgeRecord> {
  const payload = await client.request<{ knowledge: KnowledgeRecord }>(
    `/admin/knowledge/${encodeURIComponent(knowledgeId)}`,
  )
  return payload.knowledge
}

export async function createKnowledge(client: RequestClient, body: KnowledgeUpsert): Promise<unknown> {
  return client.request('/admin/knowledge', { method: 'POST', json: body })
}

export async function updateKnowledge(
  client: RequestClient,
  knowledgeId: string,
  body: KnowledgeUpsert,
): Promise<unknown> {
  return client.request(`/admin/knowledge/${encodeURIComponent(knowledgeId)}`, { method: 'PUT', json: body })
}

export async function deleteKnowledge(client: RequestClient, knowledgeId: string): Promise<unknown> {
  return client.request(`/admin/knowledge/${encodeURIComponent(knowledgeId)}`, { method: 'DELETE' })
}

export async function searchKnowledge(
  client: RequestClient,
  query: string,
  topK = 10,
  threshold = 0.3,
): Promise<KnowledgeSearchResult[]> {
  const payload = await client.request<{ results?: KnowledgeSearchResult[] }>('/admin/knowledge/search', {
    method: 'POST',
    json: { query, top_k: topK, threshold },
  })
  return Array.isArray(payload.results) ? payload.results : []
}

export async function importKnowledge(client: RequestClient, entries: KnowledgeUpsert[]): Promise<unknown> {
  return client.request('/admin/knowledge/import', { method: 'POST', json: { entries } })
}

export async function rebuildKnowledgeIndex(client: RequestClient): Promise<unknown> {
  return client.request('/admin/knowledge/rebuild-index', { method: 'POST' })
}

export type AuthorizationScopeType = 'VENUE' | 'DEPARTMENT' | 'ROLE' | 'JOB_TITLE' | 'USER'

export interface AuthorizationScope {
  scope_type: AuthorizationScopeType
  scope_value: string
}

export interface ExpertRecord {
  id: string
  user_id: string
  display_name?: string
  job_title?: string
  department?: string
  years_experience?: number
  expertise?: string[]
  authorization_status?: 'PENDING' | 'SIGNED'
  status?: 'ACTIVE' | 'INACTIVE'
  updated_at?: number
}

export interface ExpertCreate {
  user_id: string
  display_name: string
  job_title: string
  department: string
  years_experience: number
  expertise: string[]
  authorization_status?: 'PENDING' | 'SIGNED'
  authorization_statement?: string | null
}

export interface InterviewRecord {
  id: string
  title?: string
  status?: string
  expert_name?: string
  expert_job_title?: string
  updated_at?: number
  progress?: { answered?: number; total?: number; percent?: number }
  turns?: Array<{ turn_number?: number; question_text?: string; answer_text?: string; source_excerpt?: string }>
  authorization_scopes?: AuthorizationScope[]
}

export interface InterviewCreate {
  expert_id: string
  title: string
  source_event_id?: string | null
  authorization_scopes: AuthorizationScope[]
}

export interface ExperienceCardRecord {
  id: string
  title?: string
  status?: string
  expert_name?: string
  expert_job_title?: string
  current_version?: number
  applicable_context?: string
  decision_rule?: string
  rationale?: string
  updated_at?: number
  signals?: string[]
  recommended_actions?: string[]
  prohibitions?: string[]
  exceptions?: string[]
  source_excerpts?: string[]
  authorization_scopes?: AuthorizationScope[]
  review_timeline?: Array<{ action?: string; comment?: string; created_at?: number }>
  versions?: Array<{ version_number?: number; change_note?: string; created_at?: number }>
  usage_summary?: { total?: number; retrieved?: number; viewed?: number; referenced?: number; feedback?: number }
  usage_records?: Array<{ usage_type?: string; user_display_name?: string; query_text?: string; note?: string; score?: number; experience_version?: number; created_at?: number }>
}

export async function loadExperts(client: RequestClient): Promise<ExpertRecord[]> {
  const payload = await client.request<{ experts?: ExpertRecord[] }>('/admin/experts?limit=200')
  return Array.isArray(payload.experts) ? payload.experts : []
}

export async function createExpert(client: RequestClient, body: ExpertCreate): Promise<unknown> {
  return client.request('/admin/experts', { method: 'POST', json: body })
}

export async function loadInterviews(client: RequestClient): Promise<InterviewRecord[]> {
  const payload = await client.request<{ interviews?: InterviewRecord[] }>('/admin/experience-interviews?limit=200')
  return Array.isArray(payload.interviews) ? payload.interviews : []
}

export async function loadInterview(client: RequestClient, interviewId: string): Promise<InterviewRecord> {
  const payload = await client.request<{ interview: InterviewRecord }>(
    `/admin/experience-interviews/${encodeURIComponent(interviewId)}`,
  )
  return payload.interview
}

export async function createInterview(client: RequestClient, body: InterviewCreate): Promise<unknown> {
  return client.request('/admin/experience-interviews', { method: 'POST', json: body })
}

export async function loadExperienceCards(client: RequestClient): Promise<ExperienceCardRecord[]> {
  const payload = await client.request<{ experience_cards?: ExperienceCardRecord[] }>('/admin/experience-cards?limit=200')
  return Array.isArray(payload.experience_cards) ? payload.experience_cards : []
}

export async function loadExperienceCard(client: RequestClient, cardId: string): Promise<ExperienceCardRecord> {
  const payload = await client.request<{ experience_card: ExperienceCardRecord }>(
    `/admin/experience-cards/${encodeURIComponent(cardId)}`,
  )
  return payload.experience_card
}

export async function submitExperienceCard(client: RequestClient, cardId: string): Promise<unknown> {
  return client.request(`/admin/experience-cards/${encodeURIComponent(cardId)}/submit`, { method: 'POST' })
}

export async function rejectExperienceCard(client: RequestClient, cardId: string, comment: string): Promise<unknown> {
  return client.request(`/admin/experience-cards/${encodeURIComponent(cardId)}/reject`, {
    method: 'POST',
    json: { comment },
  })
}

export async function publishExperienceCard(client: RequestClient, cardId: string, comment = ''): Promise<unknown> {
  return client.request(`/admin/experience-cards/${encodeURIComponent(cardId)}/publish`, {
    method: 'POST',
    json: { comment },
  })
}

export async function deprecateExperienceCard(client: RequestClient, cardId: string, comment: string): Promise<unknown> {
  return client.request(`/admin/experience-cards/${encodeURIComponent(cardId)}/deprecate`, {
    method: 'POST',
    json: { comment },
  })
}

export interface WatcherPolicyRecord {
  id: string
  name?: string
  description?: string
  schedule_cron?: string
  enabled?: boolean
  version?: number
  check_types?: string[]
  config?: Record<string, unknown>
}

export interface WatcherPolicyUpsert {
  name: string
  description: string
  schedule_cron: string
  enabled: boolean
  check_types: string[]
  config: Record<string, unknown>
}

export interface WatcherFindingRecord {
  id: string
  title?: string
  finding_type?: string
  description?: string
  details?: string
  severity?: string
  status?: string
  assigned_to?: string
  resolution?: string
  updated_at?: number
}

export interface WatcherRunRecord {
  id: string
  started_at?: number
  trigger_source?: string
  status?: string
  finding_count?: number
  trace_id?: string
  result?: Record<string, unknown>
}

export async function loadWatcherPolicies(client: RequestClient): Promise<WatcherPolicyRecord[]> {
  const payload = await client.request<{ policies?: WatcherPolicyRecord[] }>('/admin/watcher/policies')
  return Array.isArray(payload.policies) ? payload.policies : []
}

export async function createWatcherPolicy(client: RequestClient, body: WatcherPolicyUpsert): Promise<unknown> {
  return client.request('/admin/watcher/policies', { method: 'POST', json: body })
}

export async function updateWatcherPolicy(
  client: RequestClient,
  policyId: string,
  body: Partial<WatcherPolicyUpsert>,
): Promise<unknown> {
  return client.request(`/admin/watcher/policies/${encodeURIComponent(policyId)}`, { method: 'PUT', json: body })
}

export async function toggleWatcherPolicy(client: RequestClient, policyId: string, enabled: boolean): Promise<unknown> {
  return client.request(`/admin/watcher/policies/${encodeURIComponent(policyId)}`, { method: 'PUT', json: { enabled } })
}

export async function runWatcherPolicy(client: RequestClient, policyId: string): Promise<unknown> {
  return client.request(`/admin/watcher/policies/${encodeURIComponent(policyId)}/run`, { method: 'POST' })
}

export async function loadWatcherFindings(client: RequestClient): Promise<WatcherFindingRecord[]> {
  const payload = await client.request<{ findings?: WatcherFindingRecord[] }>('/admin/watcher/findings?limit=200')
  return Array.isArray(payload.findings) ? payload.findings : []
}

export async function assignWatcherFinding(client: RequestClient, findingId: string, assignedTo: string): Promise<unknown> {
  return client.request(`/admin/watcher/findings/${encodeURIComponent(findingId)}`, {
    method: 'PATCH',
    json: { assigned_to: assignedTo, status: 'IN_PROGRESS' },
  })
}

export async function closeWatcherFinding(client: RequestClient, findingId: string, resolution: string): Promise<unknown> {
  return client.request(`/admin/watcher/findings/${encodeURIComponent(findingId)}/close`, {
    method: 'POST',
    json: { resolution },
  })
}

export async function loadWatcherRuns(client: RequestClient): Promise<WatcherRunRecord[]> {
  const payload = await client.request<{ runs?: WatcherRunRecord[] }>('/admin/watcher/runs?limit=50')
  return Array.isArray(payload.runs) ? payload.runs : []
}

export interface SopRecord {
  id: number
  title: string
  content: string
  category?: string
  priority?: number
  version?: string
  status?: string
  source_event_id?: string | null
  created_at?: number
  updated_at?: number
  versions?: Array<{ version?: string; status?: string; change_note?: string; created_at?: number }>
}

export interface SopCreate {
  title: string
  content: string
  category: string
  priority: number
  source_event_id?: string | null
  version?: string
}

export interface SopUpdate {
  title: string
  content: string
  category: string
  priority: number
  source_event_id?: string | null
  change_note?: string | null
}

export function formatSopTimestamp(value?: number | string): string {
  if (value === undefined || value === null || value === '') return '—'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

export async function loadSops(client: RequestClient): Promise<SopRecord[]> {
  const payload = await client.request<{ sops?: SopRecord[] }>('/admin/sops')
  return Array.isArray(payload.sops) ? payload.sops : []
}

export async function loadSop(client: RequestClient, sopId: number | string): Promise<SopRecord> {
  const payload = await client.request<{ sop: SopRecord; versions?: SopRecord['versions'] }>(
    `/admin/sops/${encodeURIComponent(String(sopId))}`,
  )
  return { ...payload.sop, versions: payload.versions || [] }
}

export async function createSop(client: RequestClient, body: SopCreate): Promise<unknown> {
  return client.request('/admin/sops', { method: 'POST', json: body })
}

export async function updateSop(client: RequestClient, sopId: number | string, body: SopUpdate): Promise<unknown> {
  return client.request(`/admin/sops/${encodeURIComponent(String(sopId))}`, { method: 'PUT', json: body })
}

export async function submitSop(client: RequestClient, sopId: number | string): Promise<unknown> {
  return client.request(`/admin/sops/${encodeURIComponent(String(sopId))}/submit`, { method: 'POST' })
}

export async function publishSop(client: RequestClient, sopId: number | string, comment = ''): Promise<unknown> {
  return client.request(`/admin/sops/${encodeURIComponent(String(sopId))}/publish`, {
    method: 'POST',
    json: { comment },
  })
}

export async function rejectSop(client: RequestClient, sopId: number | string, comment: string): Promise<unknown> {
  return client.request(`/admin/sops/${encodeURIComponent(String(sopId))}/reject`, {
    method: 'POST',
    json: { comment },
  })
}
