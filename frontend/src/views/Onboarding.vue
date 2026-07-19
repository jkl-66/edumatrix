<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { updateStudentProfile } from '../api'
import { 
  GraduationCap, 
  Target, 
  BookOpen, 
  Compass, 
  ChevronRight, 
  ChevronLeft,
  Sparkles
} from '@lucide/vue'

const router = useRouter()
const currentStep = ref(1)
const loading = ref(false)
const error = ref('')

// User State selection
const major = ref('人工智能')
const customMajor = ref('')

const selectedGoals = ref([])

const targetCourse = ref('机器学习导论')
const customCourse = ref('')

const selectedPreferences = ref([])

// Constants list
const majors = ['计算机科学与技术', '人工智能', '软件工程', '其他']
const goalsList = [
  { label: '期末复习冲刺', value: '期末复习冲刺', desc: '高强度覆盖面广的核心考点串讲' },
  { label: '科研学术深造', value: '科研学术深造', desc: '学术论文多模态检索与前沿公式推导' },
  { label: '求职面试准备', value: '求职面试准备', desc: '编程沙箱真题与核心实操算法练习' }
]

const courses = [
  { name: '机器学习导论', desc: '以逻辑回归、支持向量机、混淆矩阵为核心' },
  { name: '深度学习与计算机视觉', desc: '以卷积层、最大池化、CNN 前向传播为核心' },
  { name: '数据结构与算法分析', desc: '以树、图、拓扑排序、沙箱实操为核心' },
  { name: '其他自选课程', desc: '手动填写您想学习的任何课程科目' }
]

const preferenceOptions = [
  { value: '分步引导', desc: '循序渐进，将复杂推导拆解为易读的微步' },
  { value: '具体例子', desc: '理论结合实例，用实际场景加深具象化理解' },
  { value: '对比解析', desc: '相似概念横向PK，理清易错和易混淆的细节' },
  { value: '图示演示', desc: '一图胜千言，提供 Mermaid 拓扑图与结构可视化' },
  { value: '代码实操', desc: '手脑结合，提供沙箱运行校验与动手写代码' }
]

// Dynamic Style Name Generator based on checkbox selection combinations
const generatedStyleName = computed(() => {
  const list = selectedPreferences.value
  if (list.length === 0) return '⏳ 请至少选择一项偏好'
  if (list.length === 5) return '👑 全脑开发矩阵导师'
  if (list.length === 4) return '✨ 极客全能融会式'
  if (list.length === 3) return '⚡ 多模态自适应协作式'
  
  const sorted = [...list].sort()
  
  if (list.length === 2) {
    if (sorted.includes('分步引导') && sorted.includes('对比解析')) return '🟢 苏格拉底启发式'
    if (sorted.includes('具体例子') && sorted.includes('代码实操')) return '🔴 案例驱动工程式'
    if (sorted.includes('分步引导') && sorted.includes('具体例子')) return '🟠 渐进铺垫引导式'
    if (sorted.includes('对比解析') && sorted.includes('图示演示')) return '🟣 概念流形对比式'
    if (sorted.includes('代码实操') && sorted.includes('对比解析')) return '🧪 探索性工程诊断式'
    if (sorted.includes('图示演示') && sorted.includes('代码实操')) return '🔬 视觉几何实操式'
    return '💫 混双个性交叉式'
  }
  
  // Length is 1
  const single = list[0]
  if (single === '分步引导') return '💡 阶梯渐进引导式'
  if (single === '具体例子') return '📖 启发例证传授式'
  if (single === '对比解析') return '🔍 辩证剖析辨析式'
  if (single === '图示演示') return '🖼️ 形象几何直观式'
  if (single === '代码实操') return '💻 沙箱极客攻坚式'
  
  return '🌱 自适应渐进探索式'
})

// Step Validations
const step1Valid = computed(() => {
  const hasMajor = major.value !== '其他' || (customMajor.value && customMajor.value.trim().length > 0)
  const hasGoals = selectedGoals.value.length > 0
  return hasMajor && hasGoals
})

const step2Valid = computed(() => {
  return targetCourse.value !== '其他自选课程' || (customCourse.value && customCourse.value.trim().length > 0)
})

const step3Valid = computed(() => {
  return selectedPreferences.value.length > 0
})

function toggleGoal(goal) {
  const index = selectedGoals.value.indexOf(goal)
  if (index > -1) {
    selectedGoals.value.splice(index, 1)
  } else {
    selectedGoals.value.push(goal)
  }
}

function togglePreference(pref) {
  const index = selectedPreferences.value.indexOf(pref)
  if (index > -1) {
    selectedPreferences.value.splice(index, 1)
  } else {
    selectedPreferences.value.push(pref)
  }
}

