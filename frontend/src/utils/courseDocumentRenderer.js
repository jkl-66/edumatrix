export const COURSE_DOCUMENT_RENDERER_VERSION = 'course-document-renderer-v4'

const CACHE_PREFIX = 'edumatrix.course-document.preview.'
const BLOCK_START_RE = /^\s*(#{1,6})\s+(.+?)\s*#*\s*$/
const FENCE_START_RE = /^\s*```([A-Za-z0-9_+#.-]*)\s*$/
const LIST_RE = /^\s*(?:[-*+]\s+|\d+[.)]\s+)/
const TABLE_DIVIDER_RE = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/
const CALLOUT_RE = /^\s*>\s*\[!(NOTE|TIP|WARNING|IMPORTANT|CAUTION)\]\s*(.*)$/i
const ADMONITION_RE = /^\s*!!!\s*([A-Za-z-]+)?\s*(.*)$/i

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function safeUrl(value, image = false) {
  const raw = String(value || '').trim()
  if (!image && raw.startsWith('#')) return `#course-anchor-${encodeURIComponent(raw.slice(1))}`
  if (/^(https?:\/\/|\/|data:image\/)/i.test(raw) && !/^(?:javascript|vbscript|data:text)/i.test(raw)) {
    return raw
  }
  return image ? '' : '#'
}

function slug(value, index) {
  const normalized = String(value || '').toLocaleLowerCase().trim().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '')
  return `course-section-${normalized || index}`
}

function sourceSpan(text, start, end, inner = escapeHtml(text), className = '') {
  if (end <= start) return inner
  const classes = className ? ` class="${className}"` : ''
  return `<span${classes} data-source-start="${start}" data-source-end="${end}">${inner}</span>`
}

const TECHNICAL_META_LINE_RE = /^(?:课程|来源|来源角色|上游来源|上游仓库|上游文件|许可标识|许可证|解析状态|解析器|文档版本|固定版本|课程角色|改编说明|转换说明|版本|source|source role|repository|file|license|parser|version|hash)\s*[:：]/i

function isTechnicalMetadataQuote(block) {
  if (block.kind !== 'quote') return false
  const text = block.lines
    .map((record) => record.text)
    .join('\n')
    .replace(/\\n\s*>\s*/g, '\n> ')
  const lines = text
    .split('\n')
    .map((line) => line.replace(/^\s*>\s?/, '').trim())
    .filter(Boolean)
  return lines.length > 0 && lines.every((line) => TECHNICAL_META_LINE_RE.test(line))
}

function isNonTeachingMarkerLine(text) {
  return /^(?:\s*<!--.*-->\s*|\s*:label:`[^`]+`\s*|\s*:cite:`[^`]+`\s*|\s*<\/?(?:table|thead|tbody|tr|td)\b[^>]*>\s*)$/i.test(String(text || ''))
}

function htmlAttribute(tag, name) {
  const match = tag.match(new RegExp(`(?:^|\\s)${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s"'=<>]+))`, 'i'))
  if (!match) return null
  const value = match[1] ?? match[2] ?? match[3]
  const quoted = match[1] !== undefined || match[2] !== undefined
  return { value, start: match.index + match[0].length - value.length - (quoted ? 1 : 0) }
}

function linkHtml(href, inner) {
  const external = href.startsWith('#') ? '' : ' target="_blank" rel="noopener noreferrer"'
  return `<a class="course-link" href="${escapeHtml(href)}"${external}>${inner}</a>`
}

function normalizeLineEnd(value) {
  return String(value || '').replace(/\r\n?/g, '\n')
}

function lineRecords(markdown) {
  const source = normalizeLineEnd(markdown)
  const records = []
  let cursor = 0
  source.split('\n').forEach((text, index, lines) => {
    const start = cursor
    const end = start + text.length
    records.push({ index, text, start, end, newlineEnd: end + (index < lines.length - 1 ? 1 : 0) })
    cursor = end + (index < lines.length - 1 ? 1 : 0)
  })
  return { source, records }
}

function splitTableRow(record) {
  let cursor = record.text.search(/\S/)
  if (record.text[cursor] === '|') cursor += 1
  const end = record.text.trimEnd().length - (record.text.trimEnd().endsWith('|') ? 1 : 0)
  return record.text.slice(cursor, end).split('|').map((cell) => {
    const result = { text: cell.trim(), start: record.start + cursor + cell.search(/\S|$/) }
    cursor += cell.length + 1
    return result
  })
}

