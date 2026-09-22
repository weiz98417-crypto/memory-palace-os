<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { createApiClient } from '@memory-palace/api-client'
import { StatePanel, StatusBadge } from '@memory-palace/domain-ui'
import {
  createKnowledge,
  deleteKnowledge,
  importKnowledge,
  loadKnowledge,
  loadKnowledgeEntry,
  rebuildKnowledgeIndex,
  searchKnowledge,
  updateKnowledge,
  type KnowledgeRecord,
  type KnowledgeSearchResult,
  type KnowledgeUpsert,
} from '../governance'
import ModalShell from '../components/ModalShell.vue'

const knowledge = ref<KnowledgeRecord[]>([])
const loading = ref(false)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const filter = ref('')
const searchQuery = ref('')
const searchResults = ref<KnowledgeSearchResult[]>([])
const searchPending = ref(false)
const showForm = ref(false)
const importOpen = ref(false)
const importPayload = ref('')
const editingId = ref('')
const session = createApiClient().auth.read() as { role?: string } | null
const isAdmin = computed(() => session?.role === 'admin')
const form = ref<KnowledgeUpsert>({ title: '', content: '', category: '通用', tags: [] })

const filteredKnowledge = computed(() => {
  const query = filter.value.trim().toLowerCase()
  if (!query) return knowledge.value
  return knowledge.value.filter((item) => [item.title, item.content, item.category, (item.tags || []).join(' ')].join(' ').toLowerCase().includes(query))
})

function format(value?: number): string {
  return value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '—'
}
function resetForm() {
  editingId.value = ''
  form.value = { title: '', content: '', category: '通用', tags: [] }
}
function openCreate() {
  resetForm()
  showForm.value = true
}
async function openEdit(item: KnowledgeRecord) {
  busy.value = true
  try {
    const detail = await loadKnowledgeEntry(createApiClient(), item.id)
    editingId.value = detail.id
    form.value = {
      title: detail.title,
      content: detail.content,
      category: detail.category || '通用',
      tags: detail.tags || [],
    }
    showForm.value = true
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '知识详情读取失败'
  } finally {
    busy.value = false
  }
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    knowledge.value = await loadKnowledge(createApiClient())
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '知识库读取失败'
  } finally {
    loading.value = false
  }
}
async function save() {
  busy.value = true
  error.value = ''
  try {
    const body: KnowledgeUpsert = {
      title: form.value.title.trim(),
      content: form.value.content.trim(),
      category: form.value.category.trim() || '通用',
      tags: form.value.tags.map((tag) => tag.trim()).filter(Boolean),
    }
    if (editingId.value) await updateKnowledge(createApiClient(), editingId.value, body)
    else await createKnowledge(createApiClient(), body)
    notice.value = editingId.value ? '知识已更新并同步索引' : '知识已新增并同步索引'
    showForm.value = false
    resetForm()
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '知识保存失败'
  } finally {
    busy.value = false
  }
}
async function remove(item: KnowledgeRecord) {
  if (!globalThis.confirm(`确认删除「${item.title}」及其向量索引？`)) return
  busy.value = true
  try {
    await deleteKnowledge(createApiClient(), item.id)
    notice.value = '知识已删除'
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '知识删除失败'
  } finally {
    busy.value = false
  }
}
async function runSearch() {
  const query = searchQuery.value.trim()
  if (query.length < 2) {
    error.value = '检索问题至少需要 2 个字符'
    return
  }
  searchPending.value = true
  error.value = ''
  try {
    searchResults.value = await searchKnowledge(createApiClient(), query)
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '知识检索失败'
  } finally {
    searchPending.value = false
  }
}
async function submitImport() {
  busy.value = true
  error.value = ''
  try {
    const parsed: unknown = JSON.parse(importPayload.value)
    if (!Array.isArray(parsed)) throw new Error('批量导入需要 JSON 数组')
    await importKnowledge(createApiClient(), parsed as KnowledgeUpsert[])
    notice.value = '知识批次导入成功'
    importOpen.value = false
    importPayload.value = ''
    await load()
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '知识批量导入失败'
  } finally {
    busy.value = false
  }
}
async function rebuildIndex() {
  if (!globalThis.confirm('确认以 PostgreSQL 当前数据为准重建知识索引？')) return
  busy.value = true
  try {
    const result = await rebuildKnowledgeIndex(createApiClient()) as { rebuilt?: number }
    notice.value = `已重建 ${result.rebuilt ?? 0} 条索引`
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '知识索引重建失败'
  } finally {
    busy.value = false
  }
}
onMounted(load)
</script>

