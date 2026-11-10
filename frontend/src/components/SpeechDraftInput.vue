<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { LoaderCircle, Mic, Square } from '@lucide/vue'
import { cancelSpeechSession, createSpeechSession, transcribeSpeechSession } from '../api/speech'
import { recorderBlobToWav } from '../utils/recordingAudio'
import { useLearningPreferences } from '../services/learningPreferences'

const props = defineProps({ disabled: Boolean })
const emit = defineEmits(['transcript'])
const preferences = useLearningPreferences()
const state = ref('idle')
const notice = ref('')
const seconds = ref(0)
let recorder = null
let stream = null
let timer = null
let requestId = 0
let sessionId = ''

function release() {
  stream?.getTracks().forEach(track => track.stop())
  stream = null
  clearInterval(timer)
  timer = null
}

function cancel() {
  requestId += 1
  if (recorder?.state === 'recording') recorder.stop()
  release()
  if (sessionId) cancelSpeechSession(sessionId).catch(() => {})
  sessionId = ''
  state.value = 'idle'
}

async function start() {
  if (state.value !== 'idle' || props.disabled || !preferences.speechInput) return
  notice.value = ''
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
    notice.value = '当前浏览器无法使用麦克风，可以继续输入文字。'
    return
  }
  const current = ++requestId
  state.value = 'starting'
  try {
    const acquired = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } })
    if (current !== requestId) { acquired.getTracks().forEach(track => track.stop()); return }
    stream = acquired
    const parts = []
    recorder = new MediaRecorder(stream)
    const mimeType = recorder.mimeType
    recorder.ondataavailable = event => { if (event.data?.size) parts.push(event.data) }
    recorder.onerror = () => { cancel(); notice.value = '录音未能完成，原有文字仍然保留，请重新录入。' }
    recorder.onstop = async () => {
      if (current !== requestId) return
      release()
      state.value = 'transcribing'
      notice.value = '正在整理录音，完成后会加入草稿，你可以先检查和修改。'
      try {
        const wav = await recorderBlobToWav(new Blob(parts, { type: mimeType }))
        if (current !== requestId) return
        const created = await createSpeechSession(wav, 'zh')
        if (current !== requestId) { cancelSpeechSession(created.id).catch(() => {}); return }
        sessionId = created.id
        const result = await transcribeSpeechSession(created.id, 'zh')
        if (current !== requestId) return
        if (result.status !== 'completed' || !result.transcript?.trim()) {
          notice.value = '这次没有整理出可用文字。原有草稿仍在，可以重新录入或继续打字。'
        } else {
          emit('transcript', result.transcript.trim())
          notice.value = '录音已加入草稿，请检查文字后再提交。'
        }
      } catch {
        if (current === requestId) notice.value = '录音暂时未能转成文字，原有草稿仍在，可以重试或继续打字。'
      } finally {
        if (current === requestId) { state.value = 'idle'; sessionId = '' }
      }
    }
    recorder.start(500)
    state.value = 'recording'
    seconds.value = 0
    timer = setInterval(() => { seconds.value += 1; if (seconds.value >= 300) stop() }, 1000)
  } catch (e) {
    if (current !== requestId) return
    cancel()
    notice.value = e?.name === 'NotAllowedError'
      ? '尚未获得麦克风权限。可以允许麦克风后重试，也可以继续输入文字。'
      : '无法开始录音，请检查麦克风连接，也可以继续输入文字。'
  }
}
function stop() {
  if (recorder?.state === 'recording') recorder.stop()
  state.value = 'transcribing'
  clearInterval(timer)
}
watch(() => preferences.speechInput, enabled => { if (!enabled) cancel() })
watch(() => props.disabled, disabled => { if (disabled) cancel() })
onBeforeUnmount(cancel)
</script>

<template>
  <span v-if="preferences.speechInput" class="speech-draft">
    <button v-if="state === 'idle'" type="button" :disabled="disabled" @click="start"><Mic :size="16" />语音输入</button>
    <button v-else-if="state === 'recording'" type="button" @click="stop"><Square :size="16" />停止录入 · {{ seconds }} 秒</button>
    <span v-else><LoaderCircle :size="16" />{{ state === 'starting' ? '正在打开麦克风…' : '正在整理录音…' }}</span>
    <button v-if="state !== 'idle'" type="button" @click="cancel">取消录入</button>
    <span v-if="notice" role="status">{{ notice }}</span>
  </span>
</template>

<style scoped>
.speech-draft { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
button, span > span { display: inline-flex; align-items: center; gap: 6px; }
button { padding: 7px 10px; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 6px; color: var(--color-text-secondary); cursor: pointer; font: inherit; }
[role=status] { flex-basis: 100%; font-size: 13px; color: var(--color-text-secondary); }
</style>
