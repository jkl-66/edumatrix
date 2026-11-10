<script setup>
import { computed, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, BookOpen, Check, LoaderCircle, Plus, Trash2, X } from '@lucide/vue'
import { analyzeCourseStructure, confirmCourseStructure, getCanonicalCourseSource, getCourseStructure, resetCourseStructure, saveCourseStructure } from '../api/knowledge.js'
import { acceptStructureSuggestion, canAcceptStructureSuggestion, remapUnitChapters, splitChapterAtQuote } from '../utils/courseStructureEditing.js'
import { userMessage } from '../services/errorTranslator.js'
import IncrementalMarkdownRenderer from './IncrementalMarkdownRenderer.vue'
import SearchField from './ui/SearchField.vue'

const props = defineProps({ courseId: { type: String, required: true } })
const emit = defineEmits(['close', 'applied'])
const state = ref(null)
const structure = ref(null)
const snapshot = ref('')
const loading = ref(false)
const busy = ref('')
const error = ref('')
const notice = ref('')
const tab = ref('chapters')
const selectedKey = ref('')
const query = ref('')
const splitText = ref('')
const splitOpen = ref(false)
const dirty = computed(() => JSON.stringify(structure.value) !== snapshot.value)
const tabs = [{ key: 'chapters', label: '章节' }, { key: 'concepts', label: '知识点' }, { key: 'units', label: '学习单元' }, { key: 'prerequisites', label: '先修关系' }, { key: 'suggestions', label: '合并建议' }]
const mergeSuggestions = computed(() => (state.value?.semantic_analysis?.suggestions || [])
  .filter(item => structure.value && canAcceptStructureSuggestion(structure.value, item)))
const entries = computed(() => {
  const all = structure.value?.[tab.value] || []
  const needle = query.value.trim().toLocaleLowerCase()
  return all.map((item, index) => ({ item, index, key: item.key || item.id || String(index) }))
    .filter(entry => !needle || entryTitle(entry.item).toLocaleLowerCase().includes(needle))
})
const selected = computed(() => entries.value.find(entry => entry.key === selectedKey.value) || entries.value[0] || null)
const conceptName = id => structure.value?.concepts.find(point => point.id === id)?.title || '请选择知识点'
const sourceTitle = id => state.value?.sources.find(source => source.id === id)?.title || ''
const selectedChapter = computed(() => tab.value === 'chapters' ? selected.value?.item : null)
const nextChapter = computed(() => selectedChapter.value ? structure.value.chapters[selected.value.index + 1] : null)
const canMerge = computed(() => selectedChapter.value && nextChapter.value
  && selectedChapter.value.source_document_id === nextChapter.value.source_document_id
  && selectedChapter.value.parent_key === nextChapter.value.parent_key
  && selectedChapter.value.learning_role === nextChapter.value.learning_role
  && selectedChapter.value.char_end <= nextChapter.value.char_start)
const primaryChapterOptions = computed(() => tab.value === 'units' && selected.value
  ? structure.value.chapters.filter(chapter => chapter.knowledge_point_ids.some(id => selected.value.item.knowledge_point_ids.includes(id))) : [])

