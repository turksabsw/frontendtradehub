<template>
  <aside
    id="sidePanel"
    class="fixed top-0 left-[82px] z-40 h-screen bg-[#1c1c26] border-r border-[#26263a] flex flex-col transition-all duration-200"
    :style="{ width: nav.panelCollapsed ? '0px' : '296px', overflow: nav.panelCollapsed ? 'hidden' : 'visible' }"
  >
    <!-- Panel Header -->
    <div class="flex items-center justify-between h-[64px] px-5 border-b border-[#26263a] flex-shrink-0">
      <span class="text-[15px] font-bold text-white tracking-tight">{{ nav.sectionTitle }}</span>
      <button
        class="w-7 h-7 rounded-md flex items-center justify-center text-[#6e6e82] hover:text-white hover:bg-[#24243a] transition-all"
        @click="nav.togglePanel()"
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
import { useNavigationStore } from '@/stores/navigation'
import { useRoute } from 'vue-router'

const nav = useNavigationStore()
const route = useRoute()

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
