<script setup>
import { computed, onMounted, ref } from 'vue'
import { BarChart3, CalendarRange, CircleAlert, Download, RefreshCw, UsersRound } from '@lucide/vue'
import { listTeachingClasses } from '../api/courseGovernance'
import { createTeachingAnalyticsReport, downloadTeachingAnalyticsReport, listTeachingAnalyticsReports } from '../api/teachingAnalytics'

const loading = ref(true)
const busy = ref(false)
const error = ref('')
const classes = ref([])
const classId = ref('')
const reports = ref([])
const selected = ref(null)
const end = new Date()
const start = new Date(end.getTime() - 7 * 86400000)
function localDate(value) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const periodStart = ref(localDate(start))
const periodEnd = ref(localDate(end))
const metrics = computed(() => selected.value?.metrics || [])
const learners = computed(() => selected.value?.learners || [])

function message(value) { const detail = value?.detail || value?.message || value; return typeof detail === 'string' ? detail : detail?.message || JSON.stringify(detail || '') }
function metricValue(item) { if (item.value == null) return '暂无'; return item.unit === 'ratio' ? `${Math.round(item.value * 100)}%` : `${Math.round(item.value)} 分钟` }
function localDay(value) { return value ? value.slice(0, 10) : '' }

async function loadReports() {
  if (!classId.value) { reports.value = []; selected.value = null; return }
  const data = await listTeachingAnalyticsReports(classId.value)
  reports.value = data.items || []
  selected.value = reports.value[0] || null
}

async function load() {
  loading.value = true; error.value = ''
  try {
    const data = await listTeachingClasses()
    classes.value = (data.items || []).filter(item => item.can_manage)
    if (!classId.value && classes.value.length) classId.value = classes.value[0].id
    await loadReports()
  } catch (e) { error.value = message(e) }
  finally { loading.value = false }
}

async function generate() {
  if (!classId.value) return
  busy.value = true; error.value = ''
  try {
    selected.value = await createTeachingAnalyticsReport({ class_id: classId.value, period_start: `${periodStart.value}T00:00:00`, period_end: `${periodEnd.value}T23:59:59` })
    await loadReports()
  } catch (e) { error.value = message(e) }
  finally { busy.value = false }
}

async function changeClass() { try { await loadReports() } catch (e) { error.value = message(e) } }
onMounted(load)
</script>

<template>
  <main class="analytics-page" data-testid="teaching-analytics-page">
    <header>
      <div><p class="eyebrow"><BarChart3 :size="14" /> Explainable teaching analytics</p><h1>教学分析与周期报告</h1><p>每项指标都公开公式、时间窗、来源、样本量和演示阈值依据；报告冻结后可复核和导出。</p></div>
      <button class="icon" aria-label="刷新教学分析" title="刷新" @click="load"><RefreshCw :size="17" /></button>
    </header>
    <div v-if="error" class="error"><CircleAlert :size="15" />{{ error }}</div>
    <div v-if="loading" class="loading"><RefreshCw class="spin" :size="16" />正在读取教学班与周期报告</div>
    <template v-else>
      <section class="controls">
        <label>教学班<select v-model="classId" @change="changeClass"><option v-for="item in classes" :key="item.id" :value="item.id">{{ item.title }} · {{ item.term }}</option></select></label>
        <label>开始日期<input v-model="periodStart" type="date" /></label>
        <label>结束日期<input v-model="periodEnd" type="date" /></label>
        <button class="primary" :disabled="busy || !classId" @click="generate"><CalendarRange :size="15" />生成冻结报告</button>
      </section>
      <section v-if="!classes.length" class="empty"><UsersRound :size="34" /><h2>尚无可管理教学班</h2><p>请先在“班级与任务”中创建教学班并添加学习者。</p></section>
      <section v-else-if="!selected" class="empty"><BarChart3 :size="34" /><h2>尚无周期报告</h2><p>选择时间窗生成第一份可解释报告。</p></section>
      <template v-else>
        <section class="report-meta">
          <div><strong>{{ selected.class.title }}</strong><span>{{ localDay(selected.period.start) }} 至 {{ localDay(selected.period.end) }} · {{ selected.population.active_learners }} 名活动学员</span></div>
          <span class="demo">比赛演示指标</span>
          <button title="导出 JSON" aria-label="导出 JSON" @click="downloadTeachingAnalyticsReport(selected.id, 'json')"><Download :size="15" />JSON</button>
          <button title="导出 CSV" aria-label="导出 CSV" @click="downloadTeachingAnalyticsReport(selected.id, 'csv')"><Download :size="15" />CSV</button>
        </section>
        <section class="metric-grid">
          <article v-for="item in metrics" :key="item.key" class="metric" :data-testid="`metric-${item.key}`">
            <div class="metric-top"><span>{{ item.name }}</span><b :class="item.state">{{ metricValue(item) }}</b></div>
            <p>{{ item.formula }}</p>
            <dl><div><dt>样本</dt><dd>{{ item.sample_size }} · {{ item.sample_state === 'small_sample' ? '小样本' : '样本满足演示门槛' }}</dd></div><div><dt>来源</dt><dd>{{ item.sources.join(' + ') }}</dd></div><div><dt>阈值依据</dt><dd>{{ item.threshold_basis }}</dd></div></dl>
          </article>
        </section>
        <section class="drilldown">
          <div class="section-title"><div><h2>学员路径负担下钻</h2><p>由规范路径节点预计上限汇总，不替代教师判断。</p></div><span>{{ learners.length }} 人</span></div>
          <div class="table"><div class="thead"><span>学员</span><span>学习事件</span><span>测评均分</span><span>路径完成</span><span>待完成负担</span></div><div v-for="row in learners" :key="row.learner_public_id" class="tr"><strong>{{ row.learner_public_id }}</strong><span>{{ row.event_count }} 条</span><span>{{ row.assessment_average == null ? '暂无' : `${Math.round(row.assessment_average * 100)}%` }}</span><span>{{ row.path_completion_rate == null ? '暂无' : `${Math.round(row.path_completion_rate * 100)}%` }}</span><span :class="row.burden_state">{{ row.pending_burden_minutes }} 分钟</span></div></div>
        </section>
      </template>
    </template>
  </main>
