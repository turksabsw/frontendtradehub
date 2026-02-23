<template>
  <header class="sticky top-0 z-30 bg-white border-b border-[#e8e8ef] h-[60px] flex items-center px-6">
    <div class="flex items-center justify-between w-full">
      <!-- Left -->
      <div class="flex items-center gap-4">
        <button
          class="lg:hidden p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg"
          @click="$emit('toggle-mobile-sidebar')"
        >
          <i class="fas fa-bars"></i>
        </button>
        <div>
          <h2 class="text-[15px] font-bold text-gray-900">{{ pageTitle }}</h2>
          <nav class="flex items-center gap-1.5 text-xs text-gray-400">
            <router-link to="/dashboard" class="hover:text-violet-600 transition-colors">Ana Sayfa</router-link>
            <i class="fas fa-chevron-right text-[7px]"></i>
            <span class="text-gray-600">{{ breadcrumbText }}</span>
          </nav>
        </div>
      </div>

      <!-- Right -->
      <div class="flex items-center gap-1">
        <!-- View toggles -->
        <button class="hdr-btn" title="Grid View"><i class="fas fa-grip"></i></button>
        <button class="hdr-btn" title="List View"><i class="fas fa-list"></i></button>
        <button class="hdr-btn" title="Filtre"><i class="fas fa-sliders"></i></button>

        <!-- Search -->
        <div class="relative ml-2">
          <i class="fas fa-magnifying-glass absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs"></i>
          <input
            v-model="searchQuery"
            type="text"
            placeholder="Ara..."
            class="w-44 pl-8 pr-3 py-2 text-[13px] bg-gray-50 border border-gray-200 rounded-lg focus:ring-2 focus:ring-violet-500/20 focus:border-violet-400 outline-none transition-all placeholder:text-gray-400"
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

        <!-- Notifications -->
        <button
          class="hdr-btn relative ml-1"
          @click="notifications.togglePanel()"
          title="Bildirimler"
        >
          <i class="fas fa-bell"></i>
          <span
            v-if="notifications.hasUnread"
            class="absolute top-1 right-1 w-2 h-2 bg-red-500 rounded-full"
          ></span>
        </button>

        <!-- Reports -->
        <button class="hdr-btn-outlined ml-1" @click="toast.info('Rapor indiriliyor...')">
          <i class="fas fa-chart-column mr-1.5 text-xs"></i>Raporlar
        </button>

        <!-- Add -->
        <router-link to="/app/product-add" class="hdr-btn-primary ml-1">
          <i class="fas fa-plus mr-1.5 text-xs"></i>Ekle
        </router-link>
      </div>
    </div>
  </header>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useNotificationStore } from '@/stores/notification'
import { useToast } from '@/composables/useToast'
import GlobalSearch from '@/components/common/GlobalSearch.vue'

const route = useRoute()
const notifications = useNotificationStore()
const toast = useToast()

const searchQuery = ref('')
const showSearchResults = ref(false)

const pageTitle = computed(() => route.meta?.title || 'Genel Bakış')
const breadcrumbText = computed(() => route.meta?.breadcrumb || route.meta?.title || 'Genel Bakış')

function hideSearchResults() {
  setTimeout(() => { showSearchResults.value = false }, 200)
}

function handleSearchSelect(item) {
  searchQuery.value = ''
  showSearchResults.value = false
}

defineEmits(['toggle-mobile-sidebar'])
</script>
