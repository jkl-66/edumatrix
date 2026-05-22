<script setup>
import { ref, computed, onMounted } from 'vue'
import { getHistory } from '../api'
import { Clock, MessageSquare, Search, ArrowRight } from '@lucide/vue'

const props = defineProps({ studentId: String })

const history = ref([])
const loading = ref(true)
const searchFilter = ref('')

onMounted(async () => {
  try {
    const data = await getHistory(props.studentId)
    const raw = data.conversations || data.history || []
    history.value = Array.isArray(raw) ? raw : []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
})

const filtered = computed(() => {
  if (!searchFilter.value) return history.value
  const q = searchFilter.value.toLowerCase()
  return history.value.filter(h =>
    (h.message || '').toLowerCase().includes(q) ||
    (h.response || '').toLowerCase().includes(q)
  )
})

function ago(ts) {
  if (!ts) return ''
  const s = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (s < 60) return '刚刚'
  if (s < 3600) return `${Math.floor(s / 60)}分钟前`
  if (s < 86400) return `${Math.floor(s / 3600)}小时前`
  return `${Math.floor(s / 86400)}天前`
}
</script>

<template>
  <div class="max-w-4xl mx-auto">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-sm font-semibold text-gray-800">对话历史 ({{ filtered.length }})</h2>
      <div class="relative w-64">
        <Search :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input v-model="searchFilter" class="input pl-8" placeholder="搜索对话内容..." />
      </div>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="pulse-dot" />
      <span class="ml-3 text-gray-400 text-sm">加载中...</span>
    </div>

    <div v-else-if="filtered.length === 0" class="text-center py-12 text-gray-400">
      <MessageSquare :size="40" class="mx-auto mb-3 text-gray-300" />
      <p class="text-sm">{{ searchFilter ? '没有匹配的对话记录' : '暂无对话历史' }}</p>
      <p class="text-xs mt-1">在智能对话中开始学习</p>
    </div>

    <div v-else class="space-y-3">
      <div v-for="item in filtered" :key="item.id || item.timestamp" class="card">
        <div class="flex items-start justify-between gap-4">
          <div class="flex-1 min-w-0 space-y-2">
            <!-- Student message -->
            <div class="flex items-start gap-2">
              <div class="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center text-blue-600 text-xs font-bold shrink-0">S</div>
              <p class="text-sm text-gray-800">{{ item.message || item.question || '-' }}</p>
            </div>

            <!-- Response summary -->
            <div v-if="item.response || item.target" class="flex items-start gap-2">
              <div class="w-6 h-6 rounded-full bg-purple-100 flex items-center justify-center text-purple-600 text-xs font-bold shrink-0">A</div>
              <div class="text-sm text-gray-600">
                <span>目标：{{ item.target || '-' }}</span>
                <span v-if="item.resources" class="ml-2 text-xs text-gray-400">({{ item.resources }} 资源)</span>
              </div>
            </div>

            <!-- Tags -->
            <div v-if="item.target" class="flex flex-wrap gap-1">
              <span class="badge bg-blue-50 text-blue-700 text-[10px]">{{ item.target }}</span>
              <span v-if="item.resources" class="badge bg-gray-100 text-gray-600 text-[10px]">{{ item.resources }} 资源</span>
            </div>
          </div>

          <!-- Timestamp -->
          <div class="shrink-0 text-right">
            <span class="text-[10px] text-gray-400 flex items-center gap-1">
              <Clock :size="10" /> {{ ago(item.created_at || item.timestamp) }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
