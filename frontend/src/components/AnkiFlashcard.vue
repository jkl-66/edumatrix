<script setup>
import { ref, watch } from 'vue'
import { RotateCw, CheckCircle2, AlertTriangle, HelpCircle, Loader2 } from '@lucide/vue'
import { reviewFlashcard } from '../api'

const props = defineProps({
  card: {
    type: Object,
    required: true,
  },
  studentId: {
    type: String,
    default: 'default',
  },
})

const emit = defineEmits(['reviewed'])

const isFlipped = ref(false)
const submitting = ref(false)
const reviewMessage = ref('')
const nextReviewInterval = ref(0)

// 切换翻转状态
function flipCard() {
  if (submitting.value) return
  isFlipped.value = !isFlipped.value
  reviewMessage.value = ''
}

// 提交复习评分 (quality: 2=困难, 4=一般, 5=简单)
async function submitQuality(quality) {
  if (submitting.value) return
  submitting.value = true
  reviewMessage.value = ''
  try {
    const res = await reviewFlashcard(props.studentId, props.card.concept, quality)
    nextReviewInterval.value = res.interval_new
    reviewMessage.value = res.message || `复习成功！下次复习间隔 ${res.interval_new} 天`
    emit('reviewed', res)
  } catch (e) {
    console.error('提交复习评分失败:', e)
    reviewMessage.value = '提交评分失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}

// 当卡片对象改变时重置翻转状态
watch(() => props.card, () => {
  isFlipped.value = false
  reviewMessage.value = ''
  nextReviewInterval.value = 0
}, { deep: true })
</script>

<template>
  <div class="anki-card-container">
    <div class="anki-perspective w-full h-[320px]">
      <div 
        class="anki-card-inner relative w-full h-full cursor-pointer"
        :class="{ 'is-flipped': isFlipped }"
      >
        <!-- 正面 -->
        <div 
          class="anki-card-front absolute inset-0 rounded-2xl p-6 flex flex-col justify-between border select-none transition-all shadow-md bg-gradient-to-br from-white to-indigo-50 border-indigo-100 text-slate-800"
          @click="flipCard"
        >
          <div class="flex items-center justify-between">
            <span class="text-[10px] uppercase font-bold tracking-widest text-indigo-700 bg-indigo-50 px-2.5 py-1 rounded-full border border-indigo-100">
              记忆闪卡 · 正面
            </span>
            <HelpCircle :size="16" class="text-indigo-500 animate-pulse" />
          </div>

          <div class="my-auto text-center px-4 space-y-3">
            <h3 class="text-xs text-slate-500 font-medium">需要召回的概念问题</h3>
            <p class="text-lg font-semibold leading-relaxed tracking-wide text-indigo-900">{{ card.front || '加载中...' }}</p>
          </div>

          <div class="flex items-center justify-center gap-1.5 text-xs text-slate-500 font-medium">
            <RotateCw :size="12" class="text-indigo-500" />
            点击卡片以翻面查看解析
          </div>
        </div>

        <!-- 反面 -->
        <div 
          class="anki-card-back absolute inset-0 rounded-2xl p-6 flex flex-col justify-between border transition-all shadow-md bg-gradient-to-br from-white to-emerald-50 border-emerald-100 text-slate-800"
        >
          <div class="flex items-center justify-between" @click="flipCard">
            <span class="text-[10px] uppercase font-bold tracking-widest text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-100">
              记忆闪卡 · 诊断解析
            </span>
            <div class="flex items-center gap-1.5 text-xs text-slate-500 cursor-pointer hover:text-indigo-600 transition-colors">
              <RotateCw :size="12" />
              <span>翻回正面</span>
            </div>
          </div>

          <div class="my-auto overflow-y-auto max-h-[160px] pr-1 scrollbar-thin text-slate-700 text-sm leading-relaxed space-y-2 whitespace-pre-line py-3">
            <div class="text-xs font-bold text-slate-400">💡 记忆要点与微断点诊断：</div>
            {{ card.back }}
          </div>

          <div class="pt-3 border-t border-slate-800 flex flex-col gap-2">
            <!-- 成功提示 -->
            <div v-if="reviewMessage" class="text-center text-xs p-2 rounded-lg" :class="reviewMessage.includes('失败') ? 'bg-red-50 text-red-600 border border-red-200' : 'bg-emerald-50 text-emerald-600 border border-emerald-200'">
              {{ reviewMessage }}
            </div>

            <!-- 复习参数展示 -->
            <div class="flex items-center justify-between text-[11px] text-slate-500 px-1">
              <span>掌握度: {{ (card.mastery != null ? card.mastery * 100 : 30).toFixed(0) }}%</span>
              <span>易记因子: {{ (card.easiness || 2.5).toFixed(2) }}</span>
              <span>复习次数: {{ card.review_count || 0 }} 次</span>
            </div>

            <!-- 反馈按钮区 -->
            <div v-if="!reviewMessage && !submitting" class="grid grid-cols-3 gap-2">
              <button 
                @click.stop="submitQuality(2)"
                class="py-2 text-xs font-semibold rounded-xl bg-red-50 hover:bg-red-100 text-red-600 border border-red-200 active:scale-[0.97] transition-all"
              >
                困难
              </button>
              <button 
                @click.stop="submitQuality(4)"
                class="py-2 text-xs font-semibold rounded-xl bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200 active:scale-[0.97] transition-all"
              >
                一般
              </button>
              <button 
                @click.stop="submitQuality(5)"
                class="py-2 text-xs font-semibold rounded-xl bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200 active:scale-[0.97] transition-all"
              >
                简单
              </button>
            </div>

            <!-- 加载状态 -->
            <div v-else-if="submitting" class="flex items-center justify-center py-2">
              <Loader2 :size="16" class="text-indigo-400 animate-spin mr-2" />
              <span class="text-xs text-slate-500">正在同步记忆状态...</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.anki-perspective {
  perspective: 1000px;
}

.anki-card-inner {
  transition: transform 0.6s cubic-bezier(0.4, 0, 0.2, 1);
  transform-style: preserve-3d;
}

.anki-card-inner.is-flipped {
  transform: rotateY(180deg);
}

.anki-card-front,
.anki-card-back {
  backface-visibility: hidden;
  box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3), 0 8px 10px -6px rgba(0, 0, 0, 0.3);
}

.anki-card-back {
  transform: rotateY(180deg);
}

/* 滚动条美化 */
.scrollbar-thin::-webkit-scrollbar {
  width: 4px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: transparent;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.2);
  border-radius: 2px;
}
.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.4);
}
</style>
