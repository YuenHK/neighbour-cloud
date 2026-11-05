<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ phase: string, message: string }>()
const names: Record<string, string> = {
  ready: '我喺度',
  thinking: '整理緊',
  replying: '回覆中',
  preparing: '準備語音',
  speaking: '朗讀中',
  attention: '服務提示',
}
const label = computed(() => names[props.phase] || names.ready)
</script>

<template>
  <div class="resident-conversation-state" :data-phase="phase" role="status" aria-live="polite" aria-atomic="true">
    <span class="resident-state-mark" aria-hidden="true"><i /><i /><i /><i /></span>
    <div class="resident-state-copy">
      <strong>{{ label }}</strong>
      <Transition name="resident-state-copy" mode="out-in">
        <span :key="message">{{ message }}</span>
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.resident-conversation-state { display:flex; align-items:center; gap:12px; min-height:48px; padding:10px 12px; border-radius:14px; background:#ecf5f099; color:#24564d; }
.resident-state-copy { flex:1 1 0; min-width:0; display:grid; gap:3px; line-height:1.5; }
.resident-state-copy strong { font-size:13px; font-weight:650; }
.resident-state-copy span { font-size:13px; overflow-wrap:anywhere; will-change:transform; }
.resident-state-mark { flex:0 0 28px; height:28px; display:flex; align-items:center; justify-content:center; gap:3px; }
.resident-state-mark i { width:3px; height:6px; border-radius:4px; background:currentColor; transition:height .18s ease; }
[data-phase="ready"] .resident-state-mark i { height:4px; }
[data-phase="ready"] .resident-state-mark i:last-child { display:none; }
[data-phase="thinking"] .resident-state-mark i,[data-phase="replying"] .resident-state-mark i,[data-phase="preparing"] .resident-state-mark i { animation:resident-state-breathe 1.5s ease-in-out infinite; }
.resident-state-mark i:nth-child(2) { animation-delay:120ms; }
.resident-state-mark i:nth-child(3) { animation-delay:240ms; }
.resident-state-mark i:nth-child(4) { animation-delay:360ms; }
[data-phase="speaking"] .resident-state-mark i { animation:resident-state-voice .7s ease-in-out infinite alternate; }
[data-phase="attention"] { color:#854b2b; background:#fbf0e3; }
[data-phase="attention"] .resident-state-mark i { height:12px; }
.resident-state-copy-enter-active,.resident-state-copy-leave-active { transition:opacity .12s ease,transform .12s ease; }
.resident-state-copy-enter-from { opacity:0; transform:translateY(3px); }
.resident-state-copy-leave-to { opacity:0; transform:translateY(-3px); }
@keyframes resident-state-breathe { 0%,100% { opacity:.45; } 50% { opacity:1; } }
@keyframes resident-state-voice { from { height:5px; } to { height:18px; } }
@media(prefers-reduced-motion:reduce) { *,*::before,*::after { animation:none!important; transition:none!important; } [data-phase="speaking"] .resident-state-mark i:nth-child(even) { height:16px; } }
</style>
