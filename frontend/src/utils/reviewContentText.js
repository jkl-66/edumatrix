// Read the submitted teaching content without exposing its storage format.
const labels = {
  title: '标题', summary: '内容简介', learningGoal: '学习目标', learning_objective: '学习目标',
  concepts: '核心概念', figures: '图示与公式', examples: '示例', counterExamples: '边界与反例',
  codeBlocks: '代码示例', miniQuiz: '学习检查', question: '题目', stem: '题目',
  options: '选项', prompt: '题目或学习要求', explanation: '讲解', body: '正文', content: '内容',
  answer: '参考答案', answer_key: '参考答案', correct_answer: '参考答案', rubric: '评价要求',
  steps: '步骤', checkpoints: '检查点', deliverables: '提交内容', prerequisites: '学习准备',
  slides: '课件页面', bullets: '要点', speakerNotes: '讲解提示',
  nodes: '学习安排', taskPrompt: '练习要求', observations: '观察',
  description: '说明', instructions: '操作说明', reflectionQuestions: '思考问题',
  estimatedMinutes: '预计分钟', estimate_min_minutes: '最少分钟', estimate_max_minutes: '最多分钟',
  code: '教学代码', starterCode: '起始代码', initialCode: '起始代码',
}
const hidden = /^(?:id|.*[Ii]ds?|.*_ids?|.*[Hh]ash|.*_hash|schema.*|metadata|sourceRefs|source_refs|profile.*|agent.*|completionRule|completion_rule|created.*|updated.*|lock_version|version|status|node_key|node_type|resource_status|target_object_id|system_prompt|developer_prompt|private_reasoning|chain_of_thought|api_key|secret|raw_log|agent_log|trace)$/
const codeKeys = new Set(['code', 'starterCode', 'initialCode'])

export function reviewContentText(content) {
  let value = content
  if (typeof value === 'string') {
    try { value = JSON.parse(value) } catch { return value }
  }
  function render(item) {
    if (item == null || typeof item === 'boolean') return ''
    if (typeof item !== 'object') return String(item)
    if (Array.isArray(item)) return item.map((child, index) => {
      const text = render(child)
      return text ? `${index + 1}. ${text}` : ''
    }).filter(Boolean).join('\n\n')
    const parts = []
    for (const [name, child] of Object.entries(item)) {
      if (hidden.test(name) || name === 'language' || name === 'correctIndex') continue
      const text = render(child)
      if (!text) continue
      if (codeKeys.has(name)) parts.push(`${labels[name]}\n${text}`)
      else if (labels[name]) parts.push(`${labels[name]}：\n${text}`)
      else if (typeof child === 'object' || /[\u4e00-\u9fff]/.test(text)) parts.push(text)
    }
    if (Number.isInteger(item.correctIndex) && Array.isArray(item.options) && item.options[item.correctIndex] != null) {
      parts.push(`参考答案：${render(item.options[item.correctIndex])}`)
    }
    return parts.join('\n\n')
  }
  return render(value) || '本项暂无文字内容。'
}
