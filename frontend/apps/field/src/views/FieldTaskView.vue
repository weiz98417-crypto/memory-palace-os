<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import { buildFieldView } from '../fieldStatus'
import {
  acceptAssistantInterview,
  answerAssistantInterview,
  blockAssistantTask,
  completeAssistantInterview,
  completeAssistantTask,
  confirmAssistantExperienceCard,
  loadAssistantEvent,
  loadAssistantExperience,
  loadAssistantInterview,
  loadAssistantMessages,
  loadAssistantSessions,
  loadAssistantSop,
  loadAssistantTask,
  loadAssistantWork,
  pauseAssistantInterview,
  recordAssistantExperienceFeedback,
  resumeAssistantInterview,
  retryAssistantMessage,
  reviseAssistantExperienceCard,
  searchAssistantExperience,
  sendAssistantMessage,
  startAssistantTask,
  uploadAssistantAttachment,
  type AssistantConversationMessage,
  type AssistantExperienceHome,
  type AssistantInterview,
  type AssistantSession,
  type FieldEvent,
  type FieldTask,
} from '../field'

const emit = defineEmits<{ logout: [] }>()
const client = createApiClient()
const user = ref<any>(client.auth.read())
const section = ref<'chat' | 'work' | 'experience' | 'me'>('chat')
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)

const sessions = ref<AssistantSession[]>([])
const activeSessionId = ref('')
const messages = ref<AssistantConversationMessage[]>([])
const messageInput = ref('')
const attachment = ref<any>(null)
const fileInput = ref<any>(null)

const tasks = ref<FieldTask[]>([])
const events = ref<FieldEvent[]>([])
const selectedTask = ref<FieldTask | null>(null)
const selectedEvent = ref<FieldEvent | null>(null)
const advice = ref<any>(null)
const taskSummary = ref('')
const taskResult = ref('')
const blockReason = ref('')

const experience = ref<AssistantExperienceHome>({ expert: null, interviews: [], cards: [] })
const selectedInterview = ref<AssistantInterview | null>(null)
const selectedCard = ref<Record<string, any> | null>(null)
const interviewAnswer = ref('')
const interviewSource = ref('')
const cardForm = ref({ title: '', applicable_context: '', signals: '', decision_rule: '', recommended_actions: '', rationale: '', prohibitions: '', exceptions: '', source_excerpts: '', change_note: '' })
const experienceQuery = ref('')
const experienceResults = ref<Array<Record<string, any>>>([])

const expert = computed(() => experience.value.expert || null)
const interviews = computed(() => experience.value.interviews || [])
const cards = computed(() => experience.value.cards || [])
const activeSession = computed(() => sessions.value.find((item) => item.session_id === activeSessionId.value) || null)
const interviewCompleteReady = computed(() => {
  const progress = selectedInterview.value?.progress || {}
  return Number(progress.answered || 0) >= Number(progress.total || 0) && Number(progress.total || 0) > 0
})
const currentInterviewQuestion = computed(() => {
  const turns = selectedInterview.value?.turns || []
  const progress = selectedInterview.value?.progress || {}
  const nextIndex = Number(progress.answered || 0)
  return turns[nextIndex]?.question_text || turns[turns.length - 1]?.question_text || '请描述你的现场经验'
})

