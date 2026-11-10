import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { sourceReferenceAtOffset } from '../src/utils/courseDocumentRenderer.js'
import { sourceTextMap, sourceTextLength, trimSourceTextRange } from '../src/utils/sourceTextOffsets.js'

const knowledge = readFileSync(new URL('../src/views/Knowledge.vue', import.meta.url), 'utf8')
const reader = readFileSync(new URL('../src/views/KnowledgeDocumentReader.vue', import.meta.url), 'utf8')
const preview = readFileSync(new URL('../src/components/CourseDocumentPreview.vue', import.meta.url), 'utf8')
const ref = value => ({ value })

test('original webpage follows the current reading position across bundled source files', () => {
  const source = { url: 'https://github.com/example/course/tree/version', parts: [
    { url: 'https://github.com/example/course/blob/version/first.md', char_start: 20, char_end: 50 },
    { url: 'https://github.com/example/course/blob/version/last.md', char_start: 50, char_end: 100 },
    { url: 'https://github.com/example/course/blob/version/unmapped.md', char_start: null, char_end: null },
  ] }
  const code = reader.slice(reader.indexOf('const originalSourceUrl ='), reader.indexOf('function buildReaderPresentation('))
  const offset = ref(75)
  const get = vm.runInNewContext(`${code}; originalSourceUrl`, { computed: callback => callback,
    readerDoc:ref({source}),charOffset:offset })
  assert.equal(get(), source.parts[1].url)
  offset.value=25
  assert.equal(get(), source.parts[0].url)
  offset.value=0
  assert.equal(get(), source.url)
})

test('a search hit omitted by reading layout opens its actual source text', async () => {
  const mode = ref('preview')
  let scrolled = false
  const code = preview.slice(preview.indexOf('async function scrollToCurrentMatch('), preview.indexOf('function scrollToSourceOffset('))
  const reveal = vm.runInNewContext(`${code}; scrollToCurrentMatch`, {
    mode, rootRef: ref({querySelector:()=>null}),
    rawRef: ref({querySelector:()=>({scrollIntoView:()=>{scrolled=true}})}),
    rawMatches:ref([29]),props:{searchIndex:0},nextTick:async()=>{},setMode:next=>{mode.value=next},
  })
  await reveal()
  assert.equal(mode.value,'raw')
  assert.equal(scrolled,true)
})

test('reader search and selected text use source code points, including math letters and literal line breaks', () => {
  const source = '𝒘😀前文  \\n# 标题\n  目标𝒙片段  '
  const code = reader.slice(reader.indexOf('function buildReaderPresentation('), reader.indexOf('const readerPresentation ='))
  const present = vm.runInNewContext(`${code}; buildReaderPresentation`, { sourceTextMap })(source)
  const start = Array.from(source.slice(0, source.indexOf('目标'))).length
  assert.equal(present.displayToSource[present.text.indexOf('目标')], start)
  assert.equal(present.displayToSource.at(-1), Array.from(source).length)
  assert.equal(trimSourceTextRange(source, start - 2, Array.from(source).length).quote, '目标𝒙片段')
  const raw = sourceTextMap(source)
  assert.equal(source.slice(raw.sourceToDisplay[start], raw.sourceToDisplay[start + 5]), '目标𝒙片段')
  assert.equal(sourceTextLength('𝒘😀中文'), 4)
  const reverseCode = reader.slice(reader.indexOf('function displayOffsetForSource('), reader.indexOf('const searchMatches ='))
  const reverse = vm.runInNewContext(`${reverseCode}; displayOffsetForSource`, {readerPresentation:ref(present)})
  assert.equal(reverse(0),0)
  assert.equal(reverse(1),2)
  assert.equal(present.text.slice(reverse(start),reverse(start+5)),'目标𝒙片段')
})

test('DOM selection lengths and source slicing agree on supplementary characters', () => {
  const element = { contains: () => true }
  const code = reader.slice(reader.indexOf('function textLengthToBoundary('), reader.indexOf('function pageSelectionBounds('))
  const length = vm.runInNewContext(`${code}; textLengthToBoundary`, {
    sourceTextLength,
    document: { createRange: () => ({ selectNodeContents() {}, setEnd() {}, toString: () => '𝒘😀前文' }) },
  })
  assert.equal(length(element, {}, 6), 4)
  assert.deepEqual(trimSourceTextRange('前文  𝒘😀  后文', 2, 8), { start: 4, end: 6, quote: '𝒘😀' })
})

