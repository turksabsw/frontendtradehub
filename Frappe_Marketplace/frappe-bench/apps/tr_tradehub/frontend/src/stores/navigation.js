import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { panelSections, sectionTitles } from '@/data/navigation'
import { useSidebarStore } from '@/stores/sidebar'

export const useNavigationStore = defineStore('navigation', () => {
  const activeSection = ref('dashboard')
  const activePanelItem = ref(null) // doctype or route
  const openGroups = ref(new Set())

  const sectionTitle = computed(() => sectionTitles[activeSection.value] || 'TradeHub')
  const currentGroups = computed(() => panelSections[activeSection.value] || [])

  function switchSection(sectionId) {
    activeSection.value = sectionId
    openGroups.value = new Set()
    // Auto-open first collapsible group
    const groups = panelSections[sectionId] || []
    const firstCollapsible = groups.find(g => g.title)
    if (firstCollapsible) {
      openGroups.value.add(firstCollapsible.title)
    }
    // Open sidebar panel if collapsed
    useSidebarStore().openPanel()
  }

  function setActiveItem(itemKey) {
    activePanelItem.value = itemKey
  }

  function toggleGroup(groupTitle) {
    if (openGroups.value.has(groupTitle)) {
      openGroups.value.delete(groupTitle)
    } else {
      openGroups.value.add(groupTitle)
    }
    // Force reactivity
    openGroups.value = new Set(openGroups.value)
  }

  function isGroupOpen(groupTitle) {
    return openGroups.value.has(groupTitle)
  }

  return {
    activeSection,
    activePanelItem,
    openGroups,
    sectionTitle,
    currentGroups,
    switchSection,
    setActiveItem,
    toggleGroup,
    isGroupOpen,
  }
})