<template>
  <section class="knowledge-workspace">
    <header class="workspace-head">
      <div><p class="eyebrow">VERIFIED MEMORY</p><h1>知识库</h1><p class="muted">结构化知识与 PostgreSQL pgvector 索引保持一致，支持来源、版本、相关度、导入和索引重建。</p></div>
      <div class="actions">
        <button :disabled="busy" @click="importOpen = true">批量导入</button>
        <button v-if="isAdmin" :disabled="busy" @click="rebuildIndex">重建索引</button>
        <button class="primary" :disabled="busy" @click="openCreate">新增知识</button>
      </div>
    </header>
    <StatePanel v-if="loading" state="loading" title="正在读取知识库" />
    <StatePanel v-else-if="error" state="error" title="知识库操作失败" :message="error" />
    <p v-else-if="notice" class="notice">{{ notice }}</p>

    <section class="panel search-panel">
      <div class="panel-head"><div><h2>向量检索</h2><small class="muted">pgvector 余弦相似度</small></div><StatusBadge label="PostgreSQL 索引" tone="info" /></div>
      <form class="toolbar" @submit.prevent="runSearch"><input v-model="searchQuery" required minlength="2" placeholder="输入业务问题进行语义检索"><button class="primary" :disabled="searchPending">{{ searchPending ? '检索中' : '检索' }}</button></form>
      <div v-if="searchResults.length" class="results">
        <article v-for="(result, index) in searchResults" :key="String(result.id || index)" class="result-card">
          <div class="card-head"><strong>{{ result.metadata?.title || result.id || '检索结果' }}</strong><StatusBadge :label="`${Math.round(Number(result.similarity ?? result.score ?? 0) * 100)}%`" tone="info" /></div>
          <p>{{ result.document || result.content || '未提供命中内容' }}</p>
          <small>来源 {{ result.metadata?.source_type || '—' }} · 版本 {{ result.metadata?.version ?? '—' }}</small>
        </article>
      </div>
      <p v-else class="muted">输入业务问题后，结果显示真实 pgvector 命中内容；没有达到阈值时不会伪造结果。</p>
    </section>

    <article class="panel">
      <div class="panel-head"><h2>知识条目</h2><span class="muted">{{ filteredKnowledge.length }} 条</span></div>
      <input v-model="filter" placeholder="按标题、正文、分类或标签筛选">
      <div class="table-wrap"><table><thead><tr><th>更新时间</th><th>标题</th><th>分类</th><th>来源</th><th>版本</th><th>标签</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in filteredKnowledge" :key="item.id">
          <td class="mono">{{ format(item.updated_at) }}</td>
          <td><strong>{{ item.title }}</strong><small>{{ item.content.slice(0, 100) }}</small></td>
          <td>{{ item.category || '通用' }}</td>
          <td><StatusBadge :label="item.source_type || 'MANUAL'" tone="neutral" /></td>
          <td>v{{ item.version ?? 1 }}</td>
          <td>{{ (item.tags || []).join(', ') || '—' }}</td>
          <td class="row-actions"><button :disabled="busy" @click="openEdit(item)">编辑</button><button class="danger" :disabled="busy" @click="remove(item)">删除</button></td>
        </tr>
        <tr v-if="!filteredKnowledge.length"><td colspan="7" class="empty">暂无知识条目。新增知识或从已闭环事件沉淀经验。</td></tr>
      </tbody></table></div>
    </article>

    <ModalShell v-if="showForm" label="知识编辑" @close="showForm = false">
      <form class="panel form-panel" @submit.prevent="save">
      <div class="panel-head"><h2>{{ editingId ? '编辑知识' : '新增知识' }}</h2><button type="button" class="ghost" @click="showForm = false">取消</button></div>
      <label>标题<input v-model="form.title" required minlength="2" maxlength="200"></label>
      <label>分类<input v-model="form.category" required maxlength="80"></label>
      <label>标签（逗号分隔）<input :value="form.tags.join(', ')" @input="form.tags = ($event.target as HTMLInputElement).value.split(',').map((tag) => tag.trim()).filter(Boolean)"></label>
      <label class="wide">正文<textarea v-model="form.content" required minlength="5" maxlength="20000" rows="8"></textarea></label>
      <button type="submit" :disabled="busy">保存并同步索引</button>
    </form>
    </ModalShell>

    <ModalShell v-if="importOpen" label="导入知识" @close="importOpen = false">
      <form class="panel form-panel" @submit.prevent="submitImport">
      <div class="panel-head"><h2>批量导入知识</h2><button type="button" class="ghost" @click="importOpen = false">取消</button></div>
      <label class="wide">JSON 数组<textarea v-model="importPayload" required rows="10" placeholder='[{"title":"标题","content":"至少五个字符","category":"通用","tags":[]}]'></textarea></label>
      <p class="muted">每项包含 title、content、category、tags；导入请求由后端事务和向量索引共同校验。</p>
      <button type="submit" :disabled="busy">开始导入</button>
    </form>
    </ModalShell>
  </section>