function entryTitle(item) {
  return tab.value === 'prerequisites' ? `${conceptName(item.prerequisite_id)} → ${conceptName(item.dependent_id)}` : item.title
}
function key() { return `draft-${crypto.randomUUID()}` }
function install(data) {
  state.value = data
  structure.value = structuredClone(data.structure)
  for (const unit of structure.value.units) unit.primary_chapter_keys ||= []
  snapshot.value = JSON.stringify(structure.value)
}
async function load() {
  loading.value = true; error.value = ''; notice.value = ''
  try { install(await getCourseStructure(props.courseId)) }
  catch (e) { error.value = userMessage(e, '课程结构暂时没有打开，请重试。') }
  finally { loading.value = false }
}
async function persist() {
  const data = await saveCourseStructure(props.courseId, {
    revision: state.value.revision, source_fingerprint: state.value.source_fingerprint,
    structure: structure.value,
  })
  install(data)
  return data
}
async function save() {
  busy.value = 'save'; error.value = ''; notice.value = ''
  try { await persist(); notice.value = '草稿已保存。' }
  catch (e) { error.value = userMessage(e, '草稿未能保存，当前修改仍在。') }
  finally { busy.value = '' }
}
async function restart() {
  busy.value = 'reset'; error.value = ''; notice.value = ''
  try { install(await resetCourseStructure(props.courseId, state.value.revision)); notice.value = '已重新读取当前课程。' }
  catch (e) { error.value = userMessage(e, '暂时不能重新读取，当前草稿仍在。') }
  finally { busy.value = '' }
}
async function analyze() {
  busy.value = 'analyze'; error.value = ''; notice.value = ''
  try {
    if (dirty.value) await persist()
    install(await analyzeCourseStructure(props.courseId, state.value.revision))
    tab.value = 'suggestions'
  } catch (e) { error.value = userMessage(e, '暂时没有完成整理，请重试。已保存的草稿仍在。') }
  finally { busy.value = '' }
}
function acceptSuggestion(item) {
  if (acceptStructureSuggestion(structure.value, item)) notice.value = '已加入草稿，确认应用后更新课程。'
}
function evidenceUrl(evidence) {
  const params = new URLSearchParams({ course_id: props.courseId, char_start: String(evidence.start), char_end: String(evidence.end) })
  return `/knowledge/documents/${encodeURIComponent(evidence.source_id)}?${params}`
}
async function apply() {
  busy.value = 'apply'; error.value = ''; notice.value = ''
  try {
    if (dirty.value || !state.value.draft_saved) await persist()
    const result = await confirmCourseStructure(props.courseId, state.value.revision)
    install(result); notice.value = '课程结构已更新。'; emit('applied')
  } catch (e) { error.value = userMessage(e, '暂时不能应用，请检查课程结构。') }
  finally { busy.value = '' }
}
function move(delta) {
  const from = selected.value.index, to = from + delta
  if (to < 0 || to >= structure.value.chapters.length) return
  const item = structure.value.chapters.splice(from, 1)[0]
  structure.value.chapters.splice(to, 0, item)
}
function mergeNext() {
  if (!canMerge.value) return
  const left = selectedChapter.value, right = nextChapter.value
  left.member_ids = [...new Set([...left.member_ids, ...right.member_ids])]
  left.char_end = right.char_end
  left.knowledge_point_ids = [...new Set([...left.knowledge_point_ids, ...right.knowledge_point_ids])]
  for (const chapter of structure.value.chapters) if (chapter.parent_key === right.key) chapter.parent_key = left.key
  remapUnitChapters(structure.value, right.key, [left.key])
  structure.value.chapters.splice(selected.value.index + 1, 1)
}
async function splitChapter() {
  const chapter = selectedChapter.value, quote = splitText.value.trim()
  if (!chapter || !quote) return
  busy.value = 'split'; error.value = ''
  try {
    const source = await getCanonicalCourseSource(chapter.source_document_id)
    const next = splitChapterAtQuote(chapter, source.content, quote, key())
    chapter.char_end = next.char_start
    structure.value.chapters.splice(selected.value.index + 1, 0, next)
    remapUnitChapters(structure.value, chapter.key, [chapter.key, next.key])
    selectedKey.value = next.key; splitOpen.value = false; splitText.value = ''
  } catch (e) { error.value = userMessage(e, '还没有找到拆分位置，请检查原文。') }
  finally { busy.value = '' }
}
function addEntry() {
  const item = tab.value === 'units'
    ? { key: key(), title: '新学习单元', goal: '', knowledge_point_ids: [], primary_chapter_keys: [] }
    : { prerequisite_id: '', dependent_id: '', basis: 'teaching_suggestion', source_ref_id: null, quote: '' }
  structure.value[tab.value].push(item)
  selectedKey.value = item.key || String(structure.value[tab.value].length - 1); query.value = ''
}
function removeEntry() {
  structure.value[tab.value].splice(selected.value.index, 1); selectedKey.value = ''
}
function readChapter() {
  const chapter = selectedChapter.value
  const params = new URLSearchParams({ course_id: props.courseId, char_start: String(chapter.char_start) })
  return `/knowledge/documents/${encodeURIComponent(chapter.source_document_id)}?${params}`
}
watch(tab, () => { selectedKey.value = ''; query.value = ''; splitOpen.value = false; error.value = ''; notice.value = '' })
watch(() => props.courseId, load, { immediate: true })
</script>

