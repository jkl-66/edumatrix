// Presentation only: keep protocol values, saved answers and course code intact.
const LABELS = {
  warning: '需要留意', reviewing: '正在审核', json: '学习内容', python: '编程练习',
  level1_pending: '等待初审', level2_pending: '等待复核', level3_pending: '等待最终确认', signed: '已确认通过', returned: '已退回', mentor: '指导教师', manager: '教学负责人',
  reuse_existing: '沿用已有记录', reject_old_sequence: '保留较新的记录', keep_revoked: '保持停止授权', preserve_original: '保留原有内容', reconnect: '重新连接', retry_after_backoff: '稍后重新尝试', explicit_requeue: '重新安排处理',
  dead_letter: '多次尝试未完成，需要重新安排', retrying: '正在重新尝试', valid: '安排合理', invalid: '需要调整', baseline: '按课程基础安排', frozen_profile_snapshot: '结合已确认的学习情况',
  concept_then_evidence_then_practice: '先讲概念，再看示例，最后练习', evidence_then_example_then_concept: '先观察材料和示例，再理解概念',
  standard: '常规节奏', measured: '放慢节奏，逐步理解', artifact: '学习资源', generation_task: '内容准备', source_document: '课程资料',
  pending: '等待处理', queued: '等待处理', running: '正在处理', processing: '正在处理',
  loading: '正在读取', generating: '正在准备', streaming: '正在回答',
  completed: '已完成', complete: '已完成', succeeded: '已完成', success: '已完成',
  ready: '已准备好', available: '可以使用', passed: '已通过', failed: '未完成，请重试', processed: '已更新',
  partial: '部分完成', partial_success: '部分完成', stopped: '已停止', cancelled: '已取消',
  canceled: '已取消', paused: '已暂停', blocked: '需要先完成前面的步骤',
  draft: '草稿', assigned: '待作答', published: '已发布', archived: '已归档', withdrawn: '已撤回',
  active: '使用中', inactive: '未启用', disabled: '未启用', enabled: '已启用',
  expired: '已到期', revoked: '已撤销', deleted: '已删除', not_started: '尚未开始',
  in_progress: '进行中', not_generated: '尚未准备', saved: '已保存', applied: '已应用',
  confirmed: '已确认', pending_confirmation: '等待确认', needs_review: '需要进一步确认',
  approved: '审核通过', rejected: '审核未通过', pending_review: '等待审核',
  graded: '已完成评分', ungraded: '等待评分', pending_grading: '等待评分',
  correct: '回答正确', incorrect: '还需要巩固', unknown: '暂时无法判断',
  supported: '有资料支持', partially_supported: '部分内容仍需确认',
  unsupported: '还缺少相关资料', insufficient_evidence: '还需要更多学习记录',
  contradicted: '与参考资料不一致', accepted: '已确认', processed: '已更新',
  missing: '暂未提供', unavailable: '暂时不可用', empty: '暂无内容',
  student: '学生', learner: '学习者', teacher: '教师', admin: '管理员', assistant: '助教',
  owner: '创建者', member: '成员', reviewer: '审核教师', system: '学习助手',
  handout: '讲义', mind_map: '思维导图', quiz: '测验', training_task: '实训任务',
  code_sandbox: '编程练习', interactive_model: '交互实验', interactive_lab: '交互实验',
  video: '学习视频', deck: '课件', feynman: '费曼练习', chapter: '章节',
  single_choice: '单选题', multiple_choice: '多选题', true_false: '判断题',
  fill_blank: '填空题', short_answer: '简答题', open_task: '综合练习', code: '编程题',
  public: '公开', private: '仅自己可见', organization: '组织内可见', course: '课程',
  high: '较高', medium: '中等', low: '较低', strong: '较充分', weak: '仍需积累',
  sufficient: '较充分', limited: '仍需积累', proceed: '继续学习', retry: '重新尝试',
  review: '复习巩固', learn: '开始学习', practice: '练习', assessment: '测评',
  planner: '学习规划', generator: '内容准备', judge: '内容审核', challenger: '问题检查',
  prover: '讲解核对', executor: '学习安排', analyst: '学情分析',
  objective: '客观题评分', ai: '学习点评', manual: '教师点评', hidden: '综合检查',
  not_saved: '尚未保存', imported: '已加入课程', not_imported: '尚未加入课程',
  source_declared: '原站说明', verified: '已核对', unverified: '尚未核对',
  personal_use_allowed: '可用于个人学习', reuse_allowed: '允许再利用',
  no_results: '暂无结果', provider_failed: '暂时无法搜索',
  round1_submitted: '首次复述已提交', round2_submitted: '再次复述已提交',
  open: '待处理', resolved: '已处理', delivered: '已送达', received: '已收到',
  satisfied: '已达到要求', unsatisfied: '还需继续学习', skipped: '本次跳过',
  not_applicable: '本次不适用', read_only: '仅供查看', legacy_compatibility: '历史学习记录',
  pdf: 'PDF 文档', docx: 'Word 文档', pptx: '演示文稿', markdown: '学习文稿', html: '网页',
  txt: '文本', text: '文字', image: '图片', audio: '音频', notebook: '编程笔记',
  create: '创建', created: '已创建', update: '更新', updated: '已更新', delete: '删除',
  submit: '提交', submitted: '已提交', approve: '审核通过', reject: '退回修改',
  revoke: '撤销', withdraw: '撤回', restore: '恢复', publish: '发布', import: '导入', export: '导出',
  login: '登录', logout: '退出登录', completed_with_warnings: '已完成，部分内容需要留意',
  healthy: '可以正常使用', degraded: '部分功能暂时不可用', error: '暂时遇到问题',
  correctness: '理解准确性', accuracy: '回答准确性', reasoning: '推理过程',
  logic: '推理过程', clarity: '表达清晰度', completeness: '回答完整性',
  application: '应用能力', evidence: '解释与举例', explanation: '讲解能力',
}

