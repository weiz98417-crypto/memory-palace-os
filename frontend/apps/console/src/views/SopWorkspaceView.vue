<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  createSop,
  formatSopTimestamp,
  loadSop,
  loadSops,
  publishSop,
  rejectSop,
  submitSop,
  updateSop,
  type SopCreate,
  type SopRecord,
  type SopUpdate,
} from '../governance'
import ModalShell from '../components/ModalShell.vue'

const sops = ref<SopRecord[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const filter = ref('')
const query = ref('')
const formOpen = ref(false)
const editingId = ref<number | null>(null)
const detail = ref<SopRecord | null>(null)
const form = ref<SopCreate & { change_note: string }>({ title: '', content: '', category: '通用', priority: 3, source_event_id: null, version: '1.0', change_note: '' })

const filtered = computed(() => sops.value.filter((item) => {
  const text = [item.title, item.category, item.content, item.source_event_id].join(' ').toLowerCase()
  return (!filter.value || item.status === filter.value) && (!query.value.trim() || text.includes(query.value.trim().toLowerCase()))
}))

function tone(value?: string): 'primary' | 'info' | 'success' | 'warning' | 'danger' | 'neutral' {
  const status = String(value || '').toUpperCase()
  if (status === 'DRAFT') return 'primary'
  if (status === 'IN_REVIEW') return 'info'
  if (status === 'PUBLISHED') return 'success'
  if (status === 'REJECTED') return 'danger'
  return 'neutral'
}
function reset() {
  editingId.value = null
  form.value = { title: '', content: '', category: '通用', priority: 3, source_event_id: null, version: '1.0', change_note: '' }
}
function openCreate() {
  reset()
  formOpen.value = true
}
function openEdit(item: SopRecord) {
  editingId.value = item.id
  form.value = {
    title: item.title,
    content: item.content,
    category: item.category || '通用',
    priority: item.priority ?? 3,
    source_event_id: item.source_event_id || null,
    version: item.version || '1.0',
    change_note: '',
  }
  formOpen.value = true
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    sops.value = await loadSops(createApiClient())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'SOP 读取失败'
  } finally {
    loading.value = false
  }
}
async function save() {
  busy.value = true
  error.value = ''
  try {
    const client = createApiClient()
    if (editingId.value !== null) {
      const body: SopUpdate = {
        title: form.value.title.trim(),
        content: form.value.content.trim(),
        category: form.value.category.trim() || '通用',
        priority: Number(form.value.priority),
        source_event_id: form.value.source_event_id?.trim() || null,
        change_note: form.value.change_note.trim() || null,
      }
      await updateSop(client, editingId.value, body)
    } else {
      await createSop(client, {
        title: form.value.title.trim(),
        content: form.value.content.trim(),
        category: form.value.category.trim() || '通用',
        priority: Number(form.value.priority),
        source_event_id: form.value.source_event_id?.trim() || null,
        version: form.value.version || '1.0',
      })
    }
    notice.value = 'SOP 草稿已保存'
    formOpen.value = false
    reset()
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'SOP 保存失败'
  } finally {
    busy.value = false
  }
}
async function openDetail(item: SopRecord) {
  busy.value = true
  try {
    detail.value = await loadSop(createApiClient(), item.id)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'SOP 详情读取失败'
  } finally {
    busy.value = false
  }
}
async function action(item: SopRecord, actionName: 'submit' | 'publish' | 'reject') {
  let comment = ''
  if (actionName === 'reject') {
    const answer = globalThis.prompt('请输入驳回原因', '')?.trim() || ''
    if (answer.length < 2) {
      error.value = '驳回原因至少需要 2 个字符'
      return
    }
    comment = answer
  } else if (actionName === 'publish') {
    const answer = globalThis.prompt('发布意见（可选）', '')
    if (answer === null) return
    comment = answer.trim()
  } else if (!globalThis.confirm('确认提交该 SOP 进入审核？')) {
    return
  }
  busy.value = true
  error.value = ''
  try {
    const client = createApiClient()
    if (actionName === 'submit') await submitSop(client, item.id)
    if (actionName === 'publish') await publishSop(client, item.id, comment)
    if (actionName === 'reject') await rejectSop(client, item.id, comment)
    notice.value = actionName === 'submit' ? '已提交审核' : actionName === 'publish' ? 'SOP 已发布并写入知识库' : 'SOP 已驳回'
    detail.value = null
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : 'SOP 状态更新失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="sop-workspace">
    <header class="workspace-head"><div><p class="eyebrow">STANDARD WORK</p><h1>SOP 中心</h1><p class="muted">从草稿、编辑、提交审核、批准发布到驳回修改，保留版本与来源事件。</p></div><button class="primary" :disabled="busy" @click="openCreate">创建 SOP 草稿</button></header>
    <StatePanel v-if="loading" state="loading" title="正在读取 SOP" />
    <StatePanel v-else-if="error" state="error" title="SOP 操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <div class="toolbar"><select v-model="filter"><option value="">全部状态</option><option value="DRAFT">草稿</option><option value="IN_REVIEW">审核中</option><option value="PUBLISHED">已发布</option><option value="REJECTED">已驳回</option></select><input v-model="query" placeholder="搜索标题、分类或正文"></div>

    <article class="panel">
      <div class="panel-head"><h2>SOP 资产</h2><span class="muted">{{ filtered.length }} 条</span></div>
      <div class="table-wrap"><table><thead><tr><th>更新时间</th><th>SOP</th><th>分类 / 优先级</th><th>版本</th><th>状态</th><th>来源事件</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in filtered" :key="item.id"><td class="mono">{{ formatSopTimestamp(item.updated_at) }}</td><td><strong>{{ item.title }}</strong><small>{{ item.content.slice(0, 100) }}</small></td><td>{{ item.category || '通用' }} / P{{ item.priority ?? 3 }}</td><td>{{ item.version || '1.0' }}</td><td><StatusBadge :label="item.status || 'DRAFT'" :tone="tone(item.status)" /></td><td class="mono">{{ item.source_event_id || '—' }}</td><td class="row-actions"><button @click="openDetail(item)">详情</button><button v-if="['DRAFT', 'REJECTED'].includes(item.status || '')" @click="openEdit(item)">编辑</button><button v-if="['DRAFT', 'REJECTED'].includes(item.status || '')" class="primary" @click="action(item, 'submit')">提交审核</button><button v-if="item.status === 'IN_REVIEW'" @click="action(item, 'publish')">发布</button><button v-if="item.status === 'IN_REVIEW'" class="danger" @click="action(item, 'reject')">驳回</button></td></tr>
        <tr v-if="!filtered.length"><td colspan="7" class="empty">暂无 SOP。创建草稿并完成审核发布。</td></tr>
      </tbody></table></div>
    </article>

    <ModalShell v-if="formOpen" label="SOP 编辑" @close="formOpen = false">
      <form class="panel form-panel" @submit.prevent="save">
      <div class="panel-head"><h2>{{ editingId !== null ? '编辑 SOP 草稿' : '创建 SOP 草稿' }}</h2><button type="button" class="ghost" @click="formOpen = false">取消</button></div>
      <label>标题<input v-model="form.title" required minlength="2" maxlength="200"></label>
      <label>分类<input v-model="form.category" required maxlength="80"></label>
      <label>优先级<select v-model.number="form.priority"><option :value="0">P0</option><option :value="1">P1</option><option :value="2">P2</option><option :value="3">P3</option><option :value="4">P4</option></select></label>
      <label>来源事件 ID<input v-model="form.source_event_id" maxlength="128" placeholder="可选"></label>
      <label v-if="editingId === null">初始版本<input v-model="form.version" required pattern="^[1-9]\d{0,2}\.\d{1,2}$"></label>
      <label v-else>修改说明<input v-model="form.change_note" maxlength="500" placeholder="本次修改原因"></label>
      <label class="wide">正文<textarea v-model="form.content" required minlength="10" maxlength="30000" rows="10"></textarea></label>
      <button type="submit" :disabled="busy">保存 SOP 草稿</button>
    </form>
    </ModalShell>

    <ModalShell v-if="detail" label="SOP 详情" @close="detail = null">
      <article class="panel detail-panel">
      <div class="panel-head"><h2>{{ detail.title }}</h2><button class="ghost" @click="detail = null">关闭</button></div>
      <dl><dt>状态</dt><dd><StatusBadge :label="detail.status || 'DRAFT'" :tone="tone(detail.status)" /></dd><dt>版本</dt><dd>{{ detail.version || '1.0' }}</dd><dt>来源事件</dt><dd class="mono">{{ detail.source_event_id || '—' }}</dd></dl>
      <section><h3>正文</h3><p class="content">{{ detail.content }}</p></section>
      <section><h3>版本记录</h3><article v-for="(version, index) in detail.versions || []" :key="`${version.version}-${index}`" class="version"><strong>{{ version.version || '—' }} · {{ version.status || '—' }}</strong><span>{{ formatSopTimestamp(version.created_at) }} · {{ version.change_note || '—' }}</span></article><p v-if="!detail.versions?.length" class="muted">暂无版本记录。</p></section>
    </article>
    </ModalShell>
  </section>
</template>

<style scoped>
.sop-workspace { display: grid; gap: 18px; }
.workspace-head, .panel-head, .row-actions { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
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
td small { display: block; color: var(--mp-color-mute); font-size: 12px; }
.form-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-panel label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.form-panel .panel-head, .form-panel .wide, .form-panel > button { grid-column: 1 / -1; }
.detail-panel dl { display: grid; grid-template-columns: 120px 1fr; gap: 8px 12px; margin: 0; color: var(--mp-color-body); font-size: 13px; }
.detail-panel dt { color: var(--mp-color-mute); }
.detail-panel dd { margin: 0; }
.content { margin: 6px 0 0; color: var(--mp-color-body); white-space: pre-wrap; }
.version { display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--mp-color-hairline); color: var(--mp-color-body); font-size: 13px; }
.version span { color: var(--mp-color-mute); }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .toolbar, .row-actions, .version { flex-direction: column; } .form-panel { grid-template-columns: 1fr; } }
</style>
