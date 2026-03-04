<template>
  <Transition name="dropdown">
    <div
      v-if="open"
      class="absolute bottom-[160px] left-[78px] w-[340px] bg-white border border-gray-200 rounded-lg shadow-2xl shadow-black/12 z-[60] overflow-hidden"
      @click.stop
    >
      <div class="flex flex-col items-center justify-center py-6 bg-cover bg-center bg-no-repeat relative" style="background-image: url('/src/assets/media/menu-header-bg.png')">
        <div class="absolute inset-0 bg-gradient-to-r from-blue-600/60 to-blue-800/60"></div>
        <h3 class="text-white font-semibold text-base relative z-10">Quick Links</h3>
        <span class="relative z-10 inline-block mt-2 text-[11px] bg-blue-500 text-white px-3 py-1 rounded-md font-medium">25 pending tasks</span>
      </div>
      <div class="grid grid-cols-2">
        <a href="#" class="flex flex-col items-center gap-3 py-6 border-r border-b border-gray-100 bg-white hover:bg-gray-50 transition-colors" @click.prevent="emit('navigate', '/app/finance')">
          <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center"><i class="fas fa-euro-sign text-blue-600 text-xl"></i></div>
          <div class="text-center"><p class="text-sm font-semibold text-gray-800">Accounting</p><p class="text-[11px] text-gray-400 mt-0.5">eCommerce</p></div>
        </a>
        <a href="#" class="flex flex-col items-center gap-3 py-6 border-b border-gray-100 bg-white hover:bg-gray-50 transition-colors" @click.prevent="emit('navigate', '/settings')">
          <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center"><i class="fas fa-shield-halved text-blue-600 text-xl"></i></div>
          <div class="text-center"><p class="text-sm font-semibold text-gray-800">Administration</p><p class="text-[11px] text-gray-400 mt-0.5">Console</p></div>
        </a>
        <a href="#" class="flex flex-col items-center gap-3 py-6 border-r border-gray-100 bg-white hover:bg-gray-50 transition-colors" @click.prevent="emit('navigate', '/projects')">
          <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center"><i class="fas fa-folder-open text-blue-600 text-xl"></i></div>
          <div class="text-center"><p class="text-sm font-semibold text-gray-800">Projects</p><p class="text-[11px] text-gray-400 mt-0.5">Pending Tasks</p></div>
        </a>
        <a href="#" class="flex flex-col items-center gap-3 py-6 bg-white hover:bg-gray-50 transition-colors" @click.prevent="emit('navigate', '/app/customers')">
          <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center"><i class="fas fa-users text-blue-600 text-xl"></i></div>
          <div class="text-center"><p class="text-sm font-semibold text-gray-800">Customers</p><p class="text-[11px] text-gray-400 mt-0.5">Latest cases</p></div>
        </a>
      </div>
      <div class="px-4 py-3 border-t border-gray-100 text-center">
        <a href="#" class="text-sm font-medium text-gray-500 hover:text-blue-600 transition-colors" @click.prevent="emit('navigate', '/dashboard')">
          View All <i class="fas fa-chevron-right text-[9px] ml-0.5"></i>
        </a>
      </div>
    </div>
  </Transition>
</template>

<script setup>
defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['navigate'])
</script>
