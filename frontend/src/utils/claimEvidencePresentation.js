export const claimSupportLabels = {
  supported: '有资料支持',
  partially_supported: '部分得到支持',
  contradicted: '与资料冲突',
  unsupported: '资料不足',
}

export function claimEvidenceStatus(claim) {
  const support = Object.hasOwn(claimSupportLabels, claim?.support) ? claim.support : 'unsupported'
  const calculations = Array.isArray(claim?.calculations) ? claim.calculations : []
  if (calculations.some(item => item?.checked === true && (item.claimConsistent ?? item.agrees) === false)) {
    return { support: 'contradicted', label: '计算需修正' }
  }
  if (claim?.basis === 'worked_example' && claim.revisionNeeded === false && support !== 'contradicted') {
    const checked = calculations.length > 0 && calculations.every(item => item?.checked === true && (item.claimConsistent ?? item.agrees) === true)
    return { support: 'worked_example', label: checked ? '按题设验算' : '题设推导' }
  }
  if (claim?.basis === 'source_scope' && claim.revisionNeeded === false && support !== 'contradicted') {
    return { support: 'source_scope', label: '本次资料范围' }
  }
  return { support, label: claimSupportLabels[support] }
}

export function hasAnswerRevision(revision) {
  return typeof revision?.before === 'string' && revision.before.trim().length > 0
    && typeof revision?.after === 'string' && revision.after.trim().length > 0
}

export function answerRevisionPresentation(revision, historical = false) {
  if (historical) {
    const state = revision?.decision === 'verified' ? '当时已完成核对。'
      : revision?.decision === 'qualified' ? '当时已调整讲解，部分内容仍缺少依据。'
        : revision?.decision === 'rejected' ? '当时仍有矛盾，未作为答案。'
          : '当时尚未完成核对，未作为答案。'
    return { message: `这是之前保留的讲解。${state}`, afterLabel: '查看当时的修订稿' }
  }
  if (revision?.decision === 'verified') {
    return { message: '相关讲解已经修正，并重新核对了资料与计算。', afterLabel: '查看修订后的讲解' }
  }
  if (revision?.decision === 'qualified') {
    return { message: '已调整相关讲解；仍缺少依据的内容会保留说明。', afterLabel: '查看修订后的讲解' }
  }
  if (revision?.decision === 'rejected') {
    return { message: '这次讲解还有矛盾，暂未作为答案。可以继续回答，重新整理。', afterLabel: '查看尚未完成的讲解' }
  }
  return { message: '这次讲解尚未核对完成，暂未作为答案。已保留本次内容，可以重试。', afterLabel: '查看尚未核对完成的讲解' }
}

export function answerRevisionEntries(current, history = []) {
  const previous = (Array.isArray(history) ? history : []).filter(item => hasAnswerRevision(item?.revision))
    .map((item, index) => ({
      key: `previous-${index}`,
      title: `第 ${Number.isInteger(item.attempt) && item.attempt > 0 ? item.attempt : index + 1} 次保留的讲解`,
      revision: item.revision,
      historical: true,
    })).reverse()
  const entries = hasAnswerRevision(current)
    ? [{ key: 'current', title: '本次核对与修正', revision: current, historical: false }, ...previous] : previous
  return entries.map(entry => ({
    ...entry,
    presentation: answerRevisionPresentation(entry.revision, entry.historical),
    issues: (entry.revision.claimsBefore || [])
      .filter(claim => claim.revisionNeeded === true || claim.support === 'contradicted'
        || (claim.support !== 'supported' && claim.revisionNeeded !== false))
      .map(claim => ({ claim: claim.claim, reason: claim.review?.revision || claim.supportReason || claim.review?.verifier })),
  }))
}
