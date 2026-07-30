<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { Volume2, VolumeX, Loader2 } from '@lucide/vue'

const props = defineProps({
  text: String,
  autoplay: { type: Boolean, default: false }
})

const emit = defineEmits(['finished'])

const canvasRef = ref(null)
const isMuted = ref(false)
const isSpeaking = ref(false)
const isLoading = ref(false)

// Browser-native speech synthesis is intentionally used here. Provider API
// secrets must never be stored or used by frontend code. A future provider
// integration must be exposed through an authenticated backend proxy.
let utterance = null

// --- 任务 7.9: 情感感知语速控制 ---
const _STRESS_KEYWORDS = ['崩溃','好难','学不会','焦虑','压力大','受不了','想放弃','太难了','完全不懂','绝望']

function _detectStress(text) {
  if (!text) return false
  const lower = text.toLowerCase()
  return _STRESS_KEYWORDS.some(kw => lower.includes(kw))
}

function _getEmpatheticSpeed(text) {
  return _detectStress(text) ? 0.85 : 1
}

function _getEmpatheticPrefix(text) {
  // 高压力时在文本前加入同理心引导
  if (!_detectStress(text)) return text
  const prefixes = [
    '我理解这部分确实有难度，别着急，我们一起慢慢来看。',
    '不用有压力，学习本身就是个循序渐进的过程。',
    '这个地方确实容易让人困惑，让我用最简单的方式给你讲讲。',
    '没关系，遇到困难是正常的，我们来换个角度理解。',
  ]
  return prefixes[Math.floor(Math.random() * prefixes.length)] + ' ' + text
}

// --- Lip Sync State ---
const lastScale = ref(1)
const smoothScale = ref(1)
const ALPHA = 0.25

