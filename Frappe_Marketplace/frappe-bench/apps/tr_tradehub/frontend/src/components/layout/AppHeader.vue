<template>
  <header class="sticky top-0 z-30 bg-white border-b border-[#e8e8ef] h-[56px] flex items-center px-5 gap-4">
    <!-- Hamburger (when panel collapsed) -->
    <button
      v-if="nav.panelCollapsed"
      class="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors flex-shrink-0"
      @click="nav.togglePanel()"
    >
      <i class="fas fa-bars text-sm"></i>
    </button>

    <!-- Search Bar -->
    <div class="relative flex-1 max-w-[540px]">
      <i class="fas fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 text-[13px]"></i>
      <input
        v-model="searchQuery"
        type="text"
        placeholder="Herşeyi Ara - Ne Alırsan 5 TL..."
        class="w-full h-[42px] pl-11 pr-4 text-[13px] bg-gray-50/80 border border-gray-200 rounded-full outline-none focus:border-violet-400 focus:ring-2 focus:ring-violet-500/10 focus:bg-white transition-all placeholder:text-gray-400"
        @focus="showSearchResults = true"
        @blur="hideSearchResults"
        @keydown.escape="showSearchResults = false"
      >
      <!-- Search Results -->
      <GlobalSearch
        v-if="showSearchResults && searchQuery.length >= 2"
        :query="searchQuery"
        @select="handleSearchSelect"
      />
    </div>

    <!-- Spacer -->
    <div class="flex-1"></div>

    <!-- Right Icons -->
    <div class="flex items-center gap-0.5">

      <!-- Notifications -->
      <button class="hdr-icon-btn relative" @click.stop="handleNotificationClick" title="Bildirimler">
        <i class="fas fa-bell text-[15px]"></i>
        <span
          v-if="notifications.hasUnread"
          class="absolute top-1.5 right-1.5 w-2 h-2 bg-green-500 rounded-full ring-2 ring-white"
        ></span>
      </button>


      <!-- Settings -->
      <button class="hdr-icon-btn" @click="navigateTo('/settings')" title="Ayarlar">
        <i class="fas fa-gear text-[15px]"></i>
      </button>
    </div>
  </header>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useNavigationStore } from '@/stores/navigation'
import { useNotificationStore } from '@/stores/notification'
import { useToast } from '@/composables/useToast'
import GlobalSearch from '@/components/common/GlobalSearch.vue'

const router = useRouter()
const nav = useNavigationStore()
const notifications = useNotificationStore()
const toast = useToast()

const searchQuery = ref('')
const showSearchResults = ref(false)
const openDropdown = ref(null) // 'quicklinks' | null

function toggleDropdown(name) {
  notifications.panelOpen = false
  if (openDropdown.value === name) {
    openDropdown.value = null
  } else {
    openDropdown.value = name
  }
}

function closeAllDropdowns() {
  openDropdown.value = null
  notifications.panelOpen = false
}

function handleNotificationClick() {
  openDropdown.value = null
  notifications.togglePanel()
}


function navigateTo(path) {
  closeAllDropdowns()
  router.push(path)
}

function hideSearchResults() {
  setTimeout(() => { showSearchResults.value = false }, 200)
}

function handleSearchSelect(item) {
  searchQuery.value = ''
  showSearchResults.value = false
}

// Close dropdowns on outside click
function handleOutsideClick(e) {
  if (!e.target.closest('.hdr-dropdown') &&
      !e.target.closest('.hdr-icon-btn') &&
      !e.target.closest('.hdr-dropdown-item') &&
      !e.target.closest('#notificationPanel') &&
      !e.target.closest('[class*="fixed top-"]')) {
    closeAllDropdowns()
  }
}

onMounted(() => {
  document.addEventListener('click', handleOutsideClick)
})

onUnmounted(() => {
  document.removeEventListener('click', handleOutsideClick)
})
</script>