function inlineTokens(value, sourceStart, search) {
  const text = String(value || '')
  const matches = Array.isArray(search?.matches) ? search.matches : []
  const current = Number.isFinite(search?.current) ? search.current : -1
  const queryLength = String(search?.query || '').length

  const renderPlain = (chunk, offset) => {
    if (!chunk) return ''
    const absoluteStart = sourceStart + offset
    if (!queryLength) return sourceSpan(chunk, absoluteStart, absoluteStart + chunk.length)
    const parts = []
    let cursor = 0
    matches.forEach((match, matchIndex) => {
      const local = match - absoluteStart
      if (local < cursor || local >= chunk.length || local + queryLength > chunk.length) return
      if (local > cursor) parts.push(sourceSpan(chunk.slice(cursor, local), absoluteStart + cursor, absoluteStart + local))
      const hit = chunk.slice(local, local + queryLength)
      const hitClass = matchIndex === current ? 'course-search-hit course-search-hit--current' : 'course-search-hit'
      parts.push(sourceSpan(hit, match, match + queryLength, escapeHtml(hit), hitClass))
      cursor = local + queryLength
    })
    if (cursor < chunk.length) parts.push(sourceSpan(chunk.slice(cursor), absoluteStart + cursor, absoluteStart + chunk.length))
    return parts.join('')
  }

  const output = []
  let cursor = 0
  const nextSpecial = () => {
    const candidates = [
      text.indexOf('**', cursor), text.indexOf('`', cursor), text.indexOf('![', cursor),
      text.indexOf('[', cursor), text.indexOf('$', cursor), text.indexOf('~~', cursor),
      text.indexOf('*', cursor), text.indexOf('<', cursor),
    ].filter((entry) => entry >= 0)
    return candidates.length ? Math.min(...candidates) : -1
  }

  while (cursor < text.length) {
    const special = nextSpecial()
    if (special < 0) {
      output.push(renderPlain(text.slice(cursor), cursor))
      break
    }
    if (special > cursor) output.push(renderPlain(text.slice(cursor, special), cursor))

    if (text.startsWith('**', special)) {
      const close = text.indexOf('**', special + 2)
      if (close > special + 2) {
        const inner = text.slice(special + 2, close)
        output.push(`<strong>${sourceSpan(inner, sourceStart + special + 2, sourceStart + close)}</strong>`)
        cursor = close + 2
        continue
      }
    }
    if (text.startsWith('~~', special)) {
      const close = text.indexOf('~~', special + 2)
      if (close > special + 2) {
        const inner = text.slice(special + 2, close)
        output.push(`<del>${sourceSpan(inner, sourceStart + special + 2, sourceStart + close)}</del>`)
        cursor = close + 2
        continue
      }
    }
    if (text[special] === '`') {
      const close = text.indexOf('`', special + 1)
      if (close > special + 1) {
        const inner = text.slice(special + 1, close)
        output.push(`<code class="course-inline-code">${sourceSpan(inner, sourceStart + special + 1, sourceStart + close)}</code>`)
        cursor = close + 1
        continue
      }
    }
    if (text[special] === '<') {
      const presentationTag = text.slice(special).match(/^<\/?(?:u|sub|sup|br)\s*>/i)
      if (presentationTag) {
        output.push(presentationTag[0].toLowerCase())
        cursor = special + presentationTag[0].length
        continue
      }
      const anchor = text.slice(special).match(/^<a\b[^>]*>([\s\S]*?)<\/a\s*>/i)
      if (anchor) {
        const opening = anchor[0].slice(0, anchor[0].indexOf('>') + 1)
        const body = anchor[1]
        const bodyStart = sourceStart + special + opening.length
        const href = htmlAttribute(opening, 'href')
        const marker = htmlAttribute(opening, 'name') || htmlAttribute(opening, 'id')
        if (marker) output.push(`<span id="course-anchor-${escapeHtml(marker.value)}" aria-hidden="true"></span>`)
        if (body.trim()) {
          const badge = body.match(/^\s*(<img\b[^>]*>)\s*$/i)
          const alt = badge && htmlAttribute(badge[1], 'alt')
          // Notebook badges become readable links; source offsets still refer
          // to the original alt text, not a rewritten copy of the document.
          const inner = alt
            ? renderPlain(alt.value, special + opening.length + body.indexOf('<') + alt.start)
            : inlineTokens(body, bodyStart, search)
          output.push(href ? linkHtml(safeUrl(href.value), inner) : inner)
        }
        cursor = special + anchor[0].length
        continue
      }
    }
    if (text.startsWith('![', special)) {
      const closeLabel = text.indexOf(']', special + 2)
      const closeUrl = closeLabel >= 0 ? text.indexOf(')', closeLabel + 1) : -1
      if (closeLabel > special + 2 && closeUrl > closeLabel) {
        const alt = text.slice(special + 2, closeLabel)
        const url = text.slice(closeLabel + 2, closeUrl)
        const safe = safeUrl(url, true)
        if (safe) {
          output.push(`<figure class="course-figure"><img src="${escapeHtml(safe)}" alt="${escapeHtml(alt)}" loading="lazy" /></figure>`)
        } else {
          output.push(sourceSpan(alt, sourceStart + special + 2, sourceStart + closeLabel, escapeHtml(alt), 'course-image-missing'))
        }
        cursor = closeUrl + 1
        continue
      }
    }
    if (text[special] === '[') {
      const closeLabel = text.indexOf(']', special + 1)
      const closeUrl = closeLabel >= 0 ? text.indexOf(')', closeLabel + 1) : -1
      if (closeLabel > special + 1 && closeUrl > closeLabel && text[closeLabel + 1] === '(') {
        const label = text.slice(special + 1, closeLabel)
        const href = safeUrl(text.slice(closeLabel + 2, closeUrl))
        output.push(linkHtml(href, inlineTokens(label, sourceStart + special + 1, search)))
        cursor = closeUrl + 1
        continue
      }
    }
    if (text[special] === '$') {
      const double = text.startsWith('$$', special)
      const markerLength = double ? 2 : 1
      const close = text.indexOf(double ? '$$' : '$', special + markerLength)
      if (close > special + markerLength) {
        const math = text.slice(special + markerLength, close)
        output.push(`<span class="course-inline-math" data-math="${escapeHtml(math)}" aria-label="${escapeHtml(math)}">${sourceSpan(math, sourceStart + special + markerLength, sourceStart + close, escapeHtml(math))}</span>`)
        cursor = close + markerLength
        continue
      }
    }
    if (text[special] === '*') {
      const close = text.indexOf('*', special + 1)
      if (close > special + 1) {
        const inner = text.slice(special + 1, close)
        output.push(`<em>${sourceSpan(inner, sourceStart + special + 1, sourceStart + close)}</em>`)
        cursor = close + 1
        continue
      }
    }
    output.push(renderPlain(text[special], special))
    cursor = special + 1
  }
  return output.join('')
}

