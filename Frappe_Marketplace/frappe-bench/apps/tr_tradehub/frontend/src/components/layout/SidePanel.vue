<template>
  <aside
    id="sidePanel"
    class="sidebar-panel border-r sidebar-panel-border flex flex-col transition-all duration-200 sticky top-0 h-screen flex-shrink-0 overflow-hidden"
    :style="{ width: sidebar.panelVisible ? panelWidth : '0px' }"
  >
    <!-- Panel Header -->
    <div class="flex items-center justify-between h-[56px] px-4 border-b sidebar-panel-border flex-shrink-0">
      <span class="text-[15px] font-bold sidebar-panel-title tracking-tight truncate">{{ nav.sectionTitle }}</span>
      <button
        class="w-7 h-7 rounded-md flex items-center justify-center sidebar-panel-close-btn transition-all flex-shrink-0"
        @click="sidebar.togglePanel()"
        title="Paneli Kapat"
      >
        <i class="fas fa-angles-left text-sm"></i>
      </button>
    </div>

    <!-- Panel Content -->
    <div class="flex-1 overflow-y-auto panel-scroll px-3 py-4">
      <template v-for="(group, idx) in nav.currentGroups" :key="idx">
        <!-- Group Title (clickable accordion header) -->
        <div
          v-if="group.title"
          class="panel-group-title"
          :class="{ open: nav.isGroupOpen(group.title) }"
          @click="nav.toggleGroup(group.title)"
        >
          <span class="flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">{{ group.title }}</span>
          <span class="pg-count">{{ group.items.length }}</span>
        </div>

        <!-- Group Items -->
        <div
          class="panel-group"
          :class="{
            collapsible: !!group.title,
            open: !group.title || nav.isGroupOpen(group.title)
          }"
        >
          <router-link
            v-for="item in group.items"
            :key="item.label"
            :to="getItemRoute(item)"
            class="panel-item"
            :class="{ active: isItemActive(item) }"
            @click="handleItemClick(item)"
          >
            <i :class="[item.icon, 'panel-item-icon']"></i>
            {{ item.label }}
          </router-link>
        </div>
      </template>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'
import { useNavigationStore } from '@/stores/navigation'
import { useSidebarStore } from '@/stores/sidebar'
import { useBreakpoint } from '@/composables/useBreakpoint'
import { useRoute } from 'vue-router'

const nav = useNavigationStore()
const sidebar = useSidebarStore()
const { isXl, is2xl } = useBreakpoint()
const route = useRoute()

// Responsive panel width: narrower on smaller screens
const panelWidth = computed(() => {
  if (is2xl.value) return '240px'
  if (isXl.value) return '220px'
  return '200px'
})

function getItemRoute(item) {
  if (item.route) return item.route
  if (item.doctype) return `/app/${slugify(item.doctype)}`
  if (item.report) return `/app/report/${slugify(item.report)}`
  return '#'
}

function slugify(str) {
  return str.toLowerCase().replace(/\s+/g, '-')
}

function isItemActive(item) {
  const currentPath = route.path
  const itemPath = getItemRoute(item)
  return currentPath === itemPath
}

function handleItemClick(item) {
  nav.setActiveItem(item.doctype || item.report || item.route)
}
</script>
