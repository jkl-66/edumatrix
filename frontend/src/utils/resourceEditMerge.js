const copy = value => value === undefined ? undefined : JSON.parse(JSON.stringify(value))
const equal = (left, right) => JSON.stringify(left) === JSON.stringify(right)
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const entryId = item => item?.id ?? item?.nodeId ?? item?.key ?? item?.path
const keyed = value => Array.isArray(value) && value.every(item => object(item) && typeof entryId(item) === 'string')

const labels = {
  title: '标题', summary: '内容摘要', learningGoal: '学习目标', adaptationSummary: '讲解方式',
  slides: '课件页面', layout: '版式', subtitle: '副标题', body: '正文', bullets: '要点',
  speakerNotes: '讲者备注', sourceRefIds: '来源选择', concepts: '概念', figures: '图示',
  examples: '示例', counterExamples: '易错示例', codeBlocks: '教学代码', miniQuiz: '自测题',
  explanation: '解析', content: '内容', code: '教学代码', prompt: '题目', answer: '答案',
  profileAdaptation: '学习安排', scaffolding: '学习提示', description: '说明', text: '内容',
  nodes: '知识点', label: '名称', relation: '知识点关系', steps: '实践步骤',
  instruction: '操作说明', expectedResult: '预期结果', errorGuidance: '遇到困难时',
  parameters: '实验参数', constraints: '实验提示', files: '代码文件',
}

// Keep independent edits from both pages. Overlapping edits require an explicit choice.
export function mergeResourceEdits(base, local, latest, choices = {}) {
  const conflicts = []
  function merge(before, mine, remote, path = [], label = '资源内容') {
    if (equal(mine, before)) return copy(remote)
    if (equal(remote, before) || equal(mine, remote)) return copy(mine)
    const conflict = () => {
      const key = JSON.stringify(path)
      if (choices[key] === 'latest') return copy(remote)
      if (choices[key] === 'local') return copy(mine)
      conflicts.push({ key, label, local: copy(mine), latest: copy(remote) })
      return copy(mine)
    }
    if (object(before) && object(mine) && object(remote)) {
      const result = {}
      for (const key of new Set([...Object.keys(before), ...Object.keys(mine), ...Object.keys(remote)])) {
        const value = merge(before[key], mine[key], remote[key], [...path, key], `${label} · ${labels[key] || '内容'}`)
        if (value !== undefined) result[key] = value
      }
      return result
    }
    if (keyed(before) && keyed(mine) && keyed(remote)) {
      const ids = items => items.map(entryId)
      const originalIds = ids(before)
      const mineIds = ids(mine)
      const remoteIds = ids(remote)
      // Choose the order separately so it never discards edits inside the pages.
      let order = equal(mineIds, originalIds) ? remoteIds : mineIds
      if (!equal(mineIds, originalIds) && !equal(remoteIds, originalIds) && !equal(mineIds, remoteIds)) {
        const key = JSON.stringify([...path, 'order'])
        if (choices[key] === 'latest') order = remoteIds
        else if (choices[key] !== 'local') conflicts.push({ key, label: `${label} · 顺序`,
          local: mine.map(item => item.title || item.prompt || '条目'),
          latest: remote.map(item => item.title || item.prompt || '条目'),
        })
      }
      const result = new Map()
      for (const id of new Set([...originalIds, ...mineIds, ...remoteIds])) {
        const old = before.find(item => entryId(item) === id)
        const localItem = mine.find(item => entryId(item) === id)
        const latestItem = remote.find(item => entryId(item) === id)
        const item = localItem || latestItem || old
        const value = merge(old, localItem, latestItem, [...path, id], `${label} · ${item.title || item.label || item.prompt || '条目'}`)
        if (value !== undefined) result.set(id, value)
      }
      const ordered = [...order].filter(id => result.has(id))
      for (const source of [remoteIds, originalIds, [...result.keys()]]) {
        source.forEach((id, index) => {
          if (!result.has(id) || ordered.includes(id)) return
          const next = source.slice(index + 1).find(candidate => ordered.includes(candidate))
          ordered.splice(next ? ordered.indexOf(next) : ordered.length, 0, id)
        })
      }
      return ordered.map(id => result.get(id))
    }
    return conflict()
  }
  return { content: merge(base, local, latest), conflicts }
}

export function editConflictText(value) {
  if (value === undefined) return '已移除'
  if (value === null || value === '') return '未填写'
  if (typeof value !== 'object') return String(value)
  if (Array.isArray(value)) return value.map(editConflictText).join('\n') || '未选择'
  return Object.entries(value).filter(([key]) => key !== 'id' && !key.endsWith('Id') && !key.endsWith('Ids'))
    .map(([key, item]) => `${labels[key] || '内容'}：${editConflictText(item)}`).join('\n')
}
