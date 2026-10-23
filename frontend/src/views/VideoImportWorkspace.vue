<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import {
  CheckCircle2,
  Download,
  FilePlus2,
  Film,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  Upload,
  X,
} from "@lucide/vue";
import {
  downloadVideoAssetFile,
  getVideoAsset,
  getVideoAssetFile,
  listVideoAssets,
  uploadVideoAsset,
} from "../api";

const assets = ref([]),
  selected = ref(null),
  loading = ref(true),
  busy = ref(false),
  error = ref(""),
  notice = ref("");
const videoFile = ref(null),
  subtitleFile = ref(null),
  previewUrl = ref(""),
  previewState = ref("idle");
let previewRequest = 0;
const form = ref({
  title: "",
  language: "zh-CN",
  course_id: "",
  chapter_id: "",
  source_url: "",
  source_author: "",
  license_status: "owner_provided",
  license_text: "上传者声明其有权在本地教学演示中使用该文件",
});
const isRevision = computed(() => Boolean(selected.value?.id));
const current = computed(() => selected.value?.current_version || null);
function detail(err) {
  return err?.response?.data?.detail?.message || err?.message || "请求失败";
}
function resetForm() {
  form.value = {
    title: "",
    language: "zh-CN",
    course_id: "",
    chapter_id: "",
    source_url: "",
    source_author: "",
    license_status: "owner_provided",
    license_text: "上传者声明其有权在本地教学演示中使用该文件",
  };
  videoFile.value = null;
  subtitleFile.value = null;
}
async function load(preferred = selected.value?.id) {
  loading.value = true;
  error.value = "";
  try {
    const response = await listVideoAssets();
    assets.value = response.items || [];
    const id = assets.value.some((item) => item.id === preferred)
      ? preferred
      : assets.value[0]?.id;
    if (id) await open(id);
    else selected.value = null;
  } catch (caught) {
    error.value = detail(caught);
  } finally {
    loading.value = false;
  }
}
async function open(id) {
  try {
    selected.value = await getVideoAsset(id);
  } catch (caught) {
    error.value = detail(caught);
  }
}
function chooseNew() {
  selected.value = null;
  resetForm();
  notice.value = "";
}
function chooseRevision() {
  if (!selected.value) return;
  form.value = {
    title: selected.value.title,
    language: selected.value.language,
    course_id: selected.value.course_id || "",
    chapter_id: selected.value.chapter_id || "",
    source_url: selected.value.source_url,
    source_author: selected.value.source_author,
    license_status: selected.value.license_status,
    license_text: selected.value.license_text,
  };
  videoFile.value = null;
  subtitleFile.value = null;
  notice.value = "请选择新视频文件；版本会以新的 hash 固化。";
}
async function submit() {
  if (!videoFile.value || !form.value.title.trim()) return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const result = await uploadVideoAsset({
      ...form.value,
      video: videoFile.value,
      subtitle: subtitleFile.value,
      asset_id: selected.value?.id,
      expected_lock_version: selected.value?.lock_version,
    });
    notice.value = result.idempotent
      ? "相同内容已存在，系统返回原版本。"
      : `导入成功：版本 v${result.current_version.version_number}`;
    await load(result.id);
    videoFile.value = null;
    subtitleFile.value = null;
  } catch (caught) {
    error.value = detail(caught);
  } finally {
    busy.value = false;
  }
}
function setVideo(event) {
  videoFile.value = event.target.files?.[0] || null;
}
function setSubtitle(event) {
  subtitleFile.value = event.target.files?.[0] || null;
}
watch(
  () => [selected.value?.id || "", current.value?.id || ""],
  async ([assetId, versionId]) => {
    const request = ++previewRequest;
    if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
    previewUrl.value = "";
    previewState.value = versionId ? "loading" : "idle";
    if (assetId && versionId) {
      try {
        const blob = await getVideoAssetFile(assetId, versionId, "video");
        const url = URL.createObjectURL(blob);
        if (request !== previewRequest) {
          URL.revokeObjectURL(url);
          return;
        }
        previewUrl.value = url;
      } catch (caught) {
        if (request === previewRequest) {
          previewState.value = "error";
          error.value = detail(caught);
        }
      }
    }
  },
  { immediate: true },
);
onMounted(() => {
  resetForm();
  load();
});
onBeforeUnmount(() => {
  previewRequest += 1;
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
});
</script>