function statusTone(value?: string): 'success' | 'warning' | 'danger' | 'neutral' | 'info' {
  const state = String(value || '').toUpperCase()
  if (['DONE', 'SUCCEEDED', 'DELIVERED', 'COMPLETED', 'EXPERT_CONFIRMED', 'PUBLISHED', 'ACTIVE'].includes(state)) return 'success'
  if (['PENDING', 'RUNNING', 'SENDING', 'ACCEPTED', 'IN_PROGRESS', 'PAUSED', 'INVITED'].includes(state)) return 'warning'
  if (['FAILED', 'BLOCKED', 'RETRY_REQUIRED', 'DEAD_LETTERED', 'REJECTED', 'DEPRECATED'].includes(state)) return 'danger'
  return 'neutral'
}
function roleLabel(value?: string): string {
  return ({ admin: '系统管理员', manager: '值班经理', operator: '现场员工', api: '企业服务账号' } as Record<string, string>)[String(value || '').toLowerCase()] || '企业成员'
}
function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function newExternalId(): string {
  return `field-${globalThis.crypto?.randomUUID?.() || Date.now().toString(36)}`
}
function sessionTitle(item: AssistantSession): string {
  return item.last_message || `会话 ${item.session_id.slice(0, 8)}`
}
function setError(cause: unknown, fallback: string) {
  error.value = cause instanceof Error ? cause.message : fallback
}
function safeEntries(value: unknown): Array<{ label: string; value: string }> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  return Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== null && item !== undefined && typeof item !== 'object')
    .map(([label, item]) => ({ label, value: String(item) }))
}
async function loadSessions() {
  try {
    sessions.value = await loadAssistantSessions(client)
    const key = `mp_assistant_last_session:${user.value?.venue_id}:${user.value?.id}`
    const saved = globalThis.sessionStorage?.getItem(key) || ''
    const candidate = sessions.value.find((item) => item.session_id === saved) || sessions.value[0]
    if (candidate) await openSession(candidate.session_id)
  } catch (cause) {
    setError(cause, '会话读取失败')
  }
}
async function openSession(sessionId: string) {
  activeSessionId.value = sessionId
  const key = `mp_assistant_last_session:${user.value?.venue_id}:${user.value?.id}`
  globalThis.sessionStorage?.setItem(key, sessionId)
  loading.value = true
  try {
    const payload = await loadAssistantMessages(client, sessionId)
    messages.value = payload.messages
  } catch (cause) {
    setError(cause, '会话消息读取失败')
  } finally {
    loading.value = false
  }
}
async function newSession() {
  activeSessionId.value = ''
  messages.value = []
  messageInput.value = ''
}
async function refreshMessages() {
  if (activeSessionId.value) await openSession(activeSessionId.value)
}
async function sendMessage() {
  const content = messageInput.value.trim()
  if (!content && !attachment.value) {
    error.value = '请输入消息或选择附件'
    return
  }
  const localId = `local-${newExternalId()}`
  const optimisticAttachments = attachment.value ? [{ filename: attachment.value.name, mime_type: attachment.value.type }] : []
  messages.value.push({ id: localId, role: 'user', content, status: 'SENDING', attachments: optimisticAttachments })
  busy.value = true
  error.value = ''
  try {
    let uploaded: Record<string, unknown> | null = null
    if (attachment.value) uploaded = await uploadAssistantAttachment(client, attachment.value)
    const accepted = await sendAssistantMessage(client, {
      content: content || `附件：${attachment.value?.name || ''}`,
      external_message_id: newExternalId(),
      external_conversation_id: activeSessionId.value || activeSession.value?.external_conversation_id || null,
      attachments: uploaded ? [uploaded] : [],
    })
    const acceptedSession = String(accepted.session_id || activeSessionId.value || '')
    messageInput.value = ''
    attachment.value = null
    if (fileInput.value) fileInput.value.value = ''
    notice.value = '消息已提交，助手正在处理'
    if (acceptedSession) {
      await openSession(acceptedSession)
      globalThis.setTimeout(() => { void refreshMessages() }, 2500)
    }
  } catch (cause) {
    const local = messages.value.find((item) => item.id === localId)
    if (local) local.status = 'FAILED'
    setError(cause, '消息发送失败')
  } finally {
    busy.value = false
  }
}
async function retryMessage(item: AssistantConversationMessage) {
  const messageId = item.message_id || item.id.split(':')[0]
  busy.value = true
  try {
    await retryAssistantMessage(client, messageId)
    notice.value = '原消息已重新入队'
    await refreshMessages()
  } catch (cause) {
    setError(cause, '消息重试失败')
  } finally {
    busy.value = false
  }
}
async function loadWork() {
  try {
    const [work, snapshot] = await Promise.all([loadAssistantWork(client), client.request<Record<string, any>>('/scenic/snapshot')])
    tasks.value = work.tasks
    events.value = work.events
    advice.value = buildFieldView(snapshot).advice
  } catch (cause) {
    setError(cause, '工作数据读取失败')
  }
}
async function openTask(item: FieldTask) {
  busy.value = true
  try {
    selectedTask.value = await loadAssistantTask(client, item.id)
    taskSummary.value = ''
    taskResult.value = ''
    blockReason.value = ''
  } catch (cause) {
    setError(cause, '任务详情读取失败')
  } finally {
    busy.value = false
  }
}
async function openEvent(item: FieldEvent) {
  busy.value = true
  try {
    selectedEvent.value = await loadAssistantEvent(client, item.event_id)
  } catch (cause) {
    setError(cause, '事件详情读取失败')
  } finally {
    busy.value = false
  }
}
async function taskAction(action: 'start' | 'complete' | 'block') {
  if (!selectedTask.value) return
  busy.value = true
  error.value = ''
  try {
    if (action === 'start') await startAssistantTask(client, selectedTask.value.id)
    if (action === 'complete') {
      let parsed: Record<string, unknown> = {}
      if (taskResult.value.trim()) {
        try { parsed = JSON.parse(taskResult.value) as Record<string, unknown> } catch { throw new Error('结构化结果必须是 JSON 对象') }
      }
      await completeAssistantTask(client, selectedTask.value.id, taskSummary.value.trim(), parsed)
    }
    if (action === 'block') await blockAssistantTask(client, selectedTask.value.id, blockReason.value.trim())
    notice.value = action === 'start' ? '任务已开始' : action === 'complete' ? '任务已完成' : '阻塞已上报'
    await openTask(selectedTask.value)
    await loadWork()
  } catch (cause) {
    setError(cause, '任务状态更新失败')
  } finally {
    busy.value = false
  }
}
async function openSopFromEvent() {
  const dossier = selectedEvent.value?.dossier || {}
  const reference = (dossier.sop || dossier.sop_reference || dossier.reference || {}) as Record<string, any>
  const sopId = reference.id || reference.sop_id || dossier.sop_id
  if (!sopId) {
    error.value = '当前事件没有已发布 SOP 引用'
    return
  }
  busy.value = true
  try {
    const sop = await loadAssistantSop(client, sopId, String(reference.version || ''))
    notice.value = `已打开 SOP：${sop.title || sopId}`
  } catch (cause) {
    setError(cause, 'SOP 读取失败')
  } finally {
    busy.value = false
  }
}
async function loadExperience() {
  try {
    experience.value = await loadAssistantExperience(client)
  } catch (cause) {
    setError(cause, '经验共创读取失败')
  }
}
function openInterview(item: Record<string, any>) {
  return loadAssistantInterview(client, String(item.id)).then((detail) => { selectedInterview.value = detail; interviewAnswer.value = ''; interviewSource.value = '' }).catch((cause) => setError(cause, '访谈详情读取失败'))
}
async function interviewAction(action: 'accept' | 'answer' | 'pause' | 'resume' | 'complete') {
  if (!selectedInterview.value) return
  busy.value = true
  error.value = ''
  try {
    const id = selectedInterview.value.id
    if (action === 'accept') await acceptAssistantInterview(client, id)
    if (action === 'answer') await answerAssistantInterview(client, id, interviewAnswer.value.trim(), interviewSource.value.trim())
    if (action === 'pause') await pauseAssistantInterview(client, id)
    if (action === 'resume') await resumeAssistantInterview(client, id)
    if (action === 'complete') await completeAssistantInterview(client, id)
    notice.value = action === 'answer' ? '回答已保存' : action === 'complete' ? '经验草稿已生成' : '访谈状态已更新'
    selectedInterview.value = await loadAssistantInterview(client, id)
    interviewAnswer.value = ''
    interviewSource.value = ''
    await loadExperience()
  } catch (cause) {
    setError(cause, '访谈操作失败')
  } finally {
    busy.value = false
  }
}
function openCard(card: Record<string, any>) {
  selectedCard.value = card
  cardForm.value = {
    title: card.title || '',
    applicable_context: card.applicable_context || '',
    signals: (card.signals || []).join('\n'),
    decision_rule: card.decision_rule || '',
    recommended_actions: (card.recommended_actions || []).join('\n'),
    rationale: card.rationale || '',
    prohibitions: (card.prohibitions || []).join('\n'),
    exceptions: (card.exceptions || []).join('\n'),
    source_excerpts: (card.source_excerpts || []).join('\n'),
    change_note: '',
  }
}
function lines(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}
async function reviseCard() {
  if (!selectedCard.value) return
  busy.value = true
  try {
    const payload = await reviseAssistantExperienceCard(client, String(selectedCard.value.id), {
      title: cardForm.value.title.trim(),
      applicable_context: cardForm.value.applicable_context.trim(),
      signals: lines(cardForm.value.signals),
      decision_rule: cardForm.value.decision_rule.trim(),
      recommended_actions: lines(cardForm.value.recommended_actions),
      rationale: cardForm.value.rationale.trim(),
      prohibitions: lines(cardForm.value.prohibitions),
      exceptions: lines(cardForm.value.exceptions),
      source_excerpts: lines(cardForm.value.source_excerpts),
      change_note: cardForm.value.change_note.trim(),
    })
    selectedCard.value = payload.card || selectedCard.value
    notice.value = '经验修订已保存'
    await loadExperience()
  } catch (cause) {
    setError(cause, '经验修订失败')
  } finally {
    busy.value = false
  }
}
async function confirmCard() {
  if (!selectedCard.value) return
  busy.value = true
  try {
    const payload = await confirmAssistantExperienceCard(client, String(selectedCard.value.id))
    selectedCard.value = payload.card || selectedCard.value
    notice.value = '经验已由专家确认'
    await loadExperience()
  } catch (cause) {
    setError(cause, '经验确认失败')
  } finally {
    busy.value = false
  }
}
async function searchExperience() {
  if (experienceQuery.value.trim().length < 2) {
    error.value = '检索问题至少需要 2 个字符'
    return
  }
  busy.value = true
  try {
    experienceResults.value = await searchAssistantExperience(client, experienceQuery.value.trim(), activeSessionId.value)
  } catch (cause) {
    setError(cause, '经验检索失败')
  } finally {
    busy.value = false
  }
}
async function feedback(card: Record<string, any>, value: 'HELPFUL' | 'NOT_APPLICABLE' | 'NEEDS_EXPERT') {
  busy.value = true
  try {
    await recordAssistantExperienceFeedback(client, String(card.id), value, '', activeSessionId.value)
    notice.value = '经验反馈已记录'
  } catch (cause) {
    setError(cause, '经验反馈失败')
  } finally {
    busy.value = false
  }
}
async function switchSection(next: typeof section.value) {
  section.value = next
  error.value = ''
  if (next === 'chat' && !sessions.value.length) await loadSessions()
  if (next === 'work' && !tasks.value.length && !events.value.length) await loadWork()
  if (next === 'experience' && !experience.value.expert && !interviews.value.length && !cards.value.length) await loadExperience()
}
function logout() {
  client.auth.clear()
  emit('logout')
}
onMounted(async () => {
  loading.value = true
  await Promise.allSettled([loadSessions(), loadWork(), loadExperience()])
  loading.value = false
})
</script>

