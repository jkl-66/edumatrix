import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/VideoRecommendationWorkspace.vue', import.meta.url), 'utf8')
const code = source.slice(source.indexOf('function toOriginalSourceUrl('), source.indexOf('async function syncSelectionQuery('))
const ctx = vm.createContext({ URL })
vm.runInContext(code, ctx)

test('embedded Bilibili links reopen the original video and its part, without changing ordinary sources', () => {
  assert.equal(ctx.toOriginalSourceUrl('https://player.bilibili.com/player.html?bvid=BV1CT4y137rW&page=2'),
    'https://www.bilibili.com/video/BV1CT4y137rW?p=2')
  assert.equal(ctx.toOriginalSourceUrl('https://player.bilibili.com/player.html?aid=7988'),
    'https://www.bilibili.com/video/av7988')
  assert.equal(ctx.toOriginalSourceUrl('https://example.edu/video?id=2'), 'https://example.edu/video?id=2')
  assert.equal(ctx.toOriginalSourceUrl(''), '')
  assert.equal(ctx.toOriginalSourceUrl('javascript:alert(1)'), '')
})

test('switching a segment keeps its player mounted; another resource or ordinary page still changes view', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const code = app.slice(app.indexOf('function pageViewKey('), app.indexOf('\nwatch(', app.indexOf('function pageViewKey(')))
  vm.runInContext(code, ctx)
  const route = { name: 'VideoResource', path: '/videos/one', fullPath: '/videos/one?segment_id=first' }
  assert.equal(ctx.pageViewKey(route), ctx.pageViewKey({...route, fullPath: '/videos/one?segment_id=second'}))
  assert.notEqual(ctx.pageViewKey(route), ctx.pageViewKey({...route, path: '/videos/two'}))
  assert.equal(ctx.pageViewKey({name:'Other',fullPath:'/notes?page=2'}), '/notes?page=2')
})

test('wrong-question selection keeps filters mounted while course and learner changes replace the view', () => {
  const app = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')
  const code = app.slice(app.indexOf('function pageViewKey('), app.indexOf('\nwatch(', app.indexOf('function pageViewKey(')))
  vm.runInContext(code, ctx)
  const route = {name:'WrongQuestionBook', path:'/workspace/review/wrong-questions', query:{course_id:'course-a',wrong_id:'1'}}
  assert.equal(ctx.pageViewKey(route), ctx.pageViewKey({...route,query:{course_id:'course-a',wrong_id:'2'}}))
  assert.notEqual(ctx.pageViewKey(route), ctx.pageViewKey({...route,query:{course_id:'course-b',wrong_id:'1'}}))
  assert.notEqual(ctx.pageViewKey(route), ctx.pageViewKey({...route,query:{...route.query,student_id:'another'}}))
})

test('editing video descriptions and replacement links keeps source references and media unchanged', () => {
  const editor = readFileSync(new URL('../src/components/ResourceEditorDialog.vue', import.meta.url), 'utf8')
  const functions = editor.slice(editor.indexOf('function editVideo('), editor.indexOf('</script>'))
  const original = {schemaVersion:'f5.video-recommendation.v1',recommendations:[{id:'rec-one',title:'旧标题',
    url:'https://example.edu/original',sourceRefIds:['source-one'],licenseStatus:'platform_link_only',
    segments:[{id:'segment-one',title:'第一段',startSeconds:0,endSeconds:10}],alternatives:[]}]}
  const props = {content:JSON.stringify(original)}
  const state = {props,emit:(_event,value)=>{props.content=value}}
  Object.defineProperty(state,'videoContent',{get:()=>({value:JSON.parse(props.content)})})
  const context = vm.createContext(state)
  vm.runInContext(functions,context)
  context.editVideo(['recommendations',0,'title'],'新标题')
  context.addAlternative(0)
  context.editVideo(['recommendations',0,'alternatives',0,'url'],'https://example.edu/alternative')
  const saved = JSON.parse(props.content).recommendations[0]
  assert.equal(saved.title,'新标题')
  assert.equal(saved.alternatives[0].url,'https://example.edu/alternative')
  for(const key of ['sourceRefIds','licenseStatus','segments','url']) assert.deepEqual(saved[key],original.recommendations[0][key])
  context.removeAlternative(0,0)
  assert.deepEqual(JSON.parse(props.content).recommendations[0].alternatives,[])
})
