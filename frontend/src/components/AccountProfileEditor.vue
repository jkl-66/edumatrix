<script setup>
import { onMounted, ref } from 'vue'
import { api, authConfig, getCurrentIdentity, request } from '../api/common'
import { rememberAccountIdentity } from '../services/accountIdentity'
import { userMessage } from '../services/errorTranslator'

const name = ref('')
const avatar = ref('')
const saved = ref(null)
const loading = ref(true)
const saving = ref(false)
const reading = ref(false)
const error = ref('')
const notice = ref('')
let selection = 0

function cancel() {
  selection += 1
  reading.value = false
  name.value = saved.value?.display_name || ''
  avatar.value = saved.value?.avatar_url || ''
  notice.value = ''
  error.value = ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    saved.value = await getCurrentIdentity()
    rememberAccountIdentity(saved.value)
    cancel()
  } catch (e) { error.value = userMessage(e, '资料暂未加载，请重试。') }
  finally { loading.value = false }
}

async function chooseAvatar(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  error.value = ''
  notice.value = ''
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
    error.value = '请选择不超过 5 MB 的 PNG、JPG 或 WebP 图片。'
    return
  }
  const current = ++selection
  reading.value = true
  const url = URL.createObjectURL(file)
  try {
    const image = new Image()
    image.src = url
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = canvas.height = 256
    const side = Math.min(image.width, image.height)
    canvas.getContext('2d').drawImage(image, (image.width - side) / 2, (image.height - side) / 2, side, side, 0, 0, 256, 256)
    if (current === selection) avatar.value = canvas.toDataURL('image/png')
  } catch { if (current === selection) error.value = '这张图片无法打开，请重新选择。' }
  finally {
    URL.revokeObjectURL(url)
    if (current === selection) reading.value = false
  }
}

async function save() {
  if (saving.value || reading.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    saved.value = await request(api.patch('/auth/me', { display_name: name.value.trim(), avatar_url: avatar.value }, authConfig()))
    rememberAccountIdentity(saved.value)
    cancel()
    notice.value = '资料已保存。'
  } catch (e) { error.value = userMessage(e, '资料未能保存，你的修改仍在这里，请重试。') }
  finally { saving.value = false }
}

onMounted(load)
</script>

<template>
  <section id="account-profile" class="account-profile" aria-labelledby="account-profile-title">
    <div>
      <h3 id="account-profile-title">编辑资料</h3>
      <p>设置昵称和头像。专业、学习目标和偏好请到学习画像中更新。</p>
    </div>
    <p v-if="loading" role="status">正在读取资料…</p>
    <form v-else-if="saved" @submit.prevent="save">
      <div class="avatar-preview" aria-label="头像预览"><img v-if="avatar" :src="avatar" alt="头像预览" /><span v-else>{{ (name || '学').slice(0, 1) }}</span></div>
      <div class="profile-fields">
        <label>昵称<input v-model="name" class="input" aria-label="昵称" required maxlength="64" :disabled="saving" /></label>
        <label>选择头像<input type="file" accept="image/png,image/jpeg,image/webp" aria-label="选择头像" :disabled="saving" @change="chooseAvatar" /></label>
        <small>图片会裁剪为正方形，支持 PNG、JPG、WebP，最大 5 MB。</small>
        <div class="profile-actions">
          <button type="button" class="ui-button ui-button--ghost" :disabled="saving || reading" @click="avatar = ''; notice = ''">恢复默认头像</button>
          <button type="button" class="ui-button ui-button--secondary" :disabled="saving" @click="cancel">取消修改</button>
          <button type="submit" class="ui-button ui-button--primary" :disabled="saving || reading || !name.trim()">{{ saving ? '正在保存…' : '保存资料' }}</button>
        </div>
      </div>
    </form>
    <p v-if="error" role="alert">{{ error }} <button v-if="!saved" type="button" @click="load">重试</button></p>
    <p v-if="notice" role="status">{{ notice }}</p>
  </section>
</template>

<style scoped>
.account-profile { padding: 28px 34px; border-bottom: 1px solid var(--color-border); }
h3 { margin: 0; font-size: 18px; }
p, small { color: var(--color-text-secondary); }
form { display: flex; align-items: flex-start; gap: 24px; margin-top: 20px; }
.avatar-preview { width: 88px; height: 88px; flex: 0 0 88px; border-radius: 16px; overflow: hidden; display: grid; place-items: center; background: var(--color-surface-subtle); border: 1px solid var(--color-border); font-size: 32px; }
.avatar-preview img { width: 100%; height: 100%; object-fit: cover; }
.profile-fields { display: grid; gap: 12px; flex: 1; }
label { display: grid; gap: 6px; font-size: 14px; }
input { max-width: 440px; }
.profile-actions { display: flex; gap: 10px; flex-wrap: wrap; }
</style>
