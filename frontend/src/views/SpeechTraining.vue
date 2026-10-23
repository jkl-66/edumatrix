<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { AlertCircle, CheckCircle2, Download, FileText, LoaderCircle, Mic, MicOff, Play, RotateCcw, ShieldCheck, Square, Volume2, VolumeX, X } from '@lucide/vue'
import { cancelSpeechSession, createSpeechSession, downloadSpeechSubtitles, getSpeechRuntime, listSpeechSessions, transcribeSpeechSession } from '../api'
import AvatarSpeech from '../components/AvatarSpeech.vue'

const runtime = ref(null)
const sessions = ref([])
const loading = ref(true)
const error = ref('')
const recording = ref(false)
const processing = ref(false)
const elapsedSeconds = ref(0)
const language = ref('auto')
const selectedSessionId = ref('')
const fallbackText = ref('')
const speaking = ref(false)
let mediaRecorder = null
let mediaStream = null
let recordedChunks = []
let timer = null
let startedAt = 0

const selectedSession = computed(() => sessions.value.find(item => item.id === selectedSessionId.value) || sessions.value[0] || null)
const displayText = computed(() => selectedSession.value?.transcript || fallbackText.value.trim())
const canRecord = computed(() => typeof navigator !== 'undefined' && navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== 'undefined')

function message(errorValue, fallback) {
  const detail = errorValue?.response?.data?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || errorValue?.message || fallback
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [runtimeStatus, history] = await Promise.all([getSpeechRuntime(), listSpeechSessions()])
    runtime.value = runtimeStatus
    sessions.value = history
    if (!selectedSessionId.value && history.length) selectedSessionId.value = history[0].id
  } catch (caught) {
    error.value = message(caught, '语音工作台加载失败')
  } finally {
    loading.value = false
  }
}

function writeString(view, offset, text) {
  for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index))
}

function encodeWav(samples, sampleRate = 16000) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)
  let offset = 44
  for (const sample of samples) {
    const value = Math.max(-1, Math.min(1, sample))
    view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true)
    offset += 2
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

async function recorderBlobToWav(blob) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!AudioContextClass) throw new Error('当前浏览器不支持本地音频解码')
  const context = new AudioContextClass()
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer())
    const targetRate = 16000
    const outputLength = Math.max(1, Math.round(decoded.duration * targetRate))
    const samples = new Float32Array(outputLength)
    for (let index = 0; index < outputLength; index += 1) {
      const sourceIndex = Math.min(decoded.length - 1, Math.floor(index * decoded.sampleRate / targetRate))
      let mixed = 0
      for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) mixed += decoded.getChannelData(channel)[sourceIndex]
      samples[index] = mixed / decoded.numberOfChannels
    }
    return encodeWav(samples, targetRate)
  } finally {
    await context.close()
  }
}

async function startRecording() {
  error.value = ''
  if (!canRecord.value) {
    error.value = '当前浏览器不支持麦克风录音，请使用下方文本练习。'
    return
  }
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
    recordedChunks = []
    mediaRecorder = new MediaRecorder(mediaStream)
    mediaRecorder.ondataavailable = event => { if (event.data?.size) recordedChunks.push(event.data) }
    mediaRecorder.onstop = finishRecording
    mediaRecorder.start(500)
    recording.value = true
    startedAt = Date.now()
    elapsedSeconds.value = 0
    timer = window.setInterval(() => {
      elapsedSeconds.value = Math.min(300, Math.floor((Date.now() - startedAt) / 1000))
      if (elapsedSeconds.value >= 300) stopRecording()
    }, 250)
  } catch (caught) {
    error.value = caught?.name === 'NotAllowedError' ? '麦克风权限被拒绝，请允许权限或使用文本练习。' : message(caught, '无法启动麦克风')
    releaseMicrophone()
  }
}

function stopRecording() {
  if (mediaRecorder?.state === 'recording') mediaRecorder.stop()
  recording.value = false
  if (timer) window.clearInterval(timer)
  timer = null
}

function releaseMicrophone() {
  mediaStream?.getTracks().forEach(track => track.stop())
  mediaStream = null
}

async function finishRecording() {
  releaseMicrophone()
  processing.value = true
  try {
    const blob = new Blob(recordedChunks, { type: mediaRecorder?.mimeType || 'audio/webm' })
    const wav = await recorderBlobToWav(blob)
    const created = await createSpeechSession(wav, language.value)
    selectedSessionId.value = created.id
    sessions.value = [created, ...sessions.value.filter(item => item.id !== created.id)]
    const completed = await transcribeSpeechSession(created.id, language.value)
    sessions.value = sessions.value.map(item => item.id === completed.id ? completed : item)
    if (completed.status !== 'completed') error.value = '离线转写当前不可用，录音记录已保留，请使用文本练习。'
  } catch (caught) {
    error.value = message(caught, '录音转写失败，仍可使用文本练习。')
  } finally {
    processing.value = false
    recordedChunks = []
  }
}

