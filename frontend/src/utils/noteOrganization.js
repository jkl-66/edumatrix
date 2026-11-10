export const NOTE_TEMPLATES = [
  { id: 'knowledge', label: '知识点', sections: ['核心概念', '适用条件', '例子与反例', '我的理解与疑问'] },
  { id: 'method', label: '方法', sections: ['解决什么问题', '使用前提', '操作步骤', '检查结果', '常见失误'] },
  { id: 'reflection', label: '错题复盘', sections: ['题目与条件', '我原来的思路', '错在什么地方', '修正后的方法', '下次如何检查'] },
  { id: 'comparison', label: '同类题', sections: ['共同知识与方法', '条件有什么不同', '分别如何处理', '可以推广到哪里', '不能推广的情况'] },
]

export function noteDisplayTitle(note) {
  const heading = String(note?.content || '').match(/^#\s+(.+)$/m)
  return heading?.[1] || note?.concepts?.[0] || note?.source_context?.title || '学习笔记'
}

export function noteTemplateContent(id, { concept = '', course = '', quote = '' } = {}) {
  const template = NOTE_TEMPLATES.find(item => item.id === id)
  if (!template) return ''
  const context = [course && `课程：${course}`, concept && `知识点：${concept}`].filter(Boolean).join(' · ')
  return [`# ${concept || template.label}`, context, quote && `## 原文摘录\n\n${quote.split('\n').map(line => `> ${line}`).join('\n')}`,
    ...template.sections.map(title => `## ${title}\n\n`)].filter(Boolean).join('\n\n')
}

export function noteCourseId(note) {
  return note?.source_metadata?.course_id || note?.source_context?.course_id || ''
}

export function arrangeNotes(notes, { sort = 'updated', pinned = [], recent = [] } = {}) {
  return [...notes].sort((a, b) => {
    const pin = Number(pinned.includes(b.id)) - Number(pinned.includes(a.id))
    if (pin) return pin
    if (sort === 'title') return noteDisplayTitle(a).localeCompare(noteDisplayTitle(b), 'zh-CN', { numeric: true })
    if (sort === 'recent') {
      const position = note => recent.includes(note.id) ? recent.indexOf(note.id) : Infinity
      const difference = position(a) - position(b)
      if (difference) return difference
    }
    return Date.parse(b.updated_at || b.created_at) - Date.parse(a.updated_at || a.created_at)
  })
}
