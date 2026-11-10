<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Pause, Play, Square, Volume2 } from '@lucide/vue'
import { useLearningPreferences } from '../services/learningPreferences'
import { speechChunks } from '../utils/spokenText'
import { createSpeechPlayback } from '../utils/speechPlayback'

const props = defineProps({ text: { type: String, default: '' } })
const preferences = useLearningPreferences()
const supported = Boolean(globalThis.speechSynthesis && globalThis.SpeechSynthesisUtterance)
const state = ref('idle')
const error = ref('')
const owner = {}
const playback = supported ? createSpeechPlayback({
  synthesis: globalThis.speechSynthesis,
  createUtterance: text => new SpeechSynthesisUtterance(text),
  onState: value => { state.value = value },
  onError: () => { error.value = '朗读未能继续，请检查声音设置后重试。' },
}) : null
function stop() { playback?.stop() }
function otherStarted(event) { if (event.detail !== owner) stop() }
function start() {
  error.value = ''
  if (!supported) { error.value = '当前浏览器暂不支持朗读，可以继续阅读正文。'; return }
  window.dispatchEvent(new CustomEvent('edumatrix-read-aloud-start', { detail: owner }))
  playback.start(speechChunks(props.text))
}
function togglePause() { playback?.togglePause() }
watch(() => preferences.readAloud, enabled => { if (!enabled) stop() })
watch(() => props.text, stop)
onMounted(() => window.addEventListener('edumatrix-read-aloud-start', otherStarted))
onBeforeUnmount(() => { stop(); window.removeEventListener('edumatrix-read-aloud-start', otherStarted) })
</script>

<template>
  <span v-if="preferences.readAloud && text" class="read-aloud">
    <button v-if="state === 'idle'" type="button" @click.stop="start"><Volume2 :size="16" />朗读回答</button>
    <template v-else>
      <button type="button" @click.stop="togglePause"><Play v-if="state === 'paused'" :size="16" /><Pause v-else :size="16" />{{ state === 'paused' ? '继续朗读' : '暂停朗读' }}</button>
      <button type="button" @click.stop="stop"><Square :size="16" />停止朗读</button>
    </template>
    <span v-if="error" role="status">{{ error }}</span>
  </span>
</template>

<style scoped>
.read-aloud { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
button { display: inline-flex; align-items: center; gap: 6px; border: 0; padding: 5px 0; background: none; color: var(--color-text-secondary); cursor: pointer; font: inherit; }
[role=status] { color: var(--color-text-secondary); font-size: 13px; }
</style>
