// Resolve availability first, then preserve the frozen quote's precise position.
export function sourcePassageKey(source) {
  return JSON.stringify([
    source.sourceDocumentId ?? source.source_document_id, source.kind, source.route,
    source.sourceRefId ?? source.source_ref_id ?? source.id,
    source.documentVersion ?? source.document_version ?? source.contentHash ?? source.content_hash,
    source.charStart ?? source.char_start, source.charEnd ?? source.char_end,
    source.pageNumber ?? source.page_number, source.selectionId ?? source.selection_id,
    source.quote, source.available, source.reason,
  ])
}

export function groupSourcePassages(sources) {
  const groups = new Map()
  const seen = new Set()
  for (const source of sources || []) {
    const key = sourcePassageKey(source)
    if (seen.has(key)) continue
    seen.add(key)
    const groupKey = JSON.stringify([
      source.sourceDocumentId ?? source.source_document_id ?? source.sourceRefId ?? source.source_ref_id ?? source.id,
      source.documentVersion ?? source.document_version ?? source.contentHash ?? source.content_hash,
    ])
    if (!groups.has(groupKey)) groups.set(groupKey, { key: groupKey, title: source.title || source.filename || '课程来源', passages: [] })
    groups.get(groupKey).passages.push({ key, source })
  }
  return [...groups.values()]
}

export function passagePreview(source) {
  const location = source.locationLabel || source.location_label
  if (location && location !== source.title) return location
  const quote = String(source.quote || '')
  // Keep a genuine heading or prose preview; code and display equations do
  // not make readable link labels. The full frozen passage remains untouched.
  const prose = quote.replace(/```[\s\S]*?```/g, '').replace(/\$\$[\s\S]*?\$\$/g, '')
    .split('\n').map(line => line.replace(/^\s*[#>*-]+\s*/, '').trim())
    .find(line => line && !/^[:!{\\]/.test(line))
  const text = (prose || '').replace(/\[([^\]]+)\]\([^)]*\)/g, '$1').replace(/[*`]/g, '')
  const math = text.search(/\$|\\\(/)
  const end = Math.min(64, math < 0 ? text.length : math)
  const preview = text.slice(0, end).trim()
  return preview ? preview + (end < text.length ? '…' : '') : '查看原文相关段落'
}

export function sourceCitationRoute(latest, selected) {
  const route = String(latest.route || selected.route || '')
  if (!route.startsWith('/') || route.startsWith('//')) return ''
  const field = (object, camel, snake) => object[camel] ?? object[snake]
  const selectedDocument = field(selected, 'sourceDocumentId', 'source_document_id')
  const latestDocument = field(latest, 'sourceDocumentId', 'source_document_id')
  const selectedVersion = field(selected, 'documentVersion', 'document_version')
  const latestVersion = field(latest, 'documentVersion', 'document_version')
  const start = field(selected, 'charStart', 'char_start')
  const end = field(selected, 'charEnd', 'char_end')
  if (!selectedDocument || selectedDocument !== latestDocument
      || !selectedVersion || selectedVersion !== latestVersion) return route
  const [path, search = ''] = route.split('?')
  const params = new URLSearchParams(search)
  const selectionId = field(selected, 'selectionId', 'selection_id')
  if (selectionId) params.set('selection_id', String(selectionId))
  if (Number.isInteger(start) && Number.isInteger(end) && start >= 0 && end > start) {
    params.set('char_start', String(start))
    params.set('char_end', String(end))
  } else if (!selectionId) return route
  return `${path}?${params.toString()}`
}
