<script setup>
import { ref, onMounted } from 'vue'
import { Settings, Save, Key, Globe, Cpu, Thermometer, Eye, EyeOff, CheckCircle2 } from '@lucide/vue'

const showKey = ref(false)
const saved = ref(false)

const config = ref({
  apiKey: '',
  endpoint: 'https://windhub.cc/v1/chat/completions',
  model: 'doubao-1-5-pro-32k-250115',
  temperature: 0.3,
  maxTokens: 4096,
})

function load() {
  try {
    const raw = localStorage.getItem('edumatrix_llm_config')
    if (raw) {
      const parsed = JSON.parse(raw)
      Object.assign(config.value, parsed)
    }
  } catch {}
}

function save() {
  localStorage.setItem('edumatrix_llm_config', JSON.stringify({
    apiKey: config.value.apiKey,
    endpoint: config.value.endpoint,
    model: config.value.model,
    temperature: config.value.temperature,
    maxTokens: config.value.maxTokens,
  }))
  saved.value = true
  setTimeout(() => { saved.value = false }, 3000)
}

function clearKey() {
  config.value.apiKey = ''
  save()
}

onMounted(load)
</script>

<template>
  <div class="max-w-2xl mx-auto">
    <div class="flex items-center gap-3 mb-6">
      <Settings :size="24" class="text-gray-700" />
      <div>
        <h2 class="text-lg font-semibold text-gray-800">LLM 设置</h2>
        <p class="text-xs text-gray-400 mt-0.5">配置 API Key 后自动使用真实大模型，否则使用内置模拟引擎</p>
      </div>
    </div>

    <div v-if="saved" class="mb-4 flex items-center gap-2 text-sm text-emerald-600 bg-emerald-50 px-4 py-2.5 rounded-lg">
      <CheckCircle2 :size="16" />
      <span>配置已保存</span>
    </div>

    <div class="card space-y-5">
      <!-- API Key -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Key :size="14" />
          API Key
        </label>
        <div class="flex gap-2">
          <div class="relative flex-1">
            <input
              v-model="config.apiKey"
              :type="showKey ? 'text' : 'password'"
              class="input pr-9"
              placeholder="sk-... 留空使用模拟引擎"
            />
            <button
              class="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              @click="showKey = !showKey"
            >
              <Eye v-if="!showKey" :size="16" />
              <EyeOff v-else :size="16" />
            </button>
          </div>
          <button v-if="config.apiKey" class="btn btn-outline text-xs shrink-0" @click="clearKey">清除</button>
        </div>
        <p class="text-[11px] text-gray-400 mt-1">支持任意 OpenAI 兼容接口的 API Key</p>
      </div>

      <!-- Endpoint -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Globe :size="14" />
          API Endpoint
        </label>
        <input v-model="config.endpoint" class="input" placeholder="https://api.openai.com/v1/chat/completions" />
      </div>

      <!-- Model -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Cpu :size="14" />
          模型名称
        </label>
        <input v-model="config.model" class="input" placeholder="gpt-4o-mini" />
      </div>

      <!-- Temperature -->
      <div>
        <label class="flex items-center gap-1.5 text-sm font-medium text-gray-700 mb-1.5">
          <Thermometer :size="14" />
          Temperature ({{ config.temperature }})
        </label>
        <input v-model.number="config.temperature" type="range" min="0" max="1" step="0.05" class="w-full" />
        <div class="flex justify-between text-[10px] text-gray-400 mt-0.5">
          <span>精确 (0)</span>
          <span>创造性 (1)</span>
        </div>
      </div>

      <!-- Max Tokens -->
      <div>
        <label class="text-sm font-medium text-gray-700 mb-1.5 block">Max Tokens ({{ config.maxTokens }})</label>
        <input v-model.number="config.maxTokens" type="range" min="512" max="8192" step="512" class="w-full" />
      </div>

      <div class="pt-2">
        <button class="btn btn-primary w-full justify-center" @click="save">
          <Save :size="16" />
          保存配置
        </button>
      </div>
    </div>

    <!-- Status -->
    <div class="card mt-4">
      <p class="text-sm font-medium text-gray-700 mb-2">当前状态</p>
      <div class="space-y-1.5 text-xs">
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full" :class="config.apiKey ? 'bg-emerald-500' : 'bg-gray-300'"></div>
          <span class="text-gray-600">{{ config.apiKey ? 'API Key 已配置' : '使用模拟引擎' }}</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full bg-blue-500"></div>
          <span class="text-gray-600">Endpoint: {{ config.endpoint }}</span>
        </div>
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full bg-blue-500"></div>
          <span class="text-gray-600">Model: {{ config.model }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
