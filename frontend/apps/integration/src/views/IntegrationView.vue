<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  confirmExperienceCard,
  deliveryStatusLabel,
  experienceInterviewAction,
  loadExperienceHome,
  loadIdentities,
  loadMessages,
  loadOutbox,
  loadSessions,
  retrySimulatorMessage,
  sendSimulatorMessage,
  toneForStatus,
  uploadSimulatorAttachment,
  type IntegrationClient,
  type IntegrationIdentity,
  type IntegrationMessage,
  type IntegrationSession,
  type OutboxItem,
} from '../integration'

const props = defineProps<{ client?: IntegrationClient }>()
const client = props.client || createApiClient()
const session = ref<any>(client.auth.read())
const isManager = computed(() => ['manager', 'admin'].includes(String(session.value?.role || '')))
const username = ref('wangfang')
const password = ref('')
const identities = ref<IntegrationIdentity[]>([])
const selectedUserId = ref('')
const sessions = ref<IntegrationSession[]>([])
const selectedSessionId = ref('')
const messages = ref<IntegrationMessage[]>([])
const outbox = ref<OutboxItem[]>([])
const experience = ref<Record<string, any>>({})
const activeTab = ref<'sessions' | 'outbox' | 'experience'>('sessions')
const loading = ref(false)
const error = ref('')
const notice = ref('')
const messageText = ref('')
const attachmentFile = ref<any>(null)
const busy = ref(false)

const selectedIdentity = computed(() => identities.value.find((item) => item.user_id === selectedUserId.value) || null)
const interviews = computed(() => {
  const value = experience.value.interviews || experience.value.items || []
  return Array.isArray(value) ? value.filter((item) => !item.card_type || item.card_type === 'EXPERIENCE_INTERVIEW') : []
})
const experienceCards = computed(() => Array.isArray(experience.value.cards) ? experience.value.cards : [])
const filteredMessages = computed(() => messages.value.filter((item) => item.content || item.text || item.business_cards?.length))

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value)
}
function messageTextOf(item: IntegrationMessage): string {
  return text(item.content || item.text || '')
}
function messageStatus(item: IntegrationMessage): string {
  return text(item.status || 'SENT').toUpperCase()
}

async function login() {
  error.value = ''
  try {
    const user = await client.auth.login(username.value, password.value)
    if (!['manager', 'admin'].includes(String(user?.role || ''))) {
      client.auth.clear()
      session.value = null
      throw new Error('该入口需要经理或管理员身份')
    }
    session.value = user
    password.value = ''
    await bootstrap()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '登录失败'
  }
}