async function finish() {
  if (!step3Valid.value) return
  
  const studentId = localStorage.getItem('edumatrix_student_id')
  if (!studentId) {
    error.value = '学生身份丢失，请重新登录'
    return
  }
  
  loading.value = true
  error.value = ''
  
  try {
    const finalMajor = major.value === '其他' ? customMajor.value.trim() : major.value
    const finalCourse = targetCourse.value === '其他自选课程' ? customCourse.value.trim() : targetCourse.value
    
    // 根据勾选推断认知风格
    let cognitiveStyle = '文本阅读导向'
    if (selectedPreferences.value.includes('代码实操')) {
      cognitiveStyle = '代码实操导向'
    } else if (selectedPreferences.value.includes('图示演示')) {
      cognitiveStyle = '视觉演示导向'
    }

    const hasIntrinsicGoal = selectedGoals.value.includes('科研学术深造')
    const motivation = hasIntrinsicGoal ? '内在动机' : '外在动机'

    const payload = {
      major: finalMajor,
      target_course: finalCourse,
      learning_goals: selectedGoals.value,
      learning_preferences: selectedPreferences.value,
      cognitive_style: cognitiveStyle,
      motivation_type: motivation
    }
    
    await updateStudentProfile(studentId, payload)
    localStorage.setItem('edumatrix_onboarded', 'true')
    
    // 初始化成功，重定向到系统首页（Dashboard）
    router.push('/')
  } catch (e) {
    error.value = e.response?.data?.detail || '保存学情失败，请检查网络后再试'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="onboarding-page min-h-screen bg-[#f1f5f2] text-slate-800 flex items-center justify-center p-4 relative overflow-hidden font-sans">
    <!-- Fine grain overlay -->
    <div class="absolute inset-0 bg-noise opacity-[0.02] pointer-events-none"></div>
    
    <!-- Background glows -->
    <div class="absolute top-[-20%] left-[-20%] w-[60%] h-[60%] bg-[#0ea5e9] opacity-[0.04] blur-[180px] rounded-full pointer-events-none"></div>
    <div class="absolute bottom-[-20%] right-[-20%] w-[60%] h-[60%] bg-[#10b981] opacity-[0.04] blur-[180px] rounded-full pointer-events-none"></div>

    <div class="w-full max-w-xl z-10 relative">
      <!-- Steps Indicator -->
      <div class="flex items-center justify-between mb-8 px-4">
        <span class="text-xs text-gray-500 font-semibold tracking-wider uppercase">学情初始化 ({{ currentStep }}/3)</span>
        <div class="flex gap-1.5">
          <div 
            v-for="step in 3" 
            :key="step" 
            class="h-1 rounded-full transition-all duration-300"
            :class="[
              step === currentStep ? 'w-6 bg-[#0ea5e9]' : '',
              step < currentStep ? 'w-3 bg-[#10b981]' : '',
              step > currentStep ? 'w-3 bg-white/[0.08]' : ''
            ]"
          ></div>
        </div>
      </div>

      <!-- Main card -->
      <div class="bg-[#131926]/70 backdrop-blur-md rounded-2xl border border-white/[0.06] p-8 shadow-2xl shadow-black/30 min-h-[460px] flex flex-col justify-between">
        
        <!-- Step 1: Major & Goals -->
        <div v-if="currentStep === 1" class="space-y-5">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-8 h-8 rounded-lg bg-[#0ea5e9]/10 flex items-center justify-center">
              <GraduationCap :size="16" class="text-[#0ea5e9]" />
            </div>
            <h2 class="text-lg font-bold text-white">专业背景与学习目标</h2>
          </div>
          
          <div>
            <label class="text-xs font-semibold text-gray-400 block mb-2">您当前的主修专业</label>
            <div class="grid grid-cols-2 gap-3">
              <button 
                v-for="m in majors" 
                :key="m"
                @click="major = m"
                class="px-4 py-3 rounded-xl border text-sm font-medium transition-all text-center"
                :class="[
                  major === m 
                    ? 'border-[#0ea5e9] bg-[#0ea5e9]/5 text-white' 
                    : 'border-white/[0.06] bg-[#0d121f] text-gray-400 hover:bg-white/[0.02]'
                ]"
              >
                {{ m }}
              </button>
            </div>
            
            <!-- Custom Major Input Box -->
            <div v-if="major === '其他'" class="mt-3">
              <input 
                v-model="customMajor" 
                type="text" 
                class="w-full px-4 py-2.5 text-xs rounded-xl border border-white/[0.08] bg-[#0d121f] text-white focus:border-[#0ea5e9] focus:ring-2 focus:ring-[#0ea5e9]/10 outline-none transition-all" 
                placeholder="请输入您的自定义专业名称（例如：应用物理学、金融数学）" 
              />
            </div>
          </div>

          <div>
            <label class="text-xs font-semibold text-gray-400 block mb-2">选择您的核心学习诉求 (可多选)</label>
            <div class="space-y-2.5">
              <button 
                v-for="goal in goalsList" 
                :key="goal.value"
                @click="toggleGoal(goal.value)"
                class="w-full px-4 py-3 rounded-xl border text-left transition-all flex items-center justify-between"
                :class="[
                  selectedGoals.includes(goal.value)
                    ? 'border-[#10b981] bg-[#10b981]/5 text-white' 
                    : 'border-white/[0.06] bg-[#0d121f] text-gray-400 hover:bg-white/[0.02]'
                ]"
              >
                <div>
                  <div class="text-sm font-semibold">{{ goal.label }}</div>
                  <div class="text-[10px] text-gray-500 mt-0.5">{{ goal.desc }}</div>
                </div>
                <div 
                  class="w-4 h-4 rounded border flex items-center justify-center text-xs"
                  :class="[
                    selectedGoals.includes(goal.value)
                      ? 'border-[#10b981] bg-[#10b981] text-[#0b0f19] font-bold' 
                      : 'border-white/[0.2]'
                  ]"
                >
                  <span v-if="selectedGoals.includes(goal.value)">✓</span>
                </div>
              </button>
            </div>
          </div>
        </div>

        <!-- Step 2: Target Course -->
        <div v-if="currentStep === 2" class="space-y-5">
          <div class="flex items-center gap-3 mb-2">
            <div class="w-8 h-8 rounded-lg bg-[#0ea5e9]/10 flex items-center justify-center">
              <BookOpen :size="16" class="text-[#0ea5e9]" />
            </div>
            <h2 class="text-lg font-bold text-white">选择目标学习课程</h2>
          </div>
          
          <div class="grid grid-cols-1 gap-2.5">
            <button 
              v-for="c in courses" 
              :key="c.name"
              @click="targetCourse = c.name"
              class="w-full px-4 py-3.5 rounded-xl border text-left transition-all relative overflow-hidden"
              :class="[
                targetCourse === c.name 
                  ? 'border-[#0ea5e9] bg-[#0ea5e9]/5 text-white' 
                  : 'border-white/[0.06] bg-[#0d121f] text-gray-400 hover:bg-white/[0.02]'
              ]"
            >
              <div class="text-sm font-bold">{{ c.name }}</div>
              <div class="text-[10px] text-gray-500 mt-0.5 leading-relaxed">{{ c.desc }}</div>
            </button>
          </div>

          <!-- Custom Course Input & Notification box -->
          <div v-if="targetCourse === '其他自选课程'" class="space-y-2.5 mt-3 animate-fadeIn">
            <input 
              v-model="customCourse" 
              type="text" 
              class="w-full px-4 py-2.5 text-xs rounded-xl border border-white/[0.08] bg-[#0d121f] text-white focus:border-[#0ea5e9] focus:ring-2 focus:ring-[#0ea5e9]/10 outline-none transition-all" 
              placeholder="请输入您要自选学习的学科课程名称" 
            />
            <div class="text-[10px] text-amber-400 bg-amber-950/20 border border-amber-900/30 rounded-xl p-3 leading-relaxed flex gap-2">
              <span>💡</span>
              <p>提示：该课程属于未建档的非内置课程。请在注册完成进入主系统后，前往左侧【知识库】上传该课程的参考资料或电子讲义，以便多智能体协同矩阵能精准理解并为您答疑解惑！</p>
            </div>
          </div>
        </div>

        <!-- Step 3: Custom Preferences & Dynamic Style -->
        <div v-if="currentStep === 3" class="space-y-4">
          <div class="flex items-center gap-3 mb-1">
            <div class="w-8 h-8 rounded-lg bg-[#10b981]/10 flex items-center justify-center">
              <Compass :size="16" class="text-[#10b981]" />
            </div>
            <h2 class="text-lg font-bold text-white">定制教学偏好支持</h2>
          </div>
          
          <p class="text-xs text-gray-400">请选择您平时最受用的学习支持偏好（可多选，系统将自动汇聚风格名）：</p>
          
          <div class="space-y-2 max-h-[220px] overflow-y-auto pr-1">
            <button 
              v-for="pref in preferenceOptions" 
              :key="pref.value"
              @click="togglePreference(pref.value)"
              class="w-full px-4 py-2.5 rounded-xl border text-left transition-all flex items-center justify-between"
              :class="[
                selectedPreferences.includes(pref.value)
                  ? 'border-[#10b981] bg-[#10b981]/5 text-white' 
                  : 'border-white/[0.06] bg-[#0d121f] text-gray-400 hover:bg-white/[0.02]'
              ]"
            >
              <div>
                <div class="text-xs font-bold">{{ pref.value }}</div>
                <div class="text-[9px] text-gray-500 mt-0.5">{{ pref.desc }}</div>
              </div>
              <div 
                class="w-3.5 h-3.5 rounded border flex items-center justify-center text-[10px]"
                :class="[
                  selectedPreferences.includes(pref.value)
                    ? 'border-[#10b981] bg-[#10b981] text-[#0b0f19] font-bold' 
                    : 'border-white/[0.2]'
                ]"
              >
                <span v-if="selectedPreferences.includes(pref.value)">✓</span>
              </div>
            </button>
          </div>

          <!-- Dynamic Style Preview Glow Box -->
          <div class="bg-gradient-to-r from-[#0ea5e9]/10 to-[#10b981]/10 border border-[#0ea5e9]/20 rounded-xl p-3 mt-4">
            <span class="text-[9px] text-gray-400 block mb-0.5">系统已为您自动生成专属风格：</span>
            <span class="text-xs font-bold text-transparent bg-clip-text bg-gradient-to-r from-[#0ea5e9] to-[#10b981] flex items-center gap-1.5">
              <Sparkles :size="12" class="text-[#0ea5e9]" />
              {{ generatedStyleName }}
            </span>
          </div>
          
          <div v-if="error" class="text-xs text-red-400 bg-red-950/40 border border-red-900/30 rounded-lg px-3 py-2">
            {{ error }}
          </div>
        </div>

        <!-- Controls Footer -->
        <div class="flex justify-between items-center border-t border-white/[0.04] pt-6 mt-6">
          <button 
            v-if="currentStep > 1"
            @click="currentStep--"
            class="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white font-semibold transition-all px-3 py-2"
          >
            <ChevronLeft :size="14" />
            <span>上一步</span>
          </button>
          <div v-else></div>

          <!-- Step 1 Button -->
          <button 
            v-if="currentStep === 1"
            @click="currentStep = 2"
            :disabled="!step1Valid"
            class="flex items-center gap-1.5 text-xs font-semibold px-4 py-2 bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] rounded-xl text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <span>下一步</span>
            <ChevronRight :size="14" />
          </button>

          <!-- Step 2 Button -->
          <button 
            v-else-if="currentStep === 2"
            @click="currentStep = 3"
            :disabled="!step2Valid"
            class="flex items-center gap-1.5 text-xs font-semibold px-4 py-2 bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.06] rounded-xl text-white transition-all disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <span>下一步</span>
            <ChevronRight :size="14" />
          </button>
          
          <!-- Step 3 Submit Button -->
          <button 
            v-else
            @click="finish"
            :disabled="loading || !step3Valid"
            class="flex items-center gap-1.5 text-xs font-bold px-5 py-2.5 bg-gradient-to-r from-[#0ea5e9] to-[#10b981] text-[#0b0f19] rounded-xl shadow-lg transition-all hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <span>{{ loading ? '同步配置中...' : '进入我的学习矩阵' }}</span>
          </button>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
.onboarding-page { color: #243128; }
.onboarding-page [class*="bg-[#131926]"],
.onboarding-page [class*="bg-[#0d121f]"],
.onboarding-page [class*="bg-[#0b0f19]"] { background-color: rgba(255, 255, 255, 0.92) !important; }
.onboarding-page [class*="text-white"],
.onboarding-page [class*="text-[#f3f4f6]"] { color: #243128 !important; }
.onboarding-page [class*="text-gray-400"] { color: #64756b !important; }
.onboarding-page [class*="border-white"] { border-color: #dbe5df !important; }
.onboarding-page [class*="border-[#0ea5e9]"] { border-color: #2d9b7d !important; }
.onboarding-page [class*="bg-[#0ea5e9]"] { background-color: #2d9b7d !important; }
.onboarding-page [class*="text-[#0ea5e9]"] { color: #258b70 !important; }
.onboarding-page [class*="bg-gradient-to-r"] { background: #258b70 !important; color: white !important; }
.onboarding-page [class*="text-[#0b0f19]"] { color: white !important; }
.bg-noise {
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
}
.animate-fadeIn {
  animation: fadeIn 0.25s ease-out forwards;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
