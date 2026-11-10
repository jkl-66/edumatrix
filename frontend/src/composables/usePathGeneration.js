import { computed, onBeforeUnmount, ref } from 'vue'
import { findPathGenerationTask, getPathGenerationTask } from '../api/m5.js'

// Polling only observes the persisted task; it never starts a model request.
export function usePathGeneration({ onComplete, onError, getTask = id => getPathGenerationTask(id), findTask = params => findPathGenerationTask(params) } = {}) {
  const task = ref(null)
  const connectionError = ref('')
  const busy = computed(() => task.value?.automation?.enabled
    ? !['completed', 'cancelled'].includes(task.value.automation.state)
    : ['queued', 'running'].includes(task.value?.status))
  let timer = null
  let revision = 0
  let failures = 0
  let query = null

  function reset() {
    revision += 1
    clearTimeout(timer)
    timer = null
    task.value = null
    connectionError.value = ''
    failures = 0
  }

  async function accept(value, expected = revision) {
    if (expected !== revision) return
    clearTimeout(timer)
    task.value = value
    connectionError.value = ''
    failures = 0
    if (value?.status === 'completed') await onComplete?.(value, () => expected === revision)
    else if (value?.status === 'failed' && !value.automation?.enabled) onError?.(value.message)
    else if (busy.value) timer = setTimeout(() => refresh(), 3000)
  }

  async function refresh() {
    const expected = revision
    clearTimeout(timer)
    try {
      const result = task.value?.id
        ? await getTask(task.value.id)
        : await findTask(query)
      await accept(result.task, expected)
    } catch {
      if (expected !== revision) return
      connectionError.value = '暂时无法读取进度，已保存的安排仍然保留。'
      failures += 1
      timer = setTimeout(() => refresh(), Math.min(30000, 5000 * failures))
    }
  }

  async function restore(params) {
    reset()
    query = params
    await refresh()
  }

  onBeforeUnmount(reset)
  return { task, busy, connectionError, accept, restore, refresh, reset }
}
