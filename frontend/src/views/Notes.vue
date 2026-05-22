<script setup>
import { ref, onMounted } from 'vue'
import { getNotes, createNote, deleteNote } from '../api'
import { StickyNote, Plus, Trash2, Tag, Clock } from '@lucide/vue'

const props = defineProps({ studentId: String })

const notes = ref([])
const loading = ref(true)
const showForm = ref(false)
const form = ref({ source: '', content: '', tags: '', concepts: '' })

async function load() {
  loading.value = true
  try {
    const data = await getNotes(props.studentId)
    const list = Array.isArray(data) ? data : data.notes || []
    notes.value = list
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

async function addNote() {
  if (!form.value.content.trim()) return
  try {
    await createNote(props.studentId, {
      source: form.value.source || '手动记录',
      content: form.value.content,
      tags: form.value.tags ? form.value.tags.split(/[,，]/).map(t => t.trim()).filter(Boolean) : [],
      concepts: form.value.concepts ? form.value.concepts.split(/[,，]/).map(c => c.trim()).filter(Boolean) : [],
    })
    form.value = { source: '', content: '', tags: '', concepts: '' }
    showForm.value = false
    await load()
  } catch (e) {
    console.error(e)
  }
}

async function remove(id) {
  try {
    await deleteNote(id)
    await load()
  } catch (e) {
    console.error(e)
  }
}

function ago(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  return `${Math.floor(s / 86400)}天前`
}

onMounted(load)
</script>

<template>
  <div class="max-w-4xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-sm font-semibold text-gray-800">我的笔记 ({{ notes.length }})</h2>
      <button class="btn btn-primary" @click="showForm = !showForm">
        <Plus :size="16" />
        <span>新建笔记</span>
      </button>
    </div>

    <!-- New note form -->
    <div v-if="showForm" class="card mb-6">
      <div class="space-y-3">
        <input v-model="form.content" class="input" placeholder="笔记内容（必填）" />
        <div class="grid grid-cols-3 gap-3">
          <input v-model="form.source" class="input" placeholder="来源 (如: 课程/对话)" />
          <input v-model="form.tags" class="input" placeholder="标签 (逗号分隔)" />
          <input v-model="form.concepts" class="input" placeholder="概念 (逗号分隔)" />
        </div>
        <div class="flex gap-2 justify-end">
          <button class="btn btn-outline text-xs" @click="showForm = false">取消</button>
          <button class="btn btn-primary text-xs" @click="addNote">保存</button>
        </div>
      </div>
    </div>

    <!-- Notes list -->
    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="pulse-dot" />
      <span class="ml-3 text-gray-400 text-sm">加载中...</span>
    </div>

    <div v-else-if="notes.length === 0" class="text-center py-12 text-gray-400">
      <StickyNote :size="40" class="mx-auto mb-3 text-gray-300" />
      <p class="text-sm">暂无笔记</p>
      <p class="text-xs mt-1">在对话框中学习后自动生成，或手动创建</p>
    </div>

    <div v-else class="space-y-3">
      <div v-for="note in notes" :key="note.id" class="card flex items-start gap-4">
        <div class="flex-1 min-w-0">
          <p class="text-sm text-gray-800 whitespace-pre-wrap">{{ note.content }}</p>
          <div class="flex flex-wrap items-center gap-2 mt-2">
            <span v-if="note.source" class="badge bg-gray-100 text-gray-600">{{ note.source }}</span>
            <span v-for="tag in (note.tags || [])" :key="tag" class="badge bg-blue-50 text-blue-700">{{ tag }}</span>
            <span v-for="concept in (note.concepts || [])" :key="concept" class="badge bg-purple-50 text-purple-700">{{ concept }}</span>
            <span v-if="note.created_at" class="text-[10px] text-gray-400 flex items-center gap-1 ml-auto">
              <Clock :size="10" /> {{ ago(note.created_at) }}
            </span>
          </div>
        </div>
        <button class="btn btn-outline p-1.5 shrink-0 text-red-400 hover:text-red-600 hover:border-red-200" @click="remove(note.id)">
          <Trash2 :size="14" />
        </button>
      </div>
    </div>
  </div>
</template>