<template>
  <section class="field-workspace" data-testid="field-view">
    <header class="field-head"><div><p class="eyebrow">MOBILE FIELD</p><h1>{{ section === 'chat' ? '企业运营助手' : section === 'work' ? '我的现场任务' : section === 'experience' ? '经验共创' : '我的账号' }}</h1><p class="muted">{{ user?.display_name || '现场员工' }} · {{ roleLabel(user?.role) }}</p></div><StatusBadge label="只读建议" tone="ai" /></header>
    <StatePanel v-if="loading" state="loading" title="正在同步现场工作" />
    <StatePanel v-else-if="error" state="error" title="现场端操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <nav class="section-tabs" aria-label="现场端功能">
      <button v-for="item in [{ key: 'chat', label: '助手', icon: '对' }, { key: 'work', label: '工作', icon: '工' }, { key: 'experience', label: '经验', icon: '经' }, { key: 'me', label: '我的', icon: '我' }]" :key="item.key" :class="{ active: section === item.key }" @click="switchSection(item.key as any)"><span aria-hidden="true">{{ item.icon }}</span><small>{{ item.label }}</small></button>
    </nav>

    <div v-if="section === 'chat'" class="section-grid chat-grid">
      <aside class="panel session-panel">
        <div class="panel-head"><h2>历史会话</h2><button class="icon-button" aria-label="新建会话" @click="newSession">＋</button></div>
        <button v-for="item in sessions" :key="item.session_id" class="session-item" :class="{ active: item.session_id === activeSessionId }" @click="openSession(item.session_id)"><strong>{{ sessionTitle(item) }}</strong><small>{{ format(item.updated_at || item.created_at) }}</small></button>
        <p v-if="!sessions.length" class="muted">暂无历史会话。发送第一条消息后保存在这里。</p>
      </aside>
      <article class="panel chat-panel">
        <div class="panel-head"><h2>{{ activeSession ? '当前会话' : '新会话' }}</h2><button :disabled="busy" @click="refreshMessages">刷新</button></div>
        <div class="message-list">
          <article v-for="message in messages" :key="message.id" class="message" :class="`message-${message.role}`"><div class="message-meta"><strong>{{ message.role === 'user' ? '我' : '助手' }}</strong><StatusBadge v-if="message.status" :label="message.status" :tone="statusTone(message.status)" /></div><p>{{ message.content }}</p><ul v-if="message.attachments?.length"><li v-for="file in message.attachments" :key="file.id || file.filename">{{ file.filename || '附件' }}</li></ul><details v-if="message.business_cards?.length"><summary>业务卡片</summary><p v-for="(card, index) in message.business_cards" :key="index">{{ card.title || card.label || card.type || '业务结果' }}</p></details><button v-if="['RETRY_REQUIRED', 'DEAD_LETTERED', 'FAILED'].includes(String(message.status || '').toUpperCase())" :disabled="busy" @click="retryMessage(message)">重试消息</button></article>
          <p v-if="!messages.length" class="muted">描述现场情况、上传证据，或继续已有会话。</p>
        </div>
        <form class="composer" @submit.prevent="sendMessage">
          <textarea v-model="messageInput" rows="3" maxlength="8000" placeholder="输入现场问题或处置进展"></textarea>
          <label class="file-button">附件<input ref="fileInput" type="file" accept="image/*,.pdf,.txt,.doc,.docx" @change="attachment = ($event.target as HTMLInputElement).files?.[0] || null"><span>{{ attachment?.name || '添加证据' }}</span></label>
          <button class="primary" :disabled="busy">{{ busy ? '发送中' : '发送' }}</button>
        </form>
      </article>
    </div>

    <div v-else-if="section === 'work'" class="section-grid work-grid">
      <article v-if="advice" class="panel advice-panel read-only-advice"><div class="panel-head"><h2>处置建议</h2><StatusBadge label="只读" tone="ai" /></div><p>{{ advice.text }}</p><small>{{ advice.evidenceStatus === 'NO_EVIDENCE' ? '没有依据' : advice.status }}</small></article>
      <div class="work-columns">
        <article class="panel"><div class="panel-head"><h2>任务</h2><span class="muted">{{ tasks.length }} 项</span></div><button v-for="item in tasks" :key="item.id" class="work-item" @click="openTask(item)"><span><strong>{{ item.description || item.business_id || '现场任务' }}</strong><small>{{ item.business_id || item.id }}</small></span><StatusBadge :label="item.status || 'PENDING'" :tone="statusTone(item.status)" /></button><p v-if="!tasks.length" class="muted">当前没有分配任务。</p></article>
        <article class="panel"><div class="panel-head"><h2>我的事件</h2><span class="muted">{{ events.length }} 条</span></div><button v-for="item in events" :key="item.event_id" class="work-item" @click="openEvent(item)"><span><strong>{{ item.raw_text || item.business_id || '现场事件' }}</strong><small>{{ item.event_type || '事件' }} · {{ format(item.created_at) }}</small></span><StatusBadge :label="item.severity || '—'" :tone="statusTone(item.severity)" /></button><p v-if="!events.length" class="muted">没有与你关联的现场事件。</p></article>
      </div>

      <article v-if="selectedTask" class="panel detail-panel"><div class="panel-head"><h2>任务详情</h2><button class="ghost" @click="selectedTask = null">关闭</button></div><dl><dt>任务</dt><dd>{{ selectedTask.description || selectedTask.business_id }}</dd><dt>状态</dt><dd><StatusBadge :label="selectedTask.status || 'PENDING'" :tone="statusTone(selectedTask.status)" /></dd><dt>依赖</dt><dd>{{ (selectedTask.dependencies || []).join(', ') || '无' }}</dd><dt>尝试</dt><dd>{{ selectedTask.attempts || 0 }} / {{ selectedTask.max_attempts || 3 }}</dd><dt v-if="selectedTask.block_reason">阻塞</dt><dd v-if="selectedTask.block_reason">{{ selectedTask.block_reason }}</dd></dl><button v-if="selectedTask.status === 'PENDING'" class="primary" :disabled="busy" @click="taskAction('start')">开始任务</button><template v-if="selectedTask.status === 'RUNNING'"><label>完成摘要<textarea v-model="taskSummary" required rows="3" placeholder="说明实际完成情况"></textarea></label><label>结构化结果（JSON，可选）<textarea v-model="taskResult" rows="3" placeholder='{"检查项":"通过"}'></textarea></label><button class="primary" :disabled="busy" @click="taskAction('complete')">完成任务</button><label>阻塞原因<textarea v-model="blockReason" rows="2" placeholder="说明缺少的物料、权限或条件"></textarea></label><button class="danger" :disabled="busy" @click="taskAction('block')">上报阻塞</button></template></article>

      <article v-if="selectedEvent" class="panel detail-panel"><div class="panel-head"><h2>事件详情</h2><button class="ghost" @click="selectedEvent = null">关闭</button></div><dl><dt>内容</dt><dd>{{ selectedEvent.raw_text || '—' }}</dd><dt>类型</dt><dd>{{ selectedEvent.event_type || '—' }}</dd><dt>级别</dt><dd>{{ selectedEvent.severity || '—' }}</dd><dt>状态</dt><dd><StatusBadge :label="selectedEvent.status || 'UNKNOWN'" :tone="statusTone(selectedEvent.status)" /></dd><template v-for="entry in safeEntries(selectedEvent.dossier)" :key="entry.label"><dt>{{ entry.label }}</dt><dd>{{ entry.value }}</dd></template></dl><button :disabled="busy" @click="openSopFromEvent">打开关联 SOP</button></article>
    </div>

    <div v-else-if="section === 'experience'" class="experience-layout">
      <section class="panel"><div class="panel-head"><h2>我的经验身份</h2><StatusBadge :label="expert ? '专家已建档' : '非专家账号'" :tone="expert ? 'success' : 'neutral'" /></div><p v-if="expert">{{ expert.display_name }} · {{ expert.job_title }} · {{ expert.department }}</p><p v-else class="muted">当前账号尚未建立专家档案，只能使用经验检索。</p></section>
      <section v-if="interviews.length" class="panel"><div class="panel-head"><h2>访谈邀请</h2><span class="muted">{{ interviews.length }} 项</span></div><button v-for="item in interviews" :key="item.id" class="work-item" @click="openInterview(item)"><span><strong>{{ item.title || '经验访谈' }}</strong><small>{{ item.progress?.answered || 0 }} / {{ item.progress?.total || 0 }} 题</small></span><StatusBadge :label="item.status || 'INVITED'" :tone="statusTone(item.status)" /></button></section>
      <section v-if="cards.length" class="panel"><div class="panel-head"><h2>我的经验卡</h2><span class="muted">{{ cards.length }} 条</span></div><button v-for="item in cards" :key="item.id" class="work-item" @click="openCard(item)"><span><strong>{{ item.title || '待完善经验' }}</strong><small>第 {{ item.current_version || 1 }} 版</small></span><StatusBadge :label="item.status || 'DRAFT'" :tone="statusTone(item.status)" /></button></section>

      <article v-if="selectedInterview" class="panel detail-panel"><div class="panel-head"><h2>访谈：{{ selectedInterview.title }}</h2><button class="ghost" @click="selectedInterview = null">关闭</button></div><p>{{ selectedInterview.progress?.answered || 0 }} / {{ selectedInterview.progress?.total || 0 }} 题 · <StatusBadge :label="selectedInterview.status || 'INVITED'" :tone="statusTone(selectedInterview.status)" /></p><button v-if="selectedInterview.status === 'INVITED'" class="primary" :disabled="busy" @click="interviewAction('accept')">接受访谈</button><template v-if="['ACCEPTED', 'IN_PROGRESS', 'PAUSED'].includes(String(selectedInterview.status || ''))"><p class="question">{{ currentInterviewQuestion }}</p><label>回答<textarea v-model="interviewAnswer" rows="5" maxlength="8000" required></textarea></label><label>关键原话<textarea v-model="interviewSource" rows="2" maxlength="2000"></textarea></label><div class="row-actions"><button class="primary" :disabled="busy" @click="interviewAction('answer')">提交本题</button><button v-if="selectedInterview.status !== 'PAUSED'" :disabled="busy" @click="interviewAction('pause')">暂停</button><button v-else :disabled="busy" @click="interviewAction('resume')">继续</button><button v-if="interviewCompleteReady" :disabled="busy" @click="interviewAction('complete')">生成经验草稿</button></div></template></article>

      <article v-if="selectedCard" class="panel detail-panel"><div class="panel-head"><h2>经验卡：{{ selectedCard.title || '待完善经验' }}</h2><button class="ghost" @click="selectedCard = null">关闭</button></div><p>{{ selectedCard.applicable_context || '适用情境待补充' }}</p><template v-if="selectedCard.status === 'DRAFT'"><label>标题<input v-model="cardForm.title" maxlength="200"></label><label>适用情境<textarea v-model="cardForm.applicable_context" rows="3"></textarea></label><label>识别信号（每行一条）<textarea v-model="cardForm.signals" rows="3"></textarea></label><label>判断规则<textarea v-model="cardForm.decision_rule" rows="3"></textarea></label><label>建议动作（每行一条）<textarea v-model="cardForm.recommended_actions" rows="3"></textarea></label><label>判断依据<textarea v-model="cardForm.rationale" rows="3"></textarea></label><label>禁止事项（每行一条）<textarea v-model="cardForm.prohibitions" rows="2"></textarea></label><label>例外情况（每行一条）<textarea v-model="cardForm.exceptions" rows="2"></textarea></label><label>来源原话（每行一条）<textarea v-model="cardForm.source_excerpts" rows="3"></textarea></label><label>修改说明<input v-model="cardForm.change_note" maxlength="1000"></label><div class="row-actions"><button :disabled="busy" @click="reviseCard">保存修订</button><button class="primary" :disabled="busy" @click="confirmCard">确认并提交审核</button></div></template><template v-else><section><h3>适用情境</h3><p>{{ selectedCard.applicable_context || '待补充' }}</p></section><section><h3>判断规则</h3><p>{{ selectedCard.decision_rule || '待补充' }}</p></section><section><h3>建议动作</h3><p>{{ (selectedCard.recommended_actions || []).join('、') || '待补充' }}</p></section><section><h3>禁止事项</h3><p>{{ (selectedCard.prohibitions || []).join('、') || '待补充' }}</p></section></template></article>

      <section class="panel search-panel"><div class="panel-head"><h2>经验检索</h2><span class="muted">只读已发布经验</span></div><form class="toolbar" @submit.prevent="searchExperience"><input v-model="experienceQuery" minlength="2" placeholder="描述现场信号或目标"><button class="primary" :disabled="busy">检索</button></form><article v-for="item in experienceResults" :key="item.id" class="search-result"><strong>{{ item.title || '组织经验' }}</strong><p>{{ item.applicable_context || item.decision_rule || '' }}</p><small>{{ item.expert_name || '组织专家' }} · {{ item.score ? `${Math.round(Number(item.score) * 100)}%` : '已发布' }}</small><div class="row-actions"><button :disabled="busy" @click="feedback(item, 'HELPFUL')">有帮助</button><button :disabled="busy" @click="feedback(item, 'NOT_APPLICABLE')">不适用</button><button :disabled="busy" @click="feedback(item, 'NEEDS_EXPERT')">需要专家</button></div></article></section>
    </div>

    <article v-else class="panel me-panel"><h2>{{ user?.display_name || user?.username }}</h2><dl><dt>账号</dt><dd>{{ user?.username || '—' }}</dd><dt>角色</dt><dd>{{ roleLabel(user?.role) }}</dd><dt>场地</dt><dd>{{ user?.venue_id || '—' }}</dd></dl><button class="danger" @click="logout">退出登录</button></article>
  </section>
