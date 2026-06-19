<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { Video, Loader2, Play, Maximize2, Minimize2, Volume2, VolumeX } from '@lucide/vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  videoUrl: { type: String, default: '' },
  studentId: { type: String, default: '' },
})

const emit = defineEmits(['close', 'complete'])

// --- Render progress state ---
const steps = [
  { key: 'script', label: '脚本规划', status: ref('pending') },
  { key: 'tts', label: '语音合成', status: ref('pending') },
  { key: 'visual', label: '视觉合成', status: ref('pending') },
  { key: 'render', label: '视频渲染', status: ref('pending') },
  { key: 'merge', label: '合并输出', status: ref('pending') },
]

const overallProgress = ref(0)
const isRendering = ref(false)
const isComplete = ref(false)
const currentStepIndex = ref(-1)

// --- Player state ---
const isPlaying = ref(false)
const isMuted = ref(false)
const isFullscreen = ref(false)
const playerVolume = ref(1)
const currentTime = ref(0)
const duration = ref(0)
const videoRef = ref(null)

const progressPercent = computed(() => Math.round(overallProgress.value))

function simulateRender() {
  if (!props.visible) return
  isRendering.value = true
  isComplete.value = false
  overallProgress.value = 0
  currentStepIndex.value = -1

  const stepDurations = [2000, 2500, 3000, 3000, 1500] // ms per step
  let totalElapsed = 0
  const totalTime = stepDurations.reduce((a, b) => a + b, 0)

  const interval = setInterval(() => {
    totalElapsed += 200
    overallProgress.value = Math.min(100, (totalElapsed / totalTime) * 100)

    // Determine current step
    let accumulated = 0
    for (let i = 0; i < stepDurations.length; i++) {
      accumulated += stepDurations[i]
      if (totalElapsed <= accumulated) {
        currentStepIndex.value = i
        // Mark previous steps as complete
        for (let j = 0; j < i; j++) steps[j].status.value = 'complete'
        // Mark current as rendering
        steps[i].status.value = 'rendering'
        break
      }
    }

    if (totalElapsed >= totalTime) {
      clearInterval(interval)
      for (const s of steps) s.status.value = 'complete'
      isRendering.value = false
      isComplete.value = true
      overallProgress.value = 100
      emit('complete')
    }
  }, 200)
}

function togglePlay() {
  if (!videoRef.value) return
  if (isPlaying.value) {
    videoRef.value.pause()
  } else {
    videoRef.value.play()
  }
  isPlaying.value = !isPlaying.value
}

function toggleMute() {
  isMuted.value = !isMuted.value
  if (videoRef.value) videoRef.value.muted = isMuted.value
}

