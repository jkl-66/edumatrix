import { defineStore } from 'pinia'
import { streamChat } from '../api'

export const useChatStore = defineStore('chat', {
  state: () => ({
    messages: [],
    sending: false,
    streamingProgress: 0,
    streamingStatus: '',
    streamingAgents: {},
  }),
  actions: {
    addMessage(msg) {
      this.messages.push(msg)
    },
    
    /**
     * 自动闭合未闭合的 LaTeX ($$, $) 和 Markdown (```) 块，防止前端渲染引擎崩溃
     */
    getSafeContent(text) {
      if (!text) return ''
      let result = text

      // 1. 检查代码块 ```
      const codeBlockCount = (text.match(/```/g) || []).length
      if (codeBlockCount % 2 !== 0) {
        result += '\n```'
      }

      // 2. 检查 LaTeX 双刀块 $$
      const doubleDollarCount = (text.match(/\$\$/g) || []).length
      if (doubleDollarCount % 2 !== 0) {
        result += '$$'
      }

      // 3. 检查 LaTeX 单刀块 $（跳过双刀）
      const tempText = text.replace(/\$\$/g, '')
      const singleDollarCount = (tempText.match(/(?<!\\)\$/g) || []).length
      if (singleDollarCount % 2 !== 0) {
        result += '$'
      }

      return result
    },

    async sendChatMessage(message, studentId) {
      if (this.sending) return
      this.sending = true
      this.streamingProgress = 10
      this.streamingStatus = '正在发起连接...'
      this.streamingAgents = {}

      this.addMessage({ role: 'user', content: message })

      return new Promise((resolve, reject) => {
        streamChat(
          message,
          studentId,
          (event, data) => {
            if (event === 'progress') {
              this.streamingProgress = data.progress || this.streamingProgress
              this.streamingStatus = data.message || this.streamingStatus
            } else if (event === 'agent_done') {
              this.streamingProgress = data.progress || this.streamingProgress
              this.streamingAgents[data.agent] = {
                type: data.type,
                error: data.error || null,
                done: true,
              }
              this.streamingStatus = `[${data.agent}] 生成完成`
            } else if (event === 'complete') {
              this.streamingProgress = 100
              this.streamingStatus = '生成完成！'
              
              // 物理清洗，防语法坍塌
              const safeContent = this.getSafeContent(data.content)
              
              const assistantMsg = {
                role: 'assistant',
                content: `## 学习目标：${data.target || '未识别'}\n\n` + safeContent,
                resources: data.resources || [],
                profile: data.profile || null,
                strategy: data.strategy_plan || null,
                target: data.target || '',
                safety: data.safety || null,
                alignment: data.alignment || {},
              }
              
              this.addMessage(assistantMsg)
              this.sending = false
              resolve(data)
            } else if (event === 'error') {
              this.sending = false
              this.addMessage({
                role: 'assistant',
                content: `错误：${data.message || '生成失败'}`,
                error: true,
              })
              reject(new Error(data.message))
            }
          },
          (err) => {
            this.sending = false
            this.addMessage({
              role: 'assistant',
              content: `连接异常中断，正在尝试使用语法防护网收敛输出...`,
              error: true,
            })
            reject(err)
          }
        )
      })
    }
  }
})
