<script setup>
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { listKnowledgeDocuments, uploadKnowledgeDocument, deleteKnowledgeDocument, getKnowledgeDocument, getGraphStats, crossModalSearch } from '../api'
import { BookOpen, Upload, Trash2, FileText, File, FileImage, FileVideo, Presentation, Tag, Clock, AlertCircle, CheckCircle, Image, Film, ArrowRight, GitBranch, Sparkles, Search, X, Zap, ExternalLink } from '@lucide/vue'
import KnowledgeGraphExplorer from '../components/KnowledgeGraphExplorer.vue'

const props = defineProps({ studentId: String })

const docs = ref([])
const loading = ref(true)
const uploading = ref(false)
const uploadProgress = ref(0)
const dragOver = ref(false)
const uploadError = ref('')
const uploadSuccess = ref('')
const error = ref('')
const fileInput = ref(null)

// 文档预览 & 导读
const showDocModal = ref(false)
const selectedDoc = ref(null)
let pollTimer = null

async function openDocModal(doc) {
  selectedDoc.value = doc
  showDocModal.value = true
  if (pollTimer) clearInterval(pollTimer)

  try {
    const full = await getKnowledgeDocument(doc.id, props.studentId || 'default')
    selectedDoc.value = full

    if (!full.multimodal_metadata?.doc_guide) {
      let attempts = 0
      pollTimer = setInterval(async () => {
        attempts++
        if (attempts > 6 || !showDocModal.value) {
          if (pollTimer) clearInterval(pollTimer)
          return
        }
        try {
          const updated = await getKnowledgeDocument(doc.id, props.studentId || 'default')
          if (updated.multimodal_metadata?.doc_guide) {
            selectedDoc.value = updated
            if (pollTimer) clearInterval(pollTimer)
            const idx = docs.value.findIndex(d => d.id === doc.id)
            if (idx !== -1) docs.value[idx] = updated
          }
        } catch (e) {}
      }, 2500)
    }
  } catch (e) {
    console.error('Failed to load full document:', e)
  }
}

function closeDocModal() {
  showDocModal.value = false
  if (pollTimer) clearInterval(pollTimer)
}

function triggerSelect() {
  if (fileInput.value) fileInput.value.click()
}

const fileTypes = ['.md', '.txt', '.pdf', '.docx', '.json', '.pptx', '.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv']
const acceptedTypes = '.md,.txt,.pdf,.docx,.json,.pptx,.mp4,.avi,.mov,.mkv,.webm,.flv'

