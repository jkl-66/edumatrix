<script setup>
import { ref } from 'vue'
import { Play, Tv, Sparkles, Film, ExternalLink } from '@lucide/vue'

const props = defineProps({
  videos: { type: Array, default: () => [] },
  concept: { type: String, default: '' },
})

const activePlayingIndex = ref(-1)

function startPlayback(index) {
  activePlayingIndex.value = index
}
</script>

<template>
  <div class="space-y-4 my-2">
    <div v-if="!videos || videos.length === 0" class="p-6 text-center text-xs text-slate-450 dark:text-slate-500 border border-dashed border-slate-200 dark:border-slate-800 rounded-xl bg-slate-50/30 dark:bg-slate-900/20">
      <Tv class="w-5 h-5 mx-auto mb-2 text-slate-400 dark:text-slate-655 animate-pulse" />
      暂无适配该学情的视频推荐，请尝试重算或切换学习路线。
    </div>
    <div 
      v-else
      v-for="(video, idx) in videos" 
      :key="idx"
      class="bg-white/70 dark:bg-slate-900/60 backdrop-blur-md border border-slate-200/80 dark:border-slate-800/80 rounded-xl overflow-hidden shadow-sm hover:shadow-md transition-all duration-300"
    >
      <!-- Video Header -->
      <div class="px-4 py-3 flex items-center justify-between border-b border-slate-100 dark:border-slate-800/60">
        <div class="flex items-center gap-2">
          <Film :size="16" class="text-blue-500 dark:text-blue-400 animate-pulse" />
          <span class="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            {{ video.source || '推荐视频' }}
          </span>
        </div>
        <!-- Source badge with custom styling -->
        <span 
          class="text-[10px] px-2 py-0.5 rounded-full font-medium"
          :class="{
            'bg-blue-50 text-blue-600 dark:bg-blue-950/30 dark:text-blue-400': video.source === '本地动画',
            'bg-pink-50 text-pink-600 dark:bg-pink-950/30 dark:text-pink-400': video.source === 'B站视频',
            'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/30 dark:text-emerald-400': video.source !== '本地动画' && video.source !== 'B站视频'
          }"
        >
          {{ video.source === '本地动画' ? '本地配套' : '精选外网' }}
        </span>
      </div>

      <!-- Content Area -->
      <div class="p-4 space-y-3">
        <!-- Title -->
        <h4 class="text-sm font-semibold text-slate-800 dark:text-slate-100 line-clamp-2">
          {{ video.title }}
        </h4>

        <!-- AI Recommendation description -->
        <div 
          v-if="video.recommendation"
          class="flex gap-2 p-2.5 rounded-lg bg-blue-50/40 dark:bg-slate-900/80 border border-blue-100/50 dark:border-slate-800 text-xs text-slate-600 dark:text-slate-300"
        >
          <Sparkles :size="14" class="text-blue-500 dark:text-blue-400 shrink-0 mt-0.5" />
          <div>
            <span class="font-medium text-blue-700 dark:text-blue-300">导读意见：</span>
            {{ video.recommendation }}
          </div>
        </div>

        <!-- Video Player Display -->
        <div class="relative w-full overflow-hidden rounded-lg bg-slate-900 border border-slate-200/50 dark:border-slate-800/80 aspect-video">
          <!-- Playback Active -->
          <template v-if="activePlayingIndex === idx">
            <!-- Iframe for Network / Bilibili / YouTube -->
            <iframe 
              v-if="video.source !== '本地动画'"
              :src="video.url"
              class="w-full h-full"
              frameborder="no" 
              scrolling="no" 
              allowfullscreen="true"
            />
            <!-- Native video player for Local animations -->
            <video 
              v-else
              :src="video.url"
              class="w-full h-full object-contain"
              controls
              autoplay
            />
          </template>

          <!-- Playback Poster Placeholder -->
          <div 
            v-else 
            class="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-slate-800 to-slate-950 cursor-pointer group"
            @click="startPlayback(idx)"
          >
            <!-- Background Decoration Grid -->
            <div class="absolute inset-0 bg-[radial-gradient(#ffffff0a_1px,transparent_1px)] [background-size:16px_16px] pointer-events-none" />
            
            <div class="w-12 h-12 rounded-full bg-white/10 group-hover:bg-blue-500/20 group-hover:scale-110 transition-all duration-300 backdrop-blur flex items-center justify-center border border-white/20 group-hover:border-blue-400/40 shadow-lg">
              <Play :size="20" class="text-white fill-white group-hover:text-blue-400 ml-0.5" />
            </div>
            <span class="text-xs text-slate-400 group-hover:text-slate-200 mt-3 transition-colors">
              点击就地播放
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