async function cancelCurrent() {
  if (!selectedSession.value || selectedSession.value.status === 'completed') return
  try {
    const cancelled = await cancelSpeechSession(selectedSession.value.id)
    sessions.value = sessions.value.map(item => item.id === cancelled.id ? cancelled : item)
  } catch (caught) {
    error.value = message(caught, '取消失败')
  }
}

function speak() {
  if (!displayText.value || !('speechSynthesis' in window)) {
    error.value = '当前浏览器不支持语音朗读，文本与字幕仍可正常使用。'
    return
  }
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(displayText.value)
  utterance.lang = language.value === 'en' ? 'en-US' : 'zh-CN'
  utterance.onstart = () => { speaking.value = true }
  utterance.onend = () => { speaking.value = false }
  utterance.onerror = () => { speaking.value = false }
  window.speechSynthesis.speak(utterance)
}

function stopSpeaking() {
  window.speechSynthesis?.cancel()
  speaking.value = false
}

async function downloadVtt() {
  if (!selectedSession.value?.id) return
  try {
    const blob = await downloadSpeechSubtitles(selectedSession.value.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${selectedSession.value.id}.vtt`
    link.click()
    URL.revokeObjectURL(url)
  } catch (caught) {
    error.value = message(caught, '字幕下载失败')
  }
}

function formatTime(milliseconds) {
  const seconds = Math.max(0, Math.floor(Number(milliseconds || 0) / 1000))
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`
}

onMounted(load)
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
  if (mediaRecorder?.state === 'recording') mediaRecorder.stop()
  releaseMicrophone()
  window.speechSynthesis?.cancel()
})
</script>

