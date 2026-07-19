<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick, watch, createApp } from 'vue'
import { useRouter } from 'vue-router'
import { getStudentProfile, getLearningPath, getReviewPlans, getRecommendations, getNotes, regenerateComponent, getProfileAnalysis, updateStudentProfile, getGoalRecommendations } from '../api'
import {
  Activity, Brain, ArrowRight, Sparkles, BookOpen, Target, TrendingUp,
  CheckCircle2, Clock, Calendar, GraduationCap, UserCheck, Play, Edit3
} from '@lucide/vue'
import MasteryRadar from '../components/MasteryRadar.vue'
import LearningTrendChart from '../components/LearningTrendChart.vue'
import VideoRenderPanel from '../components/VideoRenderPanel.vue'
import CollapsibleMindmap from '../components/CollapsibleMindmap.vue'
import VideoPlayerCard from '../components/VideoPlayerCard.vue'
import UiCard from '../components/ui/UiCard.vue'
import UiButton from '../components/ui/UiButton.vue'
import DashboardWidget from '../components/ui/DashboardWidget.vue'
import ChartContainer from '../components/ui/ChartContainer.vue'

const router = useRouter()
const props = defineProps({ studentId: String })

const profile = ref(null)
const learningPath = ref(null)
const reviews = ref([])
const recommendations = ref([])
const profileAnalysis = ref(null)
const loading = ref(true)

const showVideoPanel = ref(false)
const videoPanelUrl = ref('')

const studentNotes = ref([])
const activeResource = ref(null)
const activeResourceContent = ref('')
const isGenerating = ref(false)
const currentStudentId = ref(props.studentId || localStorage.getItem('edumatrix_student_id') || 'demo-student')

const pathwayLoading = ref({})

const activeLearningTarget = computed(() => learningPath.value?.active_learning_target || '')
const goalOrigin = computed(() => learningPath.value?.goal_origin || 'course_default')
const adaptiveRoute = computed(() => learningPath.value?.adaptive_route || null)
const availableConcepts = computed(() => {
  return learningPath.value?.learning_chain?.map(n => n.concept) || []
})

const goalRecommendations = ref([])
const showGoalModal = ref(false)
const newGoalInput = ref('')
const updatingGoal = ref(false)
let resourceScrollLock = null

function setResourceScrollLock(locked) {
  const appContent = document.querySelector('.app-content')
  if (!appContent) return

  if (locked && !resourceScrollLock) {
    resourceScrollLock = {
      element: appContent,
      overflow: appContent.style.overflow,
      overscrollBehavior: appContent.style.overscrollBehavior,
    }
    appContent.style.overflow = 'hidden'
    appContent.style.overscrollBehavior = 'none'
  } else if (!locked && resourceScrollLock) {
    resourceScrollLock.element.style.overflow = resourceScrollLock.overflow
    resourceScrollLock.element.style.overscrollBehavior = resourceScrollLock.overscrollBehavior
    resourceScrollLock = null
  }
}

async function handleGoalUpdate(newGoal) {
  if (!newGoal) return
  updatingGoal.value = true
  try {
    await updateStudentProfile(currentStudentId.value, {
      learning_goals: [newGoal]
    })
    // Reload path, recommendations and goal recommendations after update
    const [lp, recs, p, gr] = await Promise.all([
      getLearningPath(currentStudentId.value).catch(() => null),
      getRecommendations(currentStudentId.value).catch(() => []),
      getStudentProfile(currentStudentId.value).catch(() => null),
      getGoalRecommendations(currentStudentId.value).catch(() => [])
    ])
    learningPath.value = lp
    recommendations.value = recs || []
    if (p) profile.value = p
    goalRecommendations.value = gr || []
    newGoalInput.value = ''
    showGoalModal.value = false
  } catch (err) {
    console.error('Failed to update learning goal:', err)
  } finally {
    updatingGoal.value = false
  }
}

async function switchPathway(concept, pathwayCode) {
  pathwayLoading.value[concept] = true
  try {
    const data = await getRecommendations(currentStudentId.value, concept, pathwayCode)
    if (data && data.length) {
      const updatedRec = data[0]
      const idx = recommendations.value.findIndex(r => r.concept === concept)
      if (idx !== -1) {
        recommendations.value[idx] = updatedRec
      }
    }
  } catch (err) {
    console.error('Failed to switch pathway:', err)
  } finally {
    pathwayLoading.value[concept] = false
  }
}

const avgMastery = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m || !Object.keys(m).length) return 0
  const v = Object.values(m)
  return Math.round(v.reduce((a, b) => a + b, 0) / v.length * 100)
})

const weakConcepts = computed(() => {
  const m = profile.value?.concept_mastery
  if (!m) return []
  return Object.entries(m).filter(([, v]) => v < 0.4).sort(([, a], [, b]) => a - b).slice(0, 5)
})

const conceptMastery = computed(() => {
  const raw = profile.value?.concept_mastery || {}
  return Object.entries(raw).map(([name, score]) => ({ name, mastery: score }))
})

const inProgress = computed(() => learningPath.value?.progress_summary?.in_progress || 0)
const mastered = computed(() => learningPath.value?.progress_summary?.mastered || 0)
const locked = computed(() => learningPath.value?.progress_summary?.locked || 0)
const nextUp = computed(() => (learningPath.value?.next_steps || []).slice(0, 3))

const totalConcepts = computed(() => learningPath.value?.progress_summary?.total_concepts || 0)
const trendValues = computed(() => {
  const scores = Object.values(profile.value?.concept_mastery || {}).map(score => Math.round(score * 100))
  if (!scores.length) return []
  const average = Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length)
  return [average - 18, average - 14, average - 11, average - 7, average - 5, average - 2, average]
    .map(score => Math.max(4, Math.min(100, score)))
})

function goLearn(concept) {
  router.push({ path: '/learn', query: { q: concept } })
}

function goPath() { router.push('/learning-path') }
// Go analysis properly navigates
function goAnalysis() { router.push('/student-analysis') }
function goReview() { router.push('/review') }

function goNotes(concept) {
  router.push({ path: '/notes', query: { search: concept } })
}

function playVideo(url) {
  videoPanelUrl.value = url
  showVideoPanel.value = true
}

function getDimensionIcon(key) {
  if (key === 'lecture') return BookOpen
  if (key === 'mindmap') return Brain
  if (key === 'code') return Activity
  if (key === 'quiz') return Target
  if (key === 'video') return Play
  return BookOpen
}

function getDimensionColorClass(key) {
  if (key === 'lecture') return 'text-blue-500'
  if (key === 'mindmap') return 'text-purple-500'
  if (key === 'code') return 'text-emerald-500'
  if (key === 'quiz') return 'text-amber-500'
  if (key === 'video') return 'text-rose-500'
  return 'text-indigo-500'
}

function getSortedResources(resourcesObj) {
  if (!resourcesObj) return []
  return Object.entries(resourcesObj).map(([key, res]) => ({
    key,
    ...res
  })).sort((a, b) => (b.priority || 0) - (a.priority || 0))
}

function openResourceViewer(concept, key, res) {
  activeResource.value = { concept, key, res }
  activeResourceContent.value = ''
  
  if (res.status === 'generated' && res.note_id) {
    const found = studentNotes.value.find(n => n.id === res.note_id)
    if (found) {
      activeResourceContent.value = found.content
    } else {
      activeResourceContent.value = '未能在本地缓存中查找到该笔记，可能已被删除。'
    }
  }
}

function closeResourceViewer() {
  activeResource.value = null
  activeResourceContent.value = ''
  isGenerating.value = false
}

async function generateResource() {
  if (!activeResource.value) return
  isGenerating.value = true
  
  const { concept, key, res } = activeResource.value
  try {
    const data = await regenerateComponent(currentStudentId.value, res.role, res.resource_type, concept, res.overview)
    if (data && data.status === 'success') {
      const rec = recommendations.value.find(r => r.concept === concept)
      if (rec && rec.resources[key]) {
        rec.resources[key].status = 'generated'
        rec.resources[key].note_id = data.note_id
      }
      
      const noteIdx = studentNotes.value.findIndex(n => n.id === data.note_id)
      const newNoteObj = {
        id: data.note_id,
        source: 'adaptive_hub',
        content: data.content,
        tags: [res.resource_type],
        concepts: [concept],
        created_at: new Date().toISOString()
      }
      if (noteIdx !== -1) {
        studentNotes.value[noteIdx] = newNoteObj
      } else {
        studentNotes.value.push(newNoteObj)
      }
      
      activeResourceContent.value = data.content
      activeResource.value.res.status = 'generated'
      activeResource.value.res.note_id = data.note_id
    }
  } catch (err) {
    console.error('Failed to generate component:', err)
    alert('智能体生成失败，请重试！')
  } finally {
    isGenerating.value = false
  }
}

function openInWorkspace() {
  if (!activeResource.value) return
  const { concept, key, res } = activeResource.value
  
  closeResourceViewer()
  
  if (key === 'lecture' || key === 'mindmap') {
    router.push({ path: '/notes', query: { search: concept } })
  }
  else if (key === 'code') {
    router.push({ path: '/learn', query: { q: concept } })
  }
  else if (key === 'video') {
    const url = `/api/v1/video/stream?student_id=${currentStudentId.value}`
    playVideo(url)
  }
  else if (key === 'quiz') {
    router.push({ path: '/learn', query: { quiz: concept } })
  }
}

