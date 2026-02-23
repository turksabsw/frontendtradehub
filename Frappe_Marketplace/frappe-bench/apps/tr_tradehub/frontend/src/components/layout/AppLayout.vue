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
      <AppHeader @toggle-mobile-sidebar="toggleMobileSidebar" />

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
import { useNavigationStore } from '@/stores/navigation'

import IconRail from './IconRail.vue'
import SidePanel from './SidePanel.vue'
import AppHeader from './AppHeader.vue'
import AppFooter from './AppFooter.vue'
import NotificationPanel from './NotificationPanel.vue'
import ToastContainer from './ToastContainer.vue'

const nav = useNavigationStore()

const mainMarginLeft = computed(() => {
  return nav.panelCollapsed ? '82px' : '378px'
})

function toggleMobileSidebar() {
  // Mobile sidebar logic
  nav.togglePanel()
}
</script>