function searchMatches(source, query) {
  const needle = String(query || '').trim().toLocaleLowerCase()
  if (!needle) return []
  const haystack = String(source || '').toLocaleLowerCase()
  const result = []
  let cursor = 0
  while (cursor < haystack.length && result.length < 500) {
    const index = haystack.indexOf(needle, cursor)
    if (index < 0) break
    result.push(index)
    cursor = index + Math.max(needle.length, 1)
  }
  return result
}

function blockRecords(markdown) {
  const { source, records } = lineRecords(markdown)
  const blocks = []
  let cursor = 0
  const push = (kind, startIndex, endIndex, extra = {}) => {
    const first = records[startIndex]
    const last = records[endIndex]
    if (!first || !last) return
    blocks.push({ kind, start: first.start, end: last.end, lines: records.slice(startIndex, endIndex + 1), ...extra })
  }
  const isBoundary = (line, index) => {
    if (!line.trim()) return true
    if (BLOCK_START_RE.test(line) || FENCE_START_RE.test(line) || /^\s*\$\$/.test(line) || LIST_RE.test(line) || /^\s*>/.test(line) || ADMONITION_RE.test(line)) return true
    if (index + 1 < records.length && line.includes('|') && TABLE_DIVIDER_RE.test(records[index + 1].text)) return true
    return false
  }

  while (cursor < records.length) {
    const line = records[cursor].text
    if (!line.trim()) { cursor += 1; continue }
    const heading = line.match(BLOCK_START_RE)
    if (heading) { push('heading', cursor, cursor, { level: Math.min(heading[1].length, 4), title: heading[2], titleStart: records[cursor].start + line.indexOf(heading[2]) }); cursor += 1; continue }
    const fence = line.match(FENCE_START_RE)
    if (fence) {
      let end = cursor + 1
      while (end < records.length && !/^\s*```\s*$/.test(records[end].text)) end += 1
      const contentStart = cursor + 1 < records.length ? records[cursor + 1].start : records[cursor].end
      const contentEnd = end < records.length ? records[end].start : (records[end - 1]?.end || contentStart)
      push('code', cursor, Math.min(end, records.length - 1), { lang: fence[1] || '', content: source.slice(contentStart, contentEnd).replace(/\n$/, ''), contentStart })
      cursor = Math.min(end + 1, records.length)
      continue
    }
    if (/^\s*\$\$/.test(line)) {
      let end = cursor
      if (!/^\s*\$\$.*\$\$\s*$/.test(line)) {
        end = cursor + 1
        while (end < records.length && !/\$\$\s*$/.test(records[end].text)) end += 1
      }
      const contentStart = records[cursor].start + line.indexOf('$$') + 2
      const contentEnd = end === cursor ? records[cursor].end - 2 : records[end].start
      push('math', cursor, Math.min(end, records.length - 1), { content: source.slice(contentStart, contentEnd).replace(/^\n|\n$/g, ''), contentStart })
      cursor = Math.min(end + 1, records.length)
      continue
    }
    if (cursor + 1 < records.length && line.includes('|') && TABLE_DIVIDER_RE.test(records[cursor + 1].text)) {
      let end = cursor + 2
      while (end < records.length && records[end].text.includes('|') && records[end].text.trim()) end += 1
      push('table', cursor, end - 1, { header: splitTableRow(records[cursor]), rows: records.slice(cursor + 2, end).map(splitTableRow) })
      cursor = end
      continue
    }
    if (LIST_RE.test(line)) {
      let end = cursor + 1
      while (end < records.length && LIST_RE.test(records[end].text)) end += 1
      push('list', cursor, end - 1)
      cursor = end
      continue
    }
    if (/^\s*>/.test(line)) {
      let end = cursor + 1
      while (end < records.length && /^\s*>/.test(records[end].text)) end += 1
      const first = records[cursor].text.match(CALLOUT_RE)
      push(first ? 'callout' : 'quote', cursor, end - 1, { callout: first ? first[1].toLowerCase() : '', calloutTitle: first ? first[2] : '' })
      cursor = end
      continue
    }
    const admonition = line.match(ADMONITION_RE)
    if (admonition) {
      let end = cursor + 1
      while (end < records.length && records[end].text.trim() && !BLOCK_START_RE.test(records[end].text) && !FENCE_START_RE.test(records[end].text) && !LIST_RE.test(records[end].text) && !/^\s*>/.test(records[end].text) && !ADMONITION_RE.test(records[end].text)) end += 1
      push('callout', cursor, end - 1, { callout: admonition[1] || 'note', calloutTitle: admonition[2] || '' })
      cursor = end
      continue
    }
    let end = cursor + 1
    while (end < records.length && !isBoundary(records[end].text, end)) end += 1
    push('paragraph', cursor, end - 1)
    cursor = end
  }
  return { source, blocks }
}

function renderBlock(block, index, search) {
  const lineText = (record) => record.text
  if (block.kind === 'heading') {
    const title = String(block.title || '')
    const inner = inlineTokens(title, block.titleStart, search)
    return `<section class="lesson-block lesson-block--section"><h${block.level} id="${slug(title, index)}" class="course-heading course-heading--${block.level}" data-source-start="${block.start}" data-source-end="${block.end}">${inner}</h${block.level}></section>`
  }
  if (block.kind === 'code') {
    if (String(block.lang || '').toLocaleLowerCase() === 'mermaid') {
      return `<section class="lesson-block lesson-block--diagram" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">结构图示</div><div class="course-mermaid" data-mermaid-source="${encodeURIComponent(block.content)}"><div class="course-mermaid__canvas"></div><pre class="course-mermaid__source">${sourceSpan(block.content, block.contentStart, block.contentStart + block.content.length, escapeHtml(block.content))}</pre></div></section>`
    }
    return `<section class="lesson-block lesson-block--practice" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">代码实践</div><div class="course-code-heading"><span>${escapeHtml(block.lang || 'text')}</span><button type="button" data-copy-code="${index}">复制代码</button></div><pre class="course-code"><code>${sourceSpan(block.content, block.contentStart, block.contentStart + block.content.length, escapeHtml(block.content))}</code></pre></section>`
  }
  if (block.kind === 'math') {
    return `<section class="lesson-block lesson-block--formula" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">公式与推导</div><div class="course-math" data-math-block="${escapeHtml(block.content)}">${sourceSpan(block.content, block.contentStart, block.contentStart + block.content.length, escapeHtml(block.content))}</div></section>`
  }
  if (block.kind === 'table') {
    const header = block.header.map((cell) => `<th>${inlineTokens(cell.text, cell.start, search)}</th>`).join('')
    const rows = block.rows.map((row) => `<tr>${row.map((cell) => `<td>${inlineTokens(cell.text, cell.start, search)}</td>`).join('')}</tr>`).join('')
    return `<section class="lesson-block lesson-block--comparison" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">对比速查</div><div class="course-table-wrap"><table class="course-table"><thead><tr>${header}</tr></thead><tbody>${rows}</tbody></table></div></section>`
  }
  if (block.kind === 'list') {
    const ordered = /^\s*\d+[.)]\s+/.test(lineText(block.lines[0]))
    const tag = ordered ? 'ol' : 'ul'
    const items = block.lines.map((record) => {
      const match = record.text.match(/^\s*(?:[-*+]\s+|\d+[.)]\s+)(.*)$/)
      const value = match ? match[1] : record.text
      const valueStart = record.start + Math.max(0, record.text.indexOf(value))
      return `<li>${inlineTokens(value, valueStart, search)}</li>`
    }).join('')
    return `<section class="lesson-block lesson-block--steps" data-source-start="${block.start}" data-source-end="${block.end}"><${tag} class="course-list">${items}</${tag}></section>`
  }
  if (block.kind === 'callout' || block.kind === 'quote') {
    if (isTechnicalMetadataQuote(block)) return ''
    const text = block.lines
      .map((record, lineIndex) => lineIndex === 0 && ADMONITION_RE.test(record.text)
        ? record.text.replace(ADMONITION_RE, '').trim()
        : record.text.replace(/^\s*>\s?/, ''))
      .join('\n')
      .trim()
    if (!text) return ''
    const textStart = block.start + block.lines[0].text.indexOf('>') + 1
    const label = block.callout ? block.callout.toUpperCase() : '提示'
    return `<aside class="lesson-block lesson-block--callout lesson-callout--${escapeHtml(block.callout || 'note')}" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">${escapeHtml(label)}</div><p>${inlineTokens(text, textStart, search)}</p></aside>`
  }
  const teachingLines = block.lines.filter((record) => !isNonTeachingMarkerLine(record.text))
  if (!teachingLines.length) return ''
  const text = teachingLines.map(lineText).join('\n')
  const titleish = /(?:小结|总结|要点|takeaway|summary)/i.test(text)
  const inline = teachingLines.map((record) => inlineTokens(record.text, record.start, search)).join('\n')
  if (teachingLines.every((record) => /^(?:\s*<a\b[^>]*>\s*<\/a>\s*)+$/i.test(record.text))) return inline
  return `<section class="lesson-block ${titleish ? 'lesson-block--summary' : 'lesson-block--explanation'}" data-source-start="${block.start}" data-source-end="${block.end}"><p>${inline}</p></section>`
}

