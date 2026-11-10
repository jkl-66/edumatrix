import assert from 'node:assert/strict'
import test from 'node:test'
import { speechChunks } from '../src/utils/spokenText.js'
import { encodeWav } from '../src/utils/recordingAudio.js'
import { createSpeechPlayback } from '../src/utils/speechPlayback.js'

test('sentence completion while paused waits for explicit resume and ignores callbacks after stop', () => {
  let state = 'idle'
  const spoken = []
  const synthesis = {
    speak: utterance => spoken.push(utterance),
    pause() {}, resume() {}, cancel() {},
  }
  const playback = createSpeechPlayback({
    synthesis, createUtterance: text => ({ text }),
    onState: value => { state = value }, onError: assert.fail,
  })
  playback.start(['第一句。', '第二句。', '第三句。'])
  playback.togglePause()
  spoken[0].onend()
  assert.equal(state, 'paused')
  assert.equal(spoken.length, 1)
  playback.togglePause()
  assert.equal(state, 'playing')
  assert.equal(spoken[1].text, '第二句。')
  playback.stop()
  spoken[1].onend()
  assert.equal(state, 'idle')
  assert.equal(spoken.length, 2)
  playback.start(['新回答。'])
  spoken[0].onend()
  assert.equal(spoken.length, 3)
  assert.equal(spoken[2].text, '新回答。')
})

test('read-aloud keeps long teaching text while skipping code markup and link targets', () => {
  const prose = '决策树把样本按条件分组。'.repeat(80)
  const chunks = speechChunks('# 讲解\n' + prose + '\n```python\nprint("debug")\n```\n[教材](https://example.com)')
  assert.ok(chunks.length > 1)
  assert.ok(chunks.every(chunk => chunk.length <= 151))
  assert.equal(chunks.join('').split('决策树把样本按条件分组。').length - 1, 80)
  assert.ok(!chunks.join('').includes('debug'))
  assert.ok(!chunks.join('').includes('https://'))
  assert.ok(chunks.join('').includes('教材'))
})

test('recorded samples produce actual mono PCM WAV for existing transcription', async () => {
  const blob = encodeWav(new Float32Array([-1, 0, 1]), 16000)
  const bytes = await blob.arrayBuffer()
  const view = new DataView(bytes)
  assert.equal(new TextDecoder().decode(bytes.slice(0, 4)), 'RIFF')
  assert.equal(view.getUint16(22, true), 1)
  assert.equal(view.getUint32(24, true), 16000)
  assert.equal(view.getUint32(40, true), 6)
  assert.equal(view.getInt16(44, true), -32768)
  assert.equal(view.getInt16(48, true), 32767)
})