onMounted(async () => {
  window.startInteractiveQuiz = (conceptName) => {
    router.push({ path: '/learn', query: { quiz: conceptName } })
  }
  window.startInteractiveVideo = () => {
    const url = `/api/v1/video/stream?student_id=${currentStudentId.value}`
    playVideo(url)
  }
  window.mountCodeToSandbox = (btn) => {
    const parent = btn.closest('.relative')
    const pre = parent ? parent.querySelector('pre') : null
    if (pre) {
      const rawCode = pre.textContent || ''
      localStorage.setItem('edumatrix_sandbox_mount_code', rawCode)
      router.push({ path: '/learn', query: { q: activeResource.value?.concept || '' } })
    }
  }

  try {
    const sid = currentStudentId.value
    const [p, lp, rv, recs, notesData, analysisData, gr] = await Promise.all([
      getStudentProfile(sid),
      getLearningPath(sid).catch(() => null),
      getReviewPlans(sid).catch(() => []),
      getRecommendations(sid).catch(() => []),
      getNotes(sid).catch(() => ({ notes: [] })),
      getProfileAnalysis(sid).catch(() => null),
      getGoalRecommendations(sid).catch(() => [])
    ])
    profile.value = p
    learningPath.value = lp
    reviews.value = Array.isArray(rv) ? rv : (rv?.plans || rv?.due_reviews || [])
    recommendations.value = recs || []
    studentNotes.value = notesData?.notes || []
    profileAnalysis.value = analysisData
    goalRecommendations.value = gr || []
  } catch (e) {
    console.error('Dashboard load error:', e)
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  setResourceScrollLock(false)
  window.startInteractiveQuiz = null
  window.startInteractiveVideo = null
  window.mountCodeToSandbox = null
  cleanupCustomMindmaps()
})

watch([activeResource, activeResourceContent], () => {
  if (activeResource.value && activeResourceContent.value) {
    nextTick(() => {
      renderAllDiagrams()
    })
  }
})

watch(activeResource, (resource) => {
  setResourceScrollLock(Boolean(resource))
})

function safeParseJson(str, fallback = []) {
  if (!str) return fallback
  let cleaned = str.trim()
  if (cleaned.startsWith('```')) {
    cleaned = cleaned.replace(/^```[a-zA-Z]*\s*/, '').replace(/\s*```$/, '').trim()
  }
  const startIdx = cleaned.indexOf('[')
  const endIdx = cleaned.lastIndexOf(']')
  if (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) {
    cleaned = cleaned.substring(startIdx, endIdx + 1)
  }
  try {
    return JSON.parse(cleaned)
  } catch (e) {
    console.error("JSON parse failed in Dashboard.vue, attempting fuzzy recovery:", e, str)
    try {
      const fixed = cleaned
        .replace(/,\s*]/g, ']')
        .replace(/,\s*}/g, '}')
      return JSON.parse(fixed)
    } catch (e2) {
      console.error("Fuzzy JSON recovery failed:", e2)
      return fallback
    }
  }
}

// --- 任务 8.3: 照搬主对话资源生成的 Markdown 渲染引擎与自愈算法 ---
function extractCodeFromMarkdown(mdText) {
  if (!mdText) return ''
  const regex = /```(?:python|javascript|js|py)?\s*\n([\s\S]*?)```/gi
  const codes = []
  let match
  while ((match = regex.exec(mdText)) !== null) {
    codes.push(match[1].trim())
  }
  if (codes.length > 0) {
    return codes.join('\n\n')
  }
  return mdText.trim()
}