<template>
  <main class="imports" data-testid="video-import-workspace">
    <header>
      <div>
        <p class="eyebrow">LOCAL MEDIA GOVERNANCE</p>
        <h1>视频资产导入</h1>
        <p>
          导入本地视频与字幕，保存文件指纹、媒体探测结果、课程绑定和不可变版本。
        </p>
      </div>
      <div class="boundary">
        <ShieldCheck :size="18" />
        <div>
          <strong>本地文件边界</strong
          ><small>不自动下载外部来源；来源与许可按上传者声明展示。</small>
        </div>
      </div>
    </header>
    <p v-if="error" class="notice error">
      <X :size="14" />{{ error }}
      <button @click="load"><RefreshCw :size="13" />重试</button>
    </p>
    <p v-if="notice" class="notice ok">
      <CheckCircle2 :size="14" />{{ notice }}
    </p>
    <p v-if="loading" class="notice">正在恢复视频资产...</p>
    <template v-else>
      <section class="toolbar">
        <select
          v-if="assets.length"
          :value="selected?.id || ''"
          aria-label="选择视频资产"
          @change="open($event.target.value)"
        >
          <option v-for="asset in assets" :key="asset.id" :value="asset.id">
            {{ asset.title }} · v{{ asset.current_version?.version_number }}
          </option></select
        ><button @click="chooseNew"><FilePlus2 :size="14" />新资产</button
        ><button :disabled="!selected" @click="chooseRevision">
          <Upload :size="14" />导入新版本</button
        ><button @click="load"><RefreshCw :size="14" />刷新</button>
      </section>
      <div class="layout">
        <section class="form-panel">
          <div class="panel-head">
            <strong>{{ isRevision ? "导入新版本" : "注册视频资产" }}</strong
            ><small
              >最大视频 {{ Math.round((20 * 1024 * 1024) / 1024 / 1024) }} MB ·
              MP4/MOV/WebM</small
            >
          </div>
          <form @submit.prevent="submit">
            <label
              >标题<input
                v-model="form.title"
                required
                maxlength="256"
                aria-label="视频标题"
            /></label>
            <div class="two">
              <label>语言<input v-model="form.language" maxlength="32" /></label
              ><label
                >许可状态<input v-model="form.license_status" maxlength="64"
              /></label>
            </div>
            <div class="two">
              <label
                >课程 ID<input
                  v-model="form.course_id"
                  maxlength="128"
                  placeholder="可选" /></label
              ><label
                >章节 ID<input
                  v-model="form.chapter_id"
                  maxlength="64"
                  placeholder="需同时填写课程 ID"
              /></label>
            </div>
            <label
              >来源 URL<input
                v-model="form.source_url"
                type="url"
                maxlength="2048"
                placeholder="https://...（可选）" /></label
            ><label
              >来源作者<input
                v-model="form.source_author"
                maxlength="256" /></label
            ><label
              >许可说明<textarea
                v-model="form.license_text"
                maxlength="4000"
                rows="3"
              /></label
            ><label class="file"
              >视频文件<input
                type="file"
                aria-label="选择视频文件"
                accept=".mp4,.mov,.webm,video/mp4,video/webm,video/quicktime"
                required
                @change="setVideo"
              /><small>{{ videoFile?.name || "选择本地视频" }}</small></label
            ><label class="file"
              >字幕文件（可选）<input
                type="file"
                aria-label="选择字幕文件"
                accept=".srt,.vtt,text/vtt,application/x-subrip"
                @change="setSubtitle"
              /><small>{{
                subtitleFile?.name || "支持 UTF-8 SRT/VTT"
              }}</small></label
            ><button class="primary" :disabled="busy || !videoFile">
              <LoaderCircle v-if="busy" class="spin" :size="14" /><Upload
                v-else
                :size="14"
              />导入并固化
            </button>
          </form>
        </section>
        <aside>
          <div v-if="selected" class="preview">
            <div class="preview-head">
              <div>
                <small>当前版本 v{{ current?.version_number }}</small>
                <h2>{{ selected.title }}</h2>
              </div>
              <Film :size="19" />
            </div>
            <video
              v-if="previewUrl"
              :src="previewUrl"
              controls
              data-testid="imported-video-preview"
              @loadedmetadata="previewState = 'ready'"
              @error="previewState = 'error'"
            />
            <div v-else class="empty-preview">
              {{ previewState === "loading" ? "正在加载视频预览..." : "视频预览不可用" }}
            </div>
            <p v-if="previewState === 'error'" class="preview-status error">
              视频文件已保存，但当前浏览器无法载入预览。
            </p>
            <p v-else-if="previewState === 'ready'" class="preview-status">
              视频预览已就绪
            </p>
            <dl>
              <dt>文件 SHA-256</dt>
              <dd>{{ current?.source_sha256 }}</dd>
              <dt>媒体</dt>
              <dd>
                {{ current?.media_format?.toUpperCase() }} ·
                {{ current?.width || "未知" }}×{{ current?.height || "未知" }} ·
                {{ current?.video_codec || "未探测" }}
              </dd>
              <dt>时长</dt>
              <dd>
                {{
                  current?.duration_ms
                    ? `${(current.duration_ms / 1000).toFixed(1)} 秒`
                    : "未探测"
                }}
                · {{ current?.probe_status }}
              </dd>
              <dt>字幕</dt>
              <dd>
                {{ current?.subtitle_filename || "无字幕"
                }}<span v-if="current?.subtitle_sha256">
                  · v{{ current.subtitle_version }}</span
                >
              </dd>
            </dl>
            <div class="downloads">
              <button
                @click="
                  downloadVideoAssetFile(
                    selected.id,
                    current.id,
                    'video',
                    current.original_filename,
                  )
                "
              >
                <Download :size="13" />视频</button
              ><button
                v-if="current?.subtitle_filename"
                @click="
                  downloadVideoAssetFile(
                    selected.id,
                    current.id,
                    'subtitle',
                    current.subtitle_filename,
                  )
                "
              >
                <Download :size="13" />字幕
              </button>
            </div>
          </div>
          <div v-else class="empty">
            <Film :size="28" /><strong>尚无导入资产</strong
            ><span>选择视频和字幕文件后创建第一个版本。</span>
          </div>
          <div v-if="selected?.versions?.length" class="history">
            <strong>版本历史</strong>
            <div v-for="version in selected.versions" :key="version.id">
              <span
                >v{{ version.version_number }} ·
                {{ version.media_format.toUpperCase() }}</span
              ><small
                >{{ version.source_sha256.slice(0, 16) }}... ·
                {{ version.subtitle_filename || "无字幕" }}</small
              >
            </div>
          </div>
        </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.imports {
  max-width: 1220px;
  margin: 0 auto;
  color: #26322c;
}
.imports header {
  display: flex;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 18px;
  border-bottom: 1px solid #d7e0da;
}
.eyebrow {
  margin: 0 0 6px;
  color: #39765a;
  font-size: 10px;
  font-weight: 800;
}
.imports h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: 0;
}
.imports header p:last-child {
  margin: 6px 0 0;
  color: #6c786f;
  font-size: 12px;
}
.boundary {
  display: flex;
  gap: 9px;
  min-width: 270px;
  padding: 11px 13px;
  border: 1px solid #c9ddd0;
  background: #f1f7f3;
  color: #335c42;
}
.boundary div {
  display: flex;
  flex-direction: column;
}
.boundary strong {
  font-size: 11px;
}
.boundary small {
  margin-top: 3px;
  font-size: 9px;
}
.notice {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 10px;
  background: #f3f6f4;
  font-size: 11px;
}
.notice button,
.toolbar button,
.downloads button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid #cbd7cf;
  background: #fff;
  color: #35483c;
}
.error {
  background: #fff0ed;
  color: #8a4339;
}
.ok {
  background: #eef8f1;
  color: #3b6849;
}
.toolbar {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}
.toolbar select {
  flex: 1;
  height: 36px;
  padding: 0 10px;
  border: 1px solid #d1dbd4;
  background: #fff;
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(340px, 0.85fr);
  gap: 14px;
  margin-top: 14px;
}
.form-panel,
aside {
  border: 1px solid #d9e1dc;
  background: #fff;
  padding: 14px;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid #e4eae6;
}
.panel-head small {
  color: #849087;
  font-size: 9px;
}
.form-panel form {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}
.form-panel label {
  display: grid;
  gap: 4px;
  color: #6d7a71;
  font-size: 9px;
}
.form-panel input,
.form-panel textarea {
  box-sizing: border-box;
  width: 100%;
  padding: 8px;
  border: 1px solid #d6ded8;
  background: #fff;
  font: inherit;
  font-size: 11px;
}
.two {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 9px;
}
.file {
  padding: 10px;
  border: 1px dashed #cbd8cf;
  background: #f8fbf9;
}
.file input {
  padding: 0;
  border: 0;
}
.file small {
  color: #6b8174;
  font-size: 9px;
}
.primary {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-height: 36px;
  border: 0;
  background: #17342b;
  color: #fff;
  font-size: 11px;
}
.preview-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  color: #17342b;
}
.preview-head small {
  color: #748178;
  font-size: 9px;
}
.preview h2 {
  margin: 3px 0 0;
  font-size: 15px;
}
.preview video {
  width: 100%;
  margin-top: 12px;
  background: #101a16;
  aspect-ratio: 16/9;
}
.empty-preview {
  display: grid;
  min-height: 220px;
  place-items: center;
  margin-top: 12px;
  background: #151b17;
  color: #aab4ad;
  font-size: 10px;
}
.preview-status {
  margin: 6px 0 0;
  color: #587064;
  font-size: 9px;
}
.preview-status.error {
  background: transparent;
  color: #8a4339;
}
.preview dl {
  display: grid;
  grid-template-columns: 78px 1fr;
  gap: 7px;
  margin: 12px 0;
  font-size: 10px;
}
.preview dt {
  color: #7b887f;
}
.preview dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.downloads {
  display: flex;
  gap: 7px;
}
.empty {
  display: flex;
  min-height: 260px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #7f8b83;
}
.empty strong {
  margin-top: 8px;
  font-size: 12px;
}
.empty span {
  font-size: 9px;
}
.history {
  margin-top: 14px;
  border-top: 1px solid #e1e7e3;
  padding-top: 10px;
}
.history > strong {
  font-size: 10px;
}
.history > div {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 0;
  border-bottom: 1px solid #edf0ee;
  font-size: 9px;
}
.history small {
  color: #7c8980;
  overflow-wrap: anywhere;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
@media (max-width: 850px) {
  .imports header {
    flex-direction: column;
  }
  .boundary {
    min-width: 0;
  }
  .layout {
    grid-template-columns: 1fr;
  }
  .toolbar {
    flex-wrap: wrap;
  }
  .toolbar select {
    min-width: 100%;
  }
}
@media (max-width: 430px) {
  .imports h1 {
    font-size: 20px;
  }
  .form-panel,
  aside {
    padding: 10px;
  }
  .two {
    grid-template-columns: 1fr;
  }
  .downloads button {
    flex: 1;
  }
  .imports header p:last-child {
    font-size: 11px;
  }
}
</style>
