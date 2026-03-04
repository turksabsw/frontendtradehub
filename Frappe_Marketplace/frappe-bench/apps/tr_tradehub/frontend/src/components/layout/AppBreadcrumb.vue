<template>
  <div class="flex items-center gap-1.5 px-4 xl:px-6 py-2.5 text-xs text-gray-400 bg-white border-b border-gray-100">
    <router-link to="/dashboard" class="hover:text-violet-600 transition-colors">Ana Sayfa</router-link>
    <i class="fas fa-chevron-right text-[7px] text-gray-300"></i>
    <template v-if="route.meta?.breadcrumbParent">
      <span class="hover:text-violet-600 transition-colors cursor-pointer">{{ route.meta.breadcrumbParent }}</span>
      <i class="fas fa-chevron-right text-[7px] text-gray-300"></i>
    </template>
    <span class="text-gray-600 font-medium">{{ route.meta?.breadcrumb || route.meta?.title || 'Genel Bakış' }}</span>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>