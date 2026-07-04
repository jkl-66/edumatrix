<script setup>
import { ref, watch, computed } from 'vue'
import { Play, Pause, Maximize2, Minimize2, Volume2, VolumeX, X, Film, ChevronLeft, ChevronRight } from '@lucide/vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  videos: { type: Array, default: () => [] },
  knowledgePoint: { type: String, default: '' },
})

const emit = defineEmits(['close'])

const currentIndex = ref(0)
const isPlaying = ref(false)
const isMuted = ref(false)
const isFullscreen = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const videoRef = ref(null)
const containerRef = ref(null)

const currentVideo = computed(() => {
  if (props.videos.length === 0) return null
  return props.videos[currentIndex.value] || props.videos[0]
})

watch(() => props.visible, (val) => {
  if (val) {
    currentIndex.value = 0
    isPlaying.value = false
  }
})

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
  // 自动播放下一个
  if (currentIndex.value < props.videos.length - 1) {
    setTimeout(() => {
      nextVideo()
    }, 1000)
  }
}

function prevVideo() {
  if (currentIndex.value > 0) {
    currentIndex.value--
    isPlaying.value = false
  }
}

function nextVideo() {
  if (currentIndex.value < props.videos.length - 1) {
    currentIndex.value++
    isPlaying.value = false
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
  const m = Math.floor(s / 60)
  const sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}

function formatSize(bytes) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="visible"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      @click.self="emit('close')"
    >
      <div
        ref="containerRef"
        class="bg-gray-900 rounded-2xl shadow-2xl w-full max-w-3xl mx-4 overflow-hidden border border-gray-700"
      >
        <!-- Header -->
        <div class="flex items-center justify-between px-5 py-3 border-b border-gray-700">
          <div class="flex items-center gap-2">
            <Film :size="18" class="text-blue-400" />
            <span class="text-sm font-semibold text-gray-200">
              {{ knowledgePoint }} · 本地动画
            </span>
            <span class="text-xs text-gray-500">
              {{ currentIndex + 1 }}/{{ videos.length }}
            </span>
          </div>
          <button
            class="text-gray-400 hover:text-white transition-colors p-1"
            @click="emit('close')"
          >
            <X :size="18" />
          </button>
        </div>

        <!-- Video Player -->
        <div class="relative bg-black">
          <video
            v-if="currentVideo"
            ref="videoRef"
            :src="currentVideo.url"
            class="w-full"
            style="max-height: 60vh"
            :muted="isMuted"
            @timeupdate="onTimeUpdate"
            @ended="onVideoEnded"
            @click="togglePlay"
          />

          <!-- Play overlay -->
          <div
            v-if="!isPlaying && currentVideo"
            class="absolute inset-0 flex items-center justify-center bg-black/30 cursor-pointer"
            @click="togglePlay"
          >
            <div class="w-14 h-14 rounded-full bg-white/20 backdrop-blur flex items-center justify-center hover:bg-white/30 transition-colors">
              <Play :size="28" class="text-white ml-1" />
            </div>
          </div>
        </div>

        <!-- Controls -->
        <div class="px-4 py-3 space-y-2">
          <!-- Progress bar -->
          <div
            class="h-1.5 bg-gray-700 rounded-full cursor-pointer"
            @click="seekTo"
          >
            <div
              class="h-full bg-blue-500 rounded-full transition-all"
              :style="{ width: duration ? (currentTime / duration * 100) + '%' : '0%' }"
            />
          </div>

          <!-- Buttons -->
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <button
                class="text-gray-400 hover:text-white p-1 disabled:opacity-30"
                :disabled="currentIndex === 0"
                @click="prevVideo"
              >
                <ChevronLeft :size="20" />
              </button>
              <button
                class="text-gray-400 hover:text-white p-1"
                @click="togglePlay"
              >
                <Play v-if="!isPlaying" :size="20" />
                <Pause v-else :size="20" />
              </button>
              <button
                class="text-gray-400 hover:text-white p-1 disabled:opacity-30"
                :disabled="currentIndex >= videos.length - 1"
                @click="nextVideo"
              >
                <ChevronRight :size="20" />
              </button>
              <span class="text-xs text-gray-500 ml-2">
                {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
              </span>
            </div>
            <div class="flex items-center gap-2">
              <button
                class="text-gray-400 hover:text-white p-1"
                @click="toggleMute"
              >
                <Volume2 v-if="!isMuted" :size="18" />
                <VolumeX v-else :size="18" />
              </button>
              <button
                class="text-gray-400 hover:text-white p-1"
                @click="toggleFullscreen"
              >
                <Maximize2 v-if="!isFullscreen" :size="18" />
                <Minimize2 v-else :size="18" />
              </button>
            </div>
          </div>

          <!-- Video info -->
          <div v-if="currentVideo" class="text-xs text-gray-500 truncate">
            {{ currentVideo.filename }} · {{ formatSize(currentVideo.size) }}
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>