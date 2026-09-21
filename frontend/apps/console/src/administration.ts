import type { RequestClient } from './operational'

export type AccountRole = 'admin' | 'manager' | 'operator'
export type AccountStatus = 'ACTIVE' | 'DISABLED'

export interface UserRecord {
  id: string
  username: string
  display_name?: string
  role?: AccountRole | string
  venue_id?: string
  department?: string | null
  job_title?: string | null
  status?: AccountStatus | string
  created_at?: number | string
  updated_at?: number | string
}

export interface UserCreate {
  username: string
  display_name: string
  password: string
  role: AccountRole
  venue_id: string
  department?: string | null
  job_title?: string | null
}

export interface VenueRecord {
  id: string
  name?: string
  status?: AccountStatus | string
  created_at?: number | string
  updated_at?: number | string
}

export interface SettingRecord {
  key: string
  value: unknown
  type: 'string' | 'integer' | 'boolean' | string
  updated_by?: string | null
  updated_at?: number | string | null
}

export interface IntegrationRecord {
  id?: string
  key?: string
  name?: string
  status?: string
  configured?: boolean
  live_verified?: boolean
  model?: string
  missing?: string[]
  blocked_reason?: string | null
}

export interface FeatureRegistry {
  summary?: {
    business_total?: number
    business_ready?: number
    release_gate_passed?: boolean
    by_status?: Record<string, number>
  }
  uat_journeys?: Array<{ id?: string; name?: string; status?: string; covers?: string[]; acceptance?: { missing?: string[] } }>
  items?: Array<{ id?: string; name?: string; category?: string; owner?: string; status?: string; acceptance?: { required?: string[]; satisfied?: string[]; missing?: string[] }; runtime_evidence?: Array<{ trace_id?: string }> }>
  collection_errors?: Array<{ source?: string; error_type?: string }>
}

export interface RuntimeDiagnostics {
  status?: string
  runtime?: Record<string, Record<string, unknown>>
  agents?: Array<{ id?: string; status?: string; registered?: boolean; registry_name?: string; evidence?: Record<string, unknown> }>
  agent_coverage?: Record<string, unknown>
  deepseek?: Record<string, unknown>
  model_runtime?: Record<string, unknown>
  token_quota?: Record<string, unknown>
  circuit_breaker?: Record<string, unknown>
  observability?: Record<string, unknown>
  channels?: Record<string, Record<string, unknown>>
}

export interface LlmCallRecord {
  id?: string
  created_at?: number | string
  model_name?: string
  status?: string
  is_mock?: boolean
  trace_id?: string
}

export interface AuditLogRecord {
  id?: string
  created_at?: number | string
  action?: string
  outcome?: string
  resource_type?: string
  resource_id?: string
  trace_id?: string
}

export interface SkillRecord {
  name?: string
  description?: string
  version?: string
}

export interface RecoveryRunRecord {
  instance_id?: string
  app_version?: string
  status?: string
  started_at?: number | string
  completed_at?: number | string
  trace_id?: string
  redis_status?: string
  task_graph_recovered_count?: number
  task_graph_reset_count?: number
  approval_interrupted_count?: number
  watcher_interrupted_count?: number
  redis_claimed_count?: number
  redis_acked_count?: number
  error_summary?: string
  trace?: Array<{ phase?: string; status?: string }>
}

export async function loadUsers(client: RequestClient): Promise<UserRecord[]> {
  const payload = await client.request<{ users?: UserRecord[] }>('/admin/users')
  return Array.isArray(payload.users) ? payload.users : []
}

export async function createUser(client: RequestClient, body: UserCreate): Promise<unknown> {
  return client.request('/admin/users', { method: 'POST', json: body })
}

export async function updateUser(client: RequestClient, userId: string, body: Partial<UserCreate> & { status?: AccountStatus }): Promise<unknown> {
  return client.request(`/admin/users/${encodeURIComponent(userId)}`, { method: 'PATCH', json: body })
}

export async function resetUserPassword(client: RequestClient, userId: string, password: string): Promise<unknown> {
  return client.request(`/admin/users/${encodeURIComponent(userId)}/reset-password`, {
    method: 'POST',
    json: { password },
  })
}

export async function loadVenues(client: RequestClient): Promise<VenueRecord[]> {
  const payload = await client.request<{ venues?: VenueRecord[] }>('/admin/venues')
  return Array.isArray(payload.venues) ? payload.venues : []
}