const INTERNAL_ID = /\b(?:(?:kp|ch|ref|src|qv|art|evt|diag|snapshot)-[a-z0-9][a-z0-9_-]*|(?:task|run|trace|event|course|user|usr|session|claim|plan)-[a-f0-9-]{8,}|[a-f0-9]{24,})\b/gi
const INTERNAL_FIELD = /\b(?:source_?ref_?id|knowledge_?point_?id|chapter_?id|trace_?id|content_?hash|profile_?snapshot_?id|schema_?version|rubric_?version|lock_?version)\b\s*[:=：]\s*[\w.:-]+/gi
const PROSE_REPLACEMENTS = [
  ['模型未返回可逐条核验的结构化结论', '这次回答的依据尚未核对完成，请重新提问'],
  ['未获得结构化结论', '本次内容检查尚未完成'],
  ['无法绑定课程来源', '暂时无法提供可核对的参考材料'],
  ['发布时必须明确当前课程资料无法确认', '当前回答仍需结合课程材料确认'],
  ['缺少完整 source_ref、原文引文或位置，不能按课程证据发布。', '这条解释缺少可核对的原文和位置，请先查阅资料确认。'],
  ['支架等级：high', '会提供较详细的分步提示'], ['支架等级：medium', '会在关键步骤提供提示'], ['支架等级：light', '以独立思考为主，提供少量提示'],
  ['只有已提交且完成判分的答案才会进入诊断证据', '提交作答并获得评分后，会更新你的学习情况'],
  ['按当前画像快照校准', '根据本次学习情况安排'], ['当前画像快照', '本次学习情况'], ['当前当时的学习情况', '本次学习情况'],
  ['由诊断证据触发', '根据本次诊断建议学习'],
  ['concept_then_evidence_then_practice', '先讲概念，再看示例，最后练习'], ['evidence_then_example_then_concept', '先看材料和示例，再理解概念'],
  ['节奏：standard', '节奏：常规'], ['节奏：measured', '节奏：放慢节奏，逐步理解'],
  ['画像快照', '当时的学习情况'], ['当前快照', '本次记录'], ['冻结快照', '已保存的记录'],
  ['幂等重放', '恢复记录'], ['幂等', '避免重复记录'], ['不可变证据', '已保存的学习记录'],
  ['强证据', '有效学习记录'], ['证据不足', '现有学习记录还不够'],
  ['服务端已完成客观判分', '本题已完成评分'], ['乐观锁版本', '当前版本'],
]

