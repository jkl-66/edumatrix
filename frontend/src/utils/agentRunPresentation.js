import { learningText } from './learningCopy.js'
import { claimSupportLabels } from './claimEvidencePresentation.js'

const publicRoleTerms = [
  ['Evidence Verifier', '内容核对'],
  ['Pedagogical Agent', '表达整理'],
  ['Resource Reviewer', '质量检查'],
  ['Resource Planner', '资源安排'],
  ['Resource Generator', '内容生成'],
  ['Chat Orchestrator', '问题梳理'],
  ['Context Builder', '相关知识整理'],
  ['Subject Expert', '学科讲解'],
  ['Answer Agent', '内容讲解'],
  ['Synthesizer', '回答整理'],
  ['Challenger', '边界检查'],
  ['Publisher', '保存资源'],
  ['Retrieval', '内容查找'],
  ['Router', '问题理解'],
  ['Verifier', '内容核对'],
  ['Supervisor', '进度协调'],
  [' Agent', ''],
]

export function translatePublicText(value) {
  const legacy = String(value || '')
    .replace(/正在根据已冻结的上下文生成回答。/g, '正在结合本次问题和学习资料准备讲解。')
    .replace(/(?:课程综合回答模型|真实模型回答)失败，已保留当前内容。/g, '这次讲解暂未完成，已保留当前内容，可以重试。')
    .replace(/本次运行失败，可从保留的内容继续或重试。/g, '这次回答已中断，可以继续回答。')
  let text = learningText(legacy)
  if (/已核验.*支持状态\s+(supported|partially_supported|contradicted|unsupported)/.test(text)) {
    const state = text.match(/支持状态\s+(supported|partially_supported|contradicted|unsupported)/)[1]
    return `结论核对：${claimSupportLabels[state]}。`
  }
  for (const [from, to] of publicRoleTerms) text = text.split(from).join(to)
  return text
    .replace(/已冻结课程、来源和\s*\d+\s*个附件的本次上下文/g, '已整理课程内容和附件')
    .replace(/已冻结课程、来源/g, '已整理课程内容')
    .replace(/本次回答运行完成，公开轨迹已保存/g, '回答已完成，可以回看本次讲解和参考材料')
    .replace(/等待真实回答运行开始/g, '正在准备回答')
    .replace(/\b(?:f\d+-)?(?:kp|event|trace|run|claim|source|task|chat)-[a-z0-9-]{4,}\b/gi, '')
    .replace(/\b[a-f0-9]{24,}\b/gi, '')
    .replace(/source_ref(?:_id)?/gi, '')
    .replace(/课程来源/g, '相关内容')
    .replace(/上下文/g, '相关内容')
    .replace(/来源/g, '参考材料')
    .replace(/证据核验/g, '内容核对')
    .replace(/资源 Supervisor/g, '资源准备过程')
    .replace(/Resource Supervisor/g, '资源准备过程')
    .replace(/Resource Reviewer/g, '质量检查')
    .replace(/Resource Planner/g, '资源安排')
    .replace(/Resource Generator/g, '内容生成')
    .replace(/Supervisor/g, '进度协调')
    .replace(/确定性/g, '稳定')
    .replace(/冻结/g, '')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

// Project historical start events without rewriting saved events or inventing completion.
const activeStatuses = new Set(['pending', 'queued', 'running'])
const terminalStatuses = new Set(['completed', 'failed', 'stopped'])

export function eventStepKey(item) {
  if (item.eventType.startsWith('run.')) return 'run'
  if (item.resourceType) return `resource:${item.resourceType}`
  if (item.resourceItemId) return `resource-item:${item.resourceItemId}`
  if (item.stageId) return `stage:${item.stageId}`
  return `event:${item.eventType}:${item.id}`
}

export function presentRunEvents(items, overallStatus) {
  return items.map((item, index) => {
    const later = items.slice(index + 1)
    if (item.status === 'failed' && later.some(next => next.eventType === 'run.retry')) {
      return { ...item, status: 'previous_failed', candidateSummary: `前次记录：${item.candidateSummary}` }
    }
    if (!activeStatuses.has(item.status)) return item
    if (later.some(next => eventStepKey(next) === eventStepKey(item))) {
      return { ...item, status: 'recorded', candidateSummary: `当时进展：${item.candidateSummary}` }
    }
    const terminal = later.find(next => ['run.failed', 'run.stopped', 'run.completed', 'run.retry'].includes(next.eventType))
    if (!terminal && !terminalStatuses.has(overallStatus)) return item
    const endedStatus = terminal?.eventType === 'run.completed' ? 'completed'
      : terminal?.eventType === 'run.failed' ? 'failed' : terminal ? 'stopped' : overallStatus
    const reason = endedStatus === 'failed' ? '本次回答已中断，这一步尚未完成。'
      : endedStatus === 'completed' ? '回答已完成，这一步的历史记录不完整。'
        : '本次回答已停止，这一步尚未完成。'
    return { ...item, status: endedStatus === 'completed' ? 'unknown' : 'stopped', candidateSummary: reason }
  })
}

export function runRoleLabel(ownerLabel, stageLabel) {
  return stageLabel && stageLabel !== ownerLabel ? `${ownerLabel} · ${stageLabel}` : ownerLabel
}