function sanitizeMermaidCode(code) {
  let lines = code.split(/\r?\n/)
  let result = []
  let isMindmap = false
  let nodeCounter = 0

  const delimPairs = [
    { open: '((', close: '))' },
    { open: '{{', close: '}}' },
    { open: '(', close: ')' },
    { open: '[', close: ']' },
  ];

  for (let line of lines) {
    let trimmed = line.trim()
    if (!trimmed) {
      result.push(line)
      continue
    }

    if (trimmed === 'mindmap') {
      isMindmap = true
      result.push(line)
      continue
    }

    if (!isMindmap) {
      result.push(line)
      continue
    }

    let indent = line.match(/^(\s*)/)[0]
    let cleaned = trimmed.replace(/^[-*+]\s+/, '')
    cleaned = cleaned.replace(/\*\*/g, '').replace(/`/g, '')

    if (cleaned.startsWith('%%')) {
      result.push(line)
      continue
    }

    if (cleaned.startsWith('"') && cleaned.endsWith('"')) {
      cleaned = cleaned.slice(1, -1).trim()
    }

    let isShape = false
    let id = ''
    let openDelim = ''
    let innerText = ''
    let closeDelim = ''

    for (const pair of delimPairs) {
      const escapedOpen = pair.open.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const escapedClose = pair.close.replace(/[|\\{}()[\]^$+*?.]/g, '\\$&')
      const regex = new RegExp(`^([^({[\\]\\s]+)\\s*(${escapedOpen})\\s*(.*?)\\s*(${escapedClose})$`)
      const match = cleaned.match(regex)
      if (match) {
        id = match[1]
        openDelim = match[2]
        innerText = match[3]
        closeDelim = match[4]
        isShape = true
        break
      }
    }

    if (isShape) {
      let cleanText = innerText.trim()
      if (cleanText.startsWith('"') && cleanText.endsWith('"')) {
        cleanText = cleanText.slice(1, -1)
      }
      cleanText = cleanText.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      let wrappedText = '"' + cleanText + '"'
      result.push(indent + id + openDelim + wrappedText + closeDelim)
      continue
    }

    const hasSpecial = /[^a-zA-Z0-9_\-]/g.test(cleaned)
    if (hasSpecial) {
      nodeCounter++
      const nodeId = `node_${nodeCounter}`
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      let wrappedText = '"' + cleanText + '"'
      result.push(indent + nodeId + '[' + wrappedText + ']')
    } else {
      let cleanText = cleaned.replace(/\\"/g, '"').replace(/"/g, '&quot;').trim()
      result.push(indent + cleanText)
    }
  }

  return result.join('\n')
}

function renderMarkdown(text, type = '', conceptName = '') {
  if (!text) return ''

  let cleaned = text.trim()
  
  const openTicksCount = (cleaned.match(/```/g) || []).length
  if (openTicksCount % 2 !== 0) {
    cleaned += '\n```'
  }
  const doubleDollarCount = (cleaned.match(/\$\$/g) || []).length
  if (doubleDollarCount % 2 !== 0) {
    cleaned += '\n$$'
  }

  if (cleaned.startsWith('```markdown') && cleaned.endsWith('```')) {
    cleaned = cleaned.slice(11, -3).trim()
  } else if (cleaned.startsWith('```') && cleaned.endsWith('```')) {
    const firstLineEnd = cleaned.indexOf('\n')
    if (firstLineEnd !== -1) {
      const lang = cleaned.substring(3, firstLineEnd).trim().toLowerCase()
      if (lang === '' || lang === 'markdown' || lang === 'text' || lang === 'txt') {
        cleaned = cleaned.substring(firstLineEnd + 1, cleaned.length - 3).trim()
      }
    }
  }

  const svgBlocks = []
  cleaned = cleaned.replace(/(<svg[\s\S]*?<\/svg>)/gi, (match) => {
    const idx = svgBlocks.length
    svgBlocks.push(match)
    return `@@SVGBLOCKTOKEN${idx}@@`
  })

  const layoutBlocks = []
  function protectLayout(htmlTag) {
    const idx = layoutBlocks.length
    layoutBlocks.push(htmlTag)
    return `@@LAYOUTTOKEN${idx}@@`
  }

  function buildThreeLevelHintLadderHtml(rawContent) {
    if (!rawContent) return ''

    let text = rawContent
      .replace(/<details[\s\S]*?>/gi, '')
      .replace(/<\/details>/gi, '')
      .replace(/<summary>[\s\S]*?<\/summary>/gi, '')
      .replace(/^[#*\s]*💡?\s*提示阶梯[（(]点击展开[）)]?[#*\s]*\n+/gim, '')
      .trim()

    const layer1Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[1一]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=(?:[-*+\s]*)\*?\*?第\s*[2二]\s*层|$)/i)
    const layer2Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[2二]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=(?:[-*+\s]*)\*?\*?第\s*[3三]\s*层|$)/i)
    const layer3Match = text.match(/(?:[-*+\s]*)\*?\*?第\s*[3三]\s*层[（(]([^）)]+)[）)]\*?\*?\s*[：:]\s*([\s\S]*?)(?=$)/i)

    const layers = []
    if (layer1Match) layers.push({ num: 1, name: layer1Match[1].trim(), content: layer1Match[2].trim() })
    if (layer2Match) layers.push({ num: 2, name: layer2Match[1].trim(), content: layer2Match[2].trim() })
    if (layer3Match) layers.push({ num: 3, name: layer3Match[1].trim(), content: layer3Match[2].trim() })

    if (layers.length === 0) {
      const cardStart = protectLayout(`<div class="edumatrix-accordion-card border border-slate-200/80 dark:border-slate-800/80 rounded-xl my-3 overflow-hidden shadow-sm bg-slate-50/40 dark:bg-slate-900/40 transition-all duration-300">
  <div onclick="const body=this.nextElementSibling; const icon=this.querySelector('.accordion-icon'); if(body.style.display==='none'||!body.style.display){ body.style.display='block'; if(icon) icon.textContent='▼'; }else{ body.style.display='none'; if(icon) icon.textContent='▶'; }" class="px-4 py-3 font-semibold text-slate-800 dark:text-slate-200 cursor-pointer bg-slate-100/60 dark:bg-slate-800/40 hover:bg-slate-100 dark:hover:bg-slate-800/60 transition-colors flex items-center justify-between select-none text-xs">
    <span class="flex items-center gap-1.5">💡 提示阶梯（点击展开）</span>
    <span class="accordion-icon text-[10px] text-slate-400 font-mono">▶</span>
  </div>
  <div class="accordion-body px-5 py-4 border-t border-slate-100 dark:border-slate-800/60 text-slate-700 dark:text-slate-300 leading-relaxed text-xs" style="display: none;">`)
      const cardEnd = protectLayout(`</div></div>`)
      return `\n\n${cardStart}\n\n${text}\n\n${cardEnd}\n\n`
    }

    const itemsHtml = layers.map(l => {
      const cardStart = protectLayout(`<div class="edumatrix-accordion-card border border-sky-200/80 dark:border-sky-900/50 rounded-xl my-2 overflow-hidden shadow-sm bg-sky-50/20 dark:bg-slate-900/40 transition-all duration-300">
  <div onclick="const body=this.nextElementSibling; const icon=this.querySelector('.accordion-icon'); if(body.style.display==='none'||!body.style.display){ body.style.display='block'; if(icon) icon.textContent='▼'; }else{ body.style.display='none'; if(icon) icon.textContent='▶'; }" class="px-4 py-2.5 font-semibold text-sky-900 dark:text-sky-200 cursor-pointer bg-sky-50/80 dark:bg-sky-950/40 hover:bg-sky-100/80 dark:hover:bg-sky-900/60 transition-colors flex items-center justify-between select-none text-xs">
    <span class="flex items-center gap-1.5">💡 <strong class="text-sky-800 dark:text-sky-300">第 ${l.num} 层提示</strong> · ${l.name}（点击展开）</span>
    <span class="accordion-icon text-[10px] text-sky-600 dark:text-sky-400 font-mono">▶</span>
  </div>
  <div class="accordion-body px-5 py-3.5 border-t border-sky-100 dark:border-sky-900/50 text-slate-700 dark:text-slate-300 leading-relaxed text-xs bg-white/40 dark:bg-slate-900/20" style="display: none;">`)
      const cardEnd = protectLayout(`</div></div>`)
      return `\n\n${cardStart}\n\n${l.content}\n\n${cardEnd}\n\n`
    }).join('\n')

    const wrapperStart = protectLayout(`<div class="edumatrix-hint-ladder-wrapper my-3.5 p-3.5 bg-gradient-to-br from-sky-50/70 via-blue-50/40 to-slate-50/60 dark:from-slate-900/80 dark:via-sky-950/30 dark:to-slate-900/90 rounded-2xl border border-sky-200/80 dark:border-sky-900/50 shadow-sm">
  <div class="text-xs font-bold text-sky-900 dark:text-sky-300 mb-2 flex items-center gap-1.5 px-1">
    <span>🪜</span>
    <span>三层递进提示阶梯（点击各层按需展开查看）：</span>
  </div>`)
    const wrapperEnd = protectLayout(`</div>`)

    return `\n\n${wrapperStart}\n${itemsHtml}\n${wrapperEnd}\n\n`
  }

  cleaned = cleaned.replace(/(?:^|\n)\s*[-*+]*\s*(?:[#*\s]*提示阶梯[：:]*\s*\n+)?<details[\s\S]*?>([\s\S]*?)<\/details>/gi, (match, bodyContent) => {
    return buildThreeLevelHintLadderHtml(bodyContent)
  })

  if (!cleaned.includes('@@LAYOUTTOKEN')) {
    cleaned = cleaned.replace(
      /(?:[#*]*\s*提示阶梯[：:]?\s*[#*]*\s*\n+)?((?:[-*]\s*\*?第[123一二三]层[\s\S]*?)(?=\n\s*\n(?![-\s]*\*?第[123一二三]层)|\n[#*]{1,3}\s+|<div|$))/gi,
      (match, hintsContent) => {
        return buildThreeLevelHintLadderHtml(hintsContent)
      }
    )
  }

  let html = cleaned
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')

  const blockMath = []
  html = html.replace(/\DoubleDollar([\s\S]*?)\DoubleDollar/g, (_, math) => {
    const idx = blockMath.length
    blockMath.push({ math: math.trim(), display: true })
    return `@@BLOCKMATHTOKEN${idx}@@`
  }).replace(/\$\$/g, '$$$$') // Escape backslashes for double dollars replacement safely
  html = html.replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => {
    const idx = blockMath.length
    blockMath.push({ math: math.trim(), display: true })
    return `@@BLOCKMATHTOKEN${idx}@@`
  })

  const inlineMath = []
  html = html.replace(/\\\(([\s\S]*?)\\\)/g, (_, math) => {
    const idx = inlineMath.length
    inlineMath.push({ math: math.trim(), display: false })
    return `@@INLINEMATHTOKEN${idx}@@`
  })
  html = html.replace(/\$([^$\n]+?)\$/g, (_, math) => {
    const idx = inlineMath.length
    inlineMath.push({ math: math.trim(), display: false })
    return `@@INLINEMATHTOKEN${idx}@@`
  })

  const codeBlocks = []
  html = html.replace(/```([^\r\n]*)\r?\n([\s\S]*?)```/g, (_, lang, code) => {
    const isMermaid = lang.toLowerCase().includes('mermaid') || code.includes('mindmap') || code.includes('graph ') || code.includes('sequenceDiagram')
    let blockHtml = ''
    if (isMermaid) {
      let cleanCode = code.trim()
        .replace(/&amp;/g, '&')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")

      const tokenRegex = /@@INLINEMATHTOKEN(\d+)@@/g
      cleanCode = cleanCode.replace(tokenRegex, (match, idx) => {
        const item = inlineMath[parseInt(idx)]
        if (item) {
          return item.math
            .replace(/\$/g, '')
            .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1^')
            .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$1/$2')
            .replace(/\\partial/g, 'd')
            .replace(/\\Sigma/g, 'sum')
            .replace(/\\sigma/g, 'sigma')
            .replace(/\\alpha/g, 'alpha')
            .replace(/\\cdot/g, '·')
            .replace(/\\/g, '')
        }
        return ''
      })

      const blockTokenRegex = /@@BLOCKMATHTOKEN(\d+)@@/g
      cleanCode = cleanCode.replace(blockTokenRegex, (match, idx) => {
        const item = blockMath[parseInt(idx)]
        if (item) {
          return item.math
            .replace(/\$/g, '')
            .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '$1^')
            .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '$1/$2')
            .replace(/\\partial/g, 'd')
            .replace(/\\Sigma/g, 'sum')
            .replace(/\\sigma/g, 'sigma')
            .replace(/\\alpha/g, 'alpha')
            .replace(/\\cdot/g, '·')
            .replace(/\\/g, '')
        }
        return ''
      })

      cleanCode = sanitizeMermaidCode(cleanCode)
      const escapedCode = encodeURIComponent(cleanCode)

      if (cleanCode.includes('mindmap')) {
        blockHtml = `<div class="custom-mindmap-placeholder" data-code="${escapedCode}"></div>`
      } else {
        blockHtml = `<div class="my-3 p-4 bg-white border border-gray-200 rounded-xl text-xs flex flex-col items-center shadow-sm max-w-full">
          <div class="w-full flex items-center justify-between mb-3 pb-2 border-b border-gray-100">
            <div class="flex items-center gap-1.5">
              <span class="text-base">📊</span>
              <span class="font-bold text-gray-800 text-xs">概念思维导图</span>
            </div>
            <div class="flex items-center gap-2">
              <span class="text-[9px] bg-purple-50 text-purple-600 px-1.5 py-0.5 rounded font-mono font-medium">Mermaid</span>
            </div>
          </div>
          <div class="mermaid-container w-full overflow-auto flex justify-center py-2 bg-white max-h-[300px]">
            <div class="mermaid w-full flex justify-center" data-code="${escapedCode}"><div class="mermaid-loading flex flex-col items-center justify-center gap-1.5 py-6 text-gray-400 select-none"><div class="w-5 h-5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin"></div><span class="text-[10px] text-indigo-500 font-semibold animate-pulse">正在绘制思维导图...</span></div></div>
          </div>
        </div>`
      }
    } else {
      const cleanLang = (lang || 'python').trim().toLowerCase()
      blockHtml = `<div class="relative group my-3">
        <pre class="p-3 bg-gray-900 rounded-lg overflow-x-auto text-xs leading-relaxed language-${cleanLang}"><code class="language-${cleanLang}">${code.trim()}</code></pre>
        <button onclick="window.mountCodeToSandbox && window.mountCodeToSandbox(this)" class="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity px-2.5 py-1 bg-green-700 hover:bg-green-600 text-white rounded text-[10px] flex items-center gap-1 shadow-sm font-semibold transition-all">
          💻 挂载至沙箱
        </button>
      </div>`
    }
    const idx = codeBlocks.length
    codeBlocks.push(blockHtml)
    return `@@CODEBLOCKTOKEN${idx}@@`
  })

  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const blockHtml = `<code class="px-1.5 py-0.5 bg-gray-100 text-red-600 rounded font-mono text-xs font-medium">${code}</code>`
    const idx = codeBlocks.length
    codeBlocks.push(blockHtml)
    return `@@CODEBLOCKTOKEN${idx}@@`
  })

  const lines = html.split('\n')
  let inTable = false
  let tableHeader = []
  let tableRows = []
  let inList = false
  const processedLines = []

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    const trimmed = line.trim()
    const isTableRow = trimmed.startsWith('|') && trimmed.endsWith('|')
    if (isTableRow) {
      if (inList) {
        processedLines.push('</ul>')
        inList = false
      }
      const cells = trimmed.slice(1, -1).split('|').map(c => c.trim())
      const isSeparator = cells.every(c => /^[:-]+$/.test(c))
      if (isSeparator) {
        continue
      }
      if (!inTable) {
        inTable = true
        tableHeader = cells
      } else {
        tableRows.push(cells)
      }
      continue
    } else {
      if (inTable) {
        processedLines.push(generateTableHtml(tableHeader, tableRows))
        inTable = false
        tableHeader = []
        tableRows = []
      }
    }

    const listMatch = line.match(/^(\s*)[-*+]\s+(.*)$/)
    if (listMatch) {
      const content = listMatch[2]
      if (!inList) {
        processedLines.push('<ul class="my-2 space-y-1 list-disc list-inside">')
        inList = true
      }
      processedLines.push(`<li class="ml-4 text-xs text-gray-600 my-1 leading-relaxed">${content}</li>`)
    } else {
      if (inList) {
        processedLines.push('</ul>')
        inList = false
      }
      processedLines.push(line)
    }
  }

  if (inTable) {
    processedLines.push(generateTableHtml(tableHeader, tableRows))
  }
  if (inList) {
    processedLines.push('</ul>')
  }

  html = processedLines.join('\n')

  function generateTableHtml(header, rows) {
    let tableHtml = '<div class="overflow-x-auto my-4 border border-gray-200/80 rounded-xl shadow-sm bg-white"><table class="min-w-full divide-y divide-gray-200">'
    if (header && header.length > 0) {
      tableHtml += '<thead class="bg-gray-50/75"><tr>'
      header.forEach(h => {
        tableHtml += `<th class="px-4 py-2.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">${h}</th>`
      })
      tableHtml += '</tr></thead>'
    }
    tableHtml += '<tbody class="divide-y divide-gray-100 bg-white">'
    rows.forEach(row => {
      tableHtml += '<tr class="hover:bg-gray-50/50 transition-colors">'
      row.forEach(cell => {
        tableHtml += `<td class="px-4 py-2 text-xs text-gray-600">${cell}</td>`
      })
      tableHtml += '</tr>'
    })
    tableHtml += '</tbody></table></div>'
    return tableHtml
  }

  html = html.replace(/!\[([^\]]*)\]\s*\(([^)]+)\)/g, (match, alt, url) => {
    const cleanUrl = url.replace(/\s+/g, '')
    return `<img src="${cleanUrl}" alt="${alt}" class="max-w-full max-h-[300px] object-contain rounded-xl my-3 shadow-sm border border-gray-100 bg-white p-1" />`
  })
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-bold text-gray-900">$1</strong>')
  html = html.replace(/\*([^*]+)\*/g, '<em class="italic text-gray-800">$1</em>')
  html = html.replace(/^### (.*$)/gim, '<h4 class="text-xs font-bold text-gray-800 mt-4 mb-1.5 flex items-center gap-1">$1</h4>')
  html = html.replace(/^## (.*$)/gim, '<h3 class="text-sm font-semibold text-gray-900 mt-5 mb-2 border-b border-gray-100 pb-1 flex items-center gap-1.5">$1</h3>')
  html = html.replace(/^# (.*$)/gim, '<h2 class="text-base font-bold text-gray-900 mt-6 mb-3 flex items-center gap-2">$1</h2>')

  html = html.replace(/\n\n/g, '<div class="h-2.5"></div>')

  function renderMath(math, display) {
    const cleanMathContent = math
      .replace(/&amp;/g, '&')
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")

    if (window.katex) {
      try {
        return window.katex.renderToString(cleanMathContent, {
          displayMode: display,
          throwOnError: false,
          trust: true
        })
      } catch (err) {
        console.error('KaTeX rendering error:', err)
      }
    }
    const cleanMath = cleanMathContent
      .replace(/\\Sigma/g, '∑')
      .replace(/\\sigma/g, 'σ')
      .replace(/\\mu/g, 'μ')
      .replace(/\\beta/g, 'β')
      .replace(/\\theta/g, 'θ')
      .replace(/\\alpha/g, 'α')
      .replace(/\\lambda/g, 'λ')
      .replace(/\\partial/g, '∂')
      .replace(/\\infty/g, '∞')
      .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '<span style="text-decoration: overline">$1</span>')
      .replace(/([a-zA-Z0-9]+)_([a-zA-Z0-9]+)/g, '$1<sub>$2</sub>')
      .replace(/([a-zA-Z0-9]+)\^([a-zA-Z0-9]+)/g, '$1<sup>$2</sup>')
      .replace(/\\cdot/g, '·')
      .replace(/\\times/g, '×')
      .replace(/\\frac\{([^}]+)\}\{([^}]+)\}/g, '($1)/($2)')
      .replace(/\\sqrt\{([^}]+)\}/g, '√($1)')
      .replace(/\\text\{([^}]+)\}/g, '$1')
      .replace(/\\quad/g, '&nbsp;&nbsp;')

    if (display) {
      return `<div class="my-3.5 p-4 bg-gray-50/75 border border-gray-100 rounded-xl text-center font-serif text-sm overflow-x-auto select-all shadow-inner text-gray-800">${cleanMath}</div>`
    } else {
      return `<span class="font-serif italic bg-gray-50/75 px-1.5 py-0.5 rounded text-xs select-all text-gray-800 border border-gray-100/50">${cleanMath}</span>`
    }
  }

  html = html
    .replace(/\\in\b/g, ' ∈ ')
    .replace(/\\sigma\b/g, 'σ')
    .replace(/\\hat\{([a-zA-Z0-9]+)\}/g, '<span style="text-decoration: overline">$1</span>')
    .replace(/\\([{}])/g, '$1')
    .replace(/([a-zA-Z0-9])_([a-zA-Z0-9_]+)/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])_\{([^}]+)\}/g, '$1<sub>$2</sub>')
    .replace(/([a-zA-Z0-9])\^([a-zA-Z0-9+-\\*\\top\\partial]+)/g, (match, base, exp) => {
      const displayExp = exp === '\\top' || exp === 'top' ? 'T' : exp
      return `${base}<sup>${displayExp}</sup>`
    })
    .replace(/([a-zA-Z0-9])\^\{([^}]+)\}/g, (match, base, exp) => {
      const displayExp = exp === '\\top' || exp === 'top' ? 'T' : exp
      return `${base}<sup>${displayExp}</sup>`
    })

  layoutBlocks.forEach((block, idx) => {
    html = html.split(`@@LAYOUTTOKEN${idx}@@`).join(block)
  })

  blockMath.forEach((item, idx) => {
    html = html.split(`@@BLOCKMATHTOKEN${idx}@@`).join(renderMath(item.math, true))
  })
  inlineMath.forEach((item, idx) => {
    html = html.split(`@@INLINEMATHTOKEN${idx}@@`).join(renderMath(item.math, false))
  })
  codeBlocks.forEach((block, idx) => {
    html = html.split(`@@CODEBLOCKTOKEN${idx}@@`).join(block)
  })
  svgBlocks.forEach((block, idx) => {
    html = html.split(`@@SVGBLOCKTOKEN${idx}@@`).join(block)
  })

  const normalizedType = type.toLowerCase()
  if (normalizedType.includes('assess') || normalizedType.includes('quiz') || normalizedType.includes('考官') || normalizedType.includes('评测')) {
    const escapedConcept = (conceptName || '机器学习').replace(/'/g, "\\'")
    html += `<div class="mt-4 p-3 bg-blue-50/50 rounded-xl border border-blue-100 flex items-center justify-between">
      <div class="text-xs text-blue-800">
        <strong>📝 评测联动已就绪：</strong>已为您准备了针对此概念的自适应多步评测。
      </div>
      <button onclick="window.startInteractiveQuiz && window.startInteractiveQuiz('${escapedConcept}')" class="px-3.5 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-sm transition-all whitespace-nowrap">
        去测验板作答 (CAT) →
      </button>
    </div>`
  } else if (normalizedType.includes('director') || normalizedType.includes('video') || normalizedType.includes('导演') || normalizedType.includes('视频')) {
    html += `<div class="mt-4 p-3 bg-indigo-50/50 rounded-xl border border-indigo-100 flex items-center justify-between">
      <div class="text-xs text-indigo-800">
        <strong>🎬 视频演示已就绪：</strong>已为您量身定制并合成了该知识点的教学短视频。
      </div>
      <button onclick="window.startInteractiveVideo && window.startInteractiveVideo()" class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-semibold shadow-sm transition-all whitespace-nowrap">
        播放讲解视频 →
      </button>
    </div>`
  }

  return html
}

