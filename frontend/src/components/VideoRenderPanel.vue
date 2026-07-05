<script setup>
import { ref, watch, computed } from 'vue'
import { Video, Loader2, Play, Pause, Maximize2, Minimize2, Volume2, VolumeX, Film, ChevronLeft, ChevronRight, FolderOpen } from '@lucide/vue'
import { listAllAnimations } from '../api'

const props = defineProps({
  visible: { type: Boolean, default: false },
  studentId: { type: String, default: '' },
  knowledgePoint: { type: String, default: '' },
})

const emit = defineEmits(['close', 'complete'])

const loading = ref(false)
const error = ref('')
const allAnimations = ref({})
const knowledgePoints = ref([])

const selectedKp = ref('')
const selectedVideoIdx = ref(0)

const videoRef = ref(null)
const containerRef = ref(null)
const isPlaying = ref(false)
const isMuted = ref(false)
const isFullscreen = ref(false)
const currentTime = ref(0)
const duration = ref(0)

const isComplete = ref(false)

const currentVideos = computed(() => {
  if (!selectedKp.value) return []
  return allAnimations.value[selectedKp.value] || []
})

const currentVideo = computed(() => {
  const list = currentVideos.value
  if (list.length === 0) return null
  return list[selectedVideoIdx.value] || list[0]
})

watch(() => props.visible, async (val) => {
  if (val) {
    selectedKp.value = ''
    selectedVideoIdx.value = 0
    isPlaying.value = false
    isComplete.value = false
    loading.value = true
    error.value = ''
    try {
      const data = await listAllAnimations()
      allAnimations.value = data.knowledge_points || {}
      knowledgePoints.value = Object.keys(allAnimations.value)
      // 自动定位到当前知识点
      if (props.knowledgePoint) {
        const kp = props.knowledgePoint
        // 精确匹配
        if (allAnimations.value[kp]) {
          selectKnowledgePoint(kp)
        } else {
          // 模糊匹配
          for (const key of knowledgePoints.value) {
            if (kp.includes(key) || key.includes(kp)) {
              selectKnowledgePoint(key)
              break
            }
          }
        }
      }
    } catch (e) {
      error.value = '加载动画列表失败: ' + (e.message || e)
    } finally {
      loading.value = false
    }
  }
})

function selectKnowledgePoint(kp) {
  selectedKp.value = kp
  selectedVideoIdx.value = 0
  isPlaying.value = false
  isComplete.value = false
}

function backToList() {
  selectedKp.value = ''
  selectedVideoIdx.value = 0
  isPlaying.value = false
  isComplete.value = false
}

function selectVideo(idx) {
  selectedVideoIdx.value = idx
  isPlaying.value = false
  isComplete.value = false
}

function togglePlay() {
  if (!videoRef.value) return
  if (isPlaying.value) {
    videoRef.value.pause()
  } else {
    videoRef.value.play().catch(() => {})
  }
  isPlaying.value = !isPlaying.value
}

function toggleMute() {
  isMuted.value = !isMuted.value
  if (videoRef.value) videoRef.value.muted = isMuted.value
}

function toggleFullscreen() {
  if (!containerRef.value) return
  if (!isFullscreen.value) {
    containerRef.value.requestFullscreen?.()
  } else {
    document.exitFullscreen?.()
  }
  isFullscreen.value = !isFullscreen.value
}

function onTimeUpdate() {
  if (videoRef.value) {
    currentTime.value = videoRef.value.currentTime
    duration.value = videoRef.value.duration || 0
  }
}

function onVideoEnded() {
  isPlaying.value = false
  isComplete.value = true
  emit('complete')
  if (selectedVideoIdx.value < currentVideos.value.length - 1) {
    setTimeout(() => {
      selectVideo(selectedVideoIdx.value + 1)
      setTimeout(() => {
        videoRef.value?.play().catch(() => {})
        isPlaying.value = true
      }, 200)
    }, 800)
  }
}

function seekTo(e) {
  if (videoRef.value && duration.value) {
    const rect = e.currentTarget.getBoundingClientRect()
    const pos = (e.clientX - rect.left) / rect.width
    videoRef.value.currentTime = pos * duration.value
  }
}

