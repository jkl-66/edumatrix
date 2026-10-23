const MIN_ASSESSMENT_MINUTES = 5

export const ASSESSMENT_MINUTES_PER_QUESTION = Object.freeze({
  single_choice: 1,
  multiple_choice: 2,
  true_false: 1,
  fill_blank: 2,
  short_answer: 5,
})

export function calculateAssessmentDuration(counts = {}) {
  const total = Object.entries(ASSESSMENT_MINUTES_PER_QUESTION).reduce(
    (minutes, [type, weight]) => minutes + Math.max(0, Number(counts[type] || 0)) * weight,
    0,
  )
  return Math.max(MIN_ASSESSMENT_MINUTES, Math.ceil(total))
}

export function courseOptionsFromShelf(payload = {}) {
  const seen = new Set()
  return [...(payload.shelf || []), ...(payload.recommendations || [])].filter((course) => {
    const id = String(course?.id || '').trim()
    if (!id || seen.has(id)) return false
    seen.add(id)
    // The server is the source of truth.  Keep compatibility with legacy
    // payloads that omitted health fields, but never re-offer an explicitly
    // withdrawn/unavailable or empty course from stale client state.
    if (course?.selectable === false) return false
    if (['withdrawn', 'archived', 'draft'].includes(String(course?.status || '').toLowerCase())) return false
    if (course?.source_health === 'missing' && course?.index_status === 'missing') return false
    return true
  })
}

// Every course picker consumes the same server-projected shelf/recommendation
// payload.  The API remains authoritative; this defensive projection prevents
// a stale response or local cache from re-introducing withdrawn/empty shells.
export function selectableCourseOptions(payload = {}) {
  return courseOptionsFromShelf(payload)
}

export function todayKnowledgePointIds(items = [], courseId = '') {
  const expectedCourseId = String(courseId || '')
  const seen = new Set()
  return (items || []).reduce((ids, item) => {
    const itemCourseId = String(item?.course_id || '')
    const pointId = String(item?.knowledge_point_id || '').trim()
    if (expectedCourseId && itemCourseId && itemCourseId !== expectedCourseId) return ids
    if (pointId && !seen.has(pointId)) {
      seen.add(pointId)
      ids.push(pointId)
    }
    return ids
  }, [])
}

export function sortKnowledgePoints(points = [], todayIds = []) {
  const today = new Set(todayIds)
  return [...(points || [])].sort((left, right) => {
    const todayDelta = Number(today.has(String(left?.id))) - Number(today.has(String(right?.id)))
    if (todayDelta) return -todayDelta
    return String(left?.title || '').localeCompare(String(right?.title || ''), 'zh-Hans')
  })
}
