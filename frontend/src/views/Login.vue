<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { loginUser } from '../api'
import { BrainCircuit, LogIn, User, Lock, Eye, EyeOff } from '@lucide/vue'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')
const showPwd = ref(false)

async function login() {
  if (!username.value.trim() || !password.value.trim()) return
  loading.value = true
  error.value = ''
  try {
    const data = await loginUser(username.value.trim(), password.value.trim())
    localStorage.setItem('edumatrix_token', data.access_token)
    localStorage.setItem('edumatrix_username', username.value.trim())
    router.push('/')
  } catch (e) {
    error.value = e.response?.data?.detail || '登录失败，请检查用户名和密码'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="min-h-screen bg-gradient-to-br from-gray-50 via-white to-purple-50 flex items-center justify-center p-4">
    <div class="w-full max-w-sm">
      <!-- Logo -->
      <div class="text-center mb-8">
        <div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-600 to-indigo-600 flex items-center justify-center mx-auto mb-4 shadow-lg">
          <BrainCircuit :size="28" class="text-white" />
        </div>
        <h1 class="text-xl font-bold text-gray-800">EduMatrix 智教矩阵</h1>
        <p class="text-xs text-gray-400 mt-1">个性化自适应学习系统</p>
      </div>

      <!-- Login Card -->
      <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
        <div class="space-y-4">
          <div>
            <label class="text-xs font-medium text-gray-600 mb-1.5 block">用户名</label>
            <div class="relative">
              <User :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input v-model="username" class="w-full pl-9 pr-3 py-2.5 text-sm rounded-xl border border-gray-200 bg-white focus:border-purple-300 focus:ring-2 focus:ring-purple-100 outline-none transition-all" placeholder="输入用户名" @keydown.enter="login" />
            </div>
          </div>
          <div>
            <label class="text-xs font-medium text-gray-600 mb-1.5 block">密码</label>
            <div class="relative">
              <Lock :size="14" class="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <input v-model="password" :type="showPwd ? 'text' : 'password'" class="w-full pl-9 pr-9 py-2.5 text-sm rounded-xl border border-gray-200 bg-white focus:border-purple-300 focus:ring-2 focus:ring-purple-100 outline-none transition-all" placeholder="输入密码" @keydown.enter="login" />
              <button class="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600" @click="showPwd = !showPwd">
                <Eye v-if="!showPwd" :size="14" />
                <EyeOff v-else :size="14" />
              </button>
            </div>
          </div>
          <div v-if="error" class="text-xs text-red-500 bg-red-50 rounded-lg px-3 py-2">{{ error }}</div>
          <button class="w-full py-2.5 text-sm font-semibold rounded-xl bg-gradient-to-r from-purple-600 to-indigo-600 text-white hover:from-purple-700 hover:to-indigo-700 shadow-sm transition-all flex items-center justify-center gap-2 disabled:opacity-50" :disabled="loading || !username.trim() || !password.trim()" @click="login">
            <LogIn :size="14" /> {{ loading ? '登录中...' : '登录' }}
          </button>
          <p class="text-[10px] text-gray-400 text-center mt-4">
            教师账号: teacher / teacher123<br>
            学生账号: student1 / password123
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