function formatTime(s) {
  if (!s || isNaN(s)) return '0:00'
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
    <div
      ref="containerRef"
      class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col overflow-hidden"
    >
      <!-- Header -->
      <div class="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
        <div class="flex items-center gap-2">
          <Film :size="18" class="text-blue-500" />
          <span class="text-sm font-semibold text-gray-800">本地动画库</span>
          <span v-if="knowledgePoints.length" class="text-xs text-gray-400 bg-gray-100 px-2 py-0.5 rounded-full">
            {{ knowledgePoints.length }} 个知识点
          </span>
        </div>
        <button class="text-gray-400 hover:text-gray-600 transition-colors" @click="emit('close')">✕</button>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <Loader2 :size="32" class="animate-spin text-blue-500" />
      </div>

      <!-- Error -->
      <div v-else-if="error" class="flex flex-col items-center justify-center py-20 px-6 text-center">
        <p class="text-red-500 text-sm">{{ error }}</p>
        <p class="text-gray-400 text-xs mt-2">请确认后端已启动且 data/animations/ 下有视频文件</p>
      </div>

      <!-- Empty -->
      <div v-else-if="knowledgePoints.length === 0" class="flex flex-col items-center justify-center py-20 px-6 text-center">
        <FolderOpen :size="48" class="text-gray-300 mb-3" />
        <p class="text-gray-500 text-sm">暂无本地动画</p>
        <p class="text-gray-400 text-xs mt-1">请先运行爬虫下载动画视频到 data/animations/ 目录</p>
      </div>

      <!-- Knowledge Point List -->
      <div v-else-if="!selectedKp" class="flex-1 overflow-y-auto p-4">
        <div class="grid grid-cols-2 gap-3">
          <button
            v-for="kp in knowledgePoints"
            :key="kp"
            class="flex flex-col items-start gap-1 p-3 rounded-xl border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-all text-left"
            @click="selectKnowledgePoint(kp)"
          >
            <div class="flex items-center gap-2 w-full">
              <Film :size="16" class="text-blue-500 shrink-0" />
              <span class="text-sm font-medium text-gray-700 truncate">{{ kp }}</span>
            </div>
            <span class="text-xs text-gray-400 ml-6">{{ allAnimations[kp].length }} 个视频</span>
          </button>
        </div>
      </div>

      <!-- Video Player for selected KP -->
      <div v-else class="flex-1 flex flex-col overflow-hidden">
        <!-- Sub-header -->
        <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100 shrink-0">
          <div class="flex items-center gap-2">
            <button class="text-gray-400 hover:text-blue-500 transition-colors" @click="backToList">
              <ChevronLeft :size="18" />
            </button>
            <span class="text-sm font-semibold text-gray-800">{{ selectedKp }}</span>
            <span class="text-xs text-gray-400">
              {{ selectedVideoIdx + 1 }}/{{ currentVideos.length }}
            </span>
          </div>
        </div>

        <!-- Video area -->
        <div class="relative bg-black shrink-0">
          <video
            v-if="currentVideo"
            ref="videoRef"
            :src="currentVideo.url"
            class="w-full"
            style="max-height: 45vh"
            :muted="isMuted"
            @timeupdate="onTimeUpdate"
            @ended="onVideoEnded"
            @loadedmetadata="duration = $event.target.duration"
            @play="isPlaying = true"
            @pause="isPlaying = false"
          />
          <div v-else class="w-full aspect-video flex items-center justify-center bg-gray-100">
            <p class="text-gray-400 text-sm">点击下方视频列表播放</p>
          </div>

          <!-- Video controls -->
          <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent px-4 py-3">
            <div class="h-1 bg-white/20 rounded-full mb-2 cursor-pointer" @click="seekTo">
              <div
                class="h-full bg-blue-500 rounded-full transition-all"
                :style="{ width: duration > 0 ? (currentTime / duration * 100) + '%' : '0%' }"
              />
            </div>
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <button @click="togglePlay" class="text-white hover:text-blue-300 transition-colors">
                  <Play v-if="!isPlaying" :size="18" />
                  <Pause v-else :size="18" />
                </button>
                <button @click="toggleMute" class="text-white/70 hover:text-white transition-colors">
                  <Volume2 v-if="!isMuted" :size="16" />
                  <VolumeX v-else :size="16" />
                </button>
                <span class="text-xs text-white/70">{{ formatTime(currentTime) }} / {{ formatTime(duration) }}</span>
              </div>
              <div class="flex items-center gap-2">
                <button
                  :disabled="selectedVideoIdx === 0"
                  class="text-white/70 hover:text-white transition-colors disabled:opacity-30"
                  @click="selectVideo(selectedVideoIdx - 1)"
                >
                  <ChevronLeft :size="16" />
                </button>
                <button
                  :disabled="selectedVideoIdx >= currentVideos.length - 1"
                  class="text-white/70 hover:text-white transition-colors disabled:opacity-30"
                  @click="selectVideo(selectedVideoIdx + 1)"
                >
                  <ChevronRight :size="16" />
                </button>
                <button @click="toggleFullscreen" class="text-white/70 hover:text-white transition-colors">
                  <Maximize2 v-if="!isFullscreen" :size="16" />
                  <Minimize2 v-else :size="16" />
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Video list -->
        <div class="flex-1 overflow-y-auto p-3 space-y-2">
          <div
            v-for="(v, idx) in currentVideos"
            :key="v.filename"
            class="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer transition-colors"
            :class="selectedVideoIdx === idx ? 'bg-blue-50 border border-blue-200' : 'hover:bg-gray-50 border border-transparent'"
            @click="selectVideo(idx)"
          >
            <div
              class="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
              :class="selectedVideoIdx === idx ? 'bg-blue-500 text-white' : 'bg-gray-100 text-gray-500'"
            >
              <Play v-if="selectedVideoIdx !== idx || !isPlaying" :size="14" />
              <Pause v-else :size="14" />
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm text-gray-700 truncate">{{ v.filename }}</p>
              <p class="text-xs text-gray-400">{{ formatSize(v.size) }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-5 py-3 border-t border-gray-100 shrink-0 flex justify-between items-center">
        <p class="text-xs text-gray-400">
          共 {{ knowledgePoints.length }} 个知识点，{{ Object.values(allAnimations).reduce((s, v) => s + v.length, 0) }} 个视频
        </p>
        <button class="text-xs text-blue-600 hover:text-blue-700 font-medium" @click="emit('close')">关闭</button>
      </div>
    </div>
  </div>
</template>