<template>
  <div class="mx-auto max-w-5xl text-slate-800" data-testid="speech-training-workspace">
    <header class="border-b border-slate-200 pb-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div><h1 class="text-lg font-semibold text-slate-950">语音技能训练</h1><p class="mt-1 text-sm text-slate-600">浏览器录音，本机 CPU 转写，字幕与文本全程可用。</p></div>
        <span v-if="runtime" data-testid="speech-runtime-status" class="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium" :class="runtime.available ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800'"><CheckCircle2 v-if="runtime.available" :size="14" /><AlertCircle v-else :size="14" />{{ runtime.available ? `${runtime.version} · ${runtime.model_name}` : '文本降级模式' }}</span>
      </div>
    </header>

    <div v-if="loading" class="flex min-h-64 items-center justify-center gap-2 text-sm text-slate-500"><LoaderCircle :size="17" class="animate-spin" />正在检查离线语音运行时...</div>
    <template v-else>
      <div v-if="error" data-testid="speech-error" class="mt-4 flex items-start gap-2 border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800"><AlertCircle :size="16" class="mt-0.5 shrink-0" /><span>{{ error }}</span><button class="ml-auto" title="关闭" aria-label="关闭" @click="error = ''"><X :size="15" /></button></div>

      <section class="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(280px,0.85fr)]">
        <div class="border-y border-slate-200 py-5">
          <div class="flex flex-wrap items-center justify-between gap-3"><div><h2 class="text-sm font-semibold text-slate-950">口述练习</h2><p class="mt-1 text-xs text-slate-600">最长 5 分钟，浏览器本地转换为 16kHz 单声道 WAV。</p></div><select v-model="language" class="h-9 border border-slate-300 bg-white px-3 text-xs"><option value="auto">自动识别</option><option value="zh">中文</option><option value="en">English</option></select></div>
          <div class="mt-6 flex min-h-48 flex-col items-center justify-center border border-slate-200 bg-slate-50 p-6 text-center">
            <button v-if="!recording" type="button" data-testid="speech-record" :disabled="processing" class="flex h-16 w-16 items-center justify-center rounded-full bg-red-600 text-white shadow-sm disabled:opacity-50" title="开始录音" @click="startRecording"><Mic :size="25" /></button>
            <button v-else type="button" data-testid="speech-stop" class="flex h-16 w-16 items-center justify-center rounded-full bg-slate-900 text-white" title="停止录音" @click="stopRecording"><Square :size="22" /></button>
            <p class="mt-4 text-sm font-medium text-slate-900">{{ processing ? '本机 CPU 正在转写...' : recording ? `录音中 ${elapsedSeconds}s` : '点击开始口述' }}</p>
            <p class="mt-1 text-xs text-slate-500">{{ canRecord ? '音频只保存在当前账号范围，不发送到外部模型。' : '浏览器不支持录音，请使用文本练习。' }}</p>
            <LoaderCircle v-if="processing" :size="18" class="mt-3 animate-spin text-cyan-700" />
          </div>

          <div class="mt-5">
            <label for="speech-fallback" class="text-xs font-medium text-slate-700">文本练习与降级输入</label>
            <textarea id="speech-fallback" v-model="fallbackText" data-testid="speech-text-fallback" maxlength="5000" rows="4" class="mt-2 w-full resize-y border border-slate-300 bg-white p-3 text-sm outline-none focus:border-cyan-600" placeholder="没有麦克风或 ASR 不可用时，直接输入训练内容。" />
            <div class="mt-2 flex flex-wrap gap-2"><button type="button" :disabled="!displayText" class="inline-flex h-9 items-center gap-2 bg-slate-900 px-3 text-xs font-medium text-white disabled:opacity-40" @click="speak"><Volume2 :size="14" />朗读</button><button v-if="speaking" type="button" class="inline-flex h-9 items-center gap-2 border border-slate-300 px-3 text-xs" @click="stopSpeaking"><VolumeX :size="14" />停止</button></div>
          </div>
        </div>

        <aside class="min-w-0 border-y border-slate-200 py-5">
          <div class="flex items-center justify-between gap-2"><h2 class="text-sm font-semibold text-slate-950">转写记录</h2><button type="button" class="text-slate-500" title="刷新" aria-label="刷新" @click="load"><RotateCcw :size="15" /></button></div>
          <div v-if="!sessions.length" class="mt-4 border border-dashed border-slate-300 px-4 py-8 text-center text-xs text-slate-500">完成一次录音后，字幕和运行时证据会保存在这里。</div>
          <div v-else class="mt-3 max-h-44 space-y-2 overflow-y-auto">
            <button v-for="item in sessions" :key="item.id" type="button" data-testid="speech-session" class="w-full border px-3 py-2 text-left" :class="selectedSessionId === item.id ? 'border-cyan-500 bg-cyan-50' : 'border-slate-200 bg-white'" @click="selectedSessionId = item.id"><div class="flex items-center justify-between gap-2"><span class="truncate text-xs font-medium text-slate-900">{{ item.title }}</span><span class="text-[10px] text-slate-500">{{ item.status }}</span></div><p class="mt-1 text-[10px] text-slate-500">{{ Math.round(item.duration_ms / 1000) }}s · {{ item.truth_state }}</p></button>
          </div>
          <div v-if="selectedSession" class="mt-4" data-testid="speech-transcript-panel">
            <div class="mb-4 flex items-center gap-3 border border-blue-100 bg-blue-50/60 px-3 py-2" data-testid="local-avatar-speech">
              <AvatarSpeech :text="displayText" />
              <div class="min-w-0">
                <p class="text-xs font-semibold text-slate-900">本地数字人讲解层</p>
                <p class="mt-1 text-[11px] leading-relaxed text-slate-600">浏览器 TTS 与字幕同步展示；不可用时保留文本和 WebVTT，不依赖外部模型。</p>
              </div>
            </div>
            <div class="flex flex-wrap items-center justify-between gap-2"><span class="text-xs font-medium text-slate-800">{{ selectedSession.truth_state === 'real_offline' ? '真实离线转写' : selectedSession.truth_state }}</span><div class="flex gap-1"><button v-if="selectedSession.status === 'completed'" type="button" class="flex h-8 w-8 items-center justify-center border border-slate-300" title="下载 WebVTT 字幕" @click="downloadVtt"><Download :size="14" /></button><button v-else-if="!['cancelled','failed','unavailable'].includes(selectedSession.status)" type="button" class="flex h-8 w-8 items-center justify-center border border-red-200 text-red-700" title="取消任务" @click="cancelCurrent"><MicOff :size="14" /></button></div></div>
            <p class="mt-3 min-h-16 whitespace-pre-wrap border border-slate-200 bg-slate-50 p-3 text-sm leading-relaxed text-slate-800">{{ selectedSession.transcript || '尚无转写文本，可使用左侧文本练习。' }}</p>
            <ol v-if="selectedSession.segments?.length" class="mt-3 max-h-52 space-y-2 overflow-y-auto" data-testid="speech-subtitle-timeline"><li v-for="segment in selectedSession.segments" :key="segment.index" class="grid grid-cols-[48px_1fr] gap-2 border-b border-slate-100 pb-2 text-xs"><span class="font-mono text-slate-500">{{ formatTime(segment.start_ms) }}</span><span class="text-slate-700">{{ segment.text }}</span></li></ol>
          </div>
          <div class="mt-4 flex items-start gap-2 border border-emerald-200 bg-emerald-50 px-3 py-2 text-[11px] leading-relaxed text-emerald-800"><ShieldCheck :size="14" class="mt-0.5 shrink-0" />无 CUDA、Docker、联网和 API Key；运行时哈希不匹配时自动切换文本模式。</div>
        </aside>
      </section>
    </template>
  </div>
</template>