function mountCustomMindmaps() {
  nextTick(() => {
    try {
      const placeholders = document.querySelectorAll('.custom-mindmap-placeholder:not([data-mounted="true"])')
      placeholders.forEach((el) => {
        const rawCode = decodeURIComponent(el.getAttribute('data-code') || '')
        const app = createApp(CollapsibleMindmap, { code: rawCode })
        app.mount(el)
        el.setAttribute('data-mounted', 'true')
        el.__vue_app__ = app
      })
    } catch (err) {
      console.error('Mount custom mindmaps error:', err)
    }
  })
}

function cleanupCustomMindmaps() {
  const elements = document.querySelectorAll('.custom-mindmap-placeholder[data-mounted="true"]')
  elements.forEach((el) => {
    if (el.__vue_app__) {
      try {
        el.__vue_app__.unmount()
      } catch (e) {}
      delete el.__vue_app__
    }
  })
}

function initMermaid() {
  if (typeof window.mermaid !== 'undefined') {
    nextTick(() => {
      try {
        window.mermaid.initialize({
          startOnLoad: false,
          theme: 'default',
          securityLevel: 'loose',
          themeVariables: {
            background: '#ffffff',
            primaryColor: '#ff79c6',
            primaryTextColor: '#111827',
            lineColor: '#6366f1',
            fontSize: '12px'
          }
        })
        const elements = document.querySelectorAll('.mermaid:not([data-processed="true"])')
        elements.forEach((el) => {
          try {
            const rawCode = decodeURIComponent(el.getAttribute('data-code') || '')
            if (rawCode) {
              el.textContent = rawCode
            }
            window.mermaid.init(undefined, el)
          } catch (err) {
            console.error('Individual Mermaid render error:', err)
          }
        })
      } catch (err) {
        console.error('Mermaid render error:', err)
      }
    })
  }
}

function renderAllDiagrams() {
  initMermaid()
  mountCustomMindmaps()
  if (typeof window.Prism !== 'undefined') {
    nextTick(() => {
      window.Prism.highlightAll()
    })
  }
}
</script>

