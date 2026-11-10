/** Local browsing preferences only. Learning progress is never written here. */
export function materialBrowserKey(owner, courseId) {
  return `edumatrix_material_browser:${encodeURIComponent(owner)}:${encodeURIComponent(courseId)}`
}

export function readMaterialBrowser(storage, owner, courseId) {
  try {
    return JSON.parse(storage.getItem(materialBrowserKey(owner, courseId)) || '{}') || {}
  } catch {
    return {}
  }
}

export function saveMaterialBrowser(storage, owner, courseId, state) {
  try {
    storage.setItem(materialBrowserKey(owner, courseId), JSON.stringify(state))
  } catch {
    // Storage can be unavailable; reading and opening materials still works.
  }
}

export function arrangeCourseMaterials(items, { query = '', sort = 'course', pinned = [], recent = [] } = {}) {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  return items.filter(item => {
    const text = [item.title, ...(item.chapters || []).map(chapter => chapter.title)].join(' ').toLocaleLowerCase()
    return words.every(word => text.includes(word))
  }).sort((left, right) => {
    const pinDifference = Number(pinned.includes(right.id)) - Number(pinned.includes(left.id))
    if (pinDifference) return pinDifference
    if (sort === 'title') return left.title.localeCompare(right.title, 'zh-CN', { numeric: true })
    if (sort === 'recent') {
      const rank = item => recent.includes(item.id) ? recent.indexOf(item.id) : Number.MAX_SAFE_INTEGER
      return rank(left) - rank(right)
    }
    return 0
  })
}
