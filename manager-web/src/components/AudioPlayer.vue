<template>
  <div class="ap">
    <audio ref="audioRef" :src="src" preload="metadata" @timeupdate="updateProgress" @loadedmetadata="updateDuration"
      @ended="onEnded" style="display: none"></audio>

    <button type="button" class="ap-play" :aria-label="isPlaying ? 'Pause' : 'Play'" @click="togglePlay">
      <svg width="14" height="14" viewBox="0 0 20 20" aria-hidden="true">
        <path fill="currentColor" :d="isPlaying ? 'M5 3h3.5v14H5zm6.5 0H15v14h-3.5z' : 'M6 3l11 7-11 7z'" />
      </svg>
    </button>

    <div class="ap-bar" ref="progressBar" @click="handleProgressClick">
      <div class="ap-track" :style="{ width: progress + '%' }"></div>
      <div class="ap-thumb" :style="{ left: progress + '%' }" @mousedown="startDrag"></div>
    </div>

    <span class="ap-time">{{ formattedCurrentTime }} / {{ formattedDuration }}</span>

    <div class="ap-volume" ref="volumeControl">
      <button type="button" ref="volumeButton" class="ap-vol-btn" aria-label="Mute" @click="toggleMute"
        @mouseenter="handleVolumeMouseEnter" @mouseleave="startVolumeSliderHideTimer">
        <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" :d="volumeIconPath" /></svg>
      </button>
      <div v-show="showVolumeSlider" class="ap-vol-pop" ref="volumeSlider"
        @mouseenter="cancelVolumeSliderHideTimer" @mouseleave="startVolumeSliderHideTimer">
        <input type="range" v-model="volume" min="0" max="1" step="0.1" class="ap-vol-range" aria-label="Volume" @input="handleVolumeChange">
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { playableUrl } from '@/utils/media'

const props = defineProps({
  audioUrl: String
})

// 播放地址：real 模式原样使用；mock 模式换成浏览器内生成的演示音频，不请求服务端地址
const src = computed(() => (props.audioUrl ? playableUrl(props.audioUrl) : ''))

// 音频元素引用
const audioRef = ref(null)
const progressBar = ref(null)
const volumeButton = ref(null)
const volumeSlider = ref(null)

// 播放状态
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const progress = ref(0)

// 音量状态
const volume = ref(0.7)
const isMuted = ref(false)
const showVolumeSlider = ref(false)
let volumeSliderHideTimer = null

// 格式化时间为 MM:SS
const formatTime = (seconds) => {
  const sec = Math.floor(seconds || 0)
  return `${Math.floor(sec / 60)}:${(sec % 60).toString().padStart(2, '0')}`
}

const formattedCurrentTime = computed(() => formatTime(currentTime.value))
const formattedDuration = computed(() => formatTime(duration.value))

// 根据音量状态返回对应的图标路径
const volumeIconPath = computed(() => {
  if (isMuted.value || volume.value === 0) {
    return 'M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z'
  }
  return 'M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z'
})

// 播放控制
const togglePlay = () => {
  if (isPlaying.value) {
    audioRef.value.pause()
  } else {
    const p = audioRef.value.play()
    if (p && p.catch) p.catch(() => { isPlaying.value = false })
  }
  isPlaying.value = !isPlaying.value
}

const onEnded = () => {
  isPlaying.value = false
}

const updateDuration = () => {
  if (audioRef.value) {
    duration.value = audioRef.value.duration
  }
}

const updateProgress = () => {
  if (audioRef.value?.duration) {
    currentTime.value = audioRef.value.currentTime
    progress.value = (currentTime.value / duration.value) * 100
  }
}

const handleProgressClick = (e) => {
  const rect = e.currentTarget.getBoundingClientRect()
  const percentage = ((e.clientX - rect.left) / rect.width) * 100
  seekToPercentage(percentage)
}

// 音量控制
const toggleMute = () => {
  isMuted.value = !isMuted.value
  audioRef.value.muted = isMuted.value

  // 如果取消静音且音量为0，则恢复默认音量
  if (!isMuted.value && volume.value === 0) {
    volume.value = 0.5
    audioRef.value.volume = 0.5
  }
}

const handleVolumeChange = (e) => {
  const newVolume = parseFloat(e.target.value)
  audioRef.value.volume = newVolume
  isMuted.value = newVolume === 0
}

// 进度条拖拽功能
let isDragging = false

const startDrag = (e) => {
  isDragging = true
  document.addEventListener('mousemove', handleDrag)
  document.addEventListener('mouseup', stopDrag)
  e.preventDefault()
}

const handleDrag = (e) => {
  if (!isDragging) return

  if (!progressBar.value) return
  const rect = progressBar.value.getBoundingClientRect()
  const percentage = ((e.clientX - rect.left) / rect.width) * 100
  seekToPercentage(percentage)
}

const stopDrag = () => {
  isDragging = false
  document.removeEventListener('mousemove', handleDrag)
  document.removeEventListener('mouseup', stopDrag)
}

const seekToPercentage = (percentage) => {
  const clampedPercentage = Math.min(Math.max(percentage, 0), 100)
  progress.value = clampedPercentage
  audioRef.value.currentTime = (clampedPercentage / 100) * duration.value
}

// 音量滑块显示/隐藏控制
const startVolumeSliderHideTimer = () => {
  volumeSliderHideTimer = setTimeout(() => {
    showVolumeSlider.value = false
  }, 300)
}

const cancelVolumeSliderHideTimer = () => {
  clearTimeout(volumeSliderHideTimer)
}

// 音量滑块定位
const updateSliderPosition = () => {
  nextTick(() => {
    if (!volumeButton.value || !volumeSlider.value) return

    // 音量滑块相对音量按钮绝对定位（见样式 .ap-vol-pop），这里无需再按视口坐标计算
  })
}

const handleVolumeMouseEnter = () => {
  showVolumeSlider.value = true
  updateSliderPosition()
}

// 初始化
onMounted(() => {
  if (audioRef.value) {
    audioRef.value.volume = volume.value
  }
  window.addEventListener('resize', updateSliderPosition)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateSliderPosition)
})
</script>

<style scoped>
.ap { display: flex; align-items: center; gap: 10px; height: 36px; padding: 0 8px 0 4px; border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: #fff; min-width: 200px; }
.ap-play { display: inline-flex; align-items: center; justify-content: center; flex: none; width: 28px; height: 28px; border: 0; border-radius: 50%; background: var(--xn-ink); color: #fff; cursor: pointer; }
.ap-play:hover { background: #2B3C57; }
.ap-bar { position: relative; flex: 1; height: 4px; border-radius: 2px; background: var(--xn-line); cursor: pointer; }
.ap-track { height: 100%; border-radius: 2px; background: var(--xn-lake); }
.ap-thumb { position: absolute; top: 50%; width: 10px; height: 10px; border-radius: 50%; background: var(--xn-lake); transform: translate(-50%, -50%); cursor: grab; }
.ap-time { flex: none; font-size: 12px; color: var(--xn-ink-3); font-variant-numeric: tabular-nums; }
.ap-volume { position: relative; flex: none; }
.ap-vol-btn { display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; padding: 0; border: 0; background: none; color: var(--xn-ink-3); cursor: pointer; }
.ap-vol-btn:hover { color: var(--xn-ink); }
.ap-vol-pop { position: absolute; right: calc(100% + 4px); top: 50%; transform: translateY(-50%); z-index: 10; display: flex; align-items: center; padding: 4px 8px; border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: #fff; box-shadow: var(--xn-shadow-pop); }
.ap-vol-range { width: 90px; accent-color: var(--xn-lake); }
</style>
