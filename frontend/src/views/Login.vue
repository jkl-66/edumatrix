<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { loginUser, registerUser, getStudentProfile } from '../api'
import { BrainCircuit, LogIn, User, Lock, Eye, EyeOff, UserPlus } from '@lucide/vue'

const router = useRouter()
const isRegister = ref(false)

// Input Fields
const username = ref('')
const password = ref('')
const displayName = ref('')
const confirmPassword = ref('')

const loading = ref(false)
const error = ref('')
const showPwd = ref(false)

async function handleAction() {
  if (isRegister.value) {
    await register()
  } else {
    await login()
  }
}

async function login() {
  if (!username.value.trim() || !password.value.trim()) return
  loading.value = true
  error.value = ''
  try {
    const data = await loginUser(username.value.trim(), password.value.trim())
    localStorage.setItem('edumatrix_token', data.access_token)
    localStorage.setItem('edumatrix_username', data.username || username.value.trim())
    localStorage.setItem('edumatrix_display_name', data.display_name || data.username || username.value.trim())
    localStorage.setItem('edumatrix_role', data.role || 'student')
    localStorage.setItem('edumatrix_student_id', data.student_id || data.username || username.value.trim())
    
    if (data.role === 'teacher') {
      router.push('/teacher')
    } else {
      try {
        const profile = await getStudentProfile(data.student_id)
        if (!profile || !profile.major || !profile.target_course) {
          localStorage.removeItem('edumatrix_onboarded')
          router.push('/onboarding')
        } else {
          localStorage.setItem('edumatrix_onboarded', 'true')
          router.push('/')
        }
      } catch (err) {
        router.push('/')
      }
    }
  } catch (e) {
    error.value = e.response?.data?.detail || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}

async function register() {
  if (!username.value.trim() || !password.value.trim()) return
  if (password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const name = displayName.value.trim() || username.value.trim()
    const data = await registerUser(username.value.trim(), password.value.trim(), name)
    localStorage.setItem('edumatrix_token', data.access_token)
    localStorage.setItem('edumatrix_username', data.username || username.value.trim())
    localStorage.setItem('edumatrix_display_name', data.display_name || name)
    localStorage.setItem('edumatrix_role', 'student')
    localStorage.setItem('edumatrix_student_id', data.student_id || data.username || username.value.trim())
    localStorage.removeItem('edumatrix_onboarded')
    
    // 新注册学生必须进入初始化向导
    router.push('/onboarding')
  } catch (e) {
    error.value = e.response?.data?.detail || '注册失败，用户名可能已存在且密码需至少4位'
  } finally {
    loading.value = false
  }
}

function toggleMode() {
  isRegister.value = !isRegister.value
  error.value = ''
  password.value = ''
  confirmPassword.value = ''
}
</script>

<template>
  <div class="min-h-screen bg-[#0b1220] text-[#f3f7ff] flex items-center justify-center p-4 relative overflow-hidden font-sans">
    <!-- Fine grain overlay -->
    <div class="absolute inset-0 bg-noise opacity-[0.02] pointer-events-none"></div>
    
    <!-- Glow spots -->
    <div class="absolute top-[-20%] left-[-20%] w-[60%] h-[60%] bg-[#38bdf8] opacity-[0.08] blur-[180px] rounded-full pointer-events-none ambient-float"></div>
    <div class="absolute bottom-[-20%] right-[-20%] w-[60%] h-[60%] bg-[#6366f1] opacity-[0.08] blur-[180px] rounded-full pointer-events-none ambient-float"></div>

    <div class="w-full max-w-md z-10 relative">
      <!-- Logo -->
      <div class="text-center mb-8">
        <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-[#67e8f9] via-[#60a5fa] to-[#6366f1] flex items-center justify-center mx-auto mb-4 shadow-xl shadow-blue-500/20">
          <BrainCircuit :size="28" class="text-[#0b0f19]" />
        </div>
        <h1 class="text-2xl font-bold tracking-tight text-white">EduMatrix 智教矩阵</h1>
        <p class="text-xs text-gray-400 mt-1">智能多智能体个性化自适应教育系统</p>
      </div>

      <!-- Login/Register Card -->
      <div class="bg-[#131c2d]/78 backdrop-blur-xl rounded-3xl border border-white/[0.08] p-8 shadow-2xl shadow-black/30">
        <div class="space-y-5">
          <div class="flex items-center justify-between border-b border-white/[0.04] pb-3 mb-2">
            <span class="text-sm font-bold text-white">{{ isRegister ? '新用户注册' : '账号登录' }}</span>
            <button @click="toggleMode" class="text-xs text-[#0ea5e9] hover:underline">
              {{ isRegister ? '已有账号？去登录' : '没有账号？立即注册' }}
            </button>
          </div>

          <div>
            <label class="text-xs font-medium text-gray-400 mb-1.5 block">用户名 / 账号</label>
            <div class="relative">
              <User :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input 
                v-model="username" 
                class="w-full pl-9 pr-3 py-2.5 text-sm rounded-xl border border-white/[0.08] bg-[#0d121f] text-white focus:border-[#0ea5e9] focus:ring-2 focus:ring-[#0ea5e9]/10 outline-none transition-all" 
                :placeholder="isRegister ? '设置用户名' : '请输入用户名'" 
                @keydown.enter="handleAction" 
              />
            </div>
          </div>

          <!-- Display Name (Nickname) only shown in Registration -->
          <div v-if="isRegister">
            <label class="text-xs font-medium text-gray-400 mb-1.5 block">个性化昵称 (选填)</label>
            <div class="relative">
              <User :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input 
                v-model="displayName" 
                class="w-full pl-9 pr-3 py-2.5 text-sm rounded-xl border border-white/[0.08] bg-[#0d121f] text-white focus:border-[#0ea5e9] focus:ring-2 focus:ring-[#0ea5e9]/10 outline-none transition-all" 
                placeholder="输入展示的昵称" 
                @keydown.enter="handleAction" 
              />
            </div>
          </div>
          
          <div>
            <label class="text-xs font-medium text-gray-400 mb-1.5 block">密码</label>
            <div class="relative">
              <Lock :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input 
                v-model="password" 
                :type="showPwd ? 'text' : 'password'" 
                class="w-full pl-9 pr-9 py-2.5 text-sm rounded-xl border border-white/[0.08] bg-[#0d121f] text-white focus:border-[#0ea5e9] focus:ring-2 focus:ring-[#0ea5e9]/10 outline-none transition-all" 
                :placeholder="isRegister ? '设置登录密码' : '请输入密码'" 
                @keydown.enter="handleAction" 
              />
              <button class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300" @click="showPwd = !showPwd">
                <Eye v-if="!showPwd" :size="14" />
                <EyeOff v-else :size="14" />
              </button>
            </div>
          </div>

          <!-- Password confirmation only shown in Registration -->
          <div v-if="isRegister">
            <label class="text-xs font-medium text-gray-400 mb-1.5 block">确认密码</label>
            <div class="relative">
              <Lock :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" />
              <input 
                v-model="confirmPassword" 
                :type="showPwd ? 'text' : 'password'" 
                class="w-full pl-9 pr-9 py-2.5 text-sm rounded-xl border border-white/[0.08] bg-[#0d121f] text-white focus:border-[#0ea5e9] focus:ring-2 focus:ring-[#0ea5e9]/10 outline-none transition-all" 
                placeholder="再次输入密码" 
                @keydown.enter="handleAction" 
              />
            </div>
          </div>
          
          <div v-if="error" class="text-xs text-red-400 bg-red-950/40 border border-red-900/30 rounded-lg px-3 py-2.5">
            {{ error }}
          </div>
          
          <button 
            class="w-full py-3 text-sm font-semibold rounded-xl bg-gradient-to-r from-[#67e8f9] via-[#60a5fa] to-[#818cf8] text-[#0b1220] hover:brightness-110 hover:-translate-y-0.5 shadow-lg shadow-blue-500/20 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
            :disabled="loading || !username.trim() || !password.trim() || (isRegister && !confirmPassword.trim())" 
            @click="handleAction"
          >
            <component :is="isRegister ? UserPlus : LogIn" :size="14" /> 
            <span>{{ loading ? (isRegister ? '账号创建中...' : '登录中...') : (isRegister ? '创建并启动学习' : '启动学习') }}</span>
          </button>
          
          <div class="text-[10px] text-gray-500 text-center leading-relaxed mt-4 border-t border-white/[0.04] pt-4">
            教师账号: teacher / admin123<br>
            学生可自行注册或使用演示账号: stu-cs-001 / 123456
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bg-noise {
  background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noiseFilter'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='3' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noiseFilter)'/%3E%3C/svg%3E");
}
</style>
