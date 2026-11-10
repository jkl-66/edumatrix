import { sourceTextMap } from './sourceTextOffsets.js'

export const COURSE_DOCUMENT_RENDERER_VERSION = 'course-document-renderer-v12'

export function renderCourseMath(root, renderer) {
  if (!root || !renderer) return
  root.querySelectorAll('.course-inline-math[data-math], .course-math[data-math-block]').forEach(element => {
    if (element.dataset.rendered === 'true' || element.querySelector('.course-search-hit')) return
    const math = element.dataset.math || element.dataset.mathBlock || element.textContent || ''
    const source = element.querySelector('[data-source-start][data-source-end]')
    if (source) {
      element.dataset.sourceStart = source.dataset.sourceStart
      element.dataset.sourceEnd = source.dataset.sourceEnd
    }
    try {
      element.innerHTML = renderer.renderToString(math, { displayMode: element.classList.contains('course-math'), throwOnError: false, trust: false })
      element.dataset.rendered = 'true'
      if (source) element.dataset.sourceAtomic = 'true'
    } catch {}
  })
}

const CACHE_PREFIX = 'edumatrix.course-document.preview.'
const BLOCK_START_RE = /^\s*(#{1,6})\s+(.+?)\s*#*\s*$/
const FENCE_START_RE = /^\s*(`{3,}|~{3,})([^\n]*)$/
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
  if (!image && raw.startsWith('#')) {
    let fragment = raw.slice(1)
    try { fragment = decodeURIComponent(fragment) } catch {}
    return `#course-anchor-${encodeURIComponent(fragment)}`
  }
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
  return /^(?:\s*<!--.*-->\s*|\s*:(?:label|eqlabel|width):`[^`]+`\s*|\s*:end_tab:\s*|\s*<\/?(?:table|thead|tbody|tr|td)\b[^>]*>\s*|\s*---\s*(?:Page|幻灯片)\s+\d+\s*---\s*|\s*\[OCR 第 \d+ 页 · [a-z_]+\]\s*|\s*\[第 \d+ 页图片内容\]\s*)$/i.test(String(text || ''))
}

function htmlAttribute(tag, name) {
  const match = tag.match(new RegExp(`(?:^|\\s)${name}\\s*=\\s*(?:"([^"]*)"|'([^']*)'|([^\\s"'=<>]+))`, 'i'))
  if (!match) return null
  const value = match[1] ?? match[2] ?? match[3]
  const quoted = match[1] !== undefined || match[2] !== undefined
  return { value, start: match.index + match[0].length - value.length - (quoted ? 1 : 0) }
}

