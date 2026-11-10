// Keep pause intent across sentence-end callbacks from the browser voice engine.
export function createSpeechPlayback({ synthesis, createUtterance, onState, onError }) {
  let generation = 0
  let state = 'idle'
  let pendingNext = null
  let activeUtterance = null
  const setState = value => { state = value; onState(value) }
  function stop() {
    generation += 1
    pendingNext = null
    activeUtterance = null
    if (state !== 'idle') synthesis.cancel()
    setState('idle')
  }
  function start(chunks) {
    stop()
    synthesis.resume()
    const current = ++generation
    let index = 0
    function next() {
      if (current !== generation) return
      activeUtterance = null
      if (index >= chunks.length) { setState('idle'); return }
      if (state === 'paused') { pendingNext = next; return }
      pendingNext = null
      setState('playing')
      activeUtterance = createUtterance(chunks[index++])
      activeUtterance.lang = 'zh-CN'
      activeUtterance.rate = 1
      activeUtterance.onend = next
      activeUtterance.onerror = event => {
        if (current !== generation || ['canceled', 'interrupted'].includes(event.error)) return
        stop()
        onError(event)
      }
      synthesis.speak(activeUtterance)
    }
    next()
  }
  function togglePause() {
    if (state === 'paused') {
      setState('playing')
      synthesis.resume()
      const next = pendingNext
      pendingNext = null
      next?.()
    } else if (state === 'playing') {
      setState('paused')
      synthesis.pause()
    }
  }
  return { start, stop, togglePause }
}
