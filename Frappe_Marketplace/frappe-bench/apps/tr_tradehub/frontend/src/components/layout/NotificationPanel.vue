<template>
  <Transition name="dropdown">
    <div
      v-if="notifications.panelOpen"
      id="notificationPanel"
      class="fixed top-[60px] right-6 w-[380px] bg-white border border-gray-200 rounded-xl shadow-xl shadow-black/5 z-50 overflow-hidden"
      @click.stop
    >
      <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100">
        <h3 class="text-sm font-bold text-gray-800">Bildirimler</h3>
        <button
          @click="handleMarkAllRead"
          class="text-[11px] text-violet-600 hover:text-violet-700 font-medium"
        >
          Tümünü Okundu İşaretle
        </button>
      </div>
      <div class="max-h-80 overflow-y-auto divide-y divide-gray-50">
        <div
          v-for="n in notifications.notifications"
          :key="n.id"
          class="notif-item"
          :class="{ unread: !n.read }"
          @click="notifications.markRead(n.id)"
        >
          <div :class="`notif-dot-${n.dot}`"></div>
          <div class="flex-1">
            <p class="text-xs text-gray-800" v-html="n.message"></p>
            <p class="text-[10px] text-gray-400 mt-0.5">{{ n.time }}</p>
          </div>
        </div>
      </div>
      <div class="px-5 py-3 border-t border-gray-100 text-center">
        <router-link to="/messaging/notifications" class="text-xs font-medium text-violet-600 hover:text-violet-700">
          Tüm Bildirimleri Gör
        </router-link>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { useNotificationStore } from '@/stores/notification'
import { useToast } from '@/composables/useToast'

const notifications = useNotificationStore()
const toast = useToast()

function handleMarkAllRead() {
  notifications.markAllRead()
  toast.success('Tüm bildirimler okundu')
}
</script>