<template>
  <div v-if="loading" class="dashboard-skeleton" aria-label="正在加载仪表盘">
    <div class="dashboard-skeleton__hero" />
    <div class="dashboard-skeleton__grid"><span v-for="i in 4" :key="i" /></div>
  </div>
  <div v-else class="dashboard-page space-y-7 max-w-[1380px] mx-auto soft-reveal">

    <section class="dashboard-overview">
      <UiCard class="dashboard-hero" tone="dark">
        <div class="dashboard-hero__content">
          <div>
            <span class="dashboard-hero__eyebrow"><Sparkles :size="13" /> 今日学习焦点</span>
            <h1>{{ activeLearningTarget || '继续构建你的知识网络' }}</h1>
            <p>AI 已结合掌握度、认知负荷和复习节奏，为你生成当前最值得投入的学习任务。</p>
          </div>
          <div class="dashboard-hero__actions">
            <UiButton variant="secondary" @click="goLearn(activeLearningTarget)"><template #icon><Play :size="15" /></template>继续学习</UiButton>
            <UiButton variant="ghost" @click="goPath">查看学习路径 <ArrowRight :size="14" /></UiButton>
          </div>
        </div>
        <div class="dashboard-hero__meta">
          <div><span>目标课程</span><strong>{{ profile?.target_course || '机器学习导论' }}</strong></div>
          <div><span>今日建议</span><strong>{{ Math.max(1, nextUp.length) }} 项任务</strong></div>
          <div><span>学习状态</span><strong>{{ profile?.cognitive_load > 0.6 ? '建议轻量推进' : '适合深度学习' }}</strong></div>
        </div>
      </UiCard>

      <ChartContainer title="学习趋势" subtitle="最近 7 天知识掌握度变化" eyebrow="Learning momentum">
        <template #action><span class="dashboard-trend-status"><span />较上周稳步提升</span></template>
        <LearningTrendChart :values="trendValues" />
      </ChartContainer>
    </section>

    <section class="dashboard-metrics">
      <DashboardWidget label="平均掌握度" :value="`${avgMastery}%`" detail="综合全部知识点计算" tone="sage">
        <template #icon><TrendingUp :size="16" /></template><template #signal>核心指标</template>
      </DashboardWidget>
      <DashboardWidget label="课程完成" :value="`${mastered}/${totalConcepts}`" detail="已达到稳定掌握标准" tone="violet">
        <template #icon><CheckCircle2 :size="16" /></template><template #signal>课程进度</template>
      </DashboardWidget>
      <DashboardWidget label="正在学习" :value="inProgress" detail="当前路径中的活跃知识点" tone="sand">
        <template #icon><Activity :size="16" /></template><template #signal>进行中</template>
      </DashboardWidget>
      <DashboardWidget label="风险知识点" :value="weakConcepts.length" detail="建议在本周优先强化" tone="rose">
        <template #icon><Target :size="16" /></template><template #signal>AI 预测</template>
      </DashboardWidget>
    </section>

    <!-- 🎓 课程全局学情诊断与自适应评价 -->
    <div v-if="profileAnalysis && profile" class="dashboard-insight bg-gradient-to-br from-indigo-50/80 via-white/90 to-blue-50/70 rounded-3xl border border-indigo-100/70 p-6 shadow-sm space-y-5 relative overflow-hidden">
      <div class="absolute -right-16 -top-20 w-56 h-56 rounded-full bg-indigo-300/15 blur-3xl pointer-events-none" />
      <div class="flex items-center justify-between border-b border-indigo-100/60 pb-3 flex-wrap gap-2">
        <div class="flex items-center gap-2">
          <GraduationCap :size="18" class="text-indigo-600 animate-pulse" />
          <h2 class="text-base font-bold tracking-tight text-slate-800">课程全局学情诊断与自适应评价</h2>
        </div>
        <div class="flex items-center gap-2 text-[10px] text-slate-500 font-medium">
          <span>📚 目标课程: <strong class="text-indigo-700 font-semibold">{{ profile?.target_course || '机器学习导论' }}</strong></span>
          <span>🎓 专业方向: <strong class="text-indigo-700 font-semibold">{{ profile?.major || '自适应' }}</strong></span>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-5">
        <!-- 左侧及中间：全局学情诊断报告 (Dashboard Analysis) -->
        <div class="md:col-span-2 bg-slate-50/60 border border-slate-100 rounded-xl p-4 relative overflow-hidden flex flex-col justify-between">
          <Sparkles class="absolute right-3 top-3 text-slate-200/40 w-12 h-12 pointer-events-none" />
          <div class="space-y-2">
            <h3 class="text-xs font-bold text-slate-800 flex items-center gap-1">
              📊 全局学情诊断报告
            </h3>
            <div class="text-[11px] text-slate-700 leading-relaxed whitespace-pre-wrap font-medium">
              {{ profileAnalysis.dashboard_report || '正在加载中...' }}
            </div>
          </div>
        </div>

        <!-- 右侧：全局心智负荷与偏好评价 -->
        <div class="bg-white/90 border border-slate-100 rounded-xl p-4 flex flex-col justify-between space-y-3">
          <div class="space-y-3">
            <h3 class="text-xs font-bold text-slate-800 flex items-center gap-1">
              🧠 脑力心智负荷与风格评价
            </h3>
            
            <div class="space-y-2.5 text-[10px] text-slate-600">
              <div class="flex items-center justify-between">
                <span class="font-medium">认知负荷:</span>
                <span class="font-bold" :class="profile.cognitive_load > 0.6 ? 'text-amber-600' : 'text-emerald-600'">
                  {{ Math.round(profile.cognitive_load * 100) }}%
                </span>
              </div>
              <div class="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div class="h-full rounded-full" 
                  :class="profile.cognitive_load > 0.6 ? 'bg-amber-500' : 'bg-emerald-500'"
                  :style="{ width: (profile.cognitive_load * 100) + '%' }" />
              </div>

              <div class="flex items-center justify-between">
                <span class="font-medium">情绪避障/挫败感:</span>
                <span class="font-bold" :class="profile.frustration_index > 0.4 ? 'text-rose-600' : 'text-emerald-600'">
                  {{ Math.round(profile.frustration_index * 100) }}%
                </span>
              </div>
              <div class="w-full h-1.5 bg-slate-100 rounded-full overflow-hidden">
                <div class="h-full rounded-full" 
                  :class="profile.frustration_index > 0.4 ? 'bg-rose-500' : 'bg-emerald-500'"
                  :style="{ width: (profile.frustration_index * 100) + '%' }" />
              </div>
              
              <div class="pt-2 border-t border-slate-100 space-y-1">
                <div class="flex justify-between">
                  <span class="text-slate-500">学习风格:</span>
                  <span class="font-bold text-indigo-600">{{ profile.cognitive_style || '自适应' }}</span>
                </div>
                <div class="flex justify-between">
                  <span class="text-slate-500">学习动机:</span>
                  <span class="font-bold text-indigo-600">{{ profile.motivation_type || '未诊断' }}</span>
                </div>
              </div>
            </div>
          </div>
          
          <button class="w-full py-2 text-center text-xs font-bold text-indigo-600 bg-indigo-50/50 hover:bg-indigo-50 border border-indigo-100/50 rounded-lg transition-all"
            @click="router.push({ path: '/profile', query: { student_id: currentStudentId } })">
            查看数字孪生详细分析 →
          </button>
        </div>
      </div>
    </div>

    <!-- 🎯 唯一主攻锚点与最终目标微调中心 -->
    <div v-if="activeLearningTarget" class="bg-gradient-to-r from-amber-500/10 via-amber-600/5 to-amber-700/0 border border-amber-500/30 rounded-2xl p-5 shadow-sm space-y-3 relative overflow-hidden">
      <!-- Background micro-glow decoration -->
      <div class="absolute -right-8 -top-8 w-24 h-24 rounded-full bg-amber-400/20 blur-xl pointer-events-none" />

      <!-- Card Header / Goal Resolver UI -->
      <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-amber-500/20 pb-3">
        <div class="flex items-center gap-2">
          <span class="w-6 h-6 rounded-lg bg-amber-500 text-white flex items-center justify-center text-xs font-bold shadow-md shadow-amber-500/20">🎯</span>
          <div>
            <h3 class="text-xs font-bold text-slate-800 leading-none">自适应学习主攻卡</h3>
            <span class="text-[9px] text-slate-400 mt-1 block">A* 算法全局拓扑寻优路线</span>
          </div>
        </div>

        <!-- 最终目标微调中心 -->
        <div class="flex items-center gap-1.5 bg-white/60 border border-slate-200/80 px-2.5 py-1 rounded-xl text-[10px] font-semibold text-slate-600 shadow-inner">
          <span>最终通关目标:</span>
          <strong class="text-indigo-600 font-bold">{{ adaptiveRoute?.target_concept || '未指定' }}</strong>
          <span class="px-1.5 py-0.5 text-[8px] rounded-md scale-95 font-bold"
            :class="{
              'bg-blue-50 text-blue-700': goalOrigin === 'user',
              'bg-emerald-50 text-emerald-700': goalOrigin === 'document',
              'bg-amber-50 text-amber-700': goalOrigin === 'course_default',
            }">
            {{ goalOrigin === 'user' ? '✨ 手设' : goalOrigin === 'document' ? '📂 文档' : '📚 大纲' }}
          </span>
          <button @click="showGoalModal = true" class="ml-1 p-0.5 hover:bg-slate-200 rounded transition-colors text-slate-400 hover:text-indigo-600" title="微调目标">
            <Edit3 :size="10" />
          </button>
        </div>
      </div>

      <!-- Core Guidance Statement -->
      <div class="space-y-1 pb-1">
        <h4 class="text-xs font-bold text-slate-850 flex items-center gap-1">
          🎯 当前主攻概念：{{ activeLearningTarget }}（掌握度: {{ Math.round((profile?.concept_mastery?.[activeLearningTarget] || 0.0) * 100) }}%）
        </h4>
        <p class="text-[11px] text-slate-600 leading-relaxed font-medium mt-1.5">
          💡 智能指引：这是根据您的备考目标规划出的 A* 核心路线第一步。系统已在下方为您准备了该概念的 5 维专属自适应学习资源，请优先攻克。
        </p>
      </div>

      <!-- Horizontal Step Pipeline -->
      <div v-if="adaptiveRoute?.nodes?.length" class="pt-2">
        <div class="text-[9px] text-slate-400 font-bold mb-1.5 flex items-center gap-1">
          <span>🛤️ A* 通关推进链条:</span>
          <span class="text-slate-300">(共 {{ adaptiveRoute.nodes.length }} 步)</span>
        </div>
        <div class="flex flex-wrap items-center gap-y-2 gap-x-1.5 py-1.5 max-w-full">
          <div v-for="(node, index) in adaptiveRoute.nodes" :key="node.concept" class="flex items-center shrink-0">
            <div class="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-[10px] font-bold select-none transition-all cursor-pointer hover:scale-[1.01]"
              @click="goLearn(node.concept)"
              :class="node.concept === activeLearningTarget 
                ? 'bg-amber-500 text-white border-amber-500 shadow-md ring-2 ring-amber-400/40 ring-offset-2 scale-[1.03] animate-pulse'
                : (profile?.concept_mastery?.[node.concept] || 0.0) >= 0.7 
                  ? 'bg-emerald-50 text-emerald-700 border-emerald-100'
                  : 'bg-white text-slate-500 border-slate-100 hover:border-slate-200'">
              <span>{{ index + 1 }}. {{ node.concept }}</span>
              <span v-if="(profile?.concept_mastery?.[node.concept] || 0.0) >= 0.7" class="text-[8px]">✅</span>
            </div>
            <span v-if="index < adaptiveRoute.nodes.length - 1" class="text-slate-300 mx-1 font-bold text-xs">→</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Goal Resolver Select Modal -->
    <Teleport to="body">
    <div v-if="showGoalModal" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/45 backdrop-blur-sm transition-all" @click="showGoalModal = false">
      <div class="w-full max-w-2xl bg-white rounded-2xl shadow-2xl p-5 space-y-4 border border-slate-100 animate-scale-up mx-4 max-h-[90vh] overflow-y-auto" @click.stop>
        <div class="flex items-center justify-between border-b border-slate-100 pb-3">
          <h3 class="text-xs font-bold text-slate-800 flex items-center gap-1.5">
            🎯 A* 最终学习目标与智能路径规划中心
          </h3>
          <button @click="showGoalModal = false" class="text-slate-400 hover:text-slate-600 text-sm">✕</button>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
          <!-- Left side: Manual selection -->
          <div class="md:col-span-1 space-y-3.5">
            <div>
              <label class="text-[10px] text-slate-400 font-bold block mb-1">手动微调最终通关目标</label>
              <select v-model="newGoalInput" class="w-full p-2.5 bg-slate-50 border border-slate-200 hover:border-slate-300 rounded-xl text-xs font-bold text-slate-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white transition-all">
                <option value="" disabled>-- 请选择目标概念 --</option>
                <option v-for="conceptName in availableConcepts" :key="conceptName" :value="conceptName">
                  {{ conceptName }}
                </option>
              </select>
            </div>

            <p class="text-[10px] text-slate-400 leading-relaxed">
              ✏️ 说明：选择目标概念后，A* 寻路算法及推送卡片会自动更新以其为终点。如果包含未掌握的前置依赖，系统将引导您优先攻克首个薄弱概念。
            </p>

            <div class="flex items-center gap-2 pt-2">
              <button @click="showGoalModal = false" class="flex-1 py-2 border border-slate-200 text-slate-600 hover:bg-slate-50 text-xs font-bold rounded-xl transition-all">
                取消
              </button>
              <button @click="handleGoalUpdate(newGoalInput)" :disabled="!newGoalInput || updatingGoal"
                class="flex-1 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 text-white text-xs font-bold rounded-xl shadow-md transition-all flex items-center justify-center gap-1">
                <span v-if="updatingGoal" class="animate-spin w-3 h-3 border-2 border-white border-t-transparent rounded-full" />
                确认设定
              </button>
            </div>
          </div>

          <!-- Right side: AI smart pathway recommendations -->
          <div class="md:col-span-2 border-t md:border-t-0 md:border-l border-slate-100 pt-4 md:pt-0 md:pl-4">
            <h4 class="text-[11px] font-bold text-slate-800 flex items-center gap-1.5 mb-2.5">
              <Sparkles :size="12" class="text-amber-500 animate-pulse" />
              AI 自适应学习路径推荐 (多路线通关)
            </h4>
            <div v-if="goalRecommendations.length" class="space-y-3 max-h-[320px] overflow-y-auto pr-1">
              <div v-for="pw in goalRecommendations" :key="pw.target_concept"
                class="bg-slate-50 hover:bg-slate-100/70 border border-slate-150 rounded-xl p-3 space-y-2 transition-all">
                
                <div class="flex items-center justify-between gap-3 flex-wrap">
                  <div>
                    <h5 class="text-[11px] font-extrabold text-slate-800">{{ pw.pathway_name }}</h5>
                    <p class="text-[9px] text-slate-400 font-medium mt-0.5">{{ pw.description }}</p>
                  </div>
                  <button @click="handleGoalUpdate(pw.target_concept)" :disabled="updatingGoal"
                    class="px-2.5 py-1 bg-amber-500 hover:bg-amber-600 disabled:bg-slate-300 text-white text-[10px] font-extrabold rounded-lg shadow-sm transition-all shrink-0">
                    选择该目标
                  </button>
                </div>

                <!-- Progress bar and Metrics -->
                <div class="flex items-center justify-between gap-3 text-[9px] font-mono text-slate-500 flex-wrap">
                  <div class="flex items-center gap-1.5 flex-1 min-w-[120px]">
                    <span class="font-bold shrink-0">通关进度:</span>
                    <div class="flex-1 h-1.5 bg-slate-200 rounded-full overflow-hidden">
                      <div class="h-full bg-emerald-500 rounded-full transition-all" :style="{ width: pw.completion_rate + '%' }" />
                    </div>
                    <span class="font-bold text-emerald-600 shrink-0">{{ pw.completion_rate }}%</span>
                  </div>
                  
                  <div class="flex items-center gap-1.5">
                    <span class="px-2 py-0.5 rounded bg-slate-100 text-slate-600 border border-slate-200">
                      ⏱️ 预估通关: {{ pw.expected_minutes }} 分钟
                    </span>
                    <span class="px-2 py-0.5 rounded font-extrabold border"
                      :class="{
                        'bg-emerald-50 text-emerald-700 border-emerald-100': pw.cognitive_load_index === '轻度学习',
                        'bg-amber-50 text-amber-700 border-amber-100': pw.cognitive_load_index === '中度攻坚',
                        'bg-rose-50 text-rose-700 border-rose-100': pw.cognitive_load_index === '深度挑战'
                      }">
                      🧠 {{ pw.cognitive_load_index }}
                    </span>
                  </div>
                </div>

                <!-- Horizontal workflow crumbs node chain (wrapped to avoid truncation) -->
                <div class="flex flex-wrap items-center gap-y-2 gap-x-1.5 py-1.5 max-w-full">
                  <div v-for="(node, index) in pw.nodes" :key="node.concept + '_' + index" class="flex items-center shrink-0">
                    <span v-if="node.is_ellipsis" class="text-slate-400 font-bold px-1 select-none">...</span>
                    <span v-else class="px-2 py-0.5 rounded text-[9px] font-bold border select-none transition-all"
                      :class="node.concept === activeLearningTarget
                        ? 'bg-amber-500 text-white border-amber-600 shadow-sm animate-pulse'
                        : node.is_target
                          ? 'bg-indigo-50 text-indigo-700 border-indigo-200 font-extrabold ring-1 ring-indigo-100/50'
                          : node.mastered 
                            ? 'bg-emerald-50 text-emerald-700 border-emerald-100'
                            : 'bg-white text-slate-400 border-slate-100'">
                      {{ node.concept }}
                      <span v-if="node.mastered" class="text-[8px] ml-0.5">✓</span>
                    </span>
                    <span v-if="index < pw.nodes.length - 1" class="text-slate-300 mx-0.5 text-[9px] font-bold">→</span>
                  </div>
                </div>

              </div>
            </div>
            <div v-else class="flex flex-col items-center justify-center h-40 text-xs text-gray-400 gap-1.5">
              <span class="animate-spin w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full" />
              <p>AI 正在分析核心路径推荐...</p>
            </div>
          </div>
        </div>
      </div>
    </div>
    </Teleport>

    <!-- 备选解锁方向 -->
    <div v-if="nextUp.length" class="bg-blue-50/75 rounded-2xl border border-blue-100 p-4">
      <h2 class="text-sm font-bold text-blue-800 mb-1 flex items-center gap-2">
        <Sparkles :size="15" class="text-blue-600 animate-pulse" />
        <span>备选解锁方向 (Alternative Directions)</span>
      </h2>
      <p class="text-[10px] text-blue-600 font-medium mb-3">
        以下知识点您的前置依赖已满足，可以随时作为备选方向切换学习。
      </p>
      <div class="flex flex-wrap gap-2">
        <button v-for="n in nextUp" :key="n.concept"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-white text-blue-700 border border-blue-200 hover:bg-blue-100 transition-all"
          @click="goLearn(n.concept)">
          {{ n.concept }} <ArrowRight :size="11" />
        </button>
      </div>
    </div>

    <!-- 智能自适应资源推送 (5维矩阵) -->
    <div v-if="recommendations.length" class="space-y-5">
      <h2 class="text-sm font-bold text-gray-800 flex items-center gap-2">
        <Sparkles :size="15" class="text-indigo-500" />
        <span>智教自适应资源推送 (5维矩阵)</span>
        <span class="px-2 py-0.5 text-[9px] font-semibold bg-indigo-50 text-indigo-600 rounded-full border border-indigo-100 animate-pulse">AI Agent 智能体推荐底座</span>
      </h2>

      <div class="space-y-5">
        <!-- Iterate over recommended concepts -->
        <div v-for="conceptRec in recommendations" :key="conceptRec.concept"
          class="bg-white rounded-2xl border p-5 space-y-4 relative overflow-hidden transition-all duration-300"
          :class="conceptRec.concept === activeLearningTarget 
            ? 'border-amber-400/80 shadow-[0_0_15px_rgba(245,158,11,0.12)] ring-2 ring-amber-400/30 ring-offset-2' 
            : 'border-slate-100 shadow-sm'">
          
          <!-- Concept Header -->
          <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 pb-3 border-b border-slate-100">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="px-2.5 py-0.5 text-xs font-bold rounded-lg border"
                :class="{
                  'bg-rose-50 text-rose-600 border-rose-100': conceptRec.badge === '🔥 薄弱强化',
                  'bg-purple-50 text-purple-600 border-purple-100': conceptRec.badge === '💡 探索进阶'
                }">
                {{ conceptRec.badge }}
              </span>
              <h3 class="text-sm font-bold text-gray-800">
                知识强化目标: <span class="text-indigo-600 text-sm font-extrabold ml-1">{{ conceptRec.concept }}</span>
              </h3>
              <span class="text-[10px] font-semibold px-2 py-0.5 bg-slate-100 text-slate-600 rounded-full">
                当前掌握度: {{ Math.round(conceptRec.mastery * 100) }}%
              </span>
            </div>
            <p class="text-[10px] text-slate-400 font-medium leading-relaxed max-w-md">
              {{ conceptRec.reason }}
            </p>
          </div>

          <!-- Tactical Pathway Switcher -->
          <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-3 bg-slate-50/60 rounded-xl border border-slate-100/80">
            <div class="flex items-center gap-2">
              <span class="text-xs font-bold text-slate-700">战术编译路线:</span>
              <span class="inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold rounded-md border"
                :class="{
                  'bg-blue-50 text-blue-700 border-blue-100': conceptRec.pathway_meta.code === 'ICE_BREAKER',
                  'bg-emerald-50 text-emerald-700 border-emerald-100': conceptRec.pathway_meta.code === 'PRACTITIONER',
                  'bg-purple-50 text-purple-700 border-purple-100': conceptRec.pathway_meta.code === 'EXPLORER',
                  'bg-rose-50 text-rose-700 border-rose-100': conceptRec.pathway_meta.code === 'RESCUE',
                  'bg-amber-50 text-amber-700 border-amber-100': conceptRec.pathway_meta.code === 'FUSION',
                }">
                <span>{{ conceptRec.pathway_meta.name }}</span>
              </span>
            </div>
            
            <div class="flex flex-wrap gap-1.5">
              <button v-for="pw in [
                { code: 'ICE_BREAKER', name: '破冰', icon: '🚀' },
                { code: 'PRACTITIONER', name: '实操', icon: '🛠️' },
                { code: 'EXPLORER', name: '探究', icon: '🔬' },
                { code: 'RESCUE', name: '防忘', icon: '🚨' },
                { code: 'FUSION', name: '跨界', icon: '📈' }
              ]" :key="pw.code"
                @click="switchPathway(conceptRec.concept, pw.code)"
                :disabled="pathwayLoading[conceptRec.concept]"
                class="px-2.5 py-1 text-[10px] font-bold rounded-lg border transition-all flex items-center gap-1 shadow-sm"
                :class="conceptRec.pathway_meta.code === pw.code
                  ? 'bg-indigo-600 border-indigo-600 text-white font-extrabold shadow-md scale-[1.03]'
                  : 'bg-white border-slate-200 text-slate-600 hover:scale-[1.01] hover:bg-slate-50'">
                <span>{{ pw.icon }}</span>
                <span>{{ pw.name }}</span>
              </button>
            </div>
          </div>

          <!-- 学情诊断与改进意见 (细节分析、原因、意见) -->
          <div v-if="conceptRec.learning_state_overview" class="p-3.5 bg-slate-50 border border-slate-100 rounded-xl space-y-2">
            <h4 class="text-xs font-bold text-slate-800 flex items-center gap-1.5">
              📊 专属学情诊断与改进建议
            </h4>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4 text-[11px] text-slate-600 leading-relaxed">
              <div class="space-y-0.5">
                <span class="font-bold text-slate-800">🔍 细节分析：</span>
                <p>{{ conceptRec.learning_state_overview.detail_analysis }}</p>
              </div>
              <div class="space-y-0.5">
                <span class="font-bold text-slate-800">🧩 障碍原因：</span>
                <p>{{ conceptRec.learning_state_overview.reason }}</p>
              </div>
              <div class="space-y-0.5">
                <span class="font-bold text-slate-800">💡 教学意见：</span>
                <p>{{ conceptRec.learning_state_overview.advice }}</p>
              </div>
            </div>
          </div>

          <!-- 5-Dimensional Resource Matrix Grid Wrapper -->
          <div class="relative min-h-[160px]">
            <!-- Loading Indicator for compilation -->
            <div v-if="pathwayLoading[conceptRec.concept]" class="absolute inset-0 bg-white/70 backdrop-blur-[1px] z-10 flex flex-col items-center justify-center rounded-xl space-y-2">
              <div class="animate-spin w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full" />
              <span class="text-xs font-bold text-indigo-700">战术路线重新编译中...</span>
            </div>

            <!-- Grid -->
            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-4">
              <div v-for="res in getSortedResources(conceptRec.resources)" :key="res.key"
                @click="openResourceViewer(conceptRec.concept, res.key, res)"
                class="relative group overflow-hidden cursor-pointer rounded-2xl p-4 flex flex-col justify-between transition-all duration-300 border border-slate-100 hover:border-indigo-200 shadow-sm hover:shadow-md bg-white hover:bg-slate-50/20">
                
                <div class="space-y-3">
                  <!-- Icon & Title -->
                  <div class="flex items-center justify-between">
                    <div class="flex items-center gap-1.5">
                      <div class="w-6 h-6 rounded-lg flex items-center justify-center transition-transform group-hover:scale-110"
                        :class="{
                          'bg-blue-50 text-blue-600': res.key === 'lecture',
                          'bg-purple-50 text-purple-600': res.key === 'mindmap',
                          'bg-emerald-50 text-emerald-600': res.key === 'code',
                          'bg-amber-50 text-amber-600': res.key === 'quiz',
                          'bg-rose-50 text-rose-600': res.key === 'video'
                        }">
                        <component :is="getDimensionIcon(res.key)" :size="13" />
                      </div>
                      <div class="flex flex-col">
                        <span class="text-xs font-bold text-slate-800 leading-none flex items-center gap-1">
                          {{ res.resource_type }}
                        </span>
                        <span class="text-[9px] text-slate-400 mt-0.5">{{ res.role }}</span>
                      </div>
                    </div>
                    
                    <span class="px-1.5 py-0.5 text-[9px] font-bold rounded-md"
                      :class="res.status === 'generated' 
                        ? 'bg-emerald-50 text-emerald-600 border border-emerald-100' 
                        : 'bg-slate-50 text-slate-400 border border-slate-100'">
                      {{ res.status === 'generated' ? '已就绪' : '待生成' }}
                    </span>
                  </div>

                  <!-- Card Overview Description -->
                  <p class="text-[10px] text-slate-500 line-clamp-4 leading-relaxed min-h-[64px]">{{ res.overview }}</p>
                </div>

                <!-- Action Indicator -->
                <div class="mt-3.5 pt-2.5 border-t border-slate-100 flex items-center justify-between text-[10px] font-bold">
                  <span class="transition-colors" :class="res.status === 'generated' ? 'text-indigo-600 group-hover:text-indigo-700' : 'text-slate-500 group-hover:text-slate-700'">
                    {{ res.status === 'generated' ? '立即学习' : '一键生成' }}
                  </span>
                  <span class="text-xs transition-transform group-hover:translate-x-0.5">→</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 主内容：雷达图 + 薄弱点 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <!-- 雷达图 -->
      <div class="md:col-span-2 bg-white rounded-2xl border border-gray-100 shadow-sm p-4 overflow-hidden">
        <h2 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
          <Brain :size="15" class="text-purple-500" /> 知识掌握度
        </h2>
        <div class="h-56">
          <MasteryRadar v-if="conceptMastery.length" :concepts="conceptMastery" :student-id="props.studentId" />
          <div v-else class="flex items-center justify-center h-full text-xs text-gray-400">暂无数据，开始学习后自动生成</div>
        </div>
      </div>

      <!-- 薄弱点列表 -->
      <div class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
        <h2 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
          <Target :size="15" class="text-rose-500" /> 需要加强
        </h2>
        <div v-if="weakConcepts.length" class="space-y-2">
          <div v-for="([concept, score], i) in weakConcepts" :key="concept"
            class="flex items-center gap-2 p-2 rounded-lg hover:bg-rose-50 transition-all cursor-pointer group"
            @click="goLearn(concept)">
            <span class="w-5 h-5 rounded-full bg-rose-100 text-rose-700 flex items-center justify-center text-[9px] font-bold shrink-0">{{ i + 1 }}</span>
            <span class="text-xs text-gray-700 flex-1">{{ concept }}</span>
            <span class="text-[10px] font-mono text-rose-600">{{ Math.round(score * 100) }}%</span>
            <ArrowRight :size="11" class="text-gray-300 opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        </div>
        <div v-else class="flex flex-col items-center justify-center h-40 text-xs text-gray-400 gap-2">
          <CheckCircle2 :size="24" class="text-emerald-300" />
          <p>暂无薄弱点，继续保持！</p>
        </div>
      </div>
    </div>

    <!-- 快捷入口 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-purple-200 transition-all text-left flex items-center gap-3"
        @click="goLearn(nextUp[0]?.concept)">
        <div class="w-9 h-9 rounded-xl bg-purple-50 flex items-center justify-center"><BookOpen :size="16" class="text-purple-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">开始学习</p><p class="text-[9px] text-gray-400">进入对话</p></div>
      </button>
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-emerald-200 transition-all text-left flex items-center gap-3"
        @click="goAnalysis">
        <div class="w-9 h-9 rounded-xl bg-emerald-50 flex items-center justify-center"><UserCheck :size="16" class="text-emerald-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">学习画像</p><p class="text-[9px] text-gray-400">10维分析</p></div>
      </button>
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-indigo-200 transition-all text-left flex items-center gap-3"
        @click="goPath">
        <div class="w-9 h-9 rounded-xl bg-indigo-50 flex items-center justify-center"><TrendingUp :size="16" class="text-indigo-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">学习路径</p><p class="text-[9px] text-gray-400">链条推进</p></div>
      </button>
      <button class="bg-white rounded-xl border border-gray-100 shadow-sm p-3 hover:border-amber-200 transition-all text-left flex items-center gap-3"
        @click="goReview">
        <div class="w-9 h-9 rounded-xl bg-amber-50 flex items-center justify-center"><Calendar :size="16" class="text-amber-600" /></div>
        <div><p class="text-xs font-semibold text-gray-800">复习计划</p><p class="text-[9px] text-gray-400">遗忘曲线</p></div>
      </button>
    </div>

    <!-- 待复习概念 -->
    <div v-if="reviews.length" class="bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
      <h2 class="text-sm font-semibold text-gray-800 mb-2 flex items-center gap-2">
        <Clock :size="15" class="text-amber-500" /> 待复习
      </h2>
      <div class="space-y-1">
        <div v-for="r in reviews.slice(0, 5)" :key="r.concept || r.id"
          class="flex items-center gap-2 text-xs py-1.5">
          <div class="w-1.5 h-1.5 rounded-full bg-amber-400" />
          <span class="text-gray-700 flex-1">{{ r.concept || '未命名概念' }}</span>
          <span class="text-gray-400 text-[10px]">{{ r.next_review_at ? new Date(r.next_review_at).toLocaleDateString() : '' }}</span>
          <button class="text-[10px] text-amber-600 hover:text-amber-800 font-medium" @click="goLearn(r.concept)">去复习</button>
        </div>
      </div>
    </div>

    <!-- 视频微课播放模态窗 -->
    <VideoRenderPanel
      :visible="showVideoPanel"
      :videoUrl="videoPanelUrl"
      :studentId="props.studentId"
      @close="showVideoPanel = false"
    />

    <!-- Drawer/Viewer for Resource Matrix -->
    <Teleport to="body">
    <div v-if="activeResource" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm transition-opacity p-4 sm:p-6" @click="closeResourceViewer">
      <div class="w-full max-w-2xl max-h-[calc(100vh-2rem)] sm:max-h-[calc(100vh-3rem)] bg-white rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-slide-in" @click.stop>
        
        <!-- Drawer Header -->
        <div class="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50">
          <div>
            <div class="flex items-center gap-2">
              <span class="px-2 py-0.5 text-[10px] font-bold bg-indigo-50 text-indigo-700 rounded-lg">
                {{ activeResource.res.resource_type }}
              </span>
              <span class="text-xs text-slate-400">智能体：{{ activeResource.res.role }}</span>
            </div>
            <h3 class="text-base font-bold text-gray-800 mt-1">
              概念强化：<span class="text-indigo-600">{{ activeResource.concept }}</span>
            </h3>
          </div>
          <button @click="closeResourceViewer" class="p-1 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-600 transition-colors">
            <span class="text-xl">✕</span>
          </button>
        </div>

        <!-- Drawer Content -->
        <div class="flex-1 min-h-0 overflow-y-auto overscroll-contain p-6 space-y-4">
          
          <!-- Case 1: NOT GENERATED -->
          <div v-if="activeResource.res.status === 'not_generated' && !isGenerating" class="flex flex-col items-center justify-center py-12 text-center space-y-4">
            <div class="w-16 h-16 rounded-full bg-slate-100 flex items-center justify-center text-2xl">
              💡
            </div>
            <div class="max-w-md">
              <h4 class="text-sm font-bold text-gray-800">该资源尚未生成</h4>
              <p class="text-xs text-slate-500 mt-1">您可以点击下方按钮，系统将调用专属于该维度的 AI 智能体实时根据您的学情为您量身生成定制内容。</p>
            </div>
            <div class="bg-slate-50 border border-slate-100 rounded-xl p-4 w-full text-left">
              <p class="text-[11px] font-bold text-slate-600 mb-1">🔍 生成预览大纲：</p>
              <p class="text-xs text-slate-500 leading-relaxed">{{ activeResource.res.overview }}</p>
            </div>
            <button @click="generateResource" 
              class="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs rounded-xl shadow-md transition-all flex items-center gap-1.5">
              🚀 开始一键生成
            </button>
          </div>

          <!-- Case 2: GENERATING -->
          <div v-else-if="isGenerating" class="flex flex-col items-center justify-center py-16 text-center space-y-4">
            <div class="animate-spin w-8 h-8 border-4 border-indigo-600 border-t-transparent rounded-full" />
            <div>
              <h4 class="text-sm font-bold text-gray-800">智能体正在深度生成中...</h4>
              <p class="text-xs text-slate-400 mt-1">正在调用【{{ activeResource.res.role }}】智能体进行推理与编写，请稍候 (5~15秒)...</p>
            </div>
          </div>

          <!-- Case 3: GENERATED / VIEWING -->
          <div v-else-if="activeResource.res.status === 'generated'" class="space-y-4">
            
            <!-- Dynamic Actions depending on type -->
            <div class="bg-indigo-50/50 border border-indigo-100/50 rounded-xl p-4 flex items-center justify-between">
              <div class="space-y-0.5">
                <p class="text-xs font-bold text-indigo-900">✨ 资源已就绪并同步存入您的学习笔记本</p>
                <p class="text-[10px] text-indigo-700">您可以直接在此阅读，也可以点击右侧进入独立的工作空间学习。</p>
              </div>
              
              <!-- Redirection shortcut -->
              <button @click="openInWorkspace" 
                class="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-lg flex items-center gap-1 shrink-0 shadow-sm transition-all">
                进入工作空间 →
              </button>
            </div>

            <!-- Video Player Block (if video resource) -->
            <div v-if="activeResource.res.role === '视频推荐官' || activeResource.res.role === '虚拟导演' || activeResource.res.resource_type === '自适应推荐视频' || activeResource.res.resource_type === '虚拟人视频脚本'" class="space-y-3">
              <template v-if="safeParseJson(activeResourceContent).length > 0">
                <VideoPlayerCard 
                  :videos="safeParseJson(activeResourceContent)" 
                  :concept="activeResource.concept" 
                />
              </template>
              <template v-else>
                <div class="markdown-body bg-slate-50/50 border border-slate-100 rounded-xl p-5 overflow-x-auto text-xs leading-relaxed max-w-full text-slate-700">
                  <div class="prose prose-sm max-w-none text-xs text-gray-700 leading-relaxed" v-html="renderMarkdown(activeResourceContent || '内容加载中...', activeResource?.res?.resource_type || '', activeResource?.concept || '')"></div>
                </div>
              </template>
            </div>

            <!-- Content Area (Markdown render, for regular resources) -->
            <div v-else class="markdown-body bg-slate-50/50 border border-slate-100 rounded-xl p-5 overflow-x-auto text-xs leading-relaxed max-w-full text-slate-700">
              <div class="prose prose-sm max-w-none text-xs text-gray-700 leading-relaxed" v-html="renderMarkdown(activeResourceContent || '内容加载中...', activeResource?.res?.resource_type || '', activeResource?.concept || '')"></div>
            </div>

          </div>

        </div>

        <!-- Drawer Footer -->
        <div class="px-6 py-4 border-t border-slate-100 bg-slate-50 flex justify-end">
          <button @click="closeResourceViewer" class="px-4 py-2 border border-slate-200 text-slate-600 hover:bg-slate-100 text-xs font-bold rounded-xl transition-all">
            关闭窗口
          </button>
        </div>

      </div>
    </div>
    </Teleport>

  </div>