</template>

<style scoped>
.knowledge-workspace { display: grid; gap: 18px; }
.workspace-head, .actions, .panel-head, .card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.workspace-head h1 { margin: 4px 0 8px; color: var(--mp-color-ink); font-size: 28px; }
.muted { color: var(--mp-color-mute); font-size: 13px; }
.panel, .result-card { display: grid; gap: 10px; padding: 16px; border: 1px solid var(--mp-color-hairline); border-radius: var(--mp-radius-card); background: var(--mp-color-surface); }
.panel h2 { margin: 0; color: var(--mp-color-ink); font-size: 17px; }
.panel-head small { display: block; }
input, textarea, button { min-height: 38px; padding: 8px 10px; border: 1px solid var(--mp-color-hairline-strong); border-radius: var(--mp-radius-md); color: var(--mp-color-ink); background: var(--mp-color-surface-elevated); font: inherit; }
button { cursor: pointer; }
button.primary { border-color: var(--mp-color-primary); color: white; background: var(--mp-color-primary); }
button.danger { border-color: var(--mp-color-danger); color: var(--mp-color-danger); }
button.ghost { border-color: transparent; background: transparent; }
button:disabled { opacity: .55; cursor: wait; }
.toolbar { display: flex; gap: 10px; }
.toolbar input { flex: 1; }
.results { display: grid; gap: 10px; }
.result-card p { margin: 0; color: var(--mp-color-body); white-space: pre-wrap; }
.result-card small, td small { display: block; color: var(--mp-color-mute); font-size: 12px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; color: var(--mp-color-body); font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--mp-color-hairline); text-align: left; vertical-align: top; }
th { color: var(--mp-color-mute); font-weight: 500; }
td small { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-actions { display: flex; gap: 6px; }
.form-panel label { display: grid; gap: 6px; color: var(--mp-color-body); font-size: 13px; }
.form-panel { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.form-panel .panel-head, .form-panel .wide, .form-panel > button, .form-panel > p { grid-column: 1 / -1; }
.notice { color: var(--mp-color-success); font-size: 13px; }
.empty { color: var(--mp-color-mute); text-align: center; }
@media (max-width: 900px) { .workspace-head, .actions, .toolbar { flex-direction: column; } .form-panel { grid-template-columns: 1fr; } }
</style>
