const BUSINESS_MESSAGES = {
  replan_pending: '学习计划正在更新，请等待当前步骤完成后继续。',
  unauthorized: '登录状态已失效，请重新登录。',
  forbidden: '当前账号没有访问该页面的权限。',
  timeout: '处理时间较长，已保留当前输入，你可以稍后重试。',
  network: '网络连接暂时不可用，已保留当前输入。',
  capacity: '当前模型服务繁忙，已有内容仍可继续使用。',
}

export function translateError(error, fallback = '操作暂未完成，已保留当前内容。') {
  const detail = error?.response?.data?.detail ?? error?.detail ?? error?.message
  const code = typeof detail === 'object' ? detail.code : error?.code
  const raw = typeof detail === 'string' ? detail : detail?.message
  const normalized = String(code || raw || '').toLowerCase()

  for (const [token, message] of Object.entries(BUSINESS_MESSAGES)) {
    if (normalized.includes(token)) return { message, technicalCode: code || token }
  }

  return {
    message: raw && !/trace|worker|lease|schema/i.test(raw) ? raw : fallback,
    technicalCode: code || 'unclassified_error',
  }
}