function cleanTextForSpeech(text) {
  if (!text) return ''
  let clean = text
    .replace(/<svg[\s\S]*?<\/svg>/gi, '')
    .replace(/<plot[\s\S]*?<\/plot>/gi, '')
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`[^`\n]+`/g, '')
    .replace(/\$\$[\s\S]*?\$\$/g, '[公式]')
    .replace(/\$([^$\n]+?)\$/g, (_, math) => {
      return math
        .replace(/\\alpha/g, '阿尔法')
        .replace(/\\beta/g, '贝塔')
        .replace(/\\sigma/g, '西格玛')
        .replace(/\\theta/g, '西塔')
        .replace(/\\lambda/g, '兰布达')
        .replace(/\\partial/g, '偏导')
        .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1的估计值')
        .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$2分之$1')
        .replace(/\\cdot/g, '点')
        .replace(/\\times/g, '乘')
        .replace(/\\sum/g, '求和')
        .replace(/\\infty/g, '无穷大')
        .replace(/\\/g, '')
        .replace(/[{}]/g, '')
    })
    .replace(/#+\s+/g, '')
    .replace(/[*_~]+/g, '')
    .replace(/<[^>]+>/g, '')
  return clean.trim()
}

async function startTTS(text) {
  if (!text) return
  const cleanedText = cleanTextForSpeech(text)
  if (!cleanedText) return
  if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) {
    console.warn('Browser speech synthesis is unavailable')
    emit('finished')
    return
  }
  stopTTS()
  utterance = new SpeechSynthesisUtterance(_getEmpatheticPrefix(cleanedText))
  utterance.lang = 'zh-CN'
  utterance.rate = _getEmpatheticSpeed(cleanedText)
  utterance.volume = isMuted.value ? 0 : 1
  utterance.onstart = () => {
    isLoading.value = false
    isSpeaking.value = true
  }
  utterance.onend = () => {
    isSpeaking.value = false
    isPaused.value = false
    utterance = null
    emit('finished')
  }
  utterance.onerror = () => {
    isLoading.value = false
    isSpeaking.value = false
    isPaused.value = false
    utterance = null
  }
  isLoading.value = true
  window.speechSynthesis.speak(utterance)
}

// --- Canvas Animation (Task 5.2) ---
function draw() {
  if (!canvasRef.value) return
  const canvas = canvasRef.value
  const ctx = canvas.getContext('2d')
  const w = canvas.width
  const h = canvas.height

  // 1. Calculate Target Scale from Audio Amplitude
  let targetScale = 1
  if (isSpeaking.value && !isPaused.value) {
    targetScale = 1.15 + 0.15 * Math.sin(Date.now() / 90)
  }

  // 2. Task 5.2: First-Order Low-Pass Exponential Smoothing
  // SmoothScale = 0.25 * TargetScale + 0.75 * LastScale;
  smoothScale.value = ALPHA * targetScale + (1 - ALPHA) * lastScale.value
  lastScale.value = smoothScale.value

  // 3. Clear and Draw
  ctx.clearRect(0, 0, w, h)
  const centerX = w / 2
  const centerY = h / 2

  // Background Glow
  if (isSpeaking.value) {
    const grad = ctx.createRadialGradient(centerX, centerY, 20, centerX, centerY, 55)
    grad.addColorStop(0, 'rgba(59, 130, 246, 0.15)')
    grad.addColorStop(1, 'transparent')
    ctx.fillStyle = grad
    ctx.beginPath(); ctx.arc(centerX, centerY, 55, 0, Math.PI * 2); ctx.fill()
  }

  // Draw Face
  ctx.strokeStyle = '#3b82f6'
  ctx.lineWidth = 3
  ctx.lineCap = 'round'

  // Head
  ctx.beginPath(); ctx.arc(centerX, centerY, 40, 0, Math.PI * 2); ctx.stroke()

  // Eyes (Blinking effect could be added, but keeping it simple)
  ctx.fillStyle = '#3b82f6'
  ctx.beginPath(); ctx.arc(centerX - 15, centerY - 10, 3, 0, Math.PI * 2); ctx.fill()
  ctx.beginPath(); ctx.arc(centerX + 15, centerY - 10, 3, 0, Math.PI * 2); ctx.fill()

  // Mouth (Lip Sync)
  const mouthWidth = 18
  const baseHeight = 2
  const mouthHeight = baseHeight + 12 * (smoothScale.value - 1)
  
  ctx.beginPath()
  ctx.ellipse(centerX, centerY + 15, mouthWidth / 2, mouthHeight / 2, 0, 0, Math.PI * 2)
  if (isSpeaking.value && smoothScale.value > 1.05) {
    ctx.fillStyle = '#3b82f6'
    ctx.fill()
  } else {
    ctx.stroke()
  }

  requestAnimationFrame(draw)
}

const isPaused = ref(false)

function pauseTTS() {
  if ('speechSynthesis' in window && isSpeaking.value && !isPaused.value) {
    window.speechSynthesis.pause()
    isPaused.value = true
  }
}

function resumeTTS() {
  if ('speechSynthesis' in window && isPaused.value) {
    window.speechSynthesis.resume()
    isPaused.value = false
  }
}

function stopTTS() {
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  isSpeaking.value = false
  isPaused.value = false
  isLoading.value = false
  utterance = null
}

function toggleMute() {
  isMuted.value = !isMuted.value
  if (utterance) utterance.volume = isMuted.value ? 0 : 1
  if (isMuted.value) pauseTTS()
  else resumeTTS()
}

watch(() => props.text, (text) => {
  if (props.autoplay && text) startTTS(text)
})

onMounted(() => {
  draw()
})

onUnmounted(() => {
  stopTTS()
})

defineExpose({
  speak: startTTS,
  pause: pauseTTS,
  resume: resumeTTS,
  stop: stopTTS,
  isSpeaking,
  isPaused,
  isLoading,
})
</script>

<template>
  <div class="avatar-container flex flex-col items-center gap-2">
    <div class="relative">
      <canvas ref="canvasRef" width="120" height="120" class="rounded-full bg-white border border-blue-50 shadow-sm"></canvas>
      
      <div v-if="isLoading" class="absolute inset-0 flex items-center justify-center bg-white/20 rounded-full">
        <Loader2 :size="20" class="text-blue-500 animate-spin" />
      </div>

      <button 
        @click="toggleMute"
        class="absolute -bottom-1 -right-1 w-8 h-8 rounded-full bg-white shadow-md border border-slate-100 flex items-center justify-center text-slate-500 hover:text-blue-600 transition-colors"
      >
        <Volume2 v-if="!isMuted" :size="14" />
        <VolumeX v-else :size="14" class="text-red-500" />
      </button>
    </div>
    
    <div class="text-center">
      <p class="text-[10px] font-bold text-blue-500 uppercase tracking-widest">AI Tutor</p>
      <div v-if="isSpeaking" class="flex gap-0.5 mt-1 justify-center">
        <div v-for="i in 3" :key="i" class="w-1 bg-blue-400/60 rounded-full animate-pulse" :style="{ height: '4px' }"></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.avatar-container {
  padding: 0.5rem;
}
canvas {
  image-rendering: -webkit-optimize-contrast;
}
</style>