test('refreshing document layout rebuilds stale cached content while normal re-entry reuses it', () => {
  const stale = { html: '<p>旧排版</p>', rendererVersion: 'current' }
  let saved = stale
  let renders = 0
  const code = preview.slice(preview.indexOf('function buildBasePresentation('), preview.indexOf('function updatePresentation('))
  const build = vm.runInNewContext(`let basePresentation; ${code}; arg => { buildBasePresentation(arg); return basePresentation }`, {
    props: { documentId: 'source', documentVersion: 'v1', text: '本次资料正文' },
    cacheKey: () => 'source-v1', readCachedCourseDocument: () => saved,
    renderCourseDocument: text => { renders += 1; return { html: `<p>${text}</p>`, rendererVersion: 'current' } },
    writeCachedCourseDocument: (key, value) => { saved = value },
    updatePresentation: () => {},
  })
  assert.equal(build().html, stale.html)
  // Vue watch calls this function with a values array, not a refresh command.
  assert.equal(build(['changed props']).html, stale.html)
  assert.equal(renders, 0)
  assert.equal(build(true).html, '<p>本次资料正文</p>')
  assert.equal(renders, 1)
  assert.equal(build().html, '<p>本次资料正文</p>')
  assert.equal(renders, 1)
})

test('a retired chapter citation is restored explicitly without restoring old chapters to the catalog', async () => {
  const source = readFileSync(new URL('../src/api/knowledge.js', import.meta.url), 'utf8')
  const code = source.slice(source.indexOf('export async function restoreDocumentReaderReferences('), source.indexOf('export async function getDocumentReaderState(')).replace('export ', '')
  const calls = []
  const restore = vm.runInNewContext(`${code}; restoreDocumentReaderReferences`, {
    getCanonicalSourceRef: async id => {
      calls.push(id)
      return { id, available: true, source_document_id: id === 'other' ? 'different-source' : 'source',
        course_id: 'course', document_version: 'v1', char_start: 200, char_end: 300 }
    },
  })
  const document = { source_document_id: 'source', course: { id: 'course' }, document_version: 'v1',
    source_refs: [{id: 'current'}], chapters: [{ id: 'current-chapter' }] }
  await restore(document, ['current', 'historical', 'historical', 'other', undefined])
  assert.deepEqual(calls, ['historical', 'other'])
  assert.deepEqual(Array.from(document.source_refs, item => item.id), ['current', 'historical'])
  assert.deepEqual(document.chapters, [{ id: 'current-chapter' }])
  assert.equal(document.source_refs[1].char_start, 200)
})

test('opening a whole source resumes reading while explicit chapter and citation links stay precise', async () => {
  const destinations = []
  const source = { id: 'source', course_id: 'course', source_chapter_id: 'first-chapter', source_ref_id: 'first-reference' }
  const code = knowledge.slice(knowledge.indexOf('async function resolveCanonicalSourceDeepLink('), knowledge.indexOf('async function openCourseSource('))
  const navigate = vm.runInNewContext(`${code}; resolveCanonicalSourceDeepLink`, {
    getCanonicalCourseSource: async () => source, sourceError: ref(''),
    router: { push: async destination => destinations.push(destination) },
  })
  await navigate({ courseId: 'course', sourceDocumentId: 'source' })
  assert.equal(destinations[0].query.chapter_id, undefined)
  assert.equal(destinations[0].query.source_ref_id, undefined)
  await navigate({ courseId: 'course', sourceDocumentId: 'source', chapterId: 'third-chapter' })
  assert.equal(destinations[1].query.chapter_id, 'third-chapter')
  await navigate({ courseId: 'course', sourceDocumentId: 'source', sourceRefId: 'third-reference' })
  assert.equal(destinations[2].query.source_ref_id, 'third-reference')
  await navigate({ courseId: 'course', sourceDocumentId: 'source', chapterId: 'second-chapter', sourceRefId: 'second-ref', matchCharStart: 150, matchText: '召回率' })
  assert.equal(destinations[3].query.char_start, 150)
  assert.equal(destinations[3].query.search, '召回率')
  assert.equal(destinations[3].query.chapter_id, 'second-chapter')
})

