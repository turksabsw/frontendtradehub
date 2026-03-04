<template>
  <Transition name="dropdown">
    <div
      v-if="open"
      class="absolute bottom-[110px] left-[78px] w-[160px] bg-white border border-gray-200 rounded-xl shadow-xl shadow-black/10 z-[60] overflow-hidden py-1.5"
      @click.stop
    >
      <button class="dd-item w-full" :class="{ 'text-violet-600 font-semibold bg-violet-50': currentTheme === 'light' }" @click="emit('set-theme', 'light')">
        <i class="fas fa-sun text-amber-400 w-5 text-center text-[13px]"></i><span>Açık</span>
      </button>
      <button class="dd-item w-full" :class="{ 'text-violet-600 font-semibold bg-violet-50': currentTheme === 'dark' }" @click="emit('set-theme', 'dark')">
        <i class="fas fa-moon text-indigo-400 w-5 text-center text-[13px]"></i><span>Koyu</span>
      </button>
      <button class="dd-item w-full" :class="{ 'text-violet-600 font-semibold bg-violet-50': currentTheme === 'system' }" @click="emit('set-theme', 'system')">
        <i class="fas fa-desktop text-gray-400 w-5 text-center text-[13px]"></i><span>Sistem</span>
      </button>
    </div>
  </Transition>
</template>

<script setup>
defineProps({
  open: { type: Boolean, default: false },
  currentTheme: { type: String, default: 'system' },
})
const emit = defineEmits(['set-theme'])
</script>
