<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import { loadAssignees, type AssigneeRecord } from '../operational'
import {
  createExpert,
  createInterview,
  deprecateExperienceCard,
  loadExperienceCard,
  loadExperienceCards,
  loadExperts,
  loadInterview,
  loadInterviews,
  publishExperienceCard,
  rejectExperienceCard,
  submitExperienceCard,
  type AuthorizationScopeType,
  type ExperienceCardRecord,
  type ExpertRecord,
  type InterviewRecord,
} from '../governance'

const experts = ref<ExpertRecord[]>([])
const interviews = ref<InterviewRecord[]>([])
const cards = ref<ExperienceCardRecord[]>([])
const assignees = ref<AssigneeRecord[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const query = ref('')
const cardFilter = ref('')
const interviewDetail = ref<InterviewRecord | null>(null)
const cardDetail = ref<ExperienceCardRecord | null>(null)
const expertOpen = ref(false)
const interviewOpen = ref(false)
const session = createApiClient().auth.read() as { venue_id?: string } | null
const expertForm = ref({
  user_id: '',
  display_name: '',
  department: '',
  job_title: '',
  years_experience: 5,
  expertiseText: '',
  authorization_statement: '',
})
const interviewForm = ref({
  expert_id: '',
  title: '',
  scope: 'VENUE',
  user_id: '',
})

const eligibleAssignees = computed(() => {
  const profiled = new Set(experts.value.map((item) => item.user_id))
  return assignees.value.filter((item) => !profiled.has(item.id))
})
const signedExperts = computed(() => experts.value.filter((item) => item.status === 'ACTIVE' && item.authorization_status === 'SIGNED'))
const filteredExperts = computed(() => experts.value.filter((item) => matches([item.display_name, item.job_title, item.department, (item.expertise || []).join(' ')])))
const filteredInterviews = computed(() => interviews.value.filter((item) => matches([item.title, item.expert_name, item.expert_job_title])))
const filteredCards = computed(() => cards.value.filter((item) => (!cardFilter.value || item.status === cardFilter.value) && matches([item.title, item.applicable_context, item.decision_rule, item.rationale, item.expert_name])))

function matches(values: Array<string | undefined>): boolean {
  const value = query.value.trim().toLowerCase()
  return !value || values.join(' ').toLowerCase().includes(value)
}
function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function label(value?: string): string {
  const labels: Record<string, string> = {
    ACTIVE: '在岗',
    INACTIVE: '已停用',
    PENDING: '待签署授权',
    SIGNED: '已签署授权',
    INVITED: '待专家接受',
    ACCEPTED: '专家已接受',
    IN_PROGRESS: '访谈进行中',
    PAUSED: '已暂停',
    COMPLETED: '已完成',
    DRAFT: '待专家完善',
    EXPERT_CONFIRMED: '专家已确认',
    IN_REVIEW: '审核中',
    PUBLISHED: '已发布',
    DEPRECATED: '已停用',
  }
  return labels[String(value || '').toUpperCase()] || value || '状态待确认'
}
function tone(value?: string): 'success' | 'warning' | 'danger' | 'neutral' | 'info' {
  const state = String(value || '').toUpperCase()
  if (['ACTIVE', 'SIGNED', 'PUBLISHED', 'COMPLETED'].includes(state)) return 'success'
  if (['PENDING', 'INVITED', 'ACCEPTED', 'IN_PROGRESS', 'IN_REVIEW'].includes(state)) return 'warning'
  if (['INACTIVE', 'DEPRECATED', 'REJECTED'].includes(state)) return 'danger'
  if (state === 'EXPERT_CONFIRMED') return 'info'
  return 'neutral'
}
function scopeText(scope: { scope_type?: string; scope_value?: string }): string {
  const type = String(scope.scope_type || '').toUpperCase()
  if (type === 'VENUE') return '当前场地全部员工'
  if (type === 'DEPARTMENT') return `部门：${scope.scope_value || '—'}`
  if (type === 'JOB_TITLE') return `岗位：${scope.scope_value || '—'}`
  if (type === 'ROLE') return `角色：${scope.scope_value || '—'}`
  if (type === 'USER') {
    const user = assignees.value.find((item) => item.id === scope.scope_value)
    return `员工：${user?.display_name || scope.scope_value || '—'}`
  }
  return '指定业务范围'
}
function setExpertise(value: string) {
  expertForm.value.expertiseText = value
}
function selectAssignee(userId: string) {
  expertForm.value.user_id = userId
  const user = eligibleAssignees.value.find((item) => item.id === userId)
  if (user) expertForm.value.display_name = user.display_name || user.username || ''
}
function openInterview(expertId = '') {
  interviewForm.value = { expert_id: expertId, title: '', scope: 'VENUE', user_id: '' }
  interviewOpen.value = true
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const client = createApiClient()
    const [nextExperts, nextInterviews, nextCards, nextAssignees] = await Promise.all([
      loadExperts(client),
      loadInterviews(client),
      loadExperienceCards(client),
      loadAssignees(client),
    ])
    experts.value = nextExperts
    interviews.value = nextInterviews
    cards.value = nextCards
    assignees.value = nextAssignees
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '专家经验读取失败'
  } finally {
    loading.value = false
  }
}
async function saveExpert() {
  busy.value = true
  error.value = ''
  try {
    await createExpert(createApiClient(), {
      user_id: expertForm.value.user_id,
      display_name: expertForm.value.display_name.trim(),
      department: expertForm.value.department.trim(),
      job_title: expertForm.value.job_title.trim(),
      years_experience: Number(expertForm.value.years_experience || 0),
      expertise: expertForm.value.expertiseText.split(/[,，、]/).map((item) => item.trim()).filter(Boolean),
      authorization_status: 'SIGNED',
      authorization_statement: expertForm.value.authorization_statement.trim(),
    })
    notice.value = '专家档案已保存'
    expertOpen.value = false
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '专家档案保存失败'
  } finally {
    busy.value = false
  }
}
async function saveInterview() {
  busy.value = true
  error.value = ''
  try {
    const [scopeType, scopeValue] = interviewForm.value.scope.split(':')
    const authorizationScope = scopeType === 'VENUE'
      ? { scope_type: 'VENUE' as AuthorizationScopeType, scope_value: session?.venue_id || '' }
      : { scope_type: scopeType as AuthorizationScopeType, scope_value: scopeValue || interviewForm.value.user_id }
    await createInterview(createApiClient(), {
      expert_id: interviewForm.value.expert_id,
      title: interviewForm.value.title.trim(),
      authorization_scopes: [authorizationScope],
    })
    notice.value = '访谈邀请已发送'
    interviewOpen.value = false
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '访谈邀请发送失败'
  } finally {
    busy.value = false
  }
}
async function openInterviewDetail(item: InterviewRecord) {
  busy.value = true
  try {
    interviewDetail.value = await loadInterview(createApiClient(), item.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '访谈详情读取失败'
  } finally {
    busy.value = false
  }
}
async function openCardDetail(item: ExperienceCardRecord) {
  busy.value = true
  try {
    cardDetail.value = await loadExperienceCard(createApiClient(), item.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '经验详情读取失败'
  } finally {
    busy.value = false
  }
}
async function reviewCard(item: ExperienceCardRecord, action: 'submit' | 'reject' | 'publish' | 'deprecate') {
  let comment = ''
  if (action !== 'submit') {
    const answer = globalThis.prompt(action === 'reject' ? '请输入驳回原因' : action === 'deprecate' ? '请输入停用原因' : '发布说明（可选）', '')
    if (answer === null) return
    comment = answer.trim()
    if (action !== 'publish' && comment.length < 2) {
      error.value = '驳回或停用必须填写至少 2 个字符的原因'
      return
    }
  } else if (!globalThis.confirm('确认将该经验提交审核？')) {
    return
  }
  busy.value = true
  error.value = ''
  try {
    const client = createApiClient()
    if (action === 'submit') await submitExperienceCard(client, item.id)
    if (action === 'reject') await rejectExperienceCard(client, item.id, comment)
    if (action === 'publish') await publishExperienceCard(client, item.id, comment)
    if (action === 'deprecate') await deprecateExperienceCard(client, item.id, comment)
    notice.value = action === 'submit' ? '经验已进入审核' : action === 'reject' ? '经验已退回专家修改' : action === 'publish' ? '经验已发布并进入检索服务' : '经验已停用并移出检索服务'
    cardDetail.value = null
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '经验状态更新失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="experience-workspace">
    <header class="workspace-head">
      <div><p class="eyebrow">EXPERT EXPERIENCE</p><h1>专家经验</h1><p class="muted">维护专家档案、发起经验访谈，并将专家确认的经验审核后发布给当前场地员工使用。</p></div>
      <div class="actions"><button :disabled="busy" @click="openInterview()">发起访谈</button><button class="primary" :disabled="busy" @click="expertOpen = true">新增专家</button></div>
    </header>
    <StatePanel v-if="loading" state="loading" title="正在读取专家经验" />
    <StatePanel v-else-if="error" state="error" title="专家经验操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <div class="toolbar"><select v-model="cardFilter"><option value="">全部经验状态</option><option value="DRAFT">待专家完善</option><option value="EXPERT_CONFIRMED">专家已确认</option><option value="IN_REVIEW">审核中</option><option value="PUBLISHED">已发布</option><option value="DEPRECATED">已停用</option></select><input v-model="query" placeholder="搜索专家姓名、岗位、访谈主题或经验摘要"></div>

    <article class="panel">
      <div class="panel-head"><h2>专家名录</h2><span class="muted">{{ filteredExperts.length }} 位</span></div>
      <div class="table-wrap"><table><thead><tr><th>专家</th><th>部门 / 岗位</th><th>从业经验</th><th>擅长领域</th><th>状态</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in filteredExperts" :key="item.id"><td><strong>{{ item.display_name || '未命名专家' }}</strong><small><StatusBadge :label="label(item.authorization_status)" :tone="tone(item.authorization_status)" /></small></td><td>{{ item.department || '未填写部门' }}<small>{{ item.job_title || '未填写岗位' }}</small></td><td>{{ item.years_experience || 0 }} 年</td><td>{{ (item.expertise || []).join('、') || '待补充' }}</td><td><StatusBadge :label="label(item.status)" :tone="tone(item.status)" /></td><td><button v-if="item.status === 'ACTIVE' && item.authorization_status === 'SIGNED'" @click="openInterview(item.id)">发起访谈</button><span v-else class="muted">需完成授权</span></td></tr>
        <tr v-if="!filteredExperts.length"><td colspan="6" class="empty">暂无专家档案。从当前场地员工中新增专家后即可发起访谈。</td></tr>
      </tbody></table></div>
    </article>

    <article class="panel">
      <div class="panel-head"><h2>经验访谈</h2><span class="muted">{{ filteredInterviews.length }} 场</span></div>
      <div class="table-wrap"><table><thead><tr><th>更新时间</th><th>访谈主题</th><th>专家</th><th>进度</th><th>状态</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in filteredInterviews" :key="item.id"><td class="mono">{{ format(item.updated_at) }}</td><td>{{ item.title || '未命名访谈' }}</td><td>{{ item.expert_name || '未关联专家' }}<small>{{ item.expert_job_title || '' }}</small></td><td>{{ item.progress?.answered || 0 }} / {{ item.progress?.total || 0 }} 题</td><td><StatusBadge :label="label(item.status)" :tone="tone(item.status)" /></td><td><button @click="openInterviewDetail(item)">查看进度</button></td></tr>
        <tr v-if="!filteredInterviews.length"><td colspan="6" class="empty">暂无经验访谈。选择一位在岗专家发起经验访谈。</td></tr>
      </tbody></table></div>
    </article>

    <article class="panel">
      <div class="panel-head"><h2>经验资产</h2><span class="muted">{{ filteredCards.length }} 条</span></div>
      <div class="table-wrap"><table><thead><tr><th>更新时间</th><th>经验主题 / 摘要</th><th>专家</th><th>版本</th><th>状态</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in filteredCards" :key="item.id"><td class="mono">{{ format(item.updated_at) }}</td><td><strong>{{ item.title || '未命名经验' }}</strong><small>{{ (item.applicable_context || item.decision_rule || item.rationale || '内容待专家完善').slice(0, 120) }}</small></td><td>{{ item.expert_name || '未关联专家' }}<small>{{ item.expert_job_title || '' }}</small></td><td>第 {{ item.current_version || 1 }} 版</td><td><StatusBadge :label="label(item.status)" :tone="tone(item.status)" /></td><td class="row-actions"><button @click="openCardDetail(item)">查看</button><button v-if="item.status === 'EXPERT_CONFIRMED'" class="primary" @click="reviewCard(item, 'submit')">提交审核</button><button v-if="item.status === 'IN_REVIEW'" class="danger" @click="reviewCard(item, 'reject')">驳回修改</button><button v-if="item.status === 'IN_REVIEW'" @click="reviewCard(item, 'publish')">批准发布</button><button v-if="item.status === 'PUBLISHED'" class="danger" @click="reviewCard(item, 'deprecate')">停用</button></td></tr>
        <tr v-if="!filteredCards.length"><td colspan="6" class="empty">暂无符合条件的经验资产。专家完成访谈并确认后，经验会进入这里等待审核。</td></tr>
      </tbody></table></div>
    </article>

    <form v-if="expertOpen" class="panel form-panel" @submit.prevent="saveExpert">
      <div class="panel-head"><h2>新增专家</h2><button type="button" class="ghost" @click="expertOpen = false">取消</button></div>
      <label>关联员工<select v-model="expertForm.user_id" required @change="selectAssignee(expertForm.user_id)"><option value="" disabled>选择在岗员工</option><option v-for="user in eligibleAssignees" :key="user.id" :value="user.id">{{ user.display_name || user.username }} · {{ user.role }}</option></select></label>
      <label>专家姓名<input v-model="expertForm.display_name" required maxlength="80"></label>
      <label>所属部门<input v-model="expertForm.department" required maxlength="120"></label>
      <label>岗位<input v-model="expertForm.job_title" required maxlength="120"></label>
      <label>从业年限<input v-model.number="expertForm.years_experience" type="number" min="0" max="80" required></label>
      <label>擅长领域<input :value="expertForm.expertiseText" @input="setExpertise(($event.target as HTMLInputElement).value)" required placeholder="客流疏导、突发事件处置"></label>
      <label class="wide">经验使用授权声明<textarea v-model="expertForm.authorization_statement" required minlength="10" maxlength="2000" rows="3"></textarea></label>
      <p class="muted">授权声明必须由专家确认，前端不代替专家签署；未授权专家不能发起访谈。</p>
      <button type="submit" :disabled="busy">保存专家档案</button>
    </form>

    <form v-if="interviewOpen" class="panel form-panel" @submit.prevent="saveInterview">
      <div class="panel-head"><h2>发起经验访谈</h2><button type="button" class="ghost" @click="interviewOpen = false">取消</button></div>
      <label>受访专家<select v-model="interviewForm.expert_id" required><option value="" disabled>选择已授权专家</option><option v-for="item in signedExperts" :key="item.id" :value="item.id">{{ item.display_name }} · {{ item.job_title }}</option></select></label>
      <label>访谈主题<input v-model="interviewForm.title" required minlength="2" maxlength="200"></label>
      <label>经验授权范围<select v-model="interviewForm.scope"><option value="VENUE">当前场地全部员工</option><option value="ROLE:manager">指定角色：值班经理</option><option value="ROLE:operator">指定角色：现场操作员</option><option v-for="user in assignees" :key="`user-${user.id}`" :value="`USER:${user.id}`">指定员工：{{ user.display_name || user.username }}</option></select></label>
      <p class="muted">仅符合授权范围的员工可以通过 Agent 检索和引用这次访谈沉淀的经验。</p>
      <button type="submit" :disabled="busy">发送访谈邀请</button>
    </form>

    <article v-if="interviewDetail" class="panel detail-panel">
      <div class="panel-head"><h2>访谈进度：{{ interviewDetail.title || '未命名访谈' }}</h2><button class="ghost" @click="interviewDetail = null">关闭</button></div>
      <dl><dt>受访专家</dt><dd>{{ interviewDetail.expert_name || '未关联专家' }} · {{ interviewDetail.expert_job_title || '岗位待补充' }}</dd><dt>当前状态</dt><dd><StatusBadge :label="label(interviewDetail.status)" :tone="tone(interviewDetail.status)" /></dd><dt>完成进度</dt><dd>{{ interviewDetail.progress?.answered || 0 }} / {{ interviewDetail.progress?.total || 0 }} 题（{{ interviewDetail.progress?.percent || 0 }}%）</dd><dt>经验授权</dt><dd>{{ (interviewDetail.authorization_scopes || []).map(scopeText).join('；') || '授权范围待确认' }}</dd></dl>
      <div class="feed"><h3>访谈记录</h3><article v-for="turn in interviewDetail.turns || []" :key="turn.turn_number" class="feed-item"><strong>第 {{ turn.turn_number }} 题 · {{ turn.question_text || '' }}</strong><p>{{ turn.answer_text || '专家尚未回答' }}</p><small v-if="turn.source_excerpt">现场原话：{{ turn.source_excerpt }}</small></article><p v-if="!interviewDetail.turns?.length" class="muted">专家尚未开始回答；邀请已保存在系统中。</p></div>
    </article>

    <article v-if="cardDetail" class="panel detail-panel">
      <div class="panel-head"><h2>经验详情：{{ cardDetail.title || '未命名经验' }}</h2><button class="ghost" @click="cardDetail = null">关闭</button></div>
      <dl><dt>贡献专家</dt><dd>{{ cardDetail.expert_name || '未关联专家' }} · {{ cardDetail.expert_job_title || '岗位待补充' }}</dd><dt>当前状态</dt><dd><StatusBadge :label="label(cardDetail.status)" :tone="tone(cardDetail.status)" /></dd><dt>适用范围</dt><dd>{{ (cardDetail.authorization_scopes || []).map(scopeText).join('；') || '授权范围待确认' }}</dd><dt>采用情况</dt><dd>检索 {{ cardDetail.usage_summary?.retrieved || 0 }} 次 · 引用 {{ cardDetail.usage_summary?.referenced || 0 }} 次 · 反馈 {{ cardDetail.usage_summary?.feedback || 0 }} 次</dd></dl>
      <div class="sections"><article><h3>适用情境</h3><p>{{ cardDetail.applicable_context || '待补充' }}</p></article><article><h3>观察信号</h3><p>{{ (cardDetail.signals || []).join('、') || '待补充' }}</p></article><article><h3>判断规则</h3><p>{{ cardDetail.decision_rule || '待补充' }}</p></article><article><h3>建议动作</h3><p>{{ (cardDetail.recommended_actions || []).join('、') || '待补充' }}</p></article><article><h3>判断依据</h3><p>{{ cardDetail.rationale || '待补充' }}</p></article><article><h3>禁止事项</h3><p>{{ (cardDetail.prohibitions || []).join('、') || '待补充' }}</p></article><article><h3>例外情况</h3><p>{{ (cardDetail.exceptions || []).join('、') || '待补充' }}</p></article><article><h3>来源摘录</h3><p>{{ (cardDetail.source_excerpts || []).join('；') || '待补充' }}</p></article></div>
    </article>
  </section>
</template>

<style scoped>
.experience-workspace { display: grid; gap: 18px; }
.workspace-head, .actions, .panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.toolbar { display: flex; gap: 10px; }
.toolbar input { flex: 1; }
.panel { display: grid; gap: 10px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2, .panel h3 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
input, select, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.primary { border-color: var(--mp-color-primary); color: white; background: var(--mp-color-primary); }
button.danger { border-color: var(--mp-color-danger); color: var(--mp-color-danger); }
button.ghost { border-color: transparent; background: transparent; }
button:disabled { opacity: .55; cursor: wait; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small, .feed-item small { display: block; color: var(--mp-color-mute); font-size: 12px; }
.row-actions { display: flex; flex-wrap: wrap; gap: 6px; }
.form-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-panel label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.form-panel .panel-head, .form-panel .wide, .form-panel > button, .form-panel > p { grid-column: 1 / -1; }
.detail-panel dl { display: grid; grid-template-columns: 140px 1fr; gap: 8px 12px; margin: 0; color: var(--mp-color-body); font-size: 13px; }
.detail-panel dt { color: var(--mp-color-mute); }
.detail-panel dd { margin: 0; }
.feed { display: grid; gap: 10px; }
.feed-item, .sections article { padding: 12px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-md); }
.feed-item p, .sections p { margin: 6px 0 0; color: var(--mp-color-body); white-space: pre-wrap; }
.sections { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .actions, .toolbar { flex-direction: column; } .form-panel, .sections { grid-template-columns: 1fr; } }
</style>