</template>

<style scoped>
.field-workspace { display: grid; gap: 16px; padding-bottom: 76px; color: var(--mp-color-body); }
.field-head, .panel-head, .row-actions, .message-meta { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.field-head h1 { margin: 4px 0 6px; color: var(--mp-color-ink); font-size: 26px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.section-tabs { position: sticky; top: 0; z-index: 5; display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; padding: 6px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-lg); background: var(--mp-color-surface); }
.section-tabs button { display: grid; gap: 2px; min-height: 48px; border: 1px solid transparent; border-radius: var(--mp-radius-md); color: var(--mp-color-body); background: transparent; font: inherit; }
.section-tabs button.active { border-color: var(--mp-color-primary); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); }
.panel { display: grid; gap: 10px; padding: 14px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.section-grid, .experience-layout { display: grid; gap: 14px; }
.chat-grid { grid-template-columns: minmax(220px, 300px) 1fr; }
.work-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.session-item, .work-item { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; width: 100%; min-height: 52px; padding: 10px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); color: var(--mp-color-body); background: var(--mp-color-surface-elevated); text-align: left; font: inherit; }
.session-item.active { border-color: var(--mp-color-primary); }
.session-item small, .work-item small { display: block; color: var(--mp-color-mute); font-size: 12px; }
.message-list { display: grid; gap: 10px; min-height: 240px; align-content: start; }
.message { max-width: 88%; padding: 10px 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); background: var(--mp-color-surface-elevated); }
.message-user { justify-self: end; border-color: color-mix(in srgb, var(--mp-color-primary) 45%, var(--mp-color-hairline)); }
.message p { margin: 6px 0 0; white-space: pre-wrap; }
.message ul { margin: 6px 0 0; padding-left: 18px; }
.composer { display: grid; gap: 8px; }
textarea, input, select { width: 100%; min-height: 44px; padding: 10px 12px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
textarea { resize: vertical; }
button { min-height: 44px; padding: 8px 12px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button.primary { border-color: var(--mp-color-primary); color: white; background: var(--mp-color-primary); }
button.danger { border-color: var(--mp-color-danger); color: var(--mp-color-danger); }
button.ghost, .icon-button { border-color: transparent; background: transparent; }
button:disabled { opacity: .55; }
.file-button { position: relative; display: inline-flex; align-items: center; justify-content: center; min-height: 44px; padding: 8px 12px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-body); }
.file-button input { position: absolute; inset: 0; opacity: 0; }
.read-only-advice { border-color: color-mix(in srgb, var(--mp-color-ai) 45%, var(--mp-color-hairline)); }
.detail-panel dl, .me-panel dl { display: grid; grid-template-columns: 100px 1fr; gap: 8px 12px; margin: 0; }
.detail-panel dt, .me-panel dt { color: var(--mp-color-mute); }
.detail-panel dd, .me-panel dd { margin: 0; }
.question { color: var(--mp-color-ink); font-size: 16px; }
.search-result { display: grid; gap: 6px; padding: 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); }
.search-result p { margin: 0; }
.notice { color: var(--mp-color-success); font-size: 13px; }
@media (max-width: 900px) {
  .chat-grid, .work-columns { grid-template-columns: 1fr; }
  .session-panel { max-height: 220px; overflow: auto; }
  .message { max-width: 96%; }
}
</style>
