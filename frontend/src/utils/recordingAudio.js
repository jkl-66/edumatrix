function writeString(view, offset, text) {
  for (let index = 0; index < text.length; index += 1) view.setUint8(offset + index, text.charCodeAt(index))
}

export function encodeWav(samples, sampleRate = 16000) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)
  writeString(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(view, 8, 'WAVE')
  writeString(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)
  let offset = 44
  for (const sample of samples) {
    const value = Math.max(-1, Math.min(1, sample))
    view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true)
    offset += 2
  }
  return new Blob([buffer], { type: 'audio/wav' })
}

export async function recorderBlobToWav(blob) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext
  if (!AudioContextClass) throw new Error('当前浏览器不支持本地音频解码')
  const context = new AudioContextClass()
  try {
    const decoded = await context.decodeAudioData(await blob.arrayBuffer())
    const targetRate = 16000
    const outputLength = Math.max(1, Math.round(decoded.duration * targetRate))
    const samples = new Float32Array(outputLength)
    for (let index = 0; index < outputLength; index += 1) {
      const sourceIndex = Math.min(decoded.length - 1, Math.floor(index * decoded.sampleRate / targetRate))
      let mixed = 0
      for (let channel = 0; channel < decoded.numberOfChannels; channel += 1) mixed += decoded.getChannelData(channel)[sourceIndex]
      samples[index] = mixed / decoded.numberOfChannels
    }
    return encodeWav(samples, targetRate)
  } finally {
    await context.close()
  }
}