</template>

<style scoped>
@keyframes slide-in {
  from {
    transform: translateX(100%);
  }
  to {
    transform: translateX(0);
  }
}

.animate-slide-in {
  animation: slide-in 0.25s cubic-bezier(0.16, 1, 0.3, 1) forwards;
}

.dashboard-page {
  padding-bottom: 2rem;
}

.dashboard-overview {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(360px, .82fr);
  gap: 18px;
}

.dashboard-hero {
  position: relative;
  display: flex;
  min-height: 318px;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
  padding: clamp(24px, 3vw, 38px);
  background:
    radial-gradient(circle at 85% 18%, rgba(191, 205, 194, .18), transparent 34%),
    #27312b;
}

.dashboard-hero::after {
  content: '';
  position: absolute;
  right: -80px;
  bottom: -145px;
  width: 360px;
  height: 360px;
  border: 1px solid rgba(255,255,255,.09);
  border-radius: 50%;
  box-shadow: 0 0 0 46px rgba(255,255,255,.025), 0 0 0 92px rgba(255,255,255,.018);
}

.dashboard-hero__content, .dashboard-hero__meta { position: relative; z-index: 1; }
.dashboard-hero__eyebrow { display: inline-flex; align-items: center; gap: 6px; color: #c7d4ca; font-size: 10px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.dashboard-hero h1 { max-width: 650px; margin: 15px 0 10px; color: #fbfcfa; font-size: clamp(27px, 3.2vw, 43px); font-weight: 620; letter-spacing: -.055em; line-height: 1.08; }
.dashboard-hero p { max-width: 610px; margin: 0; color: rgba(237,243,238,.62); font-size: 12px; line-height: 1.75; }
.dashboard-hero__actions { display: flex; align-items: center; gap: 8px; margin-top: 24px; }
.dashboard-hero__actions :deep(.ui-button--secondary) { color: #2e3931; background: #eff3ee; }
.dashboard-hero__actions :deep(.ui-button--ghost) { color: #d4ddd6; }
.dashboard-hero__meta { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 30px; padding-top: 18px; border-top: 1px solid rgba(255,255,255,.09); }
.dashboard-hero__meta span, .dashboard-hero__meta strong { display: block; }
.dashboard-hero__meta span { margin-bottom: 4px; color: rgba(233,240,235,.38); font-size: 9px; }
.dashboard-hero__meta strong { overflow: hidden; color: rgba(250,252,250,.88); font-size: 11px; font-weight: 580; text-overflow: ellipsis; white-space: nowrap; }

.dashboard-trend-status { display: inline-flex; align-items: center; gap: 6px; color: #778179; font-size: 9px; }
.dashboard-trend-status span { width: 6px; height: 6px; border-radius: 50%; background: #829187; box-shadow: 0 0 0 4px rgba(130,145,135,.12); }
.dashboard-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; }

.dashboard-insight {
  border-color: rgba(106, 116, 108, .1) !important;
  background: rgba(250, 251, 248, .84) !important;
  box-shadow: 0 16px 42px rgba(45, 56, 49, .06);
}

.dashboard-page :deep(.bg-white.rounded-2xl),
.dashboard-page :deep(.bg-white.rounded-xl) {
  border-color: rgba(42,54,46,.075);
  background-color: rgba(253,254,251,.86);
  box-shadow: 0 12px 32px rgba(45,56,49,.05);
}

.dashboard-skeleton { max-width: 1380px; margin: 0 auto; }
.dashboard-skeleton__hero, .dashboard-skeleton__grid span { position: relative; overflow: hidden; border-radius: 22px; background: #e4e7e2; }
.dashboard-skeleton__hero { height: 318px; }
.dashboard-skeleton__grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 18px; }
.dashboard-skeleton__grid span { height: 150px; }
.dashboard-skeleton__hero::after, .dashboard-skeleton__grid span::after { content: ''; position: absolute; inset: 0; transform: translateX(-100%); background: linear-gradient(90deg, transparent, rgba(255,255,255,.55), transparent); animation: skeleton-shimmer 1.6s infinite; }
@keyframes skeleton-shimmer { to { transform: translateX(100%); } }

@media (max-width: 1100px) {
  .dashboard-overview { grid-template-columns: 1fr; }
  .dashboard-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 640px) {
  .dashboard-page {
    padding-bottom: 1rem;
  }
  .dashboard-hero { min-height: 360px; }
  .dashboard-hero__meta { grid-template-columns: 1fr; }
  .dashboard-metrics, .dashboard-skeleton__grid { grid-template-columns: 1fr 1fr; }
  .dashboard-trend-status { display: none; }
}
</style>
