// API source ranges count Unicode code points (Python strings); DOM ranges
// and JavaScript search/slice count UTF-16 code units. Convert at that boundary.
export function sourceTextMap(value, { normalizeLineEnd = false } = {}) {
  const source = String(value || '')
  const displayToSource = [0]
  const sourceToDisplay = [0]
  const parts = []
  let sourceOffset = 0
  let displayOffset = 0
  for (let index = 0; index < source.length;) {
    const character = String.fromCodePoint(source.codePointAt(index))
    const newline = normalizeLineEnd && character === '\r'
    const consumed = newline && source[index + 1] === '\n' ? 2 : 1
    const displayed = newline ? '\n' : character
    parts.push(displayed)
    for (let unit = 1; unit < displayed.length; unit += 1) displayToSource.push(sourceOffset)
    displayToSource.push(sourceOffset + consumed)
    for (let point = 1; point < consumed; point += 1) sourceToDisplay.push(displayOffset)
    displayOffset += displayed.length
    sourceOffset += consumed
    sourceToDisplay.push(displayOffset)
    index += consumed === 2 ? 2 : character.length
  }
  return { text: parts.join(''), displayToSource, sourceToDisplay }
}

export function sourceTextLength(value) {
  return Array.from(String(value || '')).length
}

export function trimSourceTextRange(value, start, end) {
  const source = Array.from(String(value || ''))
  let left = Math.max(0, Math.min(source.length, Number(start) || 0))
  let right = Math.max(left, Math.min(source.length, Number(end) || 0))
  while (left < right && /\s/.test(source[left])) left += 1
  while (right > left && /\s/.test(source[right - 1])) right -= 1
  return { start: left, end: right, quote: source.slice(left, right).join('') }
}