export function learningText(value, fallback = '', names = {}) {
  if (value === null || value === undefined) return fallback
  if (Array.isArray(value)) return value.map(item => learningText(item, '', names)).filter(Boolean).join('、') || fallback
  if (typeof value === 'object') {
    for (const key of ['message', 'feedback', 'summary', 'reason', 'title', 'text', 'detail']) {
      if (typeof value[key] === 'string') return learningText(value[key], fallback, names)
    }
    return fallback
  }
  if (typeof value === 'boolean') return fallback
  // Code examples are teaching content, including literal status names and IDs.
  // Apply wording changes only to the prose around Markdown code spans/blocks.
  const parts = String(value).split(/(^```[^\n]*\n.*?(?:^```[ \t]*(?=\n|$)|(?![\s\S]))|^~~~[^\n]*\n.*?(?:^~~~[ \t]*(?=\n|$)|(?![\s\S]))|`[^`\n]+`)/gms)
  return parts.map((part, index) => index % 2 ? part : learningProse(part, fallback, names)).join('').trim() || fallback
}

// Explanations are teaching content: no terminology, bare-ID or number cleanup.
export function teachingText(value, fallback = '') {
  const parts = String(value ?? '').split(/(^```[^\n]*\n.*?(?:^```[ \t]*(?=\n|$)|(?![\s\S]))|^~~~[^\n]*\n.*?(?:^~~~[ \t]*(?=\n|$)|(?![\s\S]))|`[^`\n]+`|\$\$[\s\S]*?\$\$|\$[^\n$]+\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|^(?: {4}|\t)[^\n]*(?:\n(?: {4}|\t)[^\n]*)*)/gms)
  const text = parts.map((part, index) => index % 2 ? part : part
    .replace(/["']?\bcorrect["']?\s*[:=]\s*["']?(true|false|null)\b["']?/gi, (_, state) => ({ true: '本题回答正确', false: '本题尚未答对', null: '本题尚未完成评分' })[state.toLowerCase()])
    .replace(/["']?\bgrading_?status["']?\s*[:=]\s*["']?(graded|pending_grading|ungraded)\b["']?/gi, (_, state) => state.toLowerCase() === 'graded' ? '已完成评分' : '等待评分')
    .replace(/["']?\b(?:source_?ref_?id|knowledge_?point_?id|chapter_?id|trace_?id|content_?hash|profile_?snapshot_?id|schema_?version|rubric_?version|lock_?version)\b["']?\s*[:=：]\s*["']?[\w.:-]+["']?/gi, '')).join('')
  return text.trim() ? text : fallback
}

function learningProse(value, fallback, names) {
  let text = value
  text = text.replace(/已由可信学习事件确认/g, '已根据本次学习结果记录')
    .replace(/可信学习任务|可信任务/g, '有效学习任务')
    .replace(/负荷处于可教学区间/g, '当前学习负担较适中')
    .replace(/多表征学习策略/g, '多种方式互相印证的学习方法')
  text = text.replace(/费曼两轮复述最高提升\s*-(\d+(?:\.\d+)?)\s*分/g, '费曼两轮复述仍下降 $1 分')
  if (/^\s*\{/.test(text)) {
    try { return learningText(JSON.parse(text), fallback, names) } catch { return fallback }
  }
  // Names are supplied by the same report/course; never infer a title from an ID.
  for (const [id, title] of Object.entries(names).sort((a, b) => b[0].length - a[0].length)) {
    if (id && title) text = text.split(id).join(String(title))
  }
  text = text.replace(/["']?\bcorrect["']?\s*[:=]\s*["']?(true|false|null)\b["']?/gi, (_, result) => ({ true: '本题回答正确', false: '本题尚未答对', null: '本题尚未完成评分' })[result.toLowerCase()])
  text = text.replace(/["']?\b(?:grading_status|gradingStatus|status)["']?\s*[:=]\s*["']?([a-z_]+)\b["']?/gi, (_, state) => LABELS[state.toLowerCase()] || '')
  text = text.replace(/\bscore\s*[:=]\s*(\d+(?:\.\d+)?)/gi, '得分：$1')
  text = text.replace(INTERNAL_FIELD, '').replace(INTERNAL_ID, '')
  text = text.replace(/来源支持(?:关系)?(?:为|是)\s*unsupported\b/g, '课程材料未直接说明这一点')
  text = text.replace(/\b(?:graded|insufficient_evidence|needs_review|partially_supported|supported|unsupported|contradicted|pending_grading)\b/g, word => LABELS[word])
  for (const [before, after] of PROSE_REPLACEMENTS) text = text.split(before).join(after)
  text = text.replace(/(^|[·•]\s*)(handout|mind_map|training_task|code_sandbox|interactive_model|feynman|quiz|deck|video)(?=\s*(?:[·•（(”」）》"']|$))/g,
    (_, prefix, type) => prefix + (LABELS[type] || type))
  // Empty parentheses and brackets can be function calls or empty containers.
  text = text.replace(/[ \t]{2,}/g, ' ').replace(/\s+([，。；：！？])/g, '$1')
  if (/^[a-z][\w]*(?:[._][\w]+)+$/i.test(text)) return LABELS[text.toLowerCase()] || fallback
  return text || fallback
}

export function displayLabel(value, fallback = '暂未说明') {
  const text = String(value ?? '').trim()
  return LABELS[text.toLowerCase()] || (/[\u3400-\u9fff]/u.test(text) ? learningText(text, fallback) : fallback)
}

export function referenceTitle(value, fallback = '学习记录') {
  return learningText(value?.title || value?.name || value?.label || value?.display_name
    || value?.course_title || value?.chapter_title || value?.knowledge_point_title || value?.filename, fallback)
}

export function hasTechnicalDetails(value) {
  return /(?:traceback|exception|stack trace|SQLAlchemy|sqlite|HTTP\s*\d{3}|status code\s*\d{3}|\b(?:worker|lease|schema|api_key|reasoning_content)\b|\b\w+(?:_\w+){2,}\b|[A-Za-z]:\\|\/api\/|\b\d{3}\s+(?:Bad Request|Not Found|Internal Server Error)|\[object Object\]|^\s*\{)/i.test(String(value || ''))
}

// Only labelled, useful facts are projected; raw diagnostic objects stay in the API.
export function recordFacts(record) {
  if (!record || typeof record !== 'object') return []
  const labels = {title: '名称', name: '名称', summary: '说明', message: '说明', description: '说明',
    requirement_level: '要求程度', risk_level: '风险程度', exemption_policy: '免修条件', evidence_requirements: '学习记录要求', acceptance_rules: '完成要求',
    score: '得分', count: '数量', question_count: '题目数量', attempt_count: '尝试次数',
    active_members: '当前成员', active_identity_mappings: '已关联账号', employee_projections: '员工记录',
    catalog_exports: '已分享课程', candidate_grades: '待确认成绩', delivered_xapi: '已发送学习记录',
    received_statements: '已收到学习记录', events: '活动记录', delivered: '已送达', accepted_receipts: '已确认收到'}
  const result = []
  for (const [key, label] of Object.entries(labels)) {
    if (record[key] == null) continue
    const value = learningText(record[key])
    if (value) result.push(`${label}：${value}`)
  }
  for (const key of ['status', 'action', 'outcome']) {
    if (record[key]) result.push(displayLabel(record[key], '状态暂未说明'))
  }
  if (typeof record.accepted === 'boolean') result.push(record.accepted ? '已接收本次记录' : '未接收本次记录')
  if (typeof record.suppressed === 'boolean') result.push(record.suppressed ? '已避免重复记录' : '本次未拦截重复记录')
  if (typeof record.replayed_access_allowed === 'boolean') result.push(record.replayed_access_allowed ? '允许访问' : '已停止访问')
  if (typeof record.mandatory === 'boolean') result.push(record.mandatory ? '需要完成' : '可以选学')
  for (const [key, change] of Object.entries(record.changes || {})) {
    if (!labels[key] && key !== 'mandatory') continue
    const text = value => typeof value === 'boolean' ? (value ? '需要完成' : '可以选学') : learningText(value, '未说明')
    result.push(`${labels[key] || '完成要求'}：${text(change.before)} → ${text(change.after)}`)
  }
  return [...new Set(result)]
}
