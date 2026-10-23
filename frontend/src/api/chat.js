import { api, buildHeaders } from './common'

export async function listChatConversations() {
  const response = await api.get('/v1/chat/conversations', { headers: buildHeaders() })
  return response.data.items || []
}

export async function listChatCourses() {
  const response = await api.get('/v1/chat/courses', { headers: buildHeaders() })
  return response.data.courses || []
}

export async function createChatConversation({ courseId = '', courseIds = [], title = '新对话' } = {}) {
  const response = await api.post('/v1/chat/conversations', {
    course_id: courseId || null,
    course_ids: courseIds,
    title,
  }, { headers: buildHeaders() })
  return response.data
}

export async function getChatConversation(conversationId) {
  const response = await api.get(`/v1/chat/conversations/${conversationId}`, { headers: buildHeaders() })
  return response.data
}

export async function archiveChatConversation(conversationId, lockVersion) {
  const response = await api.post(`/v1/chat/conversations/${conversationId}/archive`, {
    expected_lock_version: lockVersion,
  }, { headers: buildHeaders() })
  return response.data
}

export async function uploadChatAttachment(conversationId, file, idempotencyKey) {
  const form = new FormData()
  form.append('idempotency_key', idempotencyKey)
  form.append('file', file)
  const response = await api.post(`/v1/chat/conversations/${conversationId}/attachments`, form, {
    headers: buildHeaders(),
  })
  return response.data.attachment
}

export async function parseChatAttachment(attachment) {
  const response = await api.post(`/v1/chat/attachments/${attachment.id}/parse`, {
    expected_lock_version: attachment.lockVersion,
  }, { headers: buildHeaders() })
  return response.data
}

export async function confirmPartialChatAttachment(attachment) {
  const response = await api.post(`/v1/chat/attachments/${attachment.id}/confirm-partial`, {
    expected_lock_version: attachment.lockVersion,
  }, { headers: buildHeaders() })
  return response.data
}

export async function removeChatAttachment(attachment) {
  const response = await api.post(`/v1/chat/attachments/${attachment.id}/remove`, {
    expected_lock_version: attachment.lockVersion,
  }, { headers: buildHeaders() })
  return response.data
}

export async function createChatMessage(conversationId, payload) {
  const response = await api.post(`/v1/chat/conversations/${conversationId}/messages`, {
    ...payload,
    intent: payload?.intent || 'chat',
    resource_types: payload?.resource_types || [],
    context_snapshot_id: payload?.context_snapshot_id || '',
    return_to: payload?.return_to || '',
  }, {
    headers: buildHeaders(),
  })
  return response.data
}

export async function stopChatMessage(message) {
  const response = await api.post(`/v1/chat/messages/${message.id}/stop`, {
    expected_lock_version: message.lockVersion,
  }, { headers: buildHeaders() })
  return response.data
}

export async function continueChatMessage(message) {
  const response = await api.post(`/v1/chat/messages/${message.id}/continue`, {
    expected_lock_version: message.lockVersion,
  }, { headers: buildHeaders() })
  return response.data
}

export async function createChatResourceAction(message, resourceType, knowledgePointId = '') {
  const response = await api.post(`/v1/chat/messages/${message.id}/resource-actions`, {
    resource_type: resourceType,
    expected_lock_version: message.lockVersion,
    knowledge_point_id: knowledgePointId || null,
  }, { headers: buildHeaders() })
  return response.data
}
