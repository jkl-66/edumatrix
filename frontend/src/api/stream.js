import { api, buildHeaders, errorMessageText } from './common'

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

function openChatStream(studentId, body, onEvent, onError, retries) {
  abortStream(studentId)

  const controller = new AbortController()
  _activeStreamControllers.set(studentId, controller)
  const { signal } = controller
  const headers = buildHeaders()
  let retryCount = 0

  function clearActiveController() {
    // A delayed retry/error from an older stream must not remove a newer stream.
    if (_activeStreamControllers.get(studentId) === controller) {
      _activeStreamControllers.delete(studentId)
    }
  }

  function doFetch() {
    if (signal.aborted) {
      clearActiveController()
      return
    }
    fetch('/api/stream/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...headers },
      body: JSON.stringify(body),
      signal,
    }).then(response => {
      if (!response.ok) {
        if (signal.aborted) {
          clearActiveController()
          return
        }
        if (retryCount < retries && response.status >= 500) {
          retryCount++
          window.setTimeout(doFetch, Math.min(1000 * (2 ** retryCount), 5000))
          return
        }
        response.text().then((raw) => {
          let detail = raw
          try { detail = raw ? JSON.parse(raw) : raw } catch {}
          const error = new Error(errorMessageText(detail, `请求失败（HTTP ${response.status}）`))
          error.status = response.status
          error.response = { status: response.status, data: detail }
          clearActiveController()
          onError?.(error)
        }).catch(() => {
          clearActiveController()
          onError?.(new Error(`请求失败（HTTP ${response.status}）`))
        })
        return
      }

      retryCount = 0
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let currentEvent = ''

      function read() {
        if (signal.aborted) {
          reader.cancel().catch(() => {})
          return
        }
        reader.read().then(({ done, value }) => {
          if (done) {
            clearActiveController()
            return
          }
          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() || ''
          for (const line of lines) {
            if (line.startsWith('event: ')) currentEvent = line.slice(7).trim()
            if (line.startsWith('data: ')) {
              try {
                onEvent?.(currentEvent, JSON.parse(line.slice(6)))
              } catch {}
            }
          }
          read()
        }).catch(error => {
          if (error.name === 'AbortError') return
          if (retryCount < retries) {
            retryCount++
            window.setTimeout(doFetch, Math.min(1000 * (2 ** retryCount), 5000))
            return
          }
          clearActiveController()
          onError?.(error)
        })
      }
      read()
    }).catch(error => {
      if (error.name === 'AbortError') return
      if (retryCount < retries) {
        retryCount++
        window.setTimeout(doFetch, Math.min(1000 * (2 ** retryCount), 5000))
        return
      }
      clearActiveController()
      onError?.(error)
    })
  }

  doFetch()
  return () => abortStream(studentId)
}

export function streamChat(message, studentId, onEvent, onError, mode = 'chat', images = [], activeDocIds = [], retries = 3, contextSessionId = '') {
  return openChatStream(studentId, {
    message,
    student_id: studentId,
    mode,
    images,
    active_doc_ids: activeDocIds,
    context_session_id: contextSessionId || undefined,
  }, onEvent, onError, retries)
}

export function streamCanonicalChat(userMessageId, studentId, onEvent, onError, retries = 2) {
  return openChatStream(studentId, {
    student_id: studentId,
    user_message_id: userMessageId,
  }, onEvent, onError, retries)
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
    headers: { 
      'Content-Type': 'application/json',
      'Accept': 'text/event-stream',
      ...headers 
    },
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