function toggleFullscreen() {
  if (!videoRef.value) return
  if (!isFullscreen.value) {
    videoRef.value.requestFullscreen?.()
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
}

function seekTo(e) {
  if (videoRef.value && duration.value) {
    const rect = e.currentTarget.getBoundingClientRect()
    const pos = (e.clientX - rect.left) / rect.width
    videoRef.value.currentTime = pos * duration.value
  }
}

onMounted(() => {
  if (props.visible) simulateRender()
})

onUnmounted(() => {
  // cleanup
})
</script>

<template>
  <div v-if="visible" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
      <!-- Header -->
      <div class="flex items-center justify-between px-5 py-4 border-b border-gray-100">
        <div class="flex items-center gap-2">
          <Video :size="18" class="text-blue-500" />
          <span class="text-sm font-semibold text-gray-800">教学视频生成</span>
        </div>
        <button
          class="text-gray-400 hover:text-gray-600 transition-colors"
          @click="emit('close')"
        >
          ✕
        </button>
      </div>

      <!-- Rendering State -->
      <div v-if="isRendering || (steps.some(s => s.status.value !== 'pending') && !isComplete)" class="p-5 space-y-4">
        <!-- Progress ring -->
        <div class="flex flex-col items-center py-4">
          <div class="relative w-20 h-20">
            <svg class="w-20 h-20 -rotate-90" viewBox="0 0 72 72">
              <circle cx="36" cy="36" r="30" fill="none" stroke="#f0f0f0" stroke-width="6" />
              <circle
                cx="36" cy="36" r="30"
                fill="none" stroke="#3b82f6"
                stroke-width="6"
                stroke-linecap="round"
                :stroke-dasharray="188.5"
                :stroke-dashoffset="188.5 - (progressPercent / 100) * 188.5"
                class="transition-all duration-300"
              />
            </svg>
            <div class="absolute inset-0 flex items-center justify-center">
              <span class="text-sm font-bold text-blue-600">{{ progressPercent }}%</span>
            </div>
          </div>
          <p class="text-xs text-gray-400 mt-3">正在生成教学视频...</p>
        </div>

        <!-- Steps -->
        <div class="space-y-2">
          <div
            v-for="(step, idx) in steps"
            :key="step.key"
            class="flex items-center gap-3 px-3 py-2 rounded-lg"
            :class="{
              'bg-blue-50': step.status.value === 'rendering',
              'bg-emerald-50': step.status.value === 'complete',
              'bg-gray-50': step.status.value === 'pending',
            }"
          >
            <div
              class="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold"
              :class="{
                'bg-blue-500 text-white': step.status.value === 'rendering',
                'bg-emerald-500 text-white': step.status.value === 'complete',
                'bg-gray-200 text-gray-500': step.status.value === 'pending',
              }"
            >
              <Loader2 v-if="step.status.value === 'rendering'" :size="12" class="animate-spin" />
              <span v-else-if="step.status.value === 'complete'">✓</span>
              <span v-else>{{ idx + 1 }}</span>
            </div>
            <span
              class="text-sm"
              :class="{
                'text-blue-700 font-medium': step.status.value === 'rendering',
                'text-emerald-700': step.status.value === 'complete',
                'text-gray-500': step.status.value === 'pending',
              }"
            >{{ step.label }}</span>
          </div>
        </div>
      </div>

      <!-- Completed Player -->
      <div v-else-if="isComplete && props.videoUrl" class="p-0">
        <div class="relative bg-black">
          <video
            ref="videoRef"
            :src="props.videoUrl"
            class="w-full aspect-video"
            @timeupdate="onTimeUpdate"
            @ended="onVideoEnded"
            @loadedmetadata="duration = $event.target.duration"
          />
          <!-- Video Controls -->
          <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent px-4 py-3">
            <!-- Progress bar -->
            <div
              class="h-1 bg-white/20 rounded-full mb-2 cursor-pointer"
              @click="seekTo"
            >
              <div
                class="h-full bg-blue-500 rounded-full transition-all"
                :style="{ width: duration > 0 ? (currentTime / duration * 100) + '%' : '0%' }"
              />
            </div>
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-3">
                <button @click="togglePlay" class="text-white hover:text-blue-300 transition-colors">
                  <Play v-if="!isPlaying" :size="18" />
                  <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                </button>
                <button @click="toggleMute" class="text-white/70 hover:text-white transition-colors">
                  <Volume2 v-if="!isMuted" :size="16" />
                  <VolumeX v-else :size="16" />
                </button>
                <span class="text-xs text-white/70">
                  {{ Math.floor(currentTime / 60) }}:{{ String(Math.floor(currentTime % 60)).padStart(2, '0') }}
                  / {{ Math.floor(duration / 60) }}:{{ String(Math.floor(duration % 60)).padStart(2, '0') }}
                </span>
              </div>
              <button @click="toggleFullscreen" class="text-white/70 hover:text-white transition-colors">
                <Maximize2 v-if="!isFullscreen" :size="16" />
                <Minimize2 v-else :size="16" />
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="px-5 py-3 border-t border-gray-100 flex justify-between items-center">
        <p class="text-xs text-gray-400">
          {{ isComplete ? '视频生成完成' : isRendering ? '正在渲染中...' : '准备就绪' }}
        </p>
        <button
          v-if="isComplete"
          class="text-xs text-blue-600 hover:text-blue-700 font-medium"
          @click="emit('close')"
        >
          关闭
        </button>
      </div>
    </div>
  </div>
</template>
