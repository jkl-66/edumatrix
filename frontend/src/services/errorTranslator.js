import { hasTechnicalDetails, learningText } from '../utils/learningCopy.js'

const BUSINESS_MESSAGES = {
  handout_content_incomplete: '请补全讲义标题、章节和小测内容后再保存，当前草稿仍保留。',
  handout_content_invalid: '讲义内容暂时无法读取，请检查编辑内容后再保存，当前草稿仍保留。',
  deck_content_incomplete: '请补全课件标题和各页内容后再保存，当前草稿仍保留。',
  mindmap_content_incomplete: '请补全导图标题、知识点名称和说明后再保存，当前草稿仍保留。',
  training_task_content_incomplete: '请检查任务标题、实践步骤和评价要求；各项分值合计应为100，当前草稿仍保留。',
  interactive_model_content_incomplete: '请补全实验标题、说明和观察问题后再保存，当前草稿仍保留。',
  quiz_content_incomplete: '请补全练习标题和学习说明后再保存，原题目和作答仍保留。',
  resource_version_conflict: '内容已在别处更新，请先刷新版本状态，再保存保留的草稿。',
  replan_pending: '学习计划正在更新，请等待当前步骤完成后继续。',
  unauthorized: '登录状态已失效，请重新登录。',
  forbidden: '当前账号没有访问该页面的权限。',
  timeout: '等待时间较长，请稍后重试。',
  network: '暂时连接不上，请检查网络后重试。',
  capacity: '学习助手正在忙，请稍后重试。',
  model_policy: '学习助手暂时无法完成这一步，请联系管理员检查服务设置。',
  model_unavailable: '学习助手暂时无法使用，请稍后重试。',
  source_missing: '暂时找不到相关课程资料，请重新选择学习内容。',
  source_unavailable: '相关课程资料暂时不可用，请重新选择学习内容。',
  '来源解析版本已变化': '这份资料已有更新，本次回答保留的是更新前的内容。',
}

export function translateError(error, fallback = '这一步暂时没有完成，请稍后重试。') {
  const detail = error?.response?.data?.detail ?? error?.detail ?? error?.message ?? error
  const code = typeof detail === 'object' ? detail?.code : error?.code
  const raw = typeof detail === 'string' ? detail : detail?.message
  const normalized = `${code || ''} ${raw || ''}`.toLowerCase()

  for (const [token, message] of Object.entries(BUSINESS_MESSAGES)) {
    if (normalized.includes(token)) return { message, technicalCode: code || token }
  }

  if (raw && /[\u3400-\u9fff]/u.test(raw) && !hasTechnicalDetails(raw)) {
    return { message: learningText(raw, fallback), technicalCode: code || '' }
  }
  const status = error?.response?.status || error?.status
  const statusMessages = {
    401: BUSINESS_MESSAGES.unauthorized, 403: BUSINESS_MESSAGES.forbidden,
    404: '暂时找不到这项内容，请返回列表重新选择。',
    409: '内容已有更新，请刷新后再试。', 410: '这项内容已归档，请选择其他学习内容。',
    422: '请检查填写内容后再试。', 429: BUSINESS_MESSAGES.capacity,
  }
  const safeFallback = hasTechnicalDetails(fallback) ? '这一步暂时没有完成，请稍后重试。' : fallback
  return { message: statusMessages[status] || safeFallback, technicalCode: code || 'unclassified_error' }
}

export function userMessage(value, fallback) {
  return translateError(value, fallback).message
}
