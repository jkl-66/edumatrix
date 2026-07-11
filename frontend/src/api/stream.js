import { api, buildHeaders } from './common'

export async function processMessage(message, studentId = 'stu-' + Date.now()) {
  const r = await api.post('/process', { message, student_id: studentId }, { headers: buildHeaders() })
  return r.data
}

export async function getSession(sid) {
  const r = await api.get(`/sessions/${sid}`, { headers: buildHeaders() })
  return r.data
}

// --- Streaming Chat API (任务 8.2: AbortController + 内存泄漏修复) ---
const _activeStreamControllers = new Map()  // studentId -> AbortController

export function abortStream(studentId) {
  const ctrl = _activeStreamControllers.get(studentId)
  if (ctrl) {
    ctrl.abort()
    _activeStreamControllers.delete(studentId)
  }
}

export function abortAllStreams() {
  for (const [sid, ctrl] of _activeStreamControllers) {
    ctrl.abort()
  }
  _activeStreamControllers.clear()
}

export function streamChat(message, studentId, onEvent, onError, mode = 'chat', images = [], retries = 3) {
  // 强制终止该学生的旧连接，防止并发泄漏
  abortStream(studentId)

  const controller = new AbortController()
  _activeStreamControllers.set(studentId, controller)
  const { signal } = controller

  const headers = buildHeaders()
  const url = '/api/stream/chat'
  let retryCount = 0

  function doFetch() {
    if (signal.aborted) return

    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify({ message, student_id: studentId, mode, images }),
      signal,
    }).then(response => {
      if (!response.ok) {
        if (signal.aborted) return
        // 断线自动重连（最多 retries 次）
        if (retryCount < retries) {
          retryCount++
          const delay = Math.min(1000 * Math.pow(2, retryCount), 5000)
          console.warn(`[Chat] 连接断开(${response.status})，${delay}ms后重试(${retryCount}/${retries})`)
          setTimeout(doFetch, delay)
          return
        }
        onError?.(new Error(`HTTP ${response.status}`))
        return
      }

      // 连接成功，重置重试计数
      retryCount = 0
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      function read() {
        if (signal.aborted) {
          reader.cancel().catch(() => {})
          return
        }
        reader.read().then(({ done, value }) => {
          if (signal.aborted) return
          if (done) {
            _activeStreamControllers.delete(studentId)
            return
          }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          let currentEvent = ''
          for (const line of lines) {
            if (line.startsWith('event: ')) {
              currentEvent = line.slice(7).trim()
            } else if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                onEvent?.(currentEvent, data)
              } catch {}
            }
          }
          read()
        }).catch(err => {
          if (err.name === 'AbortError') return
          // 断线自动重连
          if (retryCount < retries) {
            retryCount++
            const delay = Math.min(1000 * Math.pow(2, retryCount), 5000)
            console.warn(`[Chat] 流断开，${delay}ms后重试(${retryCount}/${retries})`)
            setTimeout(doFetch, delay)
            return
          }
          onError?.(err)
        })
      }
      read()
    }).catch(err => {
      if (err.name === 'AbortError') return
      // 网络错误自动重连
      if (retryCount < retries) {
        retryCount++
        const delay = Math.min(1000 * Math.pow(2, retryCount), 5000)
        console.warn(`[Chat] 网络错误，${delay}ms后重试(${retryCount}/${retries})`)
        setTimeout(doFetch, delay)
        return
      }
      onError?.(err)
    })
  }

  doFetch()

  // 返回 abort 函数供组件销毁时调用
  return () => abortStream(studentId)
}

export async function regenerateComponent(studentId, role, resourceType, query, overview = null, pathway = null) {
  const r = await api.post('/stream/regenerate', {
    student_id: studentId,
    role,
    resource_type: resourceType,
    query,
    overview,
    pathway,
  }, { headers: buildHeaders() })
  return r.data
}

export async function socraticExplain(opts) {
  const r = await api.post('/stream/explain', {
    target_text: opts.target_text,
    context_before: opts.context_before || '',
    context_after: opts.context_after || '',
    student_id: opts.student_id || 'default',
    follow_up: opts.follow_up || '',
    history: opts.history || '',
  }, { headers: buildHeaders() })
  return r.data
}

/**
 * 流式版本：逐 token 回调 content，完成后回调 complete(content, trace)
 */
export function socraticExplainStream(opts, onContent, onComplete, onError) {
  const controller = new AbortController()
  const headers = buildHeaders()

  fetch('/api/stream/explain', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify({
      target_text: opts.target_text,
      context_before: opts.context_before || '',
      context_after: opts.context_after || '',
      student_id: opts.student_id || 'default',
      follow_up: opts.follow_up || '',
      history: opts.history || '',
    }),
    signal: controller.signal,
  }).then(response => {
    if (!response.ok) {
      onError?.(new Error(`HTTP ${response.status}`))
      return
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    function read() {
      reader.read().then(({ done, value }) => {
        if (done) return
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        let currentEvent = ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (trimmed.startsWith('event: ')) {
            currentEvent = trimmed.slice(7).trim()
          } else if (trimmed.startsWith('data: ') && currentEvent) {
            try {
              const data = JSON.parse(trimmed.slice(6))
              if (currentEvent === 'content') {
                onContent?.(data.content || '')
              } else if (currentEvent === 'complete') {
                onComplete?.(data.content || '', data)
              }
            } catch {}
          }
        }
        read()
      }).catch(err => {
        if (err.name !== 'AbortError') onError?.(err)
      })
    }
    read()
  }).catch(err => {
    if (err.name !== 'AbortError') onError?.(err)
  })

  return controller
}
