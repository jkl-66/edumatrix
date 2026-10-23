import { createM5LearningEvent } from '../api/m5'

const PENDING_KEY = 'edumatrix_pending_learning_events_v1'
const BROWSER_ACTIVITY_TYPES = new Set([
  'resource_opened',
  'reading_started',
  'reading_threshold',
  'video_started',
  'video_threshold',
  'video_completed',
  'explanation_started',
  'explanation_completed',
  'note_created',
  'code_run',
  'wrong_question_reviewed',
  'user_marked_complete',
])

function readPendingEvents() {
  try {
    const value = JSON.parse(localStorage.getItem(PENDING_KEY) || '[]')
    return Array.isArray(value) ? value : []
  } catch {
    return []
  }
}

function writePendingEvents(events) {
  if (events.length) localStorage.setItem(PENDING_KEY, JSON.stringify(events))
  else localStorage.removeItem(PENDING_KEY)
}

function sameEvent(left, right) {
  return JSON.stringify(left) === JSON.stringify(right)
}

function isNetworkError(error) {
  return !error?.status
}

export async function recordBrowserLearningEvent(payload) {
  if (!BROWSER_ACTIVITY_TYPES.has(payload?.event_type)) {
    throw new Error('浏览器只能提交普通学习活动，掌握证据必须由受信流程生成')
  }
  if (!payload?.idempotency_key) {
    throw new Error('学习活动缺少稳定幂等键')
  }
  const event = { ...payload, source: 'frontend' }
  try {
    return { status: 'synced', event: await createM5LearningEvent(event) }
  } catch (error) {
    if (!isNetworkError(error)) throw error
    const pending = readPendingEvents()
    const existing = pending.find(item => item.idempotency_key === event.idempotency_key)
    if (existing && !sameEvent(existing, event)) {
      throw new Error('该学习活动幂等键已绑定其他内容')
    }
    if (!existing) {
      pending.push(event)
      writePendingEvents(pending)
    }
    return { status: 'queued', idempotency_key: event.idempotency_key }
  }
}

export async function syncPendingLearningEvents() {
  const pending = readPendingEvents()
  const remaining = []
  const synced = []
  const rejected = []
  for (const event of pending) {
    try {
      synced.push(await createM5LearningEvent(event))
    } catch (error) {
      if (isNetworkError(error)) remaining.push(event)
      else rejected.push({ idempotency_key: event.idempotency_key, error })
    }
  }
  writePendingEvents(remaining)
  return { synced, pending: remaining.length, rejected }
}