</template>

<style scoped>
.analytics-page{max-width:1280px;margin:0 auto;padding:6px 2px 42px;color:#243028}.analytics-page>header{display:flex;justify-content:space-between;gap:20px;padding:24px 2px 20px;border-bottom:1px solid #dfe4df}.analytics-page h1{font-size:24px;margin:6px 0;font-weight:760}.analytics-page header p:last-child{font-size:12px;color:#69756d;max-width:780px}.eyebrow{display:flex;align-items:center;gap:6px;color:#356b50;font-size:10px;font-weight:700;text-transform:uppercase}.icon{width:36px;height:36px;display:grid;place-items:center;border:1px solid #d8dfd9;background:#fff;border-radius:7px}.error,.loading{display:flex;align-items:center;gap:7px;padding:12px 14px;margin-top:14px;font-size:11px}.error{background:#fff1ef;color:#963f35}.loading{background:#f4f7f4}.controls{display:grid;grid-template-columns:1.4fr .8fr .8fr auto;gap:10px;align-items:end;padding:18px 0}.controls label{display:flex;flex-direction:column;gap:5px;font-size:10px;color:#6b776f}.controls input,.controls select{height:36px;border:1px solid #d7ded8;border-radius:6px;background:#fff;padding:0 9px;font-size:11px}.primary{height:36px;display:flex;align-items:center;gap:6px;border:0;border-radius:6px;background:#285a42;color:#fff;padding:0 13px;font-size:11px;font-weight:650}.empty{min-height:330px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;gap:8px}.empty h2{font-size:17px}.empty p{font-size:11px;color:#748078}.report-meta{display:flex;align-items:center;gap:9px;padding:12px 14px;background:#f5f7f5;border:1px solid #dfe4df}.report-meta>div{display:flex;flex:1;flex-direction:column}.report-meta strong{font-size:13px}.report-meta span{font-size:10px;color:#718078}.report-meta .demo{padding:4px 7px;background:#fff4e5;color:#82551f}.report-meta button{display:flex;align-items:center;gap:5px;border:1px solid #d5ddd7;background:#fff;border-radius:5px;padding:6px 8px;font-size:10px}.metric-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:14px}.metric{border:1px solid #dde3de;background:#fff;padding:15px}.metric-top{display:flex;justify-content:space-between;align-items:center;font-size:11px}.metric-top b{font-size:18px;color:#2d6547}.metric-top b.attention{color:#a44e3f}.metric>p{font-size:10px;color:#66736b;margin:8px 0 12px;min-height:30px}.metric dl{display:grid;gap:6px}.metric dl div{display:grid;grid-template-columns:58px 1fr;gap:8px;font-size:9px}.metric dt{color:#8a948e}.metric dd{color:#4d5b52}.drilldown{margin-top:22px}.section-title{display:flex;justify-content:space-between;align-items:end;margin-bottom:9px}.section-title h2{font-size:16px}.section-title p{font-size:10px;color:#748078}.section-title>span{font-size:10px}.table{border:1px solid #dfe4df;background:#fff}.thead,.tr{display:grid;grid-template-columns:1.5fr .7fr .8fr .8fr .9fr;gap:10px;padding:11px 14px;font-size:10px}.thead{background:#f5f7f5;color:#748078}.tr{border-top:1px solid #e4e9e5;align-items:center}.tr strong{font-size:10px}.tr .attention{color:#a44e3f;font-weight:700}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:760px){.controls{grid-template-columns:1fr 1fr}.controls label:first-child,.primary{grid-column:1/-1}.metric-grid{grid-template-columns:1fr}.report-meta{align-items:flex-start;flex-wrap:wrap}.report-meta>div{flex-basis:100%}.table{overflow-x:auto}.thead,.tr{min-width:720px}}
</style>