<template>
  <section class="structure-editor" aria-label="整理课程结构" data-testid="course-structure-editor">
    <header class="editor-heading">
      <h2>整理课程结构</h2>
      <div class="editor-actions">
        <button type="button" class="secondary-button" :disabled="loading || !!busy || !structure || !state.can_edit || state.stale" @click="analyze">
          <LoaderCircle v-if="busy === 'analyze'" :size="16" class="spin" />{{ busy === 'analyze' ? '正在查找重复内容…' : '查找合并建议' }}
        </button>
        <button type="button" class="secondary-button" :disabled="loading || !!busy || !structure || !state.can_edit || state.stale" @click="save">
          <LoaderCircle v-if="busy === 'save'" :size="16" class="spin" />保存草稿
        </button>
        <button type="button" class="primary-button" :disabled="loading || !!busy || !structure || !state.can_edit || state.stale || (!state.needs_confirmation && !state.draft_saved && !dirty)" @click="apply">
          <LoaderCircle v-if="busy === 'apply'" :size="16" class="spin" /><Check v-else :size="16" />确认应用
        </button>
        <button type="button" class="icon-button" aria-label="返回课程资料" :disabled="!!busy" @click="emit('close')"><X :size="20" /></button>
      </div>
    </header>
    <p v-if="loading" class="feedback"><LoaderCircle :size="18" class="spin" />正在读取课程结构…</p>
    <p v-if="error" class="feedback error" role="alert">{{ error }}<button v-if="!structure" type="button" @click="load">重试</button></p>
    <p v-if="notice" class="feedback" role="status">{{ notice }}</p>
    <div v-if="state?.stale" class="feedback error"><span>课程资料已变化。请复制需要保留的修改，再按当前资料重新整理。</span><button type="button" class="secondary-button" :disabled="!!busy" @click="restart">按当前资料重新整理</button></div>
    <template v-if="structure && !loading">
      <nav class="editor-tabs" aria-label="课程结构编辑范围">
        <button v-for="item in tabs" :key="item.key" type="button" :aria-current="tab === item.key ? 'page' : undefined" @click="tab = item.key">{{ item.label }}</button>
      </nav>
      <div v-if="state.issues?.length && !dirty" class="structure-issues" role="status">
        <p v-for="issue in state.issues" :key="issue">{{ issue }}</p>
      </div>
      <div v-if="tab === 'suggestions'" class="merge-suggestions">
        <p v-if="state.semantic_analysis?.status === 'partial'" class="feedback" role="status">部分内容尚未整理完成，重试会接着处理。</p>
        <p v-if="!mergeSuggestions.length" class="empty">{{ state.semantic_analysis ? '当前没有可直接合并的条目。' : '点击“查找合并建议”，比较相邻章节和同义知识点。' }}</p>
        <article v-for="item in mergeSuggestions" :key="item.id" class="merge-suggestion" data-testid="structure-merge-suggestion">
          <h3>{{ item.titles.join(' · ') }}</h3>
          <p>{{ item.reason }}</p>
          <details><summary>查看原文依据</summary>
            <div v-for="evidence in item.evidence" :key="evidence.key" class="merge-evidence">
              <blockquote><IncrementalMarkdownRenderer :text="evidence.quote" /></blockquote><a :href="evidenceUrl(evidence)" target="_blank" rel="noopener" class="text-button">查看原文</a>
            </div>
          </details>
          <button type="button" class="secondary-button" :disabled="!!busy || !state.can_edit || state.stale" @click="acceptSuggestion(item)">合并为“{{ item.title }}”</button>
        </article>
      </div>
      <div v-else class="editor-workspace">
        <aside class="entry-browser">
          <div class="entry-tools">
            <SearchField v-model="query" :placeholder="`查找${tabs.find(item => item.key === tab).label}`" aria-label="筛选结构条目" clearable />
            <button v-if="tab === 'units' || tab === 'prerequisites'" type="button" class="icon-button" :disabled="!!busy || !state.can_edit" :aria-label="tab === 'units' ? '添加学习单元' : '添加先修关系'" @click="addEntry"><Plus :size="18" /></button>
          </div>
          <div class="entry-list">
            <button v-for="entry in entries" :key="entry.key" type="button" :class="{ selected: selected?.key === entry.key }" @click="selectedKey = entry.key; splitOpen = false">
              {{ entryTitle(entry.item) }}
            </button>
            <p v-if="!entries.length" class="empty">暂无{{ tabs.find(item => item.key === tab).label }}</p>
          </div>
        </aside>
        <fieldset v-if="selected" class="entry-form" :disabled="!!busy || !state.can_edit || state.stale">
          <template v-if="tab === 'chapters'">
            <label>章节名称<input v-model="selected.item.title" aria-label="章节名称" /></label>
            <div class="chapter-actions">
              <button type="button" class="secondary-button" aria-label="上移章节" :disabled="selected.index === 0" @click="move(-1)"><ArrowUp :size="16" /></button>
              <button type="button" class="secondary-button" aria-label="下移章节" :disabled="selected.index === structure.chapters.length - 1" @click="move(1)"><ArrowDown :size="16" /></button>
              <button type="button" class="secondary-button" :disabled="!canMerge" @click="mergeNext">与下一章合并</button>
              <button type="button" class="secondary-button" @click="splitOpen = !splitOpen">拆分章节</button>
              <a :href="readChapter()" target="_blank" rel="noopener" class="text-button"><BookOpen :size="16" />查看原文</a>
            </div>
            <p class="source-name">{{ sourceTitle(selected.item.source_document_id) }}</p>
            <div v-if="splitOpen" class="split-form">
              <label>新章节开头的原文<textarea v-model="splitText" rows="3" aria-label="拆分章节的原文" /></label>
              <button type="button" class="secondary-button" :disabled="!splitText.trim()" @click="splitChapter">按这段原文拆分</button>
            </div>
            <label>所属章节<select v-model="selected.item.parent_key" aria-label="所属章节"><option :value="null">独立章节</option><option v-for="chapter in structure.chapters.filter(item => item.key !== selected.item.key)" :key="chapter.key" :value="chapter.key">{{ chapter.title }}</option></select></label>
            <label>章节用途<select v-model="selected.item.learning_role" aria-label="章节用途"><option value="teaching">安排学习</option><option value="reference">参考阅读</option></select></label>
            <label>包含的知识点<select v-model="selected.item.knowledge_point_ids" multiple size="8" aria-label="章节知识点"><option v-for="point in structure.concepts" :key="point.id" :value="point.id">{{ point.title }}</option></select></label>
          </template>
          <template v-else-if="tab === 'concepts'">
            <label>知识点名称<input v-model="selected.item.title" aria-label="知识点名称" /></label>
            <label>合并到<select v-model="selected.item.merge_into" aria-label="知识点合并目标"><option :value="null">保留为独立知识点</option><option v-for="point in structure.concepts.filter(item => item.id !== selected.item.id && !item.merge_into)" :key="point.id" :value="point.id">{{ point.title }}</option></select></label>
            <p v-if="selected.item.merge_into" class="feedback">新课程结构使用“{{ conceptName(selected.item.merge_into) }}”，原有学习记录保留。</p>
            <div class="concept-sources"><h3>相关章节</h3><button v-for="chapter in structure.chapters.filter(item => item.knowledge_point_ids.includes(selected.item.id))" :key="chapter.key" type="button" class="text-button" @click="tab = 'chapters'; selectedKey = chapter.key">{{ chapter.title }}</button></div>
          </template>
          <template v-else-if="tab === 'units'">
            <label>单元名称<input v-model="selected.item.title" aria-label="单元名称" /></label>
            <label>学习目标<textarea v-model="selected.item.goal" rows="3" aria-label="单元学习目标" /></label>
            <label>包含的知识点<select v-model="selected.item.knowledge_point_ids" multiple :size="Math.min(6, Math.max(2, structure.concepts.length))" aria-label="单元知识点"><option v-for="point in structure.concepts" :key="point.id" :value="point.id">{{ point.title }}</option></select></label>
            <label>主学习章节<select v-model="selected.item.primary_chapter_keys" multiple :size="Math.min(6, Math.max(2, primaryChapterOptions.length))" aria-label="主学习章节"><option v-for="chapter in primaryChapterOptions" :key="chapter.key" :value="chapter.key">{{ chapter.title }}</option></select></label>
            <p class="feedback">选定后，其他相关章节保留为参考；留空则逐章安排。</p>
            <button type="button" class="text-button" @click="removeEntry"><Trash2 :size="16" />删除学习单元</button>
          </template>
          <template v-else>
            <label>先学<select v-model="selected.item.prerequisite_id" aria-label="先修知识点"><option disabled value="">请选择知识点</option><option v-for="point in structure.concepts" :key="point.id" :value="point.id">{{ point.title }}</option></select></label>
            <label>再学<select v-model="selected.item.dependent_id" aria-label="后续知识点"><option disabled value="">请选择知识点</option><option v-for="point in structure.concepts" :key="point.id" :value="point.id">{{ point.title }}</option></select></label>
            <label>关系依据<select v-model="selected.item.basis" aria-label="先修关系依据"><option value="teaching_suggestion">教学顺序建议</option><option value="source_explicit">原文明确说明</option></select></label>
            <template v-if="selected.item.basis === 'source_explicit'">
              <label>原文位置<select v-model="selected.item.source_ref_id" aria-label="先修依据原文位置"><option :value="null">请选择原文位置</option><option v-for="reference in state.references" :key="reference.id" :value="reference.id">{{ reference.label }}</option></select></label>
              <label>原文摘录<textarea v-model="selected.item.quote" rows="4" aria-label="先修依据摘录" /></label>
            </template>
            <button type="button" class="text-button" @click="removeEntry"><Trash2 :size="16" />删除先修关系</button>
          </template>
        </fieldset>
        <div v-else class="empty entry-form">从左侧选择条目，或添加新的学习安排。</div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.structure-editor { margin: 18px 0 28px; padding: 24px; background: var(--color-surface); border-radius: 16px; color: var(--color-text); }
