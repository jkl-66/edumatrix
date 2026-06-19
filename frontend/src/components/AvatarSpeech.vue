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

// --- Audio State ---
let audioContext = null
let analyser = null
let scriptNode = null
const BUFFER_SIZE = 4096
let audioStack = [] // Queue of Float32Array chunks

// --- 任务 7.9: 情感感知语速控制 ---
const _STRESS_KEYWORDS = ['崩溃','好难','学不会','焦虑','压力大','受不了','想放弃','太难了','完全不懂','绝望']

function _detectStress(text) {
  if (!text) return false
  const lower = text.toLowerCase()
  return _STRESS_KEYWORDS.some(kw => lower.includes(kw))
}

function _getEmpatheticSpeed(text) {
  // 高压力时语速减慢至 0.85 倍 (讯飞 speed: 50=正常, 降低到 42)
  return _detectStress(text) ? 42 : 50
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

// --- iFLYTEK Config ---
function getXfConfig() {
  try {
    const raw = localStorage.getItem('edumatrix_llm_config')
    if (raw) return JSON.parse(raw)
  } catch {}
  return {}
}

async function hmacSha256(key, message) {
  const enc = new TextEncoder()
  const keyData = enc.encode(key)
  const messageData = enc.encode(message)
  const cryptoKey = await crypto.subtle.importKey(
    'raw', keyData, { name: 'HMAC', hash: 'SHA-256' },
    false, ['sign']
  )
  const signature = await crypto.subtle.sign('HMAC', cryptoKey, messageData)
  return btoa(String.fromCharCode(...new Uint8Array(signature)))
}

async function getWebsocketUrl() {
  const cfg = getXfConfig()
  const apiKey = cfg.xfApiKey
  const apiSecret = cfg.xfApiSecret
  if (!apiKey || !apiSecret) throw new Error('iFLYTEK API keys not configured')

  const url = 'wss://tts-api.xfyun.cn/v2/tts'
  const host = 'tts-api.xfyun.cn'
  const date = new Date().toUTCString()
  const requestLine = 'GET /v2/tts HTTP/1.1'
  const signatureOrigin = `host: ${host}\ndate: ${date}\n${requestLine}`
  const signature = await hmacSha256(apiSecret, signatureOrigin)
  const authOrigin = `api_key="${apiKey}", algorithm="hmac-sha256", headers="host date request-line", signature="${signature}"`
  const authorization = btoa(authOrigin)

  return `${url}?authorization=${authorization}&date=${encodeURIComponent(date)}&host=${host}`
}

// --- Audio Playback Engine (Task 5.1: ScriptProcessor) ---
function initAudio() {
  if (audioContext) return
  audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 })
  analyser = audioContext.createAnalyser()
  analyser.fftSize = 256

  // ScriptProcessor for streaming buffer management
  scriptNode = audioContext.createScriptProcessor(BUFFER_SIZE, 1, 1)
  
  let offset = 0
  let currentChunk = null

  scriptNode.onaudioprocess = (e) => {
    const output = e.outputBuffer.getChannelData(0)
    let written = 0
    
    while (written < BUFFER_SIZE) {
      if (!currentChunk) {
        if (audioStack.length > 0) {
          currentChunk = audioStack.shift()
          offset = 0
        } else {
          // No more data, fill with silence
          output.fill(0, written)
          if (isSpeaking.value && written === 0 && !isLoading.value) {
            // Probably finished
            isSpeaking.value = false
            emit('finished')
          }
          break
        }
      }

      const available = currentChunk.length - offset
      const toWrite = Math.min(available, BUFFER_SIZE - written)
      output.set(currentChunk.subarray(offset, offset + toWrite), written)
      
      written += toWrite
      offset += toWrite

      if (offset >= currentChunk.length) {
        currentChunk = null
      }
    }
  }

  scriptNode.connect(analyser)
  analyser.connect(audioContext.destination)
}

// Convert PCM16 (base64) to Float32Array
function pcm16ToFloat32(base64) {
  const binaryString = window.atob(base64)
  const len = binaryString.length
  const bytes = new Uint8Array(len)
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i)
  }
  
  const int16Buffer = new Int16Array(bytes.buffer)
  const float32Buffer = new Float32Array(int16Buffer.length)
  for (let i = 0; i < int16Buffer.length; i++) {
    float32Buffer[i] = int16Buffer[i] / 32768
  }
  return float32Buffer
}

async function startTTS(text) {
  if (!text) return
  isLoading.value = true
  isSpeaking.value = true
  audioStack = []
  
  initAudio()
  if (audioContext.state === 'suspended') await audioContext.resume()

  try {
    const url = await getWebsocketUrl()
    const ws = new WebSocket(url)
    const cfg = getXfConfig()

    ws.onopen = () => {
      const params = {
        common: { app_id: cfg.xfAppId },
        business: {
          aue: 'raw', // Task 5.1: Raw PCM
          sfl: 1,
          tte: 'UTF8',
          vcn: 'xiaoyan',
          speed: _getEmpatheticSpeed(text),
          volume: 50,
          pitch: 50,
          bgs: 0
        },
        data: {
          status: 2,
          text: btoa(unescape(encodeURIComponent(_getEmpatheticPrefix(text))))
        }
      }
      ws.send(JSON.stringify(params))
    }

    ws.onmessage = (e) => {
      const res = JSON.parse(e.data)
      if (res.code !== 0) {
        console.error('TTS Error:', res.message)
        ws.close()
        return
      }
      
      if (res.data && res.data.audio) {
        audioStack.push(pcm16ToFloat32(res.data.audio))
      }

      if (res.data.status === 2) {
        ws.close()
        isLoading.value = false
      }
    }

    ws.onerror = (err) => {
      console.error('WS Error:', err)
      isLoading.value = false
      isSpeaking.value = false
    }
  } catch (e) {
    console.error('TTS Setup failed:', e)
    isLoading.value = false
    isSpeaking.value = false
  }
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
  if (isSpeaking.value && analyser) {
    const dataArray = new Uint8Array(analyser.frequencyBinCount)
    analyser.getByteFrequencyData(dataArray)
    const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length
    targetScale = 1 + (average / 128) * 2.0 // Adjust sensitivity
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

function toggleMute() {
  isMuted.value = !isMuted.value
  if (audioContext) {
    if (isMuted.value) audioContext.suspend()
    else audioContext.resume()
  }
}

onMounted(() => {
  draw()
})

onUnmounted(() => {
  if (audioContext) audioContext.close()
})

defineExpose({ speak: startTTS })
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