test('the visible page and slide take precedence over an old incoming citation in the source panel', () => {
  const refs = [
    { id: 'third-slide-image', location_index: 3, location_kind: 'visual_region' },
    ...[1, 2, 3].map(n => ({ id: `ref-${n}`, page_number: n, location_index: n, location_kind: 'slide' })),
  ]
  const state = { sourceReferenceAtOffset,
    computed: get => ({ get value() { return get() } }),
    hasSlides: ref(true), hasPages: ref(false), activeSlideNumber: ref(3), activePage: ref(2),
    sourceRefs: ref(refs), requestedSourceRef: ref(refs[0]), selection: ref(null),
    activeChapter: ref(null), charOffset: ref(0),
  }
  const code = reader.slice(reader.indexOf('const activeSourceRef = computed('), reader.indexOf('const currentLocationLabel = computed('))
  const current = vm.runInNewContext(`${code}; activeSourceRef`, state)
  assert.equal(current.value.id, 'ref-3')
  state.hasSlides.value = false
  state.hasPages.value = true
  assert.equal(current.value.id, 'ref-2')
})

test('saving a slide position records its actual page without changing text positions', () => {
  const state = { readerDoc: ref({ document_version: 'v1' }), hasPages: ref(false), hasSlides: ref(true),
    activePage: ref(1), activeSlideNumber: ref(3), activeChapter: ref({ id: 'chapter' }),
    charOffset: ref(0), scrollRatio: ref(0.2), zoom: ref(1.1) }
  const code = reader.slice(reader.indexOf('function currentPositionPayload()'), reader.indexOf('async function savePosition()'))
  const payload = vm.runInNewContext(`${code}; currentPositionPayload`, state)
  assert.equal(payload().page_number, 3)
  state.hasSlides.value = false
  assert.equal(payload().page_number, null)
  assert.equal(payload().zoom, 1.1)
})


test('a search or chapter offset switches to its PDF page, including exact page boundaries', async () => {
  const selected = []
  const state = { sourceReferenceAtOffset, hasPages: ref(true), hasSlides: ref(false), activePage: ref(1), sourceRefs: ref([
    { page_number: 1, char_start: 0, char_end: 100 },
    { page_number: 2, char_start: 100, char_end: 200 },
    { page_number: 3, char_start: 200, char_end: 300 },
  ]), selectPage: async page => selected.push(page) }
  const code = reader.slice(reader.indexOf('async function selectPageForOffset('), reader.indexOf('async function revealSearchMatch('))
  const jump = vm.runInNewContext(`${code}; selectPageForOffset`, state)
  await jump(50)
  await jump(100)
  await jump(250)
  state.hasPages.value = false
  await jump(150)
  assert.deepEqual(selected, [2, 3])
})

test('search inside slide text selects the corresponding slide even after restoring a later page', async () => {
  const selected = []
  const state = { sourceReferenceAtOffset, hasPages: ref(false), hasSlides: ref(true), activeSlideNumber: ref(3), sourceRefs: ref([
    { location_index: 1, char_start: 0, char_end: 100 },
    { location_index: 2, char_start: 100, char_end: 200 },
    { location_index: 3, char_start: 200, char_end: 300 },
  ]), selectSlide: page => selected.push(page) }
  const code = reader.slice(reader.indexOf('async function selectPageForOffset('), reader.indexOf('async function revealSearchMatch('))
  const jump = vm.runInNewContext(`${code}; selectPageForOffset`, state)
  await jump(150)
  assert.deepEqual(selected, [2])
})


test('scrolling a search result cannot overwrite its chapter with a scroll percentage', () => {
  const state = { charOffset: ref(150), scrollRatio: ref(0), searchQuery: ref('accuracy'),
    hasPages: ref(false), readerDoc: ref({content:'x'.repeat(1000)}), coursePreviewRef: ref(null),
    chapters: ref([{id:'first',char_start:0,char_end:100},{id:'second',char_start:100,char_end:200}]),
    activeSectionId: ref('second'), schedulePositionSave: () => {} }
  const code = reader.slice(reader.indexOf('function handleReaderScroll('), reader.indexOf('async function restoreScroll('))
  const scroll = vm.runInNewContext(`${code}; handleReaderScroll`, state)
  scroll({currentTarget:{scrollHeight:1000,clientHeight:500,scrollTop:0,getBoundingClientRect:()=>({top:0})}})
  assert.equal(state.charOffset.value,150)
  assert.equal(state.activeSectionId.value,'second')
})


