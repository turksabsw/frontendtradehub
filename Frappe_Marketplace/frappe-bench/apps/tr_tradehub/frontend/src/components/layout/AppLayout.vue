<template>
  <div class="h-full font-sans bg-[#f6f6f9] text-gray-800 antialiased">
    <!-- Icon Rail (leftmost) -->
    <IconRail />

    <!-- Side Panel (secondary sidebar) -->
    <SidePanel />

    <!-- Main Content Wrapper -->
    <div
      class="min-h-screen flex flex-col transition-all duration-200"
      :style="{ marginLeft: mainMarginLeft }"
    >
      <!-- Header -->
      <AppHeader />

      <!-- Breadcrumb Bar -->
      <div class="flex items-center gap-1.5 px-6 py-2.5 text-xs text-gray-400 bg-white border-b border-gray-100">
        <router-link to="/dashboard" class="hover:text-violet-600 transition-colors">Ana Sayfa</router-link>
        <i class="fas fa-chevron-right text-[7px] text-gray-300"></i>
        <template v-if="route.meta?.breadcrumbParent">
          <span class="hover:text-violet-600 transition-colors cursor-pointer">{{ route.meta.breadcrumbParent }}</span>
          <i class="fas fa-chevron-right text-[7px] text-gray-300"></i>
        </template>
        <span class="text-gray-600 font-medium">{{ route.meta?.breadcrumb || route.meta?.title || 'Genel Bakış' }}</span>
      </div>

      <!-- Notification Panel -->
      <NotificationPanel />

      <!-- Page Content (router-view) -->
      <main class="flex-1 p-6 page-content">
        <router-view v-slot="{ Component }">
          <Transition name="page" mode="out-in">
            <component :is="Component" />
          </Transition>
        </router-view>
      </main>

      <!-- Footer -->
      <AppFooter />
    </div>

    <!-- Toast Container -->
    <ToastContainer />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useNavigationStore } from '@/stores/navigation'

import IconRail from './IconRail.vue'
import SidePanel from './SidePanel.vue'
import AppHeader from './AppHeader.vue'
import AppFooter from './AppFooter.vue'
import NotificationPanel from './NotificationPanel.vue'
import ToastContainer from './ToastContainer.vue'

const route = useRoute()
const nav = useNavigationStore()

const mainMarginLeft = computed(() => {
  return nav.panelCollapsed ? '82px' : '378px'
})
</script>