export function renderCourseDocument(markdown, { query = '', currentMatch = 0 } = {}) {
  const parsed = blockRecords(markdown)
  const matches = searchMatches(parsed.source, query)
  const search = { source: parsed.source, query: String(query || '').trim(), matches, current: currentMatch }
  const html = parsed.blocks.map((block, index) => renderBlock(block, index, search)).join('')
  const blocks = parsed.blocks.map((block, index) => ({
    index,
    kind: block.kind,
    start: block.start,
    end: block.end,
    title: block.title || '',
    label: block.kind === 'code' ? '代码实践' : block.kind === 'math' ? '公式与推导' : block.kind === 'table' ? '对比速查' : block.kind === 'callout' ? '提示' : block.kind === 'paragraph' ? '概念说明' : '',
  }))
  return { html, blocks, plainText: parsed.source, matchCount: matches.length, rendererVersion: COURSE_DOCUMENT_RENDERER_VERSION }
}

export function cacheKey(documentId, documentVersion) {
  return `${CACHE_PREFIX}${String(documentId || 'document')}.${String(documentVersion || 'unknown')}.${COURSE_DOCUMENT_RENDERER_VERSION}`
}

export function readCachedCourseDocument(key) {
  try {
    const raw = window.localStorage.getItem(key)
    if (!raw) return null
    const value = JSON.parse(raw)
    return value?.rendererVersion === COURSE_DOCUMENT_RENDERER_VERSION ? value : null
  } catch {
    return null
  }
}

export function writeCachedCourseDocument(key, value) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
    return true
  } catch {
    return false
  }
}

export function clearCourseDocumentCache(key) {
  try { window.localStorage.removeItem(key) } catch {}
}