test('a multi-cell document shows the source at the reading offset instead of the chapter last cell', () => {
  const refs = [{id:'text',char_start:0,char_end:100},{id:'code',char_start:100,char_end:200}]
  const state = {sourceReferenceAtOffset,computed:get=>({get value(){return get()}}),hasSlides:ref(false),hasPages:ref(false),
    activeSlideNumber:ref(1),activePage:ref(1),sourceRefs:ref(refs),requestedSourceRef:ref(null),
    selection:ref(null),activeChapter:ref({source_ref_id:'code'}),charOffset:ref(0)}
  const code=reader.slice(reader.indexOf('const activeSourceRef = computed('),reader.indexOf('const currentLocationLabel = computed('))
  const current=vm.runInNewContext(`${code}; activeSourceRef`,state)
  assert.equal(current.value.id,'text')
  state.charOffset.value=100
  assert.equal(current.value.id,'code')
})

test('a whole-file reference does not replace the actual chapter at the reading position', () => {
  const refs = [
    { id:'file', location_kind:'document', char_start:0, char_end:1000 },
    { id:'first', location_kind:'chapter', char_start:0, char_end:400 },
    { id:'last', location_kind:'chapter', char_start:400, char_end:1000 },
  ]
  assert.equal(sourceReferenceAtOffset(refs, 0).id, 'first')
  assert.equal(sourceReferenceAtOffset(refs, 400).id, 'last')
  assert.equal(sourceReferenceAtOffset(refs, 900).id, 'last')
  assert.equal(refs[0].id, 'file')
})

test('a chapter on a Markdown heading marker scrolls to its text instead of the first block', () => {
  const selected = []
  const alignments = []
  const blocks = [[0,50], [104,180], [204,280]].map(([start,end]) => ({
    dataset:{sourceStart:String(start),sourceEnd:String(end)},
    scrollIntoView:options=>{ selected.push(start); alignments.push(options.block) },
  }))
  const root = {querySelectorAll:()=>blocks}
  const code = preview.slice(preview.indexOf('function scrollToSourceOffset('),preview.indexOf('function handlePreviewClick('))
  const jump = vm.runInNewContext(`${code}; scrollToSourceOffset`, {mode:ref('reader'),rawRef:ref(null),rootRef:ref(root)})
  jump(100)
  jump(204)
  jump(150)
  assert.deepEqual(selected,[104,204,104])
  assert.deepEqual(alignments,['start','start','start'])
})

test('selecting part of a generated reference preserves its complete original directive range', () => {
  const atomic = { dataset: { sourceStart: '12', sourceEnd: '35', sourceAtomic: 'true' },
    textContent: '正则化', querySelector: () => null, contains: () => true }
  const root = { contains: () => true, querySelectorAll: () => [atomic] }
  const code = reader.slice(reader.indexOf('function markdownSelectionBounds('), reader.indexOf('function textSelectionBounds('))
  const bounds = vm.runInNewContext(`${code}; markdownSelectionBounds`, {
    coursePreviewRef: ref({ getSelectionRoot: () => root }), sourceTextLength,
    textLengthToBoundary: (node, container, offset) => offset,
  })
  const range = { startContainer: {}, endContainer: {}, startOffset: 1, endOffset: 2, intersectsNode: () => true }
  assert.equal(bounds(range).start, 12)
  assert.equal(bounds(range).end, 35)
  // Ordinary teaching prose keeps precise offsets; it is not enlarged.
  atomic.dataset.sourceAtomic = 'false'
  assert.equal(bounds(range).start, 13)
  assert.equal(bounds(range).end, 14)
})

test('local textbook links move only the reading pane and preserve the surrounding workspace', () => {
  const viewport = { scrollTop: 80, getBoundingClientRect: () => ({ top: 120 }) }
  let outerScroll = 0
  let prevented = false
  const visible = { getBoundingClientRect: () => ({ top: 420, height: 40 }), scrollIntoView: () => { outerScroll += 1 } }
  const alias = { getBoundingClientRect: () => ({ height: 0 }), nextElementSibling: visible }
  const target = { id: 'course-anchor-sec_target', getBoundingClientRect: () => ({ height: 0 }), nextElementSibling: alias }
  const root = { contains: () => true, querySelectorAll: () => [target], closest: () => viewport }
  const code = preview.slice(preview.indexOf('function handlePreviewClick('), preview.indexOf('watch(() => [props.text'))
  const click = vm.runInNewContext(`${code}; handlePreviewClick`, { rootRef: ref(root), copyCode: () => {} })
  click({ target: { closest: () => ({ getAttribute: () => '#course-anchor-sec_target' }) }, preventDefault: () => { prevented = true } })
  assert.equal(prevented, true)
  assert.equal(viewport.scrollTop, 380)
  assert.equal(outerScroll, 0)
})
