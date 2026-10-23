import { defineStore } from 'pinia'
import {
  abortStream,
  archiveChatConversation,
  confirmPartialChatAttachment,
  continueChatMessage,
  createChatConversation,
  createChatMessage,
  createChatResourceAction,
  getChatConversation,
  listChatConversations,
  listChatCourses,
  parseChatAttachment,
  removeChatAttachment,
  stopChatMessage,
  streamCanonicalChat,
  uploadChatAttachment,
} from '../api'
import { errorMessageText } from '../api/common'

function operationKey(prefix) {
  const suffix = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${suffix}`
}

function errorMessage(error, fallback) {
  return errorMessageText(
    error?.response?.data?.detail ?? error?.detail ?? error?.message,
    fallback,
  )
}

function cleanStreamingContent(text) {
  if (!text) return ''
  const markers = [
    '===SUGGESTED_QUESTIONS===',
    '[建议追问]',
    '【建议追问】',
    '建议追问（点击可追问）',
    '建议追问(点击可追问)',
    '\n建议追问',
  ]
  for (const marker of markers) {
    const index = text.indexOf(marker)
    if (index >= 0) return text.slice(0, index).trim()
  }
  return text
}

function sortMessages(messages) {
  return [...messages].sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0))
}

function eventAgentAudit(data, message) {
  return data?.agent_audit
    || data?.agentAudit
    || data?.message?.agentAudit
    || data?.message?.agent_audit
    || message?.agentAudit
    || null
}

function eventRunEvents(data, message) {
  return data?.run_events
    || data?.runEvents
    || data?.message?.runEvents
    || message?.runEvents
    || message?.streamCheckpoint?.runEvents
    || []
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    conversations: [],
    availableCourses: [],
    loadingCourses: false,
    courseCatalogError: '',
    selectedCourseIds: [],
    activeConversationId: '',
    activeConversation: null,
    messages: [],
    attachments: [],
    selectedAttachmentIds: [],
    loading: false,
    creatingConversation: false,
    sending: false,
    streamingProgress: 0,
    streamingStatus: '',
    streamingAgents: {},
    streamingMode: 'chat',
    streamingContent: '',
    rawStreamingContent: '',
    latestMetrics: null,
    sessionTotalTokens: 0,
    sessionTotalCost: 0,
    attachmentActions: {},
    resourceActions: {},
    pendingSend: null,
    error: '',
    attachmentError: '',
    _cleanupStream: null,
  }),

  getters: {
    selectedAttachments(state) {
      const selected = new Set(state.selectedAttachmentIds)
      return state.attachments.filter((attachment) => selected.has(attachment.id) && attachment.status !== 'removed')
    },
    attachmentBlockReason() {
      const parsing = this.selectedAttachments.find((item) => ['queued', 'parsing'].includes(item.status))
      if (parsing) return `“${parsing.filename}”仍在解析`
      const partial = this.selectedAttachments.find((item) => item.status === 'partial_failed' && !item.partialConfirmed)
      if (partial) return `请确认“${partial.filename}”的部分解析结果`
      const failed = this.selectedAttachments.find((item) => ['failed', 'failed_retryable'].includes(item.status))
      if (failed) return `请重试或移除“${failed.filename}”`
      return ''
    },
    activeAssistant(state) {
      return [...state.messages].reverse().find((message) => message.role === 'assistant') || null
    },
  },

  actions: {
    cleanup() {
      this._cleanupStream?.()
      this._cleanupStream = null
      this.sending = false
      this.streamingProgress = 0
      this.streamingStatus = ''
      this.streamingContent = ''
      this.rawStreamingContent = ''
      this.streamingAgents = {}
      this.streamingMode = 'chat'
    },

    resetConversationState() {
      this.messages = []
      this.attachments = []
      this.selectedAttachmentIds = []
      this.pendingSend = null
      this.error = ''
      this.attachmentError = ''
    },

    syncConversation(conversation) {
      this.activeConversation = conversation
      this.activeConversationId = conversation?.id || ''
      this.messages = sortMessages(conversation?.messages || [])
      this.attachments = [...(conversation?.attachments || [])]
      const available = new Set(this.attachments.filter((item) => item.status !== 'removed').map((item) => item.id))
      this.selectedAttachmentIds = this.selectedAttachmentIds.filter((id) => available.has(id))
      if (!conversation) return
      const summary = {
        id: conversation.id,
        courseId: conversation.courseId,
        courseIds: [...(conversation.courseIds || (conversation.courseId ? [conversation.courseId] : []))],
        courses: [...(conversation.courses || [])],
        contextMode: conversation.contextMode || (conversation.courseId ? 'course' : 'general'),
        title: conversation.title,
        status: conversation.status,
        lockVersion: conversation.lockVersion,
        createdAt: conversation.createdAt,
        updatedAt: conversation.updatedAt,
      }
      const index = this.conversations.findIndex((item) => item.id === conversation.id)
      if (index >= 0) this.conversations.splice(index, 1, summary)
      else this.conversations.unshift(summary)
      this.selectedCourseIds = [...(conversation.courseIds || (conversation.courseId ? [conversation.courseId] : []))]
    },

    upsertMessage(message) {
      if (!message?.id) return
      const index = this.messages.findIndex((item) => item.id === message.id)
      if (index >= 0) this.messages.splice(index, 1, { ...this.messages[index], ...message })
      else this.messages.push(message)
      this.messages = sortMessages(this.messages)
    },

    upsertAttachment(attachment) {
      if (!attachment?.id) return
      const index = this.attachments.findIndex((item) => item.id === attachment.id)
      if (index >= 0) this.attachments.splice(index, 1, attachment)
      else this.attachments.push(attachment)
    },

    async loadCourseOptions() {
      this.loadingCourses = true
      this.courseCatalogError = ''
      try {
        this.availableCourses = await listChatCourses()
        return this.availableCourses
      } catch (error) {
        this.courseCatalogError = errorMessage(error, '课程列表加载失败')
        throw error
      } finally {
        this.loadingCourses = false
      }
    },

    setSelectedCourseIds(courseIds = []) {
      const allowed = new Set(this.availableCourses.map((course) => String(course.id)))
      const next = [...new Set((courseIds || []).map((id) => String(id)).filter((id) => id && allowed.has(id)))]
      const selectedCourses = next
        .map((id) => this.availableCourses.find((course) => String(course.id) === id))
        .filter(Boolean)
      this.selectedCourseIds = next
      if (this.activeConversation) {
        this.activeConversation = {
          ...this.activeConversation,
          courseId: next[0] || null,
          courseIds: next,
          courses: selectedCourses,
          contextMode: next.length ? 'course' : 'general',
        }
      }
      const index = this.conversations.findIndex((item) => item.id === this.activeConversationId)
      if (index >= 0) {
        this.conversations.splice(index, 1, {
          ...this.conversations[index],
          courseId: next[0] || null,
          courseIds: next,
          courses: selectedCourses,
          contextMode: next.length ? 'course' : 'general',
        })
      }
      return next
    },

    async initialize({ courseId = '', conversationId = '', createIfEmpty = true } = {}) {
      this.loading = true
      this.error = ''
      try {
        this.conversations = await listChatConversations()
        const preferred = conversationId
          ? this.conversations.find((item) => item.id === conversationId)
          : this.conversations.find((item) => !courseId || item.courseId === courseId)
        if (preferred) return await this.openConversation(preferred.id)
        if (createIfEmpty) return await this.createConversation({ courseId })
        this.activeConversation = null
        this.activeConversationId = ''
        this.resetConversationState()
        return null
      } catch (error) {
        this.error = errorMessage(error, '加载对话失败')
        throw error
      } finally {
        this.loading = false
      }
    },

    async createConversation({ courseId = '', courseIds = [], title = '新对话' } = {}) {
      if (this.creatingConversation) return this.activeConversation
      this.creatingConversation = true
      this.error = ''
      try {
        const conversation = await createChatConversation({ courseId, courseIds, title })
        this.cleanup()
        this.resetConversationState()
        this.syncConversation(conversation)
        return conversation
      } catch (error) {
        this.error = errorMessage(error, '新建对话失败')
        throw error
      } finally {
        this.creatingConversation = false
      }
    },

    async openConversation(conversationId, { resume = true } = {}) {
      if (!conversationId) return null
      this.cleanup()
      this.loading = true
      this.error = ''
      try {
        const conversation = await getChatConversation(conversationId)
        this.resetConversationState()
        this.syncConversation(conversation)
        const assistant = [...this.messages].reverse().find((message) =>
          message.role === 'assistant' && ['queued', 'streaming'].includes(message.status))
        if (resume && assistant?.replyToMessageId) this.startStream(assistant.replyToMessageId, assistant.id)
        return conversation
      } catch (error) {
        this.error = errorMessage(error, '打开对话失败')
        throw error
      } finally {
        this.loading = false
      }
    },

    async refreshActiveConversation() {
      if (!this.activeConversationId) return null
      try {
        const conversation = await getChatConversation(this.activeConversationId)
        this.syncConversation(conversation)
        return conversation
      } catch (error) {
        this.error = errorMessage(error, '刷新对话失败')
        throw error
      }
    },

    async archiveConversation(conversationId = this.activeConversationId) {
      const target = this.conversations.find((item) => item.id === conversationId)
        || (this.activeConversation?.id === conversationId ? this.activeConversation : null)
      if (!target) return null
      const archived = await archiveChatConversation(conversationId, target.lockVersion)
      this.conversations = this.conversations.filter((item) => item.id !== conversationId)
      if (this.activeConversationId !== conversationId) return archived
      this.cleanup()
      this.activeConversation = null
      this.activeConversationId = ''
      this.resetConversationState()
      const next = this.conversations[0]
      if (next) return await this.openConversation(next.id)
      return await this.createConversation({ courseId: archived.courseId || '' })
    },

    async clearHistory() {
      if (!this.activeConversationId) return this.createConversation()
      return this.archiveConversation(this.activeConversationId)
    },

    saveMessages() {
      // Canonical messages are persisted by /api/v1/chat. This compatibility hook is intentionally a no-op.
    },

    toggleAttachmentSelection(attachmentId) {
      const attachment = this.attachments.find((item) => item.id === attachmentId)
      if (!attachment || attachment.status === 'removed') return
      if (this.selectedAttachmentIds.includes(attachmentId)) {
        this.selectedAttachmentIds = this.selectedAttachmentIds.filter((id) => id !== attachmentId)
      } else {
        this.selectedAttachmentIds.push(attachmentId)
      }
    },

    setAttachmentAction(attachmentId, action = '') {
      if (!action) {
        const next = { ...this.attachmentActions }
        delete next[attachmentId]
        this.attachmentActions = next
        return
      }
      this.attachmentActions = { ...this.attachmentActions, [attachmentId]: action }
    },

    setResourceAction(messageId, resourceType, active) {
      const key = `${messageId}:${resourceType}`
      const next = { ...this.resourceActions }
      if (active) next[key] = true
      else delete next[key]
      this.resourceActions = next
    },

    async uploadAttachment(file) {
      if (!file) return null
      if (!this.activeConversationId) await this.createConversation()
      this.attachmentError = ''
      const temporaryId = `upload-${operationKey('attachment')}`
      this.setAttachmentAction(temporaryId, 'uploading')
      try {
        const uploaded = await uploadChatAttachment(
          this.activeConversationId,
          file,
          operationKey('attachment'),
        )
        this.setAttachmentAction(temporaryId)
        this.upsertAttachment(uploaded)
        if (!this.selectedAttachmentIds.includes(uploaded.id)) this.selectedAttachmentIds.push(uploaded.id)
        this.setAttachmentAction(uploaded.id, 'parsing')
        this.upsertAttachment({ ...uploaded, status: 'parsing', stage: 'parsing', progress: Math.max(uploaded.progress || 0, 0.2) })
        const parsed = await parseChatAttachment(uploaded)
        this.upsertAttachment(parsed)
        return parsed
      } catch (error) {
        this.attachmentError = errorMessage(error, '附件上传或解析失败')
        await this.refreshActiveConversation().catch(() => null)
        throw error
      } finally {
        this.setAttachmentAction(temporaryId)
        const latest = this.attachments.find((item) => item.filename === file.name)
        if (latest) this.setAttachmentAction(latest.id)
      }
    },

    async retryAttachment(attachmentId) {
      const attachment = this.attachments.find((item) => item.id === attachmentId)
      if (!attachment) return null
      this.attachmentError = ''
      this.setAttachmentAction(attachmentId, 'parsing')
      try {
        const parsed = await parseChatAttachment(attachment)
        this.upsertAttachment(parsed)
        return parsed
      } catch (error) {
        this.attachmentError = errorMessage(error, '附件重试失败')
        await this.refreshActiveConversation().catch(() => null)
        throw error
      } finally {
        this.setAttachmentAction(attachmentId)
      }
    },

    async confirmPartialAttachment(attachmentId) {
      const attachment = this.attachments.find((item) => item.id === attachmentId)
      if (!attachment) return null
      this.setAttachmentAction(attachmentId, 'confirming')
      try {
        const confirmed = await confirmPartialChatAttachment(attachment)
        this.upsertAttachment(confirmed)
        return confirmed
      } catch (error) {
        this.attachmentError = errorMessage(error, '确认部分解析结果失败')
        await this.refreshActiveConversation().catch(() => null)
        throw error
      } finally {
        this.setAttachmentAction(attachmentId)
      }
    },

    async removeAttachment(attachmentId) {
      const attachment = this.attachments.find((item) => item.id === attachmentId)
      if (!attachment) return null
      this.setAttachmentAction(attachmentId, 'removing')
      try {
        const removed = await removeChatAttachment(attachment)
        this.upsertAttachment(removed)
        this.selectedAttachmentIds = this.selectedAttachmentIds.filter((id) => id !== attachmentId)
        return removed
      } catch (error) {
        this.attachmentError = errorMessage(error, '移除附件失败')
        await this.refreshActiveConversation().catch(() => null)
        throw error
      } finally {
        this.setAttachmentAction(attachmentId)
      }
    },

    async sendMessage({
      content = '',
      contextRefs = [],
      attachmentIds = null,
      returnTo = '',
      intent = 'chat',
      resourceTypes = [],
      contextSnapshotId = '',
      idempotencyKey = '',
    } = {}) {
      if (this.sending) return null
      if (!this.activeConversationId) await this.createConversation()
      const selectedIds = attachmentIds || [...this.selectedAttachmentIds]
      const selected = this.attachments.filter((item) => selectedIds.includes(item.id) && item.status !== 'removed')
      const blocked = selected.find((item) => !item.canSend)
      if (blocked) throw new Error(this.attachmentBlockReason || `“${blocked.filename}”尚不可发送`)
      if (!content.trim() && selected.length === 0) throw new Error('请输入问题或添加可发送附件')

      const request = {
        content: content.trim(),
        attachment_ids: selected.map((item) => item.id),
        context_refs: contextRefs,
        idempotency_key: idempotencyKey || operationKey('message'),
        intent,
        resource_types: [...new Set((resourceTypes || []).map((item) => String(item).trim()).filter(Boolean))],
        context_snapshot_id: contextSnapshotId || '',
        return_to: returnTo,
      }
      this.pendingSend = request
      this.error = ''
      const optimisticId = `optimistic-${request.idempotency_key}`
      this.upsertMessage({
        id: optimisticId,
        role: 'user',
        content: request.content,
        status: 'queued',
        sequence: Math.max(...this.messages.map((item) => Number(item.sequence || 0)), 0) + 1,
        attachmentIds: request.attachment_ids,
        contextRefs: request.context_refs,
        intent: request.intent,
        idempotencyKey: request.idempotency_key,
        createdAt: new Date().toISOString(),
      })
      try {
        const pair = await createChatMessage(this.activeConversationId, request)
        this.messages = this.messages.filter((item) => item.id !== optimisticId)
        this.upsertMessage(pair.userMessage)
        this.upsertMessage(pair.assistantMessage)
        this.pendingSend = null
        this.selectedAttachmentIds = []
        this.startStream(pair.userMessage.id, pair.assistantMessage.id)
        return pair
      } catch (error) {
        this.error = errorMessage(error, '发送失败，问题已保留')
        this.upsertMessage({
          id: optimisticId,
          status: 'failed',
          failure: {
            code: error?.code || 'chat_send_failed',
            message: this.error,
          },
        })
        throw error
      }
    },

    async retryPendingMessage() {
      if (!this.pendingSend || !this.activeConversationId || this.sending) return null
      this.error = ''
      try {
        const pair = await createChatMessage(this.activeConversationId, this.pendingSend)
        const optimisticId = `optimistic-${this.pendingSend.idempotency_key}`
        this.messages = this.messages.filter((item) => item.id !== optimisticId)
        this.upsertMessage(pair.userMessage)
        this.upsertMessage(pair.assistantMessage)
        this.pendingSend = null
        this.selectedAttachmentIds = []
        this.startStream(pair.userMessage.id, pair.assistantMessage.id)
        return pair
      } catch (error) {
        this.error = errorMessage(error, '重试发送失败')
        const optimisticId = `optimistic-${this.pendingSend.idempotency_key}`
        this.upsertMessage({
          id: optimisticId,
          status: 'failed',
          failure: { code: error?.code || 'chat_retry_failed', message: this.error },
        })
        throw error
      }
    },

    startStream(userMessageId, assistantMessageId) {
      this.cleanup()
      this.sending = true
      this.streamingProgress = 10
      this.streamingStatus = '正在连接学习伙伴'
      this.rawStreamingContent = ''
      this.streamingContent = ''
      const current = this.messages.find((message) => message.id === assistantMessageId)
      if (current) this.upsertMessage({ ...current, status: 'streaming', content: '' })

      this._cleanupStream = streamCanonicalChat(
        userMessageId,
        '',
        (event, data) => {
          const messageId = data.message_id || assistantMessageId
          let message = this.messages.find((item) => item.id === messageId)
          const runEvents = eventRunEvents(data, message)
          if (message && runEvents.length) {
            this.upsertMessage({
              ...message,
              runId: data.run_id || data.runId || message.runId,
              runEvents,
              streamCheckpoint: {
                ...(message.streamCheckpoint || {}),
                runId: data.run_id || data.runId || message.streamCheckpoint?.runId,
                runEvents,
                resourceJobId: data.resource_job?.job_id || message.resourceJobId || message.streamCheckpoint?.resourceJobId || '',
                resourceStatus: data.resource_job?.status || message.resourceStatus || message.streamCheckpoint?.resourceStatus || '',
              },
              agentAudit: eventAgentAudit(data, message),
            })
            message = this.messages.find((item) => item.id === messageId) || message
          }
          if ([
            'run.started', 'stage.started', 'stage.progress', 'stage.completed', 'stage.failed',
            'claim.checked', 'source.bound', 'resource.item.started', 'resource.item.progress',
            'resource.item.completed', 'resource.item.failed', 'review_gate.started',
            'review_gate.passed', 'review_gate.failed', 'publish.completed', 'run.completed', 'run.failed',
          ].includes(event)) {
            this.streamingMode = String(data.resource_job?.status || '').length ? 'resource_generation' : this.streamingMode
            this.streamingStatus = data.event?.summary || data.message || this.streamingStatus
            const progress = Number(data.event?.progress)
            if (Number.isFinite(progress)) this.streamingProgress = Math.max(this.streamingProgress, progress * 100)
            return
          }
          if (event === 'progress') {
            this.streamingProgress = Number(data.progress || this.streamingProgress)
            this.streamingStatus = data.message || this.streamingStatus
            if (message) {
              this.upsertMessage({
                ...message,
                lockVersion: data.lock_version || message.lockVersion,
                status: 'streaming',
                agentAudit: eventAgentAudit(data, message),
              })
            }
            return
          }
          if (event === 'chat_chunk') {
            this.rawStreamingContent = data.replay
              ? String(data.content || '')
              : this.rawStreamingContent + String(data.content || '')
            this.streamingContent = cleanStreamingContent(this.rawStreamingContent)
            if (message) this.upsertMessage({ ...message, content: this.streamingContent, status: 'streaming' })
            return
          }
          if (event === 'checkpoint') {
            if (message) {
              this.upsertMessage({
                ...message,
                lockVersion: data.lock_version || message.lockVersion,
                streamCheckpoint: {
                  ...(message.streamCheckpoint || {}),
                  status: 'streaming',
                  receivedCharacters: data.received_characters || this.rawStreamingContent.length,
                  runEvents: runEvents.length ? runEvents : (message.streamCheckpoint?.runEvents || []),
                  agentAudit: eventAgentAudit(data, message),
                },
                runEvents: runEvents.length ? runEvents : message.runEvents,
                agentAudit: eventAgentAudit(data, message),
              })
            }
            return
          }
          if (event === 'complete') {
            const completed = data.message ? {
              ...data.message,
              agentAudit: eventAgentAudit(data, data.message),
            } : {
              ...message,
              id: messageId,
              status: 'completed',
              content: cleanStreamingContent(data.content || this.rawStreamingContent),
              sourceRefs: data.source_refs || message?.sourceRefs || [],
              resourceLinks: data.resource_links || message?.resourceLinks || [],
              agentAudit: eventAgentAudit(data, message),
            }
            this.upsertMessage(completed)
            this.latestMetrics = data.metrics || null
            this.sessionTotalTokens += Number(data.metrics?.tokens_used || 0)
            this.sessionTotalCost += Number(data.metrics?.cost_cny || 0)
            this.finishStream('回答完成')
            return
          }
          if (event === 'stopped') {
            if (message) {
              this.upsertMessage({
                ...message,
                status: 'stopped',
                content: data.content || message.content,
                agentAudit: eventAgentAudit(data, message),
              })
            }
            this.finishStream('回答已停止')
            void this.refreshActiveConversation().catch(() => null)
            return
          }
          if (event === 'error') {
            const failureMessage = errorMessageText(data.message, '回答暂时失败，已保留当前内容')
            if (message) {
              this.upsertMessage({
                ...message,
                status: 'failed',
                content: data.content || message.content,
                failure: { code: data.code || 'chat_stream_failed', message: failureMessage },
                agentAudit: eventAgentAudit(data, message),
              })
            }
            this.error = failureMessage
            this.finishStream('回答失败')
            void this.refreshActiveConversation().catch(() => null)
          }
        },
        (error) => {
          this.error = errorMessage(error, '连接中断，已保留当前内容')
          this.finishStream('连接中断')
          void this.refreshActiveConversation().catch(() => null)
        },
      )
    },

    finishStream(status) {
      this._cleanupStream = null
      this.sending = false
      this.streamingProgress = status === '回答完成' ? 100 : this.streamingProgress
      this.streamingStatus = status
      this.streamingContent = ''
      this.rawStreamingContent = ''
    },

    async stopActiveResponse() {
      const message = this.activeAssistant
      if (!message || !['queued', 'streaming'].includes(message.status)) return null
      try {
        const stopped = await stopChatMessage(message)
        this.upsertMessage(stopped)
        this._cleanupStream?.()
        this.finishStream('回答已停止')
        return stopped
      } catch (error) {
        if (error?.status === 409 || error?.response?.status === 409) {
          await this.refreshActiveConversation()
          const latest = this.messages.find((item) => item.id === message.id)
          if (latest && ['queued', 'streaming'].includes(latest.status)) {
            const stopped = await stopChatMessage(latest)
            this.upsertMessage(stopped)
            this._cleanupStream?.()
            this.finishStream('回答已停止')
            return stopped
          }
        }
        this.error = errorMessage(error, '停止回答失败')
        throw error
      }
    },

    async continueResponse(messageId = this.activeAssistant?.id) {
      const message = this.messages.find((item) => item.id === messageId)
      if (!message || !['stopped', 'failed'].includes(message.status)) return null
      this.error = ''
      try {
        const queued = await continueChatMessage(message)
        this.upsertMessage(queued)
        this.startStream(queued.replyToMessageId, queued.id)
        return queued
      } catch (error) {
        this.error = errorMessage(error, '继续回答失败')
        await this.refreshActiveConversation().catch(() => null)
        throw error
      }
    },

    async createResourceFromMessage(messageId, resourceType, knowledgePointId = '') {
      let message = this.messages.find((item) => item.id === messageId)
      if (!message || message.role !== 'assistant' || message.status !== 'completed') return null
      this.setResourceAction(messageId, resourceType, true)
      this.error = ''
      try {
        let result
        try {
          result = await createChatResourceAction(message, resourceType, knowledgePointId)
        } catch (error) {
          if (error?.status !== 409 && error?.response?.status !== 409) throw error
          await this.refreshActiveConversation()
          message = this.messages.find((item) => item.id === messageId)
          if (!message) throw error
          result = await createChatResourceAction(message, resourceType, knowledgePointId)
        }
        this.upsertMessage(result.message)
        return result
      } catch (error) {
        this.error = errorMessage(error, '创建资源任务失败')
        throw error
      } finally {
        this.setResourceAction(messageId, resourceType, false)
      }
    },

    async sendChatMessage(message) {
      return this.sendMessage({ content: message })
    },

    getSafeContent(text) {
      if (!text) return ''
      let result = text
      if ((text.match(/```/g) || []).length % 2) result += '\n```'
      if ((text.match(/\$\$/g) || []).length % 2) result += '$$'
      const withoutBlocks = text.replace(/\$\$/g, '')
      if ((withoutBlocks.match(/(?<!\\)\$/g) || []).length % 2) result += '$'
      return result
    },
  },
})
