import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useNotificationStore = defineStore('notification', () => {
  const notifications = ref([
    { id: 1, message: '<b>Yeni RFQ talebi:</b> RFQ-2026-1204 - Mega Yapı A.Ş.', time: '15 dakika önce', read: false, dot: 'blue' },
    { id: 2, message: '<b>Sipariş tamamlandı:</b> #ORD-7291 - ₺124,500', time: '1 saat önce', read: false, dot: 'green' },
    { id: 3, message: '<b>Stok uyarısı:</b> 5 ürün kritik seviyede', time: '2 saat önce', read: false, dot: 'amber' },
    { id: 4, message: 'Gönderi #SHP-2891 teslim edildi', time: '4 saat önce', read: true, dot: 'gray' },
    { id: 5, message: 'Yeni 5 yıldız değerlendirme alındı', time: '6 saat önce', read: true, dot: 'gray' },
  ])

  const panelOpen = ref(false)
  const unreadCount = computed(() => notifications.value.filter(n => !n.read).length)
  const hasUnread = computed(() => unreadCount.value > 0)

  function togglePanel() {
    panelOpen.value = !panelOpen.value
  }

  function closePanel() {
    panelOpen.value = false
  }

  function markAllRead() {
    notifications.value.forEach(n => { n.read = true; n.dot = 'gray' })
  }

  function markRead(id) {
    const n = notifications.value.find(n => n.id === id)
    if (n) { n.read = true; n.dot = 'gray' }
  }

  return {
    notifications,
    panelOpen,
    unreadCount,
    hasUnread,
    togglePanel,
    closePanel,
    markAllRead,
    markRead,
  }
})
