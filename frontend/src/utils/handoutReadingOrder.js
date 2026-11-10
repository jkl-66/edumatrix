const groups = ['concepts', 'figures', 'examples', 'counterExamples', 'codeBlocks', 'miniQuiz', 'transferTasks']

// The saved outline carries the author's teaching order. Older documents with
// incomplete outlines retain every remaining section in their original order.
export function orderedHandoutSections(content) {
  if (!content) return []
  const items = groups.flatMap(kind => (content[kind] || []).map(item => {
    const section = { ...item, sectionType: kind }
    if (kind === 'codeBlocks') {
      const fenced = String(item.code || '').trim().match(/^```[^\n]*\n([\s\S]*?)\n```$/)
      if (fenced) section.code = fenced[1]
    }
    return section
  }))
  const byId = new Map(items.map(item => [item.id, item]))
  const result = []
  for (const entry of content.outline || []) {
    if (!byId.has(entry.id)) continue
    result.push(byId.get(entry.id))
    byId.delete(entry.id)
  }
  return [...result, ...byId.values()]
}

export function handoutSectionMarkdown(item) {
  const title = `## ${item.title || '学习检查'}`
  if (item.sectionType === 'codeBlocks') return [title, `~~~${item.language || ''}\n${item.code}\n~~~`, item.explanation].join('\n\n')
  if (item.sectionType === 'miniQuiz') return [title, item.question, ...(item.options || []).map((option, index) => `${String.fromCharCode(65 + index)}. ${option}`), ...(item.hints || []).map((hint, index) => `**提示 ${index + 1}：** ${hint}`), `**答案：** ${item.options?.[item.correctIndex] || ''}`, item.explanation].join('\n\n')
  if (item.sectionType === 'figures') return [title, item.content, item.caption].join('\n\n')
  if (item.sectionType === 'transferTasks') return [title, item.prompt, item.hint && `**提示：** ${item.hint}`, item.successCheck && `**检查思路：** ${item.successCheck}`].filter(Boolean).join('\n\n')
  return [title, item.explanation || item.body].join('\n\n')
}
