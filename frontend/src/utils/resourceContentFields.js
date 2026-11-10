// Only learning content is editable here. Source identities, grading links and
// execution settings stay in the original object when a field is changed.
const textFields = {
  title: '标题', summary: '内容说明', learningGoal: '学习目标', objective: '学习目标',
  explanation: '讲解', adaptationSummary: '学习建议', difficulty: '难度说明',
  label: '名称', relation: '知识点关系', definition: '概念解释',
  instruction: '操作说明', instructions: '题目与数据', expectedResult: '预期结果', errorGuidance: '遇到困难时',
  verification: '核对方法', passCondition: '通过要求', description: '说明',
  format: '提交形式', criterion: '评价内容', evidence: '评价依据',
  prompt: '问题', question: '题目', code: '教学代码', content: '正文',
  notes: '讲解备注', speakerNotes: '讲解备注', caption: '图示说明',
  profileSummary: '学习特点', masterySummary: '当前基础', recentLearningSummary: '近期学习',
}
const sections = {
  nodes: '知识点', steps: '实践步骤', checkpoints: '检查点', deliverables: '学习成果',
  rubric: '评价标准', parameters: '实验参数', constraints: '实验提示',
  concepts: '概念', figures: '图示', examples: '示例', counterExamples: '易错示例',
  codeBlocks: '教学代码', miniQuiz: '自测题', slides: '课件页', files: '代码文件',
}
const textLists = {
  prerequisites: '准备知识', environment: '学习环境', data: '练习数据',
  bullets: '学习要点', scaffolding: '学习提示', options: '选项',
}
const objects = { adaptation: '学习建议', profileAdaptation: '学习建议', observationPrompt: '观察与思考' }
const supportedSchemas = new Set([
  'f5.handout.v1', 'f5.mindmap.v1', 'f5.training-task.v1', 'f5.deck.v1',
  'f6.quiz-resource.v1', 'f6.code-sandbox.v1', 'f6.interactive-model.v1',
])

export function resourceContentFields(content) {
  if (!content || !supportedSchemas.has(content.schemaVersion)) return []
  const fields = []
  function walk(object, path = [], heading = '') {
    const priority = ['title', 'label', 'summary', 'learningGoal', 'objective']
    const entries = Object.entries(object).sort(([a], [b]) =>
      (priority.includes(a) ? priority.indexOf(a) : 10) - (priority.includes(b) ? priority.indexOf(b) : 10))
    for (const [key, value] of entries) {
      const next = [...path, key]
      const label = heading ? `${heading} · ${textFields[key]}` : textFields[key]
      if (textFields[key] && typeof value === 'string') {
        fields.push({ path: next, label, value, type: 'text', code: key === 'code' || (path[0] === 'files' && key === 'content') })
      } else if (['estimatedMinutes', 'points'].includes(key) && typeof value === 'number') {
        fields.push({ path: next, label: `${heading ? heading + ' · ' : ''}${key === 'points' ? '分值' : '预计分钟'}`, value, type: 'number' })
      } else if (sections[key] && Array.isArray(value)) {
        value.forEach((item, index) => {
          if (item && typeof item === 'object') walk(item, [...next, index], `${sections[key]} ${index + 1}`)
        })
      } else if (textLists[key] && Array.isArray(value)) {
        value.forEach((item, index) => {
          if (typeof item === 'string') fields.push({ path: [...next, index], label: `${heading ? heading + ' · ' : ''}${textLists[key]} ${index + 1}`, value: item, type: 'text' })
        })
      } else if (objects[key] && value && typeof value === 'object' && !Array.isArray(value)) {
        walk(value, next, objects[key])
      }
    }
  }
  walk(content)
  return fields
}

export function updateResourceContent(content, path, value) {
  const field = resourceContentFields(content).find(item => JSON.stringify(item.path) === JSON.stringify(path))
  if (!field) return content
  const updated = structuredClone(content)
  let parent = updated
  for (const key of path.slice(0, -1)) parent = parent[key]
  parent[path.at(-1)] = field.type === 'number' ? Number(value) : String(value)
  return updated
}
