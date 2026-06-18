<script setup>
import { ref, onMounted } from 'vue'
import { healthCheck, getDatasets, getProgress, getTeacherDashboard, exportProfilePDF } from '../api'
import { Activity, Brain, BarChart3, ArrowRight, Sparkles, Users, FileText, StickyNote, Download, Loader2 } from '@lucide/vue'

const props = defineProps({ studentId: String })

const health = ref(null)
const datasets = ref([])
const teacherData = ref(null)
const loading = ref(true)
const exporting = ref(false)  // 任务 7.6: 导出加载动画

onMounted(async () => {
  try {
    const [h, ds, td] = await Promise.all([
      healthCheck(),
      getDatasets(),
      getTeacherDashboard().catch(() => null),
    ])
    health.value = h
    datasets.value = ds.datasets || []
    teacherData.value = td
  } catch (e) {
    console.error('Dashboard load error:', e)
  } finally {
    loading.value = false
  }
})

function dimValue(dim) {
  return dim[1]?.value || 0
}

function dimColor(val) {
  return val > 0.6 ? 'bg-emerald-500' : val > 0.3 ? 'bg-amber-500' : 'bg-red-500'
}

// 任务 7.6: 一键导出学情诊断 PDF
async function exportPDF() {
  exporting.value = true
  try {
    const blob = await exportProfilePDF(props.studentId)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    const now = new Date().toISOString().slice(0, 10)
    a.download = `EduMatrix_学情报告_${props.studentId}_${now}.pdf`
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('PDF 导出失败:', e)
    alert('PDF 导出失败，请查看控制台日志')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div v-if="loading" class="flex items-center justify-center h-64">
    <div class="pulse-dot" />
    <span class="ml-3 text-gray-400 text-sm">加载中...</span>
  </div>

  <div v-else class="space-y-6 max-w-6xl">
    <!-- Top stats -->
    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="card">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs text-gray-500 font-medium">后端状态</p>
            <p class="text-lg font-semibold mt-1">{{ health?.status === 'ok' ? '运行正常' : '离线' }}</p>
          </div>
          <div class="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center">
            <Activity :size="20" class="text-emerald-600" />
          </div>
        </div>
        <p class="text-[10px] text-gray-400 mt-2">{{ health?.llm_provider || '-' }} / {{ (health?.llm_model || '').slice(0, 20) }}</p>
      </div>

      <div class="card">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs text-gray-500 font-medium">Agent 数量</p>
            <p class="text-lg font-semibold mt-1">1 + 3 + 5</p>
          </div>
          <div class="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center">
            <Brain :size="20" class="text-blue-600" />
          </div>
        </div>
        <p class="text-[10px] text-gray-400 mt-2">交互中枢 + 认知治理 + 资源工厂</p>
      </div>

      <div class="card">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs text-gray-500 font-medium">数据集</p>
            <p class="text-lg font-semibold mt-1">{{ datasets.length }}</p>
          </div>
          <div class="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center">
            <FileText :size="20" class="text-purple-600" />
          </div>
        </div>
        <p class="text-[10px] text-gray-400 mt-2">机器学习课程数据</p>
      </div>

      <div class="card">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs text-gray-500 font-medium">并发 Worker</p>
            <p class="text-lg font-semibold mt-1">{{ health?.concurrent_llm || '-' }}</p>
          </div>
          <div class="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center">
            <BarChart3 :size="20" class="text-amber-600" />
          </div>
        </div>
        <p class="text-[10px] text-gray-400 mt-2">限流 {{ health?.rate_limit_rpm || '-' }} RPM</p>
      </div>

      <!-- 任务 7.6: 一键导出学情报告按钮 -->
      <div class="card cursor-pointer hover:border-blue-300 transition-colors" @click="exportPDF">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-xs text-gray-500 font-medium">学情报告</p>
            <p class="text-lg font-semibold mt-1">{{ exporting ? '生成中...' : '一键导出' }}</p>
          </div>
          <div class="w-10 h-10 rounded-xl flex items-center justify-center"
            :class="exporting ? 'bg-green-100' : 'bg-blue-50'">
            <Download v-if="!exporting" :size="20" class="text-blue-600" />
            <Loader2 v-else :size="20" class="text-green-600 animate-spin" />
          </div>
        </div>
        <p class="text-[10px] text-gray-400 mt-2">{{ exporting ? '正在使用无头浏览器渲染 PDF...' : '含掌握度雷达图、错题归因、AI建议' }}</p>
      </div>
    </div>

    <!-- Learning dimensions -->
    <div v-if="teacherData" class="card">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-semibold text-gray-800">学习状态维度</h2>
        <router-link to="/learn" class="text-xs text-blue-600 hover:text-blue-700 flex items-center gap-1">
          开始学习 <ArrowRight :size="12" />
        </router-link>
      </div>
      <div class="grid grid-cols-2 md:grid-cols-5 gap-4">
        <div v-for="dim in teacherData.dimensions" :key="dim[0]" class="text-center">
          <div class="text-[10px] text-gray-500 mb-1.5 truncate">{{ (dim[1]?.label || dim[0]).slice(0, 12) }}</div>
          <div class="relative h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              class="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
              :class="dimColor(dimValue(dim))"
              :style="{ width: (dimValue(dim) * 100) + '%' }"
            />
          </div>
          <span class="text-[10px] text-gray-400 mt-1 block">{{ (dimValue(dim) * 100).toFixed(0) }}%</span>
        </div>
      </div>
    </div>

    <!-- Datasets -->
    <div>
      <h2 class="text-sm font-semibold text-gray-800 mb-3">可用数据集</h2>
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <div v-for="ds in datasets" :key="ds.id" class="card flex items-start gap-3">
          <FileText :size="16" class="text-gray-400 mt-0.5 shrink-0" />
          <div class="min-w-0">
            <p class="text-sm font-medium text-gray-800 truncate">{{ ds.name }}</p>
            <p class="text-xs text-gray-400 mt-0.5">{{ (ds.description || '-').slice(0, 60) }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- Quick actions -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <router-link to="/learn" class="card flex items-center gap-4 hover:border-blue-200 transition-colors group">
        <div class="w-10 h-10 rounded-xl bg-blue-50 flex items-center justify-center group-hover:bg-blue-100 transition-colors">
          <Sparkles :size="20" class="text-blue-600" />
        </div>
        <div>
          <p class="text-sm font-medium text-gray-800">开始智能对话</p>
          <p class="text-xs text-gray-400 mt-0.5">最大池化与平均池化区别？</p>
        </div>
      </router-link>

      <router-link to="/notes" class="card flex items-center gap-4 hover:border-purple-200 transition-colors group">
        <div class="w-10 h-10 rounded-xl bg-purple-50 flex items-center justify-center group-hover:bg-purple-100 transition-colors">
          <StickyNote :size="20" class="text-purple-600" />
        </div>
        <div>
          <p class="text-sm font-medium text-gray-800">管理学习笔记</p>
          <p class="text-xs text-gray-400 mt-0.5">记录和整理知识点</p>
        </div>
      </router-link>

      <router-link to="/teacher" class="card flex items-center gap-4 hover:border-amber-200 transition-colors group">
        <div class="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center group-hover:bg-amber-100 transition-colors">
          <Users :size="20" class="text-amber-600" />
        </div>
        <div>
          <p class="text-sm font-medium text-gray-800">教师看板</p>
          <p class="text-xs text-gray-400 mt-0.5">热力图与干预推荐</p>
        </div>
      </router-link>
    </div>
  </div>
</template>