function formatSize(bytes) {
  if (!bytes || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

function ago(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  return `${Math.floor(s / 86400)}天前`
}

function fileIcon(type) {
  if (type === 'pdf') return FileImage
  if (type === 'pptx') return Presentation
  if (type === 'md' || type === 'docx') return FileText
  if (['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'].includes(type)) return Film
  return File
}

function fileColor(type) {
  if (type === 'pdf') return 'text-red-500 bg-red-50'
  if (type === 'pptx') return 'text-orange-500 bg-orange-50'
  if (type === 'md' || type === 'docx') return 'text-blue-500 bg-blue-50'
  if (['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'].includes(type)) return 'text-purple-500 bg-purple-50'
  if (type === 'txt') return 'text-gray-500 bg-gray-50'
  return 'text-green-500 bg-green-50'
}

function isMultimodal(doc) {
  return doc.is_multimodal || ['pptx', 'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'].includes(doc.file_type)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await listKnowledgeDocuments(props.studentId || 'default')
    docs.value = Array.isArray(data) ? data : []
  } catch (e) {
    error.value = '加载知识库失败: ' + (e.response?.data?.detail || e.message)
  } finally {
    loading.value = false
  }
}

async function handleUpload(event) {
  const files = event.target?.files || event.dataTransfer?.files
  if (!files || files.length === 0) return
  uploadError.value = ''
  uploadSuccess.value = ''
  for (const file of files) {
    const ext = '.' + file.name.split('.').pop().toLowerCase()
    if (!fileTypes.includes(ext)) {
      if (ext === '.ppt') {
        uploadError.value = `检测到旧版 PPT 文件。为了获得完美的知识图谱解析，请在 PowerPoint 中将其另存为 .pptx 格式后再上传。`
      } else {
        uploadError.value = `不支持的文件类型: ${ext}`
      }
      continue
    }
    uploading.value = true
    uploadProgress.value = 0
    try {
      const result = await uploadKnowledgeDocument(file, props.studentId || 'default', (e) => {
        if (e.total) uploadProgress.value = Math.round((e.loaded / e.total) * 100)
      })
      const typeLabel = result.is_multimodal ? (result.file_category === 'video' ? '视频' : 'PPT') : '文档'
      uploadSuccess.value = `${file.name} ${typeLabel}上传成功 (${result.chunk_count} 个知识块${result.visual_pages_parsed ? ', ' + result.visual_pages_parsed + ' 页视觉解析' : ''}${result.graph_edges_written ? ', ' + result.graph_edges_written + ' 条图谱边' : ''})`
      await load()
    } catch (e) {
      uploadError.value = `${file.name} 上传失败: ` + (e.response?.data?.detail || e.message)
    } finally {
      uploading.value = false
      uploadProgress.value = 0
    }
  }
}

async function remove(docId, filename) {
  if (!confirm(`确定删除 "${filename}"？此操作不可恢复。`)) return
  try {
    await deleteKnowledgeDocument(docId, props.studentId || 'default')
    uploadSuccess.value = `${filename} 已删除`
    await load()
  } catch (e) {
    uploadError.value = `删除失败: ` + (e.response?.data?.detail || e.message)
  }
}

function onDragOver(e) { e.preventDefault(); dragOver.value = true }
function onDragLeave() { dragOver.value = false }
function onDrop(e) { e.preventDefault(); dragOver.value = false; handleUpload(e) }

// 任务 8.6: 从文档标签提取知识图谱数据
const graphNodes = computed(() => {
  const nodes = []
  const added = new Set()

  // 文件作为概念节点
  docs.value.forEach((doc, i) => {
    if (!added.has(doc.filename)) {
      added.add(doc.filename)
      nodes.push({
        id: doc.filename,
        name: doc.filename.slice(0, 20),
        category: doc.file_type === 'pptx' || doc.file_type === 'ppt' ? 1
          : ['mp4', 'avi', 'mov'].includes(doc.file_type) ? 2 : 0,
        categoryName: doc.file_type === 'pptx' ? '课件' : ['mp4', 'avi', 'mov'].includes(doc.file_type) ? '视频' : '文档',
        symbolSize: 30 + (doc.chunk_count || 0) * 0.5,
        itemStyle: {
          color: doc.file_type === 'pptx' ? '#f59e0b' : ['mp4', 'avi', 'mov'].includes(doc.file_type) ? '#8b5cf6' : '#3b82f6',
        },
      })
    }
    // tags 作为关联概念节点
    ;(doc.tags || []).slice(0, 5).forEach(tag => {
      if (!added.has(tag)) {
        added.add(tag)
        nodes.push({
          id: tag,
          name: tag,
          category: 3,
          categoryName: '标签',
          symbolSize: 20,
          itemStyle: { color: '#10b981' },
        })
      }
    })
  })
  return nodes
})

const graphEdges = computed(() => {
  const edges = []
  docs.value.forEach(doc => {
    ;(doc.tags || []).slice(0, 5).forEach(tag => {
      edges.push({ source: doc.filename, target: tag, label: '关联' })
    })
  })
  // 标签间共现关联
  const tagPairs = {}
  docs.value.forEach(doc => {
    const tags = (doc.tags || []).slice(0, 5)
    for (let i = 0; i < tags.length; i++) {
      for (let j = i + 1; j < tags.length; j++) {
        const key = [tags[i], tags[j]].sort().join('::')
        tagPairs[key] = (tagPairs[key] || 0) + 1
      }
    }
  })
  Object.entries(tagPairs).forEach(([key, count]) => {
    if (count > 0) {
      const [s, t] = key.split('::')
      edges.push({ source: s, target: t, label: `${count}次共现` })
    }
  })
  return edges
})

onMounted(load)

// ── 成员 3: 图谱统计 ──
const graphStats = ref({ status: 'loading', nodes: 0, edges: 0, backend: 'loading' })
async function loadGraphStats() {
  try { graphStats.value = await getGraphStats() } catch (e) { /* 忽略 */ }
}
watch(docs, () => { loadGraphStats() })

// ── 成员 3: 跨模态搜索 ──
const crossModalQuery = ref('')
const crossModalMode = ref('text')
const crossModalLoading = ref(false)
const crossModalResults = ref([])
const crossModalError = ref('')
async function doCrossModalSearch() {
  if (!crossModalQuery.value.trim()) return
  crossModalLoading.value = true; crossModalError.value = ''
  try {
    const data = await crossModalSearch(crossModalQuery.value, crossModalMode.value, 5)
    crossModalResults.value = data.results || []
  } catch (e) {
    crossModalError.value = e.response?.data?.detail || e.message
  } finally { crossModalLoading.value = false }
}
</script>

<template>
  <div class="knowledge-page max-w-4xl mx-auto text-slate-800">
    <!-- 头部：标题 + 图谱状态 -->
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-sm font-semibold text-[#f3f4f6]">
        知识库 ({{ docs.length }})
        <span v-if="graphStats.backend !== 'loading'" class="ml-3 text-[10px] font-normal text-[#64748b]">
          <GitBranch :size="10" class="inline mr-1" />
          {{ graphStats.nodes }} 节点 / {{ graphStats.edges }} 边
          <span class="ml-1 px-1 py-0.5 rounded text-[8px]"
            :class="graphStats.backend === 'neo4j' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-[#64748b]/20 text-[#64748b]'">
            {{ graphStats.backend }}
          </span>
        </span>
      </h2>
    </div>

    <!-- 上传区域：暗色玻璃风格 -->
    <div class="relative mb-6">
      <input ref="fileInput" type="file" :accept="acceptedTypes" multiple class="hidden" @change="handleUpload" />
      <div
        class="border-2 border-dashed rounded-xl p-8 text-center transition-all duration-300 cursor-pointer"
        :class="dragOver
          ? 'border-[#0ea5e9]/60 bg-[#0ea5e9]/5 shadow-lg shadow-[#0ea5e9]/10'
          : 'border-[#1e293b] hover:border-[#0ea5e9]/30 hover:bg-[#0ea5e9]/[0.03]'"
        @click="triggerSelect"
        @dragover.prevent="onDragOver"
        @dragleave.prevent="onDragLeave"
        @drop.prevent="onDrop"
      >
        <Upload :size="36" class="mx-auto mb-3 pointer-events-none transition-colors" :class="dragOver ? 'text-[#0ea5e9]' : 'text-[#475569]'" />
        <p class="text-sm font-medium text-[#cbd5e1] pointer-events-none">{{ dragOver ? '释放文件以上传' : '拖拽文件到此处，或点击选择文件' }}</p>
        <p class="text-xs text-[#475569] mt-1 pointer-events-none">支持 文档(.md/.txt/.pdf/.docx) / PPT(.pptx) / 视频(.mp4/.avi/.mov) 自动解析</p>
      </div>
    </div>

    <!-- 上传进度条 -->
    <div v-if="uploading" class="bg-[#131926]/70 backdrop-blur-md border border-white/[0.06] rounded-xl p-4 mb-4">
      <div class="flex items-center gap-3">
        <div class="flex-1">
          <div class="h-2 bg-white/[0.06] rounded-full overflow-hidden">
            <div class="h-full bg-gradient-to-r from-[#0ea5e9] to-[#10b981] rounded-full transition-all duration-300" :style="{ width: uploadProgress + '%' }" />
          </div>
        </div>
        <span class="text-xs text-[#64748b] shrink-0">{{ uploadProgress }}%</span>
      </div>
    </div>

    <!-- 成功提示 -->
    <div v-if="uploadSuccess" class="bg-emerald-500/10 border border-emerald-500/20 rounded-xl p-3 mb-4 flex items-center gap-2">
      <CheckCircle :size="16" class="text-emerald-400 shrink-0" />
      <span class="text-sm text-emerald-300">{{ uploadSuccess }}</span>
      <button class="ml-auto text-emerald-400 text-xs hover:text-emerald-300" @click="uploadSuccess = ''">×</button>
    </div>

    <!-- 错误提示 -->
    <div v-if="uploadError" class="bg-red-500/10 border border-red-500/20 rounded-xl p-3 mb-4 flex items-center gap-2">
      <AlertCircle :size="16" class="text-red-400 shrink-0" />
      <span class="text-sm text-red-300">{{ uploadError }}</span>
      <button class="ml-auto text-red-400 text-xs hover:text-red-300" @click="uploadError = ''">×</button>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="pulse-dot bg-[#0ea5e9]" /><span class="ml-3 text-[#64748b] text-sm">加载中...</span>
    </div>

    <!-- 错误状态 -->
    <div v-else-if="error" class="text-center py-12">
      <AlertCircle :size="40" class="mx-auto mb-3 text-red-400/50" />
      <p class="text-sm text-red-400">{{ error }}</p>
      <button class="px-3 py-1.5 mt-4 text-xs border border-[#1e293b] rounded-lg text-[#64748b] hover:text-[#cbd5e1] hover:border-[#475569] transition-colors" @click="load">重试</button>
    </div>

    <!-- 空状态 -->
    <div v-else-if="docs.length === 0" class="text-center py-12">
      <BookOpen :size="40" class="mx-auto mb-3 text-[#1e293b]" />
      <p class="text-sm text-[#475569]">知识库为空</p>
      <p class="text-xs mt-1 text-[#334155]">上传文档/PPT/视频后，AI 将自动解析并索引，用于学习问答</p>
    </div>

    <!-- 文档卡片网格：玻璃态暗色风格 -->
    <div v-else class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div v-for="doc in docs" :key="doc.id" class="knowledge-card bg-white border border-slate-200 rounded-xl p-4 hover:border-cyan-300 hover:shadow-lg hover:shadow-slate-200/70 transition-all duration-300 group cursor-pointer" @click="openDocModal(doc)">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" :class="fileColor(doc.file_type)">
            <component :is="fileIcon(doc.file_type)" :size="20" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5">
              <h3 class="text-sm font-medium text-[#f3f4f6] truncate">{{ doc.filename }}</h3>
              <span v-if="isMultimodal(doc)" class="inline-flex items-center gap-0.5 bg-gradient-to-r from-purple-500 to-pink-500 text-white text-[9px] px-1.5 py-0 rounded-full shrink-0">多模态</span>
            </div>
            <div class="flex flex-wrap items-center gap-2 mt-1.5">
              <span class="text-[10px] text-[#64748b] bg-white/[0.04] px-1.5 py-0.5 rounded">{{ (doc.file_type || '').toUpperCase() }}</span>
              <span class="text-[10px] text-[#475569]">{{ formatSize(doc.file_size) }}</span>
              <span class="text-[10px] text-[#475569]">{{ doc.chunk_count }} 块</span>
              <span v-if="doc.multimodal_metadata?.slide_count" class="text-[10px] text-[#475569]">{{ doc.multimodal_metadata.slide_count }} 页</span>
              <span v-if="doc.multimodal_metadata?.video_duration" class="text-[10px] text-[#475569]">{{ Math.round(doc.multimodal_metadata.video_duration) }}s</span>
              <span v-if="doc.created_at" class="text-[10px] text-[#475569] flex items-center gap-1"><Clock :size="10" /> {{ ago(doc.created_at) }}</span>
            </div>
            <p v-if="doc.content_preview" class="text-[11px] text-[#94a3b8] mt-2 line-clamp-2">{{ doc.content_preview }}</p>
            <div v-if="doc.tags && doc.tags.length > 0" class="flex flex-wrap gap-1 mt-2">
              <span v-for="tag in doc.tags.slice(0, 4)" :key="tag" class="inline-flex items-center gap-0.5 bg-[#0ea5e9]/10 text-[#0ea5e9] text-[10px] px-1.5 py-0 rounded-full"><Tag :size="8" /> {{ tag }}</span>
              <span v-if="doc.tags.length > 4" class="text-[10px] text-[#475569]">+{{ doc.tags.length - 4 }}</span>
            </div>
          </div>
          <button class="p-1.5 shrink-0 text-[#64748b] hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors" @click.stop="remove(doc.id, doc.filename)" :title="`删除 ${doc.filename}`" aria-label="删除知识库文件">
            <Trash2 :size="14" />
          </button>
        </div>
      </div>
    </div>

    <!-- 成员 3: 跨模态搜索 -->
    <div class="mt-8 bg-[#131926]/70 backdrop-blur-md border border-white/[0.06] rounded-xl p-5">
      <div class="flex items-center gap-2 mb-4">
        <Sparkles :size="16" class="text-[#0ea5e9]" />
        <h2 class="text-sm font-semibold text-[#f3f4f6]">跨模态搜索</h2>
        <span class="text-[10px] text-[#475569]">用文字搜公式 · 用公式搜图片</span>
      </div>
      <div class="flex gap-2">
        <div class="flex-1 relative">
          <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-[#475569]" />
          <input v-model="crossModalQuery" @keyup.enter="doCrossModalSearch"
            placeholder="输入描述，搜索相关公式或图像..."
            class="w-full pl-9 pr-3 py-2 bg-[#0b0f19] border border-[#1e293b] rounded-lg text-sm text-[#f3f4f6] placeholder-[#475569] focus:border-[#0ea5e9]/40 focus:outline-none transition-colors" />
        </div>
        <select v-model="crossModalMode" class="bg-[#0b0f19] border border-[#1e293b] rounded-lg px-2 py-2 text-xs text-[#cbd5e1] focus:outline-none">
          <option value="text">用文字搜公式/图片</option>
          <option value="formula">用公式搜文字/图片</option>
          <option value="image">用图片搜文字/公式</option>
        </select>
        <button @click="doCrossModalSearch" :disabled="crossModalLoading"
          class="flex items-center gap-1.5 px-4 py-2 text-xs font-medium rounded-lg bg-gradient-to-r from-[#0ea5e9] to-[#10b981] text-white hover:shadow-lg hover:shadow-[#0ea5e9]/20 transition-all disabled:opacity-50">
          <Zap :size="12" /> 搜索
        </button>
      </div>
      <!-- 跨模态搜索结果 -->
      <div v-if="crossModalLoading" class="mt-4 text-center text-xs text-[#64748b]">搜索中...</div>
      <div v-else-if="crossModalError" class="mt-4 text-xs text-red-400">{{ crossModalError }}</div>
      <div v-else-if="crossModalResults.length > 0" class="mt-4 space-y-2">
        <div v-for="(r, i) in crossModalResults" :key="i"
          class="bg-[#0b0f19]/60 border border-white/[0.04] rounded-lg p-3 hover:border-white/[0.1] transition-colors">
          <div class="flex items-start justify-between gap-2">
            <p class="text-sm text-[#f3f4f6]">{{ r.pair?.concept || r.pair?.text?.slice(0, 80) || '无标题' }}</p>
            <span class="text-[10px] px-1.5 py-0 rounded text-[#10b981] bg-[#10b981]/10 shrink-0">{{ (r.score * 100).toFixed(0) }}%</span>
          </div>
          <p class="text-[11px] text-[#94a3b8] mt-1 line-clamp-2">{{ r.pair?.formula || r.pair?.image_desc || '' }}</p>
          <div class="flex items-center gap-2 mt-2">
            <span class="text-[9px] text-[#475569]">匹配模态:</span>
            <span class="text-[9px] px-1.5 py-0 rounded-full bg-[#0ea5e9]/10 text-[#0ea5e9]">{{ r.matched_modality }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 知识图谱探索器 -->
    <div class="mt-8">
      <div class="flex items-center gap-2 mb-4">
        <GitBranch :size="16" class="text-[#8b5cf6]" />
        <h2 class="text-sm font-semibold text-[#f3f4f6]">知识图谱 ({{ graphNodes.length }} 节点 / {{ graphEdges.length }} 边)</h2>
      </div>
      <KnowledgeGraphExplorer
        :nodes="graphNodes"
        :edges="graphEdges"
        :categories="[
          { name: '文档', itemStyle: { color: '#3b82f6' } },
          { name: '课件', itemStyle: { color: '#f59e0b' } },
          { name: '视频', itemStyle: { color: '#8b5cf6' } },
          { name: '标签', itemStyle: { color: '#10b981' } },
        ]"
      />
    </div>

  <!-- 文档预览 Modal（含 NotbookLM 风格导读） -->
  <Teleport to="body">
    <div v-if="showDocModal && selectedDoc" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="closeDocModal">
      <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div class="knowledge-modal relative bg-white border border-slate-200 rounded-2xl shadow-2xl max-w-2xl w-full max-h-[80vh] overflow-y-auto">
        <!-- 头部 -->
        <div class="sticky top-0 bg-[#0b0f19]/95 backdrop-blur-md border-b border-white/[0.06] px-6 py-4 flex items-center justify-between rounded-t-2xl z-10">
          <div class="flex items-center gap-3 min-w-0">
            <div class="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" :class="fileColor(selectedDoc.file_type)">
              <component :is="fileIcon(selectedDoc.file_type)" :size="20" />
            </div>
            <div class="min-w-0">
              <h3 class="text-sm font-semibold text-[#f3f4f6] truncate">{{ selectedDoc.filename }}</h3>
              <p class="text-[10px] text-[#64748b]">{{ formatSize(selectedDoc.file_size) }} · {{ selectedDoc.chunk_count }} 知识块</p>
            </div>
          </div>
          <div class="flex items-center gap-2">
            <a v-if="selectedDoc.multimodal_metadata?.url"
               :href="selectedDoc.multimodal_metadata.url"
               target="_blank"
               rel="noopener noreferrer"
               class="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white text-xs font-semibold shadow-sm hover:shadow-cyan-500/20 transition-all shrink-0"
               title="在新标签页中打开网页原文">
              <ExternalLink :size="12" /> 访问网页原文
            </a>
            <button class="p-1.5 text-[#475569] hover:text-[#cbd5e1] hover:bg-white/[0.06] rounded-lg transition-colors" @click="closeDocModal">
              <X :size="18" />
            </button>
          </div>
        </div>
        
        <div class="px-6 py-5 space-y-5">
          <!-- 导读指南面板（NotebookLM 风格） -->
          <div v-if="selectedDoc.multimodal_metadata?.doc_guide" class="bg-gradient-to-br from-[#0ea5e9]/5 to-[#10b981]/5 border border-[#0ea5e9]/20 rounded-xl p-5 backdrop-blur-sm">
            <div class="flex items-center gap-2 mb-4">
              <Sparkles :size="16" class="text-[#0ea5e9]" />
              <h4 class="text-sm font-semibold text-[#f3f4f6]">文档导读</h4>
            </div>
            
            <!-- 一句话概述 -->
            <div class="mb-4 p-3 bg-white/[0.03] rounded-lg border border-white/[0.04]">
              <p class="text-xs text-[#64748b] mb-1">📌 一句话概括</p>
              <p class="text-sm text-[#f3f4f6] leading-relaxed">{{ selectedDoc.multimodal_metadata.doc_guide.brief_summary }}</p>
            </div>
            
            <!-- 核心看点 -->
            <div class="mb-4">
              <p class="text-xs text-[#64748b] mb-2">✨ 核心看点</p>
              <ul class="space-y-1.5">
                <li v-for="(hl, i) in selectedDoc.multimodal_metadata.doc_guide.highlights" :key="i"
                  class="flex items-start gap-2 text-sm text-[#cbd5e1]">
                  <span class="w-5 h-5 rounded-full bg-[#0ea5e9]/10 text-[#0ea5e9] text-[10px] flex items-center justify-center shrink-0 mt-0.5">{{ i + 1 }}</span>
                  {{ hl }}
                </li>
              </ul>
            </div>
            
            <!-- FAQs -->
            <div v-if="selectedDoc.multimodal_metadata.doc_guide.faqs?.length > 0">
              <p class="text-xs text-[#64748b] mb-2">❓ 常见问题</p>
              <div class="space-y-2">
                <details v-for="(faq, i) in selectedDoc.multimodal_metadata.doc_guide.faqs" :key="i"
                  class="bg-white/[0.02] border border-white/[0.04] rounded-lg overflow-hidden group">
                  <summary class="px-3 py-2 text-xs font-medium text-[#cbd5e1] cursor-pointer hover:bg-white/[0.03] transition-colors list-none flex items-center gap-2">
                    <span class="w-4 h-4 rounded-full bg-[#10b981]/10 text-[#10b981] text-[9px] flex items-center justify-center shrink-0">?</span>
                    {{ faq.q }}
                  </summary>
                  <div class="px-3 pb-3 pt-1 text-xs text-[#94a3b8] leading-relaxed border-t border-white/[0.04] mt-1">
                    {{ faq.a }}
                  </div>
                </details>
              </div>
            </div>
          </div>
          
          <!-- 导读未就绪 -->
          <div v-else class="bg-white/[0.02] border border-white/[0.04] rounded-xl p-5 text-center">
            <Sparkles :size="24" class="mx-auto mb-2 text-[#0ea5e9] animate-pulse" />
            <p class="text-sm text-[#64748b]">智能导读解析中...</p>
            <p class="text-xs text-[#475569] mt-1">AI 正在提炼核心概述、看点与 FAQs 问答，请稍候 2~3 秒</p>
          </div>
          
          <!-- 内容预览与完整 Markdown -->
          <div class="bg-white/[0.02] border border-white/[0.04] rounded-xl p-4">
            <div class="flex items-center justify-between mb-2">
              <p class="text-xs text-[#64748b]">📄 内容详情 / 富媒体 Markdown</p>
              <a v-if="selectedDoc.multimodal_metadata?.url"
                 :href="selectedDoc.multimodal_metadata.url"
                 target="_blank"
                 rel="noopener noreferrer"
                 class="text-[10px] text-cyan-400 hover:underline flex items-center gap-1">
                <ExternalLink :size="10" /> {{ selectedDoc.multimodal_metadata.url }}
              </a>
            </div>
            <div class="text-xs text-[#94a3b8] leading-relaxed whitespace-pre-wrap max-h-96 overflow-y-auto font-mono text-[11px] bg-[#070a12] p-3 rounded-lg border border-white/[0.03] select-text">
              {{ selectedDoc.content || selectedDoc.content_preview }}
            </div>
          </div>
          
          <!-- 标签 -->
          <div v-if="selectedDoc.tags?.length > 0" class="flex flex-wrap gap-1.5">
            <span v-for="tag in selectedDoc.tags" :key="tag" class="inline-flex items-center gap-0.5 bg-[#0ea5e9]/10 text-[#0ea5e9] text-[10px] px-2 py-0.5 rounded-full">
              <Tag :size="8" /> {{ tag }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
  </div>
</template>

<style scoped>
.knowledge-page {
  --knowledge-ink: #1e293b;
  --knowledge-muted: #64748b;
}

.knowledge-page :deep([class*="bg-[#131926]"]),
.knowledge-page :deep([class*="bg-[#0b0f19]"]),
.knowledge-page :deep([class*="bg-[#070a12]"]) {
  background: #ffffff !important;
}

.knowledge-page :deep([class*="text-[#f3f4f6]"]),
.knowledge-page :deep([class*="text-[#cbd5e1]"]),
.knowledge-page :deep([class*="text-[#94a3b8]"]) {
  color: var(--knowledge-ink) !important;
}

.knowledge-page :deep([class*="text-[#64748b]"]),
.knowledge-page :deep([class*="text-[#475569]"]),
.knowledge-page :deep([class*="text-[#334155]"]) {
  color: var(--knowledge-muted) !important;
}

.knowledge-modal {
  color: #1e293b;
}

.knowledge-modal :deep([class*="bg-white/[0.02]"]),
.knowledge-modal :deep([class*="bg-white/[0.03]"]) {
  background: #f8fafc !important;
}

.knowledge-modal :deep([class*="bg-[#070a12]"]) {
  background: #f8fafc !important;
  border-color: #e2e8f0 !important;
}

.knowledge-modal :deep([class*="text-[#f3f4f6]"]),
.knowledge-modal :deep([class*="text-[#cbd5e1]"]) {
  color: #1e293b !important;
}

.knowledge-modal :deep([class*="text-[#94a3b8]"]),
.knowledge-modal :deep([class*="text-[#64748b]"]) {
  color: #64748b !important;
}
</style>
