// Backend source ranges count Unicode code points rather than UTF-16 units.
export function splitChapterAtQuote(chapter, content, rawQuote, newKey) {
  const quote = String(rawQuote || '').trim()
  const characters = Array.from(String(content || ''))
  const body = characters.slice(chapter.char_start, chapter.char_end).join('')
  const position = body.indexOf(quote)
  if (!quote || position <= 0 || position + quote.length > body.length) {
    throw new Error('请填写本章中间一段原文的开头，不能使用章首或其他章节的内容。')
  }
  if (body.indexOf(quote, position + 1) !== -1) {
    throw new Error('这段文字在本章出现了多次，请多填写几句以确定位置。')
  }
  const start = chapter.char_start + Array.from(body.slice(0, position)).length
  // Read fields explicitly: a Vue reactive chapter cannot be structuredClone'd.
  return {
    key: newKey, title: `${chapter.title}（续）`,
    source_document_id: chapter.source_document_id,
    member_ids: [...chapter.member_ids], char_start: start, char_end: chapter.char_end,
    parent_key: chapter.parent_key, knowledge_point_ids: [...chapter.knowledge_point_ids],
    learning_role: chapter.learning_role || 'teaching',
  }
}

export function remapUnitChapters(structure, oldKey, replacements) {
  for (const unit of structure.units || []) {
    if (unit.primary_chapter_keys?.includes(oldKey)) {
      unit.primary_chapter_keys = [...new Set(unit.primary_chapter_keys.flatMap(key => key === oldKey ? replacements : [key]))]
    }
  }
}

export function canAcceptStructureSuggestion(structure, suggestion) {
  const [leftKey, rightKey] = suggestion.keys
  const field = suggestion.kind === 'adjacent_chapters' ? 'chapters' : 'concepts'
  const left = structure[field].find(item => (item.key || item.id) === leftKey)
  const right = structure[field].find(item => (item.key || item.id) === rightKey)
  if (!left || !right || left.title !== suggestion.titles[0] || right.title !== suggestion.titles[1]) return false
  if (field === 'concepts') return !left.merge_into && !right.merge_into
  return structure.chapters.indexOf(right) === structure.chapters.indexOf(left) + 1
    && left.source_document_id === right.source_document_id && left.parent_key === right.parent_key
    && (left.learning_role || 'teaching') === (right.learning_role || 'teaching')
    && left.char_end <= right.char_start
}

export function acceptStructureSuggestion(structure, suggestion) {
  if (!canAcceptStructureSuggestion(structure, suggestion)) return false
  const [leftKey, rightKey] = suggestion.keys
  if (suggestion.kind === 'adjacent_chapters') {
    const left = structure.chapters.find(item => item.key === leftKey)
    const right = structure.chapters.find(item => item.key === rightKey)
    left.title = suggestion.title
    left.member_ids = [...new Set([...left.member_ids, ...right.member_ids])]
    left.char_end = right.char_end
    left.knowledge_point_ids = [...new Set([...left.knowledge_point_ids, ...right.knowledge_point_ids])]
    for (const chapter of structure.chapters) if (chapter.parent_key === rightKey) chapter.parent_key = leftKey
    remapUnitChapters(structure, rightKey, [leftKey])
    structure.chapters.splice(structure.chapters.indexOf(right), 1)
  } else {
    const left = structure.concepts.find(item => item.id === leftKey)
    const right = structure.concepts.find(item => item.id === rightKey)
    left.title = suggestion.title
    right.merge_into = leftKey
    for (const point of structure.concepts) if (point.merge_into === rightKey) point.merge_into = leftKey
    const resolve = id => structure.concepts.find(point => point.id === id)?.merge_into || id
    structure.prerequisites = structure.prerequisites
      .map(item => ({ ...item, prerequisite_id: resolve(item.prerequisite_id), dependent_id: resolve(item.dependent_id) }))
      .filter(item => item.prerequisite_id !== item.dependent_id)
  }
  return true
}
