// Both graph entrances use the same current learning judgment. The original
// course graph remains the authority for nodes, relations and source locations.
export function projectCourseMasteryNode(node, current) {
  const hasCurrent = current != null && Object.hasOwn(current, 'mastery')
  const rawScore = hasCurrent ? current.mastery : node.masteryScore
  const score = rawScore == null || typeof rawScore === 'boolean' ? null : Number(rawScore)
  const mastery = Number.isFinite(score) && score >= 0 && score <= 1 ? score : null
  const status = hasCurrent ? current.masteryBand : node.masteryStatus
  const masteryBand = status === 'conflict' ? 'conflict'
    : mastery == null ? 'unknown' : mastery >= .75 ? 'mastered' : mastery >= .55 ? 'developing' : 'weak'
  const labels = { mastered: '稳定掌握', developing: '正在形成', weak: '当前薄弱', conflict: '证据冲突', unknown: '暂无证据' }
  const evidenceCount = Number(hasCurrent ? current.evidenceCount || 0 : node.masteryEvidenceCount || 0)
  return {
    mastery, masteryBand, evidenceCount,
    masteryScore: mastery, masteryStatus: masteryBand, masteryLabel: labels[masteryBand], masteryEvidenceCount: evidenceCount,
    confidence: hasCurrent ? current.confidence || 0 : 0,
    judgement: hasCurrent ? current.judgement || '尚无可用于判断掌握度的学习记录。'
      : mastery == null ? '尚无可用于判断掌握度的学习记录。' : '根据已完成的课程诊断判断。',
    evidence: hasCurrent ? current.evidence || [] : [],
    behaviors: hasCurrent ? current.behaviors || [] : [],
    behaviorCount: hasCurrent ? current.behaviorCount || 0 : 0,
    sourceRefIds: hasCurrent ? current.sourceRefIds || node.masterySourceRefIds || [] : node.masterySourceRefIds || [],
  }
}
