import { onMounted, onUnmounted, reactive } from 'vue'
import { readPreference } from '../utils/learningPreferenceStorage'

export const preferenceKeys = {
  imageAnalysis: 'edumatrix_multimodal_image_enabled',
  speechInput: 'edumatrix_speech_input_enabled',
  readAloud: 'edumatrix_read_aloud_enabled',
}

export function readLearningPreferences() {
  return {
    imageAnalysis: readPreference(preferenceKeys.imageAnalysis) !== 'false',
    speechInput: readPreference(preferenceKeys.speechInput) !== 'false',
    readAloud: readPreference(preferenceKeys.readAloud) === 'true',
  }
}

export function useLearningPreferences() {
  const preferences = reactive(readLearningPreferences())
  const refresh = () => Object.assign(preferences, readLearningPreferences())
  onMounted(() => {
    window.addEventListener('edumatrix-preferences-changed', refresh)
    window.addEventListener('storage', refresh)
  })
  onUnmounted(() => {
    window.removeEventListener('edumatrix-preferences-changed', refresh)
    window.removeEventListener('storage', refresh)
  })
  return preferences
}