.editor-heading, .editor-actions, .chapter-actions, .entry-tools { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.editor-heading { justify-content: space-between; margin-bottom: 22px; }
h2 { margin: 0; font-size: 22px; } h3 { margin: 0 0 10px; font-size: 16px; }
.editor-tabs { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.editor-tabs button { padding: 10px 18px; border: 0; background: transparent; border-radius: 8px; font: inherit; color: var(--color-text-secondary); cursor: pointer; }
.editor-tabs button[aria-current] { color: var(--color-text); background: var(--color-accent-soft); }
.editor-workspace { display: grid; grid-template-columns: minmax(220px, 30%) minmax(0, 1fr); gap: 28px; min-height: 540px; }
.entry-browser { min-width: 0; background: var(--color-surface-subtle); border-radius: 12px; padding: 14px; }
.entry-tools { flex-wrap: nowrap; margin-bottom: 12px; }
.entry-tools .ui-search-field { min-width: 0; width: 100%; background: var(--color-surface); }
.entry-list { display: grid; align-content: start; gap: 5px; max-height: 580px; overflow: auto; }
.entry-list button { font: inherit; color: inherit; background: transparent; border: 0; border-radius: 8px; padding: 12px; text-align: left; line-height: 1.5; cursor: pointer; overflow-wrap: anywhere; }
.entry-list button.selected { background: var(--color-accent-soft); font-weight: 600; }
.entry-form { display: grid; align-content: start; gap: 22px; min-width: 0; padding: 2px 0; margin: 0; border: 0; }
label { display: grid; gap: 9px; font-size: 16px; }
input, textarea, select { width: 100%; box-sizing: border-box; padding: 11px 12px; border: 0; border-radius: 7px; background: var(--color-surface-subtle); color: var(--color-text); font: inherit; font-size: 16px; line-height: 1.5; }
select[multiple] { padding: 8px; } select[multiple] option { padding: 7px 10px; }
textarea { resize: vertical; }
button, a { touch-action: manipulation; }
.primary-button, .secondary-button, .icon-button, .text-button { display: inline-flex; align-items: center; justify-content: center; gap: 7px; padding: 10px 14px; border: 0; border-radius: 8px; font: inherit; cursor: pointer; text-decoration: none; color: var(--color-text); }
.primary-button { background: var(--color-accent); color: var(--color-text-inverse, #fff); }
.secondary-button { background: var(--color-surface-subtle); }
.icon-button, .text-button { background: transparent; padding: 8px; }
.text-button { color: var(--color-accent); justify-content: start; }
button:disabled { opacity: .5; cursor: default; }
.feedback { display: flex; gap: 8px; align-items: center; margin: 12px 0; font-size: 16px; line-height: 1.6; }
.error, .structure-issues { color: var(--color-danger); }
.structure-issues { padding: 12px 16px; background: var(--color-surface-subtle); border-radius: 8px; margin-bottom: 18px; }
.structure-issues p { margin: 5px 0; }
.source-name, .empty { color: var(--color-text-secondary); font-size: 16px; line-height: 1.5; margin: 0; }
.split-form { display: grid; gap: 12px; }
.concept-sources { display: grid; gap: 8px; }
.merge-suggestions { display: grid; gap: 24px; }
.merge-suggestion { padding: 20px; background: var(--color-surface-subtle); border-radius: 10px; }
.merge-suggestion p, .merge-evidence blockquote { font-size: 16px; line-height: 1.7; margin: 12px 0; }
.merge-suggestion details { margin: 14px 0; }
.merge-suggestion summary { cursor: pointer; }
.merge-evidence { margin-top: 16px; }
.spin { animation: spin 1s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
:is(button,input,select,textarea,a):focus-visible { outline: 2px solid var(--color-accent); outline-offset: 3px; }
@media (max-width: 1000px) { .structure-editor { padding: 18px; } .editor-workspace { grid-template-columns: minmax(190px, 34%) minmax(0, 1fr); gap: 16px; } }
@media (max-width: 700px) { .editor-workspace { grid-template-columns: 1fr; } .entry-list { max-height: 220px; } }
</style>
