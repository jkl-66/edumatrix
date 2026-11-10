// Older generated tasks copied the answer into all four reporting sections.
// Read those versions faithfully, but use their task instructions as prompts.
export function trainingTaskPresentation(task) {
  if (!task) return null
  const steps = task.steps || []
  const requirement = (text, stepId, title) => {
    const matches = steps.filter(step => step.expectedResult && step.expectedResult.trim() === String(text || '').trim())
    const step = matches.find(item => stepId && item.id === stepId)
      || matches.find(item => title && item.title === title)
      || (matches.length === 1 ? matches[0] : null)
    return step?.instruction || text
  }
  return {
    ...task,
    checkpoints: (task.checkpoints || []).map(item => ({ ...item, verification: requirement(item.verification, item.afterStepId, item.title) })),
    deliverables: (task.deliverables || []).map(item => ({ ...item, description: requirement(item.description, null, item.title) })),
    rubric: (task.rubric || []).map(item => ({ ...item, evidence: requirement(item.evidence, null, item.criterion) })),
  }
}

export function trainingReportTemplate(title, task, linkedResources = []) {
  const presented = trainingTaskPresentation(task)
  return [`# ${title} · 实训报告`, '', '## 实践记录',
    ...linkedResources.map(item => `- ${item.title}：${item.completed ? '已完成' : '待完成'}`),
    '', '## 我的结果与解释',
    ...(presented?.deliverables || []).flatMap(item => [
      `### ${item.title}`, '', `任务：${item.description}`, '', '我的记录：', '',
    ]),
    '## 检查与改进', '', '哪些判断还需核对？下一次准备怎样验证？', ''].join('\n')
}
