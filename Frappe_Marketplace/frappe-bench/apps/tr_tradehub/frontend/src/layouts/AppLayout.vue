<template>
  <div class="h-full font-sans bg-[#f6f6f9] text-gray-800 antialiased">
    <div class="flex h-full">
      <!-- IconRail: always visible -->
      <IconRail />

      <!-- SidePanel: toggle open/close at all sizes -->
      <SidePanel />

      <!-- Main content: flex-1 fills remaining space -->
      <div class="flex-1 min-w-0 flex flex-col min-h-screen">
        <AppHeader />
        <AppBreadcrumb />
        <NotificationPanel />

        <main class="flex-1 p-4 xl:p-6 page-content">
          <router-view v-slot="{ Component }">
            <Transition name="page" mode="out-in">
              <component :is="Component" />
            </Transition>
          </router-view>
        </main>

        <AppFooter />
      </div>
    </div>

    <ToastContainer />
  </div>
</template>

<script setup>
import IconRail from '@/components/layout/IconRail.vue'
import SidePanel from '@/components/layout/SidePanel.vue'
import AppHeader from '@/components/layout/AppHeader.vue'
import AppFooter from '@/components/layout/AppFooter.vue'
import AppBreadcrumb from '@/components/layout/AppBreadcrumb.vue'
import NotificationPanel from '@/components/layout/NotificationPanel.vue'
import ToastContainer from '@/components/layout/ToastContainer.vue'
</script>