function linkHtml(href, inner) {
  if (href === '#') return inner
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

function textWithSearch(chunk, sourceStart, search) {
  const matches = Array.isArray(search?.matches) ? search.matches : []
  const current = Number.isFinite(search?.current) ? search.current : -1
  const queryLength = String(search?.query || '').length
  if (!chunk) return ''
  const absoluteStart = sourceStart
  if (!queryLength) return sourceSpan(chunk, absoluteStart, absoluteStart + chunk.length)
  const parts = []
  let cursor = 0
  // Jump straight to this span's matches; a whole textbook can contain many
  // thousands. Scanning every match for every paragraph is quadratic work.
  let low = 0
  let high = matches.length
  while (low < high) {
    const middle = (low + high) >>> 1
    if (matches[middle] < absoluteStart) low = middle + 1
    else high = middle
  }
  for (let matchIndex = low; matchIndex < matches.length; matchIndex += 1) {
    const match = matches[matchIndex]
    const local = match - absoluteStart
    if (local >= chunk.length) break
    if (local < cursor || local + queryLength > chunk.length) continue
    if (local > cursor) parts.push(sourceSpan(chunk.slice(cursor, local), absoluteStart + cursor, absoluteStart + local))
    const hit = chunk.slice(local, local + queryLength)
    const hitClass = matchIndex === current ? 'course-search-hit course-search-hit--current' : 'course-search-hit'
    parts.push(sourceSpan(hit, match, match + queryLength, escapeHtml(hit), hitClass))
    cursor = local + queryLength
  }
  if (cursor < chunk.length) parts.push(sourceSpan(chunk.slice(cursor), absoluteStart + cursor, absoluteStart + chunk.length))
  return parts.join('')
}

function publicationReferences(parsed) {
  const references = new Map()
  const anchors = new Map()
  const occurrences = new Map()
  for (const block of parsed.blocks) {
    if (block.kind === 'code') continue
    for (const { text } of block.lines) {
      const marker = text.match(/^\s*:(?:label|eqlabel):`([^`]+)`\s*$/)
      if (marker) occurrences.set(marker[1], (occurrences.get(marker[1]) || 0) + 1)
    }
  }
  let previous = null
  parsed.blocks.forEach((block, index) => {
    if (block.kind === 'code') { previous = { block, index }; return }
    const lines = block.lines.map(record => record.text)
    const visible = lines.filter(line => !isNonTeachingMarkerLine(line)).join('\n').trim()
    for (const line of lines) {
      const marker = line.match(/^\s*:(label|eqlabel):`([^`]+)`\s*$/)
      if (!marker) continue
      const image = visible.match(/!\[([^\]]+)\]\([^\n]+\)/)
      const target = image ? { block, index } : previous
      if (!target) continue
      const targetText = target.block.lines.map(record => record.text).join('\n')
      const targetImage = image || targetText.match(/!\[([^\]]+)\]\([^\n]+\)/)
      const title = target.block.kind === 'heading' ? target.block.title
        : targetImage ? targetImage[1] : target.block.kind === 'math' ? '公式' : ''
      // Aggregated chapters may reuse labels. Do not invent which chapter
      // an ambiguous reference means; keep an original-source cue instead.
      if (!title || occurrences.get(marker[2]) !== 1) continue
      const id = `course-anchor-${encodeURIComponent(marker[2])}`
      references.set(marker[2], { id, title: title.replace(/[*`]/g, '') })
      anchors.set(target.index, [...(anchors.get(target.index) || []), id])
    }
    if (visible) previous = { block, index }
  })
  const headingCounts = new Map()
  const ids = new Set(Array.from(anchors.values()).flat())
  parsed.blocks.forEach((block, index) => {
    if (block.kind !== 'heading') return
    // Keep normal Markdown heading links usable alongside textbook labels.
    const base = block.title.toLowerCase().trim().replace(/[^\p{L}\p{N}\s_-]/gu, '').replace(/\s+/g, '-')
    const count = headingCounts.get(base) || 0
    headingCounts.set(base, count + 1)
    const id = `course-anchor-${encodeURIComponent(base + (count ? `-${count}` : ''))}`
    if (base && !ids.has(id)) {
      anchors.set(index, [...(anchors.get(index) || []), id])
      ids.add(id)
    }
  })
  return { references, anchors }
}

function publicationReferenceHtml(marker, start, search) {
  const [raw, kind, key] = marker
  const target = search.publication.references.get(key)
  let label = target?.title
  if (kind === 'cite') {
    label = key.split(/\s*[,;]\s*/).map(value => {
      const citation = value.match(/^([A-Za-z][A-Za-z-]*)(?:\.[A-Za-z-]+)*\.(\d{4}[a-z]?)$/)
      return citation ? `${citation[1]}${value.split('.').length > 2 ? '等' : ''}，${citation[2]}` : '参考文献'
    }).join('；')
    label = `（${label}）`
  }
  label ||= kind === 'eqref' ? '原文公式' : /^fig[_-]/.test(key) ? '原文图示' : '原文相关章节'
  search.readingReplacements.push({ start, end: start + raw.length, label })
  // A generated human label represents the complete original directive.
  // Selection must use that range atomically, not count label characters.
  const span = `<span data-source-start="${start}" data-source-end="${start + raw.length}" data-source-atomic="true">${escapeHtml(label)}</span>`
  return target ? linkHtml(`#${target.id}`, span) : `<span title="请在资料原文中查看对应内容">${span}</span>`
}

function linkDestinationEnd(text, open) {
  if (text[open] !== '(') return -1
  let depth = 1
  for (let index = open + 1; index < text.length; index += 1) {
    if (text[index] === '\\') { index += 1; continue }
    if (text[index] === '(') depth += 1
    if (text[index] === ')' && --depth === 0) return index
    // Some Chinese textbook source uses a full-width closing delimiter.
    // End the URL there; do not swallow the following author/citation text.
    if (text[index] === '）' && depth === 1) return index
  }
  return -1
}

function inlineTokens(value, sourceStart, search) {
  const text = String(value || '')
  const renderPlain = (chunk, offset) => textWithSearch(chunk, sourceStart + offset, search)

  const output = []
  let cursor = 0
  const nextSpecial = () => {
    const candidates = [
      text.indexOf('**', cursor), text.indexOf('`', cursor), text.indexOf('![', cursor),
      text.indexOf('[', cursor), text.indexOf('$', cursor), text.indexOf('~~', cursor),
      text.indexOf('*', cursor), text.indexOf('<', cursor),
      text.indexOf('\\(', cursor),
      ...[':numref:', ':eqref:', ':ref:', ':cite:'].map(marker => text.indexOf(marker, cursor)),
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

    const publicationMarker = text.slice(special).match(/^:(numref|eqref|ref|cite):`([^`]+)`/)
    if (publicationMarker) {
      output.push(publicationReferenceHtml(publicationMarker, sourceStart + special, search))
      cursor = special + publicationMarker[0].length
      continue
    }

    if (text.startsWith('\\(', special)) {
      const close = text.indexOf('\\)', special + 2)
      if (close > special + 2) {
        const math = text.slice(special + 2, close)
        output.push(`<span class="course-inline-math" data-math="${escapeHtml(math)}" aria-label="${escapeHtml(math)}">${textWithSearch(math, sourceStart + special + 2, search)}</span>`)
        cursor = close + 2
        continue
      }
    }

    if (text.startsWith('**', special)) {
      const close = text.indexOf('**', special + 2)
      if (close > special + 2) {
        const inner = text.slice(special + 2, close)
        output.push(`<strong>${textWithSearch(inner, sourceStart + special + 2, search)}</strong>`)
        cursor = close + 2
        continue
      }
    }
    if (text.startsWith('~~', special)) {
      const close = text.indexOf('~~', special + 2)
      if (close > special + 2) {
        const inner = text.slice(special + 2, close)
        output.push(`<del>${textWithSearch(inner, sourceStart + special + 2, search)}</del>`)
        cursor = close + 2
        continue
      }
    }
    if (text[special] === '`') {
      const close = text.indexOf('`', special + 1)
      if (close > special + 1) {
        const inner = text.slice(special + 1, close)
        output.push(`<code class="course-inline-code">${textWithSearch(inner, sourceStart + special + 1, search)}</code>`)
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
        if (marker) output.push(`<span id="course-anchor-${escapeHtml(encodeURIComponent(marker.value))}" aria-hidden="true"></span>`)
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
      const closeUrl = closeLabel >= 0 ? linkDestinationEnd(text, closeLabel + 1) : -1
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
      const closeUrl = closeLabel >= 0 ? linkDestinationEnd(text, closeLabel + 1) : -1
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
        output.push(`<span class="course-inline-math" data-math="${escapeHtml(math)}" aria-label="${escapeHtml(math)}">${textWithSearch(math, sourceStart + special + markerLength, search)}</span>`)
        cursor = close + markerLength
        continue
      }
    }
    if (text[special] === '*') {
      const close = text.indexOf('*', special + 1)
      if (close > special + 1) {
        const inner = text.slice(special + 1, close)
        output.push(`<em>${textWithSearch(inner, sourceStart + special + 1, search)}</em>`)
        cursor = close + 1
        continue
      }
    }
    output.push(renderPlain(text[special], special))
    cursor = special + 1
  }
  return output.join('')
}

export function documentSearchMatches(source, query) {
  const needle = String(query || '').trim()
  if (!needle) return []
  // Case-folding the entire source can change its length (e.g. dotted I).
  // A literal Unicode-aware regex keeps indices in the untouched source.
  const literal = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return Array.from(String(source || '').matchAll(new RegExp(literal, 'giu')), match => match.index)
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
  const isQuoteStart = (line, index) => {
    if (!/^\s*>/.test(line)) return false
    const previous = records[index - 1]?.text || ''
    // Extracted prose can wrap a comparison onto a line beginning with >.
    // An ordinary quotation needs a paragraph boundary; an explicit callout
    // or a continuation of an existing quote remains unambiguous.
    return !previous.trim() || BLOCK_START_RE.test(previous) || /^\s*>/.test(previous) || CALLOUT_RE.test(line)
  }
  const isBoundary = (line, index) => {
    if (!line.trim()) return true
    if (BLOCK_START_RE.test(line) || FENCE_START_RE.test(line) || /^\s*(?:\$\$|\\\[)/.test(line) || LIST_RE.test(line) || isQuoteStart(line, index) || ADMONITION_RE.test(line)) return true
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
      const closingFence = new RegExp(`^\\s*${fence[1][0]}{${fence[1].length},}\\s*$`)
      while (end < records.length && !closingFence.test(records[end].text)) end += 1
      const contentStart = cursor + 1 < records.length ? records[cursor + 1].start : records[cursor].end
      const contentEnd = end < records.length ? records[end].start : (records[end - 1]?.end || contentStart)
      // D2L and other textbooks use {.python .input} attribute fences.
      const lang = fence[2].trim().replace(/^\{\s*\.?/, '').match(/^[A-Za-z0-9_+#.-]+/)?.[0] || ''
      push('code', cursor, Math.min(end, records.length - 1), { lang, content: source.slice(contentStart, contentEnd).replace(/\n$/, ''), contentStart })
      cursor = Math.min(end + 1, records.length)
      continue
    }
    if (/^\s*\\\[/.test(line)) {
      let end = cursor
      while (end < records.length && !/\\\]\s*$/.test(records[end].text)) end += 1
      if (end < records.length) {
        const afterMarker = records[cursor].start + line.indexOf('\\[') + 2
        const contentStart = source[afterMarker] === '\n' ? afterMarker + 1 : afterMarker
        const contentEnd = records[end].start + records[end].text.lastIndexOf('\\]')
        push('math', cursor, end, { content: source.slice(contentStart, contentEnd).replace(/\n$/, ''), contentStart })
        cursor = end + 1
        continue
      }
    }
    if (/^\s*\$\$/.test(line)) {
      let end = cursor
      if (!/^\s*\$\$.*\$\$\s*$/.test(line)) {
        end = cursor + 1
        while (end < records.length && !/\$\$\s*$/.test(records[end].text)) end += 1
      }
      const afterMarker = records[cursor].start + line.indexOf('$$') + 2
      const contentStart = source[afterMarker] === '\n' ? afterMarker + 1 : afterMarker
      const contentEnd = end < records.length
        ? records[end].start + records[end].text.lastIndexOf('$$')
        : source.length
      push('math', cursor, Math.min(end, records.length - 1), { content: source.slice(contentStart, contentEnd).replace(/\n$/, ''), contentStart })
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
    if (isQuoteStart(line, cursor)) {
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
      return `<section class="lesson-block lesson-block--diagram" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">结构图示</div><div class="course-mermaid" data-mermaid-source="${encodeURIComponent(block.content)}"><div class="course-mermaid__canvas"></div><pre class="course-mermaid__source">${textWithSearch(block.content, block.contentStart, search)}</pre></div></section>`
    }
    return `<section class="lesson-block lesson-block--practice" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">代码实践</div><div class="course-code-heading"><span>${escapeHtml(block.lang || 'text')}</span><button type="button" data-copy-code="${index}">复制代码</button></div><pre class="course-code"><code>${textWithSearch(block.content, block.contentStart, search)}</code></pre></section>`
  }
  if (block.kind === 'math') {
    return `<section class="lesson-block lesson-block--formula" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">公式与推导</div><div class="course-math" data-math-block="${escapeHtml(block.content)}">${textWithSearch(block.content, block.contentStart, search)}</div></section>`
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
    const inline = block.lines.map((record, lineIndex) => {
      const marker = lineIndex === 0 && (record.text.match(ADMONITION_RE) || record.text.match(CALLOUT_RE))
      const prefix = marker ? record.text.length - marker[2].length : (record.text.match(/^\s*>\s?/)?.[0].length || 0)
      return inlineTokens(record.text.slice(prefix), record.start + prefix, search)
    }).join('\n')
    if (!inline.trim()) return ''
    const labels = { note: '笔记', tip: '提示', warning: '注意', important: '要点', caution: '提醒' }
    const label = labels[block.callout] || '提示'
    return `<aside class="lesson-block lesson-block--callout lesson-callout--${escapeHtml(block.callout || 'note')}" data-source-start="${block.start}" data-source-end="${block.end}"><div class="lesson-block__label">${escapeHtml(label)}</div><p>${inline}</p></aside>`
  }
  const teachingLines = block.lines.filter((record) => !isNonTeachingMarkerLine(record.text))
  if (!teachingLines.length) return ''
  const text = teachingLines.map(lineText).join('\n')
  const titleish = /(?:小结|总结|要点|takeaway|summary)/i.test(text)
  const inline = teachingLines.map((record) => {
    const framework = record.text.match(/^\s*:begin_tab:`([^`]+)`\s*$/)
    if (framework) {
      const names = { pytorch: 'PyTorch', tensorflow: 'TensorFlow', mxnet: 'MXNet', paddle: 'PaddlePaddle' }
      const title = framework[1].split(',').map(name => names[name.trim().toLowerCase()] || name.trim()).join(' / ')
      search.readingReplacements.push({ start: record.start, end: record.end, label: title })
      return `<strong data-source-start="${record.start}" data-source-end="${record.end}" data-source-atomic="true">${escapeHtml(title)}</strong>`
    }
    return inlineTokens(record.text, record.start, search)
  }).join('\n')
  if (teachingLines.every((record) => /^(?:\s*<a\b[^>]*>\s*<\/a>\s*)+$/i.test(record.text))) return inline
  return `<section class="lesson-block ${titleish ? 'lesson-block--summary' : 'lesson-block--explanation'}" data-source-start="${block.start}" data-source-end="${block.end}"><p>${inline}</p></section>`
}

export function renderCourseDocument(markdown, { query = '', currentMatch = 0, referenceDocument = '' } = {}) {
  const offsets = sourceTextMap(markdown, { normalizeLineEnd: true }).displayToSource
  const parsed = blockRecords(markdown)
  const matches = documentSearchMatches(parsed.source, query)
  const publication = publicationReferences(referenceDocument ? blockRecords(referenceDocument) : parsed)
  const search = { source: parsed.source, query: String(query || '').trim(), matches, current: currentMatch, publication, readingReplacements: [] }
  // Old bundled textbooks include a generated ingestion note, not a learning
  // objective. Hide only that exact wrapper; retain original source offsets.
  const isImportNote = block => block?.kind === 'paragraph'
    && /^围绕\s+AI-KP-\d+/u.test(block.lines.map(record => record.text).join('\n').trim())
    && /(?:正文保留上游章节结构|保留完整电子书页码标记)/u.test(block.lines.map(record => record.text).join('\n'))
  const hiddenBlocks = new Set(parsed.blocks.flatMap((block, index) => (
    isImportNote(block)
    || (block.kind === 'code' && block.lang.toLowerCase() === 'toc')
    || (block.kind === 'heading' && block.title === '本章学习目标' && isImportNote(parsed.blocks[index + 1]))
  ) ? [index] : []))
  const html = parsed.blocks.map((block, index) => {
    if (hiddenBlocks.has(index)) {
      search.readingReplacements.push({ start: block.start, end: block.end, label: '' })
      return ''
    }
    if (block.kind !== 'code') {
      for (const line of block.lines.filter(line => isNonTeachingMarkerLine(line.text))) {
        search.readingReplacements.push({ start: line.start, end: line.end, label: '' })
      }
    }
    const anchors = (referenceDocument ? [] : publication.anchors.get(index) || []).map(id => `<span id="${escapeHtml(id)}" aria-hidden="true"></span>`).join('')
    return anchors + renderBlock(block, index, search)
  }).join('').replace(/data-source-(start|end)="(\d+)"/g,
    (_, boundary, offset) => `data-source-${boundary}="${offsets[Number(offset)]}"`)
  const blocks = parsed.blocks.map((block, index) => ({
    index,
    kind: block.kind,
    start: offsets[block.start],
    end: offsets[block.end],
    title: block.title || '',
    label: block.kind === 'code' ? '代码实践' : block.kind === 'math' ? '公式与推导' : block.kind === 'table' ? '对比速查' : block.kind === 'callout' ? '提示' : block.kind === 'paragraph' ? '概念说明' : '',
  })).filter(block => !hiddenBlocks.has(block.index))
  // Excerpts and note drafts use the same resolved labels as the reading view.
  // Code and source offsets remain untouched; this is a display projection.
  let readingText = parsed.source
  for (const { start, end, label } of search.readingReplacements.sort((a, b) => b.start - a.start)) {
    readingText = readingText.slice(0, start) + label + readingText.slice(end)
  }
  return { html, blocks, plainText: parsed.source, readingText, matchCount: matches.length, rendererVersion: COURSE_DOCUMENT_RENDERER_VERSION }
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

export function sourceReferenceAtOffset(references, offset) {
  const matches = (references || []).filter(item => (
    item.char_start != null && item.char_end != null
    && Number(item.char_start) <= offset && Number(item.char_end) > offset
  ))
  // A whole-document locator must not mask a precise chapter or source block.
  matches.sort((a, b) => (
    (Number(a.char_end) - Number(a.char_start)) - (Number(b.char_end) - Number(b.char_start))
    || Number(a.location_kind === 'document') - Number(b.location_kind === 'document')
  ))
  return matches[0] || null
}
