import { ref } from 'vue'
import { mergeResourceEdits } from '../utils/resourceEditMerge.js'

export function useResourceEditMerge(draft) {
  const conflicts = ref([])
  let pending = null
  function clear() { conflicts.value = []; pending = null }
  function refresh(base, latest) {
    const result = mergeResourceEdits(base, draft.value, latest)
    pending = { base, local: draft.value, latest, choices: {} }
    conflicts.value = result.conflicts
    if (!result.conflicts.length) { draft.value = result.content; pending = null }
  }
  function choose(key, choice) {
    if (!pending) return
    pending.choices[key] = choice
    const result = mergeResourceEdits(pending.base, pending.local, pending.latest, pending.choices)
    conflicts.value = result.conflicts
    if (!result.conflicts.length) { draft.value = result.content; pending = null }
  }
  return { conflicts, refresh, choose, clear }
}
