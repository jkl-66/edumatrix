<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  EyeOff,
  GraduationCap,
  Lock,
  Presentation,
  ShieldCheck,
  User,
  UserPlus,
} from '@lucide/vue'
import { clearAuthSession, getOnboardingStatus, getStudentProfile, loginUser, registerUser } from '../api'
import { useContextStore } from '../stores/context'
import { useCourseContextStore } from '../stores/courseContext'
import { roleLandingPath } from '../utils/roleLanding'

const router = useRouter()
const route = useRoute()

const roles = [
  { value: 'student', label: '学生', icon: GraduationCap, destination: '进入个人学习空间' },
  { value: 'teacher', label: '教师', icon: Presentation, destination: '进入教学工作区' },
  { value: 'admin', label: '管理员', icon: ShieldCheck, destination: '进入系统管理' },
]

const demoAccounts = {
  student: { username: 'lzz', password: '404404aA', label: '学生演示账号' },
  teacher: { username: 'teacher', password: 'admin123', label: '教师演示账号' },
  admin: { username: 'demo-admin', password: 'EduMatrix-Demo-2026', label: '管理员演示账号' },
}

const selectedRole = ref('student')
const isRegister = ref(false)
const username = ref('')
const password = ref('')
const displayName = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const error = ref(route.query.reason === 'session-expired' ? '登录状态已失效，请重新登录。' : '')
const showPassword = ref(false)

const currentRole = computed(() => roles.find((item) => item.value === selectedRole.value) || roles[0])
const currentDemo = computed(() => demoAccounts[selectedRole.value])

function setRole(role) {
  selectedRole.value = role
  error.value = ''
}

function useDemoAccount() {
  const account = currentDemo.value
  username.value = account.username
  password.value = account.password
  error.value = ''
}

function persistSession(data, fallbackUsername) {
  clearAuthSession()
  useContextStore().clear()
  useCourseContextStore().clear({ keepCourse: false })
  localStorage.setItem('edumatrix_token', data.access_token)
  localStorage.setItem('edumatrix_username', data.username || fallbackUsername)
  localStorage.setItem('edumatrix_display_name', data.display_name || data.username || fallbackUsername)
  localStorage.setItem('edumatrix_role', data.role || 'student')
  localStorage.setItem('edumatrix_student_id', data.student_id || data.username || fallbackUsername)
}

async function routeAfterStudentLogin(data) {
  try {
    const status = await getOnboardingStatus()
    const complete = status.finalized || (!status.featureEnabled && status.legacyComplete)
      || (!status.exists && status.legacyComplete)
    if (!complete) {
      localStorage.removeItem('edumatrix_onboarded')
      await router.push('/onboarding')
      return
    }
    localStorage.setItem('edumatrix_onboarded', 'true')
    await router.push(data.landing_path || '/')
  } catch {
    try {
      const profile = await getStudentProfile(data.student_id)
      if (!profile?.major || !profile?.target_course) {
        localStorage.removeItem('edumatrix_onboarded')
        await router.push('/onboarding')
        return
      }
      localStorage.setItem('edumatrix_onboarded', 'true')
      await router.push('/')
    } catch {
      await router.push('/')
    }
  }
}

async function login() {
  const normalizedUsername = username.value.trim()
  if (!normalizedUsername || !password.value) {
    error.value = '请输入账号和密码。'
    return
  }

  loading.value = true
  error.value = ''
  try {
    const data = await loginUser(normalizedUsername, password.value)
    const actualRole = data.role || 'student'
    if (actualRole !== selectedRole.value) {
      const actual = roles.find((item) => item.value === actualRole)?.label || '其他'
      error.value = `该账号属于${actual}身份，请切换上方角色后重新登录。`
      return
    }

    persistSession(data, normalizedUsername)
    if (actualRole === 'student') {
      await routeAfterStudentLogin(data)
    } else {
      await router.push(data.landing_path || roleLandingPath(actualRole))
    }
  } catch (requestError) {
    const detail = requestError?.detail || requestError?.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : '登录失败，请检查账号和密码。'
  } finally {
    loading.value = false
  }
}