async function bootstrap() {
  loading.value = true
  error.value = ''
  try {
    identities.value = await loadIdentities(client)
    if (identities.value[0]) await selectIdentity(identities.value[0].user_id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '接入环境加载失败'
  } finally {
    loading.value = false
  }
}

async function selectIdentity(userId: string) {
  selectedUserId.value = userId
  selectedSessionId.value = ''
  messages.value = []
  outbox.value = []
  experience.value = {}
  if (!userId) return
  sessions.value = await loadSessions(client, userId)
  if (sessions.value[0]) selectedSessionId.value = sessions.value[0].session_id
  await Promise.all([reloadMessages(), reloadOutbox(), reloadExperience()])
}

async function selectSession(sessionId: string) {
  selectedSessionId.value = sessionId
  await Promise.all([reloadMessages(), reloadOutbox()])
}

async function reloadMessages() {
  if (!selectedUserId.value || !selectedSessionId.value) {
    messages.value = []
    return
  }
  try {
    messages.value = await loadMessages(client, selectedSessionId.value, selectedUserId.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '消息读取失败'
  }
}

async function reloadOutbox() {
  if (!selectedUserId.value || !selectedSessionId.value) {
    outbox.value = []
    return
  }
  try {
    outbox.value = await loadOutbox(client, selectedSessionId.value, selectedUserId.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '出站记录读取失败'
  }
}

async function reloadExperience() {
  if (!selectedUserId.value) return
  try {
    experience.value = await loadExperienceHome(client, selectedUserId.value)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '经验任务读取失败'
  }
}

function newSession() {
  selectedSessionId.value = ''
  messages.value = []
  outbox.value = []
  notice.value = '已创建新的本地会话上下文，发送消息后由服务端正式受理。'
}

async function sendMessage() {
  if (!selectedUserId.value || !messageText.value.trim() || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    let attachments: unknown[] | undefined
    if (attachmentFile.value) {
      const attachment = await uploadSimulatorAttachment(client, selectedUserId.value, attachmentFile.value)
      if (attachment) attachments = [{ attachment_id: attachment.attachment_id || attachment.id, description: attachment.filename || '' }]
    }
    const response: any = await sendSimulatorMessage(client, {
      user_id: selectedUserId.value,
      content: messageText.value.trim(),
      external_message_id: `wecom-sim-${globalThis.crypto.randomUUID()}`,
      external_conversation_id: selectedSessionId.value || undefined,
      attachments,
    })
    messageText.value = ''
    attachmentFile.value = null
    if (response?.session_id) {
      selectedSessionId.value = response.session_id
      sessions.value = await loadSessions(client, selectedUserId.value)
    }
    notice.value = '消息已提交到内部系统接入环境，不会声明生产外部送达。'
    await Promise.all([reloadMessages(), reloadOutbox()])
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '消息提交失败'
  } finally {
    busy.value = false
  }
}

async function retryMessage(messageId?: string) {
  if (!messageId || !selectedUserId.value) return
  busy.value = true
  try {
    await retrySimulatorMessage(client, messageId, selectedUserId.value)
    await reloadMessages()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '消息重试失败'
  } finally {
    busy.value = false
  }
}

async function interviewAction(item: Record<string, any>, action: 'accept' | 'pause' | 'resume' | 'complete') {
  const id = text(item.id || item.interview_id)
  if (!id || !selectedUserId.value) return
  busy.value = true
  try {
    await experienceInterviewAction(client, id, action, selectedUserId.value)
    await reloadExperience()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '访谈操作失败'
  } finally {
    busy.value = false
  }
}

async function confirmCard(item: Record<string, any>) {
  const id = text(item.id || item.card_id || item.experience_card_id)
  if (!id || !selectedUserId.value) return
  busy.value = true
  try {
    await confirmExperienceCard(client, id, selectedUserId.value)
    await reloadExperience()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '经验卡确认失败'
  } finally {
    busy.value = false
  }
}

onMounted(() => {
  if (session.value && isManager.value) void bootstrap()
})
</script>

<template>
  <section class="integration-view">
    <StatePanel v-if="!session" state="empty" title="企业内部系统接入环境" message="该入口是经理操作的通知联调控制台，只读取真实 API 和 outbox，不声明生产外部渠道送达。">
      <form class="login-form" @submit.prevent="login">
        <label>经理账号<input v-model="username" autocomplete="username"></label>
        <label>密码<input v-model="password" type="password" autocomplete="current-password"></label>
        <p v-if="error" class="error-text">{{ error }}</p>
        <button type="submit">登录</button>
      </form>
    </StatePanel>

    <StatePanel v-else-if="!isManager" state="error" title="权限不足" message="当前账号不是经理或管理员，不能进入接入环境控制台。" />

    <template v-else>
      <header class="integration-header">
        <div>
          <p class="eyebrow">INTERNAL SYSTEM ACCESS</p>
          <h1>企业运营助手接入环境</h1>
          <p class="muted">消息进入正式 Agent 与数据链路；本页面不代表任何外部渠道已完成生产接入。</p>
        </div>
        <div class="header-status">
          <StatusBadge :label="session.username" tone="ai" />
          <StatusBadge label="内部系统接入环境" tone="info" />
        </div>
      </header>

      <p v-if="notice" class="notice">{{ notice }}</p>
      <StatePanel v-if="loading" state="loading" title="正在同步接入环境" />
      <StatePanel v-else-if="error" state="error" title="接入环境操作失败" :message="error" />
      <StatePanel v-else-if="!identities.length" state="empty" title="当前租户没有可用员工身份" message="请先在管理后台启用员工的内部系统接入身份。" />

      <div v-else class="layout">
        <aside class="identity-panel">
          <h2>员工身份</h2>
          <button v-for="identity in identities" :key="identity.user_id" :class="{ active: identity.user_id === selectedUserId }" @click="selectIdentity(identity.user_id)">
            <strong>{{ identity.display_name || identity.username }}</strong>
            <span>{{ identity.job_title || identity.role }} · {{ identity.department || '' }}</span>
          </button>
        </aside>

        <main class="workspace">
          <div class="tabs">
            <button :class="{ active: activeTab === 'sessions' }" @click="activeTab = 'sessions'">消息与会话</button>
            <button :class="{ active: activeTab === 'outbox' }" @click="activeTab = 'outbox'">审批与出站回执</button>
            <button :class="{ active: activeTab === 'experience' }" @click="activeTab = 'experience'">经验共创</button>
          </div>

          <section v-if="activeTab === 'sessions'" class="panel">
            <div class="panel-head">
              <div><h2>{{ selectedIdentity?.display_name || '员工' }}</h2><p class="muted">选择会话后发送消息；新会话会在服务端受理后创建。</p></div>
              <div class="actions">
                <select :value="selectedSessionId" @change="selectSession(($event.target as HTMLSelectElement).value)">
                  <option value="">新会话上下文</option>
                  <option v-for="item in sessions" :key="item.session_id" :value="item.session_id">{{ item.last_message || item.session_id }}</option>
                </select>
                <button @click="newSession">新建会话</button>
                <button @click="reloadMessages">刷新</button>
              </div>
            </div>

            <div class="message-list">
              <article v-for="message in filteredMessages" :key="message.message_id || `${message.created_at}:${messageTextOf(message)}`" class="message" :data-role="message.role">
                <div class="message-head"><strong>{{ message.role === 'user' ? (selectedIdentity?.display_name || '员工') : '企业运营助手' }}</strong><StatusBadge :label="messageStatus(message)" :tone="toneForStatus(messageStatus(message))" /></div>
                <p>{{ messageTextOf(message) }}</p>
                <button v-if="['FAILED', 'RETRY_REQUIRED', 'DEAD_LETTERED'].includes(messageStatus(message)) && message.message_id" :disabled="busy" @click="retryMessage(message.message_id)">从原消息重试</button>
              </article>
              <p v-if="!filteredMessages.length" class="muted">当前会话还没有消息。</p>
            </div>

            <form class="composer" @submit.prevent="sendMessage">
              <textarea v-model="messageText" rows="3" placeholder="输入要发送给企业运营助手的消息"></textarea>
              <div class="composer-actions">
                <input type="file" @change="attachmentFile = (($event.target as HTMLInputElement).files || [])[0] || null">
                <button type="submit" :disabled="busy || !messageText.trim()">发送</button>
              </div>
            </form>
          </section>

          <section v-else-if="activeTab === 'outbox'" class="panel">
            <div class="panel-head"><div><h2>审批与出站回执</h2><p class="muted">内容来自真实审批与出站账本，不等于外部生产渠道送达。</p></div><button @click="reloadOutbox">刷新</button></div>
            <article v-for="item in outbox" :key="item.id || `${item.created_at}:${item.message}`" class="outbox-card">
              <div class="message-head"><strong>{{ item.tool_label || '受控通知' }}</strong><StatusBadge :label="item.status || 'RECORDED'" :tone="toneForStatus(item.status || 'RECORDED')" /></div>
              <p>{{ item.message || '未填写通知内容' }}</p>
              <dl>
                <div><dt>送达状态</dt><dd>{{ deliveryStatusLabel(item.delivery_status || '') }}</dd></div>
                <div v-if="item.status_summary"><dt>当前进展</dt><dd>{{ item.status_summary }}</dd></div>
                <div v-if="item.review_comment"><dt>审批意见</dt><dd>{{ item.review_comment }}</dd></div>
                <div v-if="item.execution_error || item.delivery_error"><dt>失败原因</dt><dd>{{ item.execution_error || item.delivery_error }}</dd></div>
              </dl>
            </article>
            <p v-if="!outbox.length" class="muted">当前会话没有审批或出站回执。</p>
          </section>

          <section v-else class="panel">
            <div class="panel-head"><div><h2>经验共创</h2><p class="muted">这里只处理已授权员工的经验访谈和经验卡，不把外部渠道回执当成生产送达。</p></div><button @click="reloadExperience">刷新</button></div>
            <div class="experience-grid">
              <article v-for="item in interviews" :key="item.id || item.interview_id" class="experience-card">
                <div class="message-head"><strong>{{ item.title || '经验访谈' }}</strong><StatusBadge :label="item.status || 'PENDING'" :tone="toneForStatus(item.status || 'PENDING')" /></div>
                <p>{{ item.expert_name || selectedIdentity?.display_name }} · {{ item.progress || item.status_summary || '等待处理' }}</p>
                <div class="actions">
                  <button v-if="item.status === 'INVITED'" :disabled="busy" @click="interviewAction(item, 'accept')">接受访谈</button>
                  <button v-if="['IN_PROGRESS','ACCEPTED'].includes(item.status)" :disabled="busy" @click="interviewAction(item, 'pause')">暂停并保存</button>
                  <button v-if="item.status === 'PAUSED'" :disabled="busy" @click="interviewAction(item, 'resume')">恢复访谈</button>
                  <button v-if="['IN_PROGRESS','PAUSED'].includes(item.status)" :disabled="busy" @click="interviewAction(item, 'complete')">完成访谈</button>
                </div>
              </article>
              <article v-for="item in experienceCards" :key="item.id || item.card_id" class="experience-card">
                <div class="message-head"><strong>{{ item.title || '经验卡' }}</strong><StatusBadge :label="item.status || 'DRAFT'" :tone="toneForStatus(item.status || 'DRAFT')" /></div>
                <p>{{ item.summary || item.excerpt || '等待专家确认' }}</p>
                <div class="actions"><button v-if="item.status === 'EXPERT_CONFIRMED'" :disabled="busy" @click="confirmCard(item)">确认并提交审核</button></div>
              </article>
              <p v-if="!interviews.length && !experienceCards.length" class="muted">当前员工没有待处理的经验任务。</p>
            </div>
          </section>
        </main>
      </div>
    </template>
  </section>
</template>

<style scoped>
.integration-view { display: grid; gap: 18px; }
.integration-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; }
.integration-header h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.header-status { display: flex; gap: 8px; align-items: center; }
.login-form { display: grid; gap: 12px; width: min(420px, 100%); margin-top: 16px; }
.login-form label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
input, select, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button:disabled { opacity: 0.55; cursor: wait; }
.layout { display: grid; grid-template-columns: 260px minmax(0, 1fr); gap: 16px; align-items: start; }
.identity-panel, .panel { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.identity-panel h2, .panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.identity-panel button { display: grid; gap: 3px; text-align: left; border-color: transparent; background: transparent; }
.identity-panel button.active { border-color: var(--mp-color-primary); background: var(--mp-color-surface-elevated); }
.identity-panel span { color: var(--mp-color-mute); font-size: 12px; }
.workspace { min-width: 0; display: grid; gap: 12px; }
.tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.tabs button { border-color: var(--mp-color-hairline); }
.tabs button.active { border-color: var(--mp-color-primary); background: var(--mp-color-primary); }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.message-list { display: grid; gap: 10px; max-height: 480px; overflow: auto; }
.message, .outbox-card, .experience-card { display: grid; gap: 8px; padding: 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); background: var(--mp-color-surface-elevated); }
.message[data-role='user'] { border-color: color-mix(in srgb, var(--mp-color-primary) 42%, var(--mp-color-hairline)); }
.message-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.message p, .outbox-card p, .experience-card p { margin: 0; color: var(--mp-color-body); font-size: 13px; line-height: 1.5; }
.outbox-card dl { display: grid; gap: 6px; margin: 0; }
.outbox-card dl div { display: grid; grid-template-columns: 90px 1fr; gap: 8px; }
dt { color: var(--mp-color-mute); font-size: 12px; }
dd { margin: 0; color: var(--mp-color-body); font-size: 13px; }
.composer { display: grid; gap: 8px; }
.composer textarea { resize: vertical; }
.composer-actions { display: flex; justify-content: space-between; gap: 12px; }
.experience-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.error-text { color: var(--mp-color-danger); font-size: 13px; }
@media (max-width: 900px) { .integration-header, .panel-head { flex-direction: column; } .layout { grid-template-columns: 1fr; } .identity-panel { max-height: 260px; overflow: auto; } }
</style>
