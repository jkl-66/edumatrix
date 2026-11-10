export function projectedTaskStatus(node, scheduled) {
  if (node.status === 'completed' || node.status === '已完成') return 'completed'
  if (scheduled?.status === 'skipped') return 'skipped'
  if (scheduled?.scheduled_day === 1) return 'in_progress'
  return node.status || scheduled?.status || 'pending'
}

export function pathProgress(nodes = []) {
  const completed = nodes.filter(node => ['completed', '已完成'].includes(node.status)).length
  const skipped = nodes.filter(node => node.status === 'skipped').length
  return { total: nodes.length, completed, skipped, percentage: nodes.length ? Math.round((completed + skipped) / nodes.length * 100) : 0 }
}

export function progressLabel(progress) {
  return `${progress.completed}/${progress.total} 项完成${progress.skipped ? ` · ${progress.skipped} 项测评已通过` : ''}`
}

export function estimatedPathMinutes(tasks = []) {
  return tasks.reduce((total, task) => {
    const estimate = task.estimate_minutes ?? [task.estimate_min_minutes, task.estimate_max_minutes]
    const values = (Array.isArray(estimate) ? estimate : [estimate]).map(Number).filter(Number.isFinite)
    return total + Math.max(0, ...values)
  }, 0)
}
