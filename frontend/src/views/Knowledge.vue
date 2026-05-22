<script setup>
import { ref, onMounted } from 'vue'
import { listKnowledgeDocuments, uploadKnowledgeDocument, deleteKnowledgeDocument } from '../api'
import { BookOpen, Upload, Trash2, FileText, File, FileImage, FileVideo, Presentation, Tag, Clock, AlertCircle, CheckCircle, Image, Film } from '@lucide/vue'

const props = defineProps({ studentId: String })

const docs = ref([])
const loading = ref(true)
const uploading = ref(false)
const uploadProgress = ref(0)
const dragOver = ref(false)
const uploadError = ref('')
const uploadSuccess = ref('')
const error = ref('')

const fileTypes = ['.md', '.txt', '.pdf', '.json', '.pptx', '.ppt', '.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv']
const acceptedTypes = '.md,.txt,.pdf,.json,.pptx,.ppt,.mp4,.avi,.mov,.mkv,.webm,.flv'

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
  if (type === 'pptx' || type === 'ppt') return Presentation
  if (type === 'md') return FileText
  if (['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'].includes(type)) return Film
  return File
}

function fileColor(type) {
  if (type === 'pdf') return 'text-red-500 bg-red-50'
  if (type === 'pptx' || type === 'ppt') return 'text-orange-500 bg-orange-50'
  if (type === 'md') return 'text-blue-500 bg-blue-50'
  if (['mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'].includes(type)) return 'text-purple-500 bg-purple-50'
  if (type === 'txt') return 'text-gray-500 bg-gray-50'
  return 'text-green-500 bg-green-50'
}

function isMultimodal(doc) {
  return doc.is_multimodal || ['pptx', 'ppt', 'mp4', 'avi', 'mov', 'mkv', 'webm', 'flv'].includes(doc.file_type)
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
      uploadError.value = `不支持的文件类型: ${ext}`
      continue
    }
    uploading.value = true
    uploadProgress.value = 0
    try {
      const result = await uploadKnowledgeDocument(file, props.studentId || 'default', (e) => {
        if (e.total) uploadProgress.value = Math.round((e.loaded / e.total) * 100)
      })
      const typeLabel = result.is_multimodal ? (result.file_category === 'video' ? '视频' : 'PPT') : '文档'
      uploadSuccess.value = `${file.name} ${typeLabel}上传成功 (${result.chunk_count} 个知识块)`
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

onMounted(load)
</script>

<template>
  <div class="max-w-4xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-sm font-semibold text-gray-800">知识库 ({{ docs.length }})</h2>
    </div>

    <div class="relative mb-6" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">
      <div class="border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer"
        :class="dragOver ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-blue-300 hover:bg-gray-50'">
        <input type="file" :accept="acceptedTypes" multiple class="absolute inset-0 opacity-0 cursor-pointer" @change="handleUpload" />
        <Upload :size="36" class="mx-auto mb-3" :class="dragOver ? 'text-blue-500' : 'text-gray-400'" />
        <p class="text-sm font-medium text-gray-700">{{ dragOver ? '释放文件以上传' : '拖拽文件到此处，或点击选择文件' }}</p>
        <p class="text-xs text-gray-400 mt-1">支持 文档(.md/.txt/.pdf) / PPT(.pptx) / 视频(.mp4/.avi/.mov) 自动解析</p>
      </div>
    </div>

    <div v-if="uploading" class="card mb-4">
      <div class="flex items-center gap-3">
        <div class="flex-1">
          <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
            <div class="h-full bg-blue-500 rounded-full transition-all duration-300" :style="{ width: uploadProgress + '%' }" />
          </div>
        </div>
        <span class="text-xs text-gray-500 shrink-0">{{ uploadProgress }}%</span>
      </div>
    </div>

    <div v-if="uploadSuccess" class="card mb-4 bg-green-50 border-green-200 flex items-center gap-2">
      <CheckCircle :size="16" class="text-green-600 shrink-0" />
      <span class="text-sm text-green-700">{{ uploadSuccess }}</span>
      <button class="ml-auto text-green-500 text-xs hover:text-green-700" @click="uploadSuccess = ''">关闭</button>
    </div>

    <div v-if="uploadError" class="card mb-4 bg-red-50 border-red-200 flex items-center gap-2">
      <AlertCircle :size="16" class="text-red-600 shrink-0" />
      <span class="text-sm text-red-700">{{ uploadError }}</span>
      <button class="ml-auto text-red-500 text-xs hover:text-red-700" @click="uploadError = ''">关闭</button>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="pulse-dot" /><span class="ml-3 text-gray-400 text-sm">加载中...</span>
    </div>

    <div v-else-if="error" class="text-center py-12">
      <AlertCircle :size="40" class="mx-auto mb-3 text-red-300" />
      <p class="text-sm text-red-500">{{ error }}</p>
      <button class="btn btn-outline text-xs mt-4" @click="load">重试</button>
    </div>

    <div v-else-if="docs.length === 0" class="text-center py-12 text-gray-400">
      <BookOpen :size="40" class="mx-auto mb-3 text-gray-300" />
      <p class="text-sm">知识库为空</p>
      <p class="text-xs mt-1">上传文档/PPT/视频后，AI 将自动解析并索引，用于学习问答</p>
    </div>

    <div v-else class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <div v-for="doc in docs" :key="doc.id" class="card hover:shadow-md transition-shadow">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-lg flex items-center justify-center shrink-0" :class="fileColor(doc.file_type)">
            <component :is="fileIcon(doc.file_type)" :size="20" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="flex items-center gap-1.5">
              <h3 class="text-sm font-medium text-gray-800 truncate">{{ doc.filename }}</h3>
              <span v-if="isMultimodal(doc)" class="badge bg-gradient-to-r from-purple-500 to-pink-500 text-white text-[9px] px-1.5 py-0 shrink-0">多模态</span>
            </div>
            <div class="flex flex-wrap items-center gap-2 mt-1.5">
              <span class="text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">{{ (doc.file_type || '').toUpperCase() }}</span>
              <span class="text-[10px] text-gray-400">{{ formatSize(doc.file_size) }}</span>
              <span class="text-[10px] text-gray-400">{{ doc.chunk_count }} 块</span>
              <span v-if="doc.multimodal_metadata?.slide_count" class="text-[10px] text-gray-400">{{ doc.multimodal_metadata.slide_count }} 页</span>
              <span v-if="doc.multimodal_metadata?.video_duration" class="text-[10px] text-gray-400">{{ Math.round(doc.multimodal_metadata.video_duration) }}s</span>
              <span v-if="doc.created_at" class="text-[10px] text-gray-400 flex items-center gap-1"><Clock :size="10" /> {{ ago(doc.created_at) }}</span>
            </div>
            <p v-if="doc.content_preview" class="text-[11px] text-gray-500 mt-2 line-clamp-2">{{ doc.content_preview }}</p>
            <div v-if="doc.tags && doc.tags.length > 0" class="flex flex-wrap gap-1 mt-2">
              <span v-for="tag in doc.tags.slice(0, 4)" :key="tag" class="badge bg-blue-50 text-blue-700 text-[10px]"><Tag :size="8" /> {{ tag }}</span>
              <span v-if="doc.tags.length > 4" class="text-[10px] text-gray-400">+{{ doc.tags.length - 4 }}</span>
            </div>
          </div>
          <button class="btn btn-outline p-1.5 shrink-0 text-red-400 hover:text-red-600 hover:border-red-200" @click="remove(doc.id, doc.filename)">
            <Trash2 :size="14" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
