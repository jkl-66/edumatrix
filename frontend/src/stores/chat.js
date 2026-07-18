import { defineStore } from 'pinia'
import { streamChat, abortStream } from '../api'

function cleanStreamingContent(text) {
  if (!text) return ''
  const markers = [
    '===SUGGESTED_QUESTIONS===',
    '[建议追问]',
    '【建议追问】',
    '建议追问（点击可追问）',
    '建议追问(点击可追问)',
    '\n建议追问'
  ]
  for (const marker of markers) {
    const idx = text.indexOf(marker)
    if (idx !== -1) {
      let sliceIdx = idx
      const before = text.substring(0, idx).trim()
      if (before.endsWith('===')) {
        sliceIdx = text.substring(0, idx).lastIndexOf('===')
      } else if (before.endsWith('---')) {
        sliceIdx = text.substring(0, idx).lastIndexOf('---')
      }
      return text.substring(0, sliceIdx).trim()
    }
  }
  return text
}

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: (() => {
      try {
        const raw = localStorage.getItem('edumatrix_chat_messages')
        return raw ? JSON.parse(raw) : []
      } catch {
        return []
      }
    })(),
    sending: false,
    streamingProgress: 0,
    streamingStatus: '',
    streamingAgents: {},
    streamingMode: 'chat',  // 当前流式传输模式 (chat / matrix)
    streamingContent: '',  // 任务 1: 增量流式内容缓存
    rawStreamingContent: '', // Full raw streaming content
    _cleanupStream: null,  // 任务 8.2: AbortController 清理函数
    latestMetrics: null,    // 上一次生成性能指标
    sessionTotalTokens: 0,  // 当前会话总Token数
    sessionTotalCost: 0,    // 当前会话估算花费(元)
  }),
  actions: {
    /**
     * 任务 8.2: 页面销毁时调用，释放流式连接
     */
    cleanup() {
      if (this._cleanupStream) {
        this._cleanupStream()
        this._cleanupStream = null
      }
      if (this.sending) {
        abortStream('current')
        this.sending = false
      }
      this.streamingMode = 'chat'
      this.streamingContent = ''
      this.rawStreamingContent = ''
    },

    saveMessages() {
      try {
        localStorage.setItem('edumatrix_chat_messages', JSON.stringify(this.messages))
      } catch (e) {
        console.error('Failed to persist chat messages:', e)
      }
    },

    addMessage(msg) {
      this.messages.push(msg)
      this.saveMessages()
    },

    clearHistory() {
      this.cleanup()
      this.messages = []
      try {
        localStorage.removeItem('edumatrix_chat_messages')
      } catch (e) {
        console.error('Failed to clear chat history:', e)
      }
    },

    /**
     * 自动闭合未闭合的 LaTeX ($$, $) 和 Markdown (```) 块
     */
    getSafeContent(text) {
      if (!text) return ''
      let result = text

      const codeBlockCount = (text.match(/```/g) || []).length
      if (codeBlockCount % 2 !== 0) {
        result += '\n```'
      }

      const doubleDollarCount = (text.match(/\$\$/g) || []).length
      if (doubleDollarCount % 2 !== 0) {
        result += '$$'
      }

      const tempText = text.replace(/\$\$/g, '')
      const singleDollarCount = (tempText.match(/(?<!\\)\$/g) || []).length
      if (singleDollarCount % 2 !== 0) {
        result += '$'
      }

      return result
    },

    async sendChatMessage(message, studentId, mode = 'chat', images = [], activeDocIds = []) {
      if (this.sending) return
      this.sending = true
      this.streamingProgress = 10
      this.streamingStatus = '正在发起连接...'
      this.streamingAgents = {}
      this.streamingMode = mode

      this.addMessage({ role: 'user', content: message, images: [...images] })
      
      // 添加助手占位符 (仅在非 matrix 模式下展示打字机/占位卡)
      if (mode !== 'matrix') {
        this.addMessage({
          role: 'assistant',
          content: '',
          resources: [],
          streaming: true,
        })
      }

      return new Promise((resolve, reject) => {
        // streamChat 返回 AbortController 清理函数
        this._cleanupStream = streamChat(
          message,
          studentId,
          (event, data) => {
            if (event === 'progress') {
              this.streamingProgress = data.progress || this.streamingProgress
              this.streamingStatus = data.message || this.streamingStatus
            } else if (event === 'chat_chunk') {
              this.rawStreamingContent += data.content || ''
              this.streamingContent = cleanStreamingContent(this.rawStreamingContent)
              
              const lastMsg = this.messages[this.messages.length - 1]
              if (lastMsg && lastMsg.role === 'assistant') {
                lastMsg.content = this.streamingContent
                this.saveMessages()
              }
            } else if (event === 'agent_done') {
              this.streamingProgress = data.progress || this.streamingProgress
              const agentName = data.agent === '视频推荐官' ? '虚拟导演' : data.agent
              this.streamingAgents[agentName] = {
                type: data.type,
                error: data.error || null,
                done: true,
              }
              this.streamingStatus = `[${agentName}] 生成完成`
            } else if (event === 'content') {
              this.rawStreamingContent += data.content || ''
              this.streamingContent = cleanStreamingContent(this.rawStreamingContent)
              this.streamingProgress = data.progress || this.streamingProgress
            } else if (event === 'complete') {
              this.streamingProgress = 100
              this.streamingStatus = '生成完成！'

              if (data.metrics) {
                this.latestMetrics = data.metrics
                this.sessionTotalTokens += data.metrics.tokens_used || 0
                this.sessionTotalCost += data.metrics.cost_cny || 0
              }

              const safeContent = this.getSafeContent(data.content)

              const finalMsgContent = (safeContent.includes('学习目标') || safeContent.includes('##'))
                ? safeContent
                : `## 学习目标：${data.target || '未识别'}\n\n` + safeContent

              const normalizedResources = (data.resources || []).map(r => ({
                ...r,
                agent: r.agent === '视频推荐官' ? '虚拟导演' : r.agent
              }))

              const lastIdx = this.messages.length - 1
              if (lastIdx >= 0 && this.messages[lastIdx].role === 'assistant') {
                this.messages.splice(lastIdx, 1, {
                  role: 'assistant',
                  content: finalMsgContent,
                  resources: normalizedResources,
                  suggested_questions: data.suggested_questions || [],
                  profile: data.profile || null,
                  strategy: data.strategy_plan || null,
                  target: data.target || '',
                  safety: data.safety || null,
                  alignment: data.alignment || {},
                  rdi: data.rdi || null,
                  metrics: data.metrics || null,
                  streaming: false,
                })
              } else {
                this.addMessage({
                  role: 'assistant',
                  content: finalMsgContent,
                  resources: normalizedResources,
                  suggested_questions: data.suggested_questions || [],
                  profile: data.profile || null,
                  strategy: data.strategy_plan || null,
                  target: data.target || '',
                  safety: data.safety || null,
                  alignment: data.alignment || {},
                  rdi: data.rdi || null,
                  metrics: data.metrics || null,
                  streaming: false,
                })
              }
              this.saveMessages()
              this.sending = false
              this.streamingContent = ''
              this.rawStreamingContent = ''
              this._cleanupStream = null
              resolve(data)
            } else if (event === 'error') {
              this.sending = false
              this.streamingContent = ''
              this.rawStreamingContent = ''
              this._cleanupStream = null
              const lastIdx = this.messages.length - 1
              if (lastIdx >= 0 && this.messages[lastIdx].role === 'assistant') {
                this.messages.splice(lastIdx, 1, {
                  role: 'assistant',
                  content: `错误：${data.message || '生成失败'}`,
                  error: true,
                  streaming: false,
                })
              } else {
                this.addMessage({
                  role: 'assistant',
                  content: `错误：${data.message || '生成失败'}`,
                  error: true,
                  streaming: false,
                })
              }
              this.saveMessages()
              reject(new Error(data.message))
            }
          },
          (err) => {
            this.sending = false
            this._cleanupStream = null
            const lastIdx = this.messages.length - 1
            if (lastIdx >= 0 && this.messages[lastIdx].role === 'assistant') {
              this.messages[lastIdx] = {
                role: 'assistant',
                content: `连接异常中断，正在尝试使用语法防护网收敛输出...`,
                error: true,
                streaming: false,
              }
            } else {
              this.addMessage({
                role: 'assistant',
                content: `连接异常中断，正在尝试使用语法防护网收敛输出...`,
                error: true,
                streaming: false,
              })
            }
            this.saveMessages()
            reject(err)
          },
          mode,
          images,
          activeDocIds
        )
      })
    }
  }
})