export async function createVenue(client: RequestClient, body: { id: string; name: string }): Promise<unknown> {
  return client.request('/admin/venues', { method: 'POST', json: body })
}

export async function updateVenue(client: RequestClient, venueId: string, body: { name?: string; status?: AccountStatus }): Promise<unknown> {
  return client.request(`/admin/venues/${encodeURIComponent(venueId)}`, { method: 'PATCH', json: body })
}

export async function enableSimulatorIdentity(client: RequestClient, user: Pick<UserRecord, 'id' | 'venue_id'>): Promise<unknown> {
  return client.request('/channels/identities', {
    method: 'POST',
    json: {
      channel: 'WECOM_SIMULATOR',
      external_tenant_id: `simulator-tenant:${user.venue_id || ''}`,
      external_user_id: `simulator-user:${user.id}`,
      user_id: user.id,
      status: 'ACTIVE',
    },
  })
}

export async function loadSettings(client: RequestClient): Promise<SettingRecord[]> {
  const payload = await client.request<{ settings?: SettingRecord[] }>('/admin/settings')
  return Array.isArray(payload.settings) ? payload.settings : []
}

export async function updateSetting(client: RequestClient, key: string, value: unknown): Promise<unknown> {
  return client.request(`/admin/settings/${encodeURIComponent(key)}`, { method: 'PUT', json: { value } })
}

export async function loadIntegrations(client: RequestClient): Promise<IntegrationRecord[]> {
  const payload = await client.request<{ integrations?: IntegrationRecord[] }>('/admin/integrations')
  return Array.isArray(payload.integrations) ? payload.integrations : []
}

export async function loadFeatureRegistry(client: RequestClient): Promise<FeatureRegistry> {
  return client.request<FeatureRegistry>('/admin/feature-registry')
}

export async function loadRuntimeDiagnostics(client: RequestClient): Promise<RuntimeDiagnostics> {
  return client.request<RuntimeDiagnostics>('/admin/diagnostics')
}

export async function loadQueueStatus(client: RequestClient): Promise<Record<string, unknown>> {
  return client.request<Record<string, unknown>>('/admin/queue')
}

export async function loadDeadLetters(client: RequestClient): Promise<Array<Record<string, unknown>>> {
  const payload = await client.request<{ dead_letters?: Array<Record<string, unknown>> }>('/admin/dead-letters?limit=50')
  return Array.isArray(payload.dead_letters) ? payload.dead_letters : []
}

export async function loadLlmCalls(client: RequestClient): Promise<LlmCallRecord[]> {
  const payload = await client.request<{ llm_calls?: LlmCallRecord[] }>('/admin/llm-calls?limit=50')
  return Array.isArray(payload.llm_calls) ? payload.llm_calls : []
}

export async function loadAuditLogs(client: RequestClient): Promise<AuditLogRecord[]> {
  const payload = await client.request<{ audit_logs?: AuditLogRecord[] }>('/admin/audit-logs?limit=50')
  return Array.isArray(payload.audit_logs) ? payload.audit_logs : []
}

export async function loadSkills(client: RequestClient): Promise<SkillRecord[]> {
  const payload = await client.request<SkillRecord[] | { skills?: SkillRecord[] }>('/skills')
  return Array.isArray(payload) ? payload : Array.isArray(payload.skills) ? payload.skills : []
}

export async function loadRecoveryRuns(client: RequestClient): Promise<RecoveryRunRecord[]> {
  const payload = await client.request<{ recovery_runs?: RecoveryRunRecord[] }>('/admin/recovery-runs?limit=20')
  return Array.isArray(payload.recovery_runs) ? payload.recovery_runs : []
}

export async function loadTrace(client: RequestClient, traceId: string): Promise<Record<string, any>> {
  return client.request<Record<string, any>>(`/admin/traces/${encodeURIComponent(traceId)}`)
}

export async function runDeepseekProbe(client: RequestClient): Promise<unknown> {
  return client.request('/admin/diagnostics/deepseek-probe', { method: 'POST' })
}

export async function reloadRuntimeConfig(client: RequestClient): Promise<unknown> {
  return client.request('/admin/config/reload', { method: 'POST' })
}

export async function reloadSkill(client: RequestClient, skillName: string): Promise<unknown> {
  return client.request(`/skills/${encodeURIComponent(skillName)}/reload`, { method: 'POST' })
}
