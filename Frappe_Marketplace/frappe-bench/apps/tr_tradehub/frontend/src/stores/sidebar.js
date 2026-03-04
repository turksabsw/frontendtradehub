import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useSidebarStore = defineStore('sidebar', () => {
  const panelVisible = ref(true)

  function togglePanel() {
    panelVisible.value = !panelVisible.value
  }

  function openPanel() {
    panelVisible.value = true
  }

  return {
    panelVisible,
    togglePanel,
    openPanel,
  }
})