async function register() {
  const normalizedUsername = username.value.trim()
  if (!normalizedUsername || !password.value) {
    error.value = '请填写用户名和密码。'
    return
  }
  if (password.value !== confirmPassword.value) {
    error.value = '两次输入的密码不一致。'
    return
  }

  loading.value = true
  error.value = ''
  try {
    const name = displayName.value.trim() || normalizedUsername
    const data = await registerUser(normalizedUsername, password.value, name)
    persistSession({ ...data, role: 'student' }, normalizedUsername)
    localStorage.removeItem('edumatrix_onboarded')
    await router.push('/onboarding')
  } catch (requestError) {
    const detail = requestError?.detail || requestError?.response?.data?.detail
    error.value = typeof detail === 'string' ? detail : '注册失败，用户名可能已存在。'
  } finally {
    loading.value = false
  }
}

function toggleMode() {
  isRegister.value = !isRegister.value
  selectedRole.value = 'student'
  error.value = ''
  password.value = ''
  confirmPassword.value = ''
}

function submit() {
  return isRegister.value ? register() : login()
}
</script>

<template>
  <div class="login-page">
    <header class="login-header">
      <button type="button" class="back-link" @click="router.push('/landing')">
        <ArrowLeft :size="17" />
        返回作品展示
      </button>
      <div class="login-brand">
        <span>E</span>
        <strong>EduMatrix</strong>
      </div>
    </header>

    <main class="login-main">
      <section class="login-panel" aria-labelledby="login-title">
        <div class="login-heading">
          <h1 id="login-title">{{ isRegister ? '开始建立你的学习画像' : '登录 EduMatrix' }}</h1>
          <span>{{ isRegister ? '注册后进入自然语言画像引导。' : '选择身份后使用账号登录，或一键填入演示账号。' }}</span>
        </div>

        <div v-if="!isRegister" class="role-segments" role="tablist" aria-label="登录身份">
          <button
            v-for="item in roles"
            :key="item.value"
            type="button"
            role="tab"
            :aria-selected="selectedRole === item.value"
            :class="{ active: selectedRole === item.value }"
            :data-testid="`login-role-${item.value}`"
            @click="setRole(item.value)"
          >
            <component :is="item.icon" :size="17" />
            {{ item.label }}
          </button>
        </div>

        <form class="login-form" @submit.prevent="submit">
          <label v-if="isRegister" class="field-label">
            <span>显示名称 <small>选填</small></span>
            <span class="field-control">
              <User :size="17" />
              <input v-model.trim="displayName" autocomplete="name" placeholder="例如：林同学" />
            </span>
          </label>

          <label class="field-label">
            <span>账号</span>
            <span class="field-control">
              <User :size="17" />
              <input
                v-model.trim="username"
                name="username"
                autocomplete="username"
                :placeholder="isRegister ? '设置登录账号' : '请输入账号'"
                data-testid="login-username"
              />
            </span>
          </label>

          <label class="field-label">
            <span>密码</span>
            <span class="field-control">
              <Lock :size="17" />
              <input
                v-model="password"
                name="password"
                :type="showPassword ? 'text' : 'password'"
                :autocomplete="isRegister ? 'new-password' : 'current-password'"
                :placeholder="isRegister ? '设置登录密码' : '请输入密码'"
                data-testid="login-password"
              />
              <button
                type="button"
                class="password-toggle"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                :title="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" :size="17" />
                <Eye v-else :size="17" />
              </button>
            </span>
          </label>

          <label v-if="isRegister" class="field-label">
            <span>确认密码</span>
            <span class="field-control">
              <Lock :size="17" />
              <input v-model="confirmPassword" :type="showPassword ? 'text' : 'password'" autocomplete="new-password" placeholder="再次输入密码" />
            </span>
          </label>

          <div v-if="error" class="login-error" role="alert" data-testid="login-error">{{ error }}</div>

          <button type="submit" class="login-submit" :disabled="loading" data-testid="login-submit">
            <span>{{ loading ? (isRegister ? '正在创建账号' : '正在登录') : (isRegister ? '创建账号并继续' : '登录') }}</span>
            <UserPlus v-if="isRegister" :size="17" />
            <ArrowRight v-else :size="17" />
          </button>
        </form>

        <details v-if="!isRegister" class="demo-account" open>
          <summary>演示账号</summary>
          <div class="demo-account__body">
            <div>
              <strong>{{ currentDemo.label }}</strong>
              <span>{{ currentDemo.username }}</span>
            </div>
            <button type="button" data-testid="fill-demo-account" @click="useDemoAccount">填入账号</button>
          </div>
        </details>

        <button type="button" class="register-link" @click="toggleMode">
          {{ isRegister ? '已有账号，返回登录' : '没有学生账号？创建账号' }}
        </button>
      </section>
    </main>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  height: 100vh;
  grid-template-rows: 64px minmax(0, 1fr);
  overflow: auto;
  color: var(--color-text);
  background: var(--color-page);
}

.login-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 40px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
}

.back-link,
.register-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 0;
  color: var(--color-text-secondary);
  border: 0;
  background: transparent;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.back-link:hover,
.register-link:hover {
  color: var(--color-text);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 9px;
}

.login-brand span {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  color: #ffffff;
  border-radius: 5px;
  background: var(--color-accent);
  font-size: 14px;
  font-weight: 700;
}

.login-brand strong {
  font-size: 16px;
}

.login-main {
  display: grid;
  min-height: 704px;
  place-items: center;
  padding: 40px;
}

.login-panel {
  width: min(100%, 500px);
  padding: 34px 36px 30px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: var(--color-surface);
  box-shadow: 0 18px 48px rgb(23 23 23 / 7%);
}

.login-heading p,
.login-heading h1,
.login-heading span {
  margin: 0;
}

.login-heading p {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 650;
}

.login-heading h1 {
  margin-top: 5px;
  color: var(--color-text);
  font-size: 28px;
  font-weight: 680;
  line-height: 1.35;
}

.login-heading > span {
  display: block;
  margin-top: 6px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.role-segments {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 3px;
  margin-top: 24px;
  padding: 3px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface-subtle);
}

.role-segments button {
  display: flex;
  min-height: 42px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: var(--color-text-secondary);
  border: 0;
  border-radius: 5px;
  background: transparent;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.role-segments button.active {
  color: #ffffff;
  background: var(--color-accent);
}

.login-form {
  display: grid;
  gap: 16px;
  margin-top: 22px;
}

.field-label {
  display: grid;
  gap: 7px;
  color: var(--color-text);
  font-size: 14px;
  font-weight: 600;
}

.field-label small {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 500;
}

.field-control {
  display: grid;
  min-height: 44px;
  grid-template-columns: 20px minmax(0, 1fr) auto;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-surface);
}

.field-control:focus-within {
  border-color: var(--color-accent);
  box-shadow: 0 0 0 3px rgb(49 91 125 / 10%);
}

.field-control input {
  width: 100%;
  min-height: 42px;
  padding: 0;
  color: var(--color-text);
  border: 0;
  outline: 0;
  background: transparent;
  font-size: 15px;
}

.password-toggle {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  color: var(--color-text-secondary);
  border: 0;
  background: transparent;
  cursor: pointer;
}

.login-error {
  padding: 10px 12px;
  color: #8c3434;
  border: 1px solid #e5c5c5;
  border-radius: 6px;
  background: #fbefef;
  font-size: 14px;
  line-height: 1.5;
}

.login-submit {
  display: flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: #ffffff;
  border: 1px solid var(--color-accent);
  border-radius: var(--radius-control);
  background: var(--color-accent);
  font-size: 15px;
  font-weight: 650;
  cursor: pointer;
}

.login-submit:hover:not(:disabled) {
  background: var(--color-text);
}

.login-submit:disabled {
  opacity: 0.55;
  cursor: wait;
}

.demo-account {
  margin-top: 18px;
  border-top: 1px solid var(--color-border);
  border-bottom: 1px solid var(--color-border);
}

.demo-account summary {
  padding: 12px 0;
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}

.demo-account__body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 0 0 13px;
}

.demo-account__body > div {
  display: grid;
}

.demo-account__body strong,
.demo-account__body span {
  font-size: 14px;
}

.demo-account__body span {
  color: #85898f;
}

.demo-account__body button {
  min-height: 36px;
  padding: 0 12px;
  color: var(--color-accent);
  border: 1px solid var(--color-border-strong);
  border-radius: var(--radius-control);
  background: var(--color-accent-soft);
  font-size: 14px;
  font-weight: 650;
  cursor: pointer;
}

.register-link {
  margin: 18px auto 0;
}
</style>
