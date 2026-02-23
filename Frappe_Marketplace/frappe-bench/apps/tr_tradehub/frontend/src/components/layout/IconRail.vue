<template>
  <div class="fixed top-0 left-0 z-50 w-[82px] h-screen bg-rail flex flex-col items-center border-r border-white/5">
    <!-- Tenant Switcher -->
    <TenantSwitcher />

    <!-- Rail Icons -->
    <div class="flex-1 w-full flex flex-col items-center py-3 gap-1 overflow-y-auto rail-scroll">
      <button
        v-for="section in railSections"
        :key="section.id"
        class="rail-icon"
        :class="{ active: nav.activeSection === section.id }"
        :data-section="section.id"
        @click="nav.switchSection(section.id)"
      >
        <i :class="section.icon"></i>
        <span class="rail-label">{{ section.label }}</span>
      </button>
    </div>

    <!-- Bottom: Help + User Avatar -->
    <div class="w-full flex flex-col items-center gap-1 py-3 border-t border-white/5">
      <button class="rail-icon" @click="toast.info('Yardım merkezi açılıyor...')">
        <i class="fas fa-circle-question"></i>
        <span class="rail-label">Yardım</span>
      </button>
      <button
        class="w-10 h-10 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white text-[11px] font-bold ring-2 ring-transparent hover:ring-[#6c5dd3]/50 transition-all mt-1"
        @click="userDropdownOpen = !userDropdownOpen"
      >
        {{ tenant.activeTenant?.initials || 'AK' }}
      </button>
    </div>

    <!-- User Dropdown -->
    <Transition name="dropdown">
      <div
        v-if="userDropdownOpen"
        class="absolute bottom-16 left-[6px] w-52 bg-white border border-gray-200 rounded-xl shadow-xl shadow-black/10 z-[60] overflow-hidden"
      >
        <div class="p-4 border-b border-gray-100">
          <p class="text-sm font-bold text-gray-800">{{ tenant.activeTenant?.name }}</p>
          <p class="text-[11px] text-gray-400">{{ auth.user?.email || 'admin@tradehub.com' }}</p>
        </div>
        <div class="py-1">
          <a href="#" class="dd-item" @click.prevent="navigateTo('/settings/profile')"><i class="fas fa-user w-4 text-gray-400"></i>Profilim</a>
          <a href="#" class="dd-item" @click.prevent="navigateTo('/settings')"><i class="fas fa-gear w-4 text-gray-400"></i>Ayarlar</a>
          <a href="#" class="dd-item"><i class="fas fa-circle-question w-4 text-gray-400"></i>Yardım</a>
        </div>
        <div class="border-t border-gray-100 py-1">
          <a href="#" class="dd-item text-red-500" @click.prevent="handleLogout"><i class="fas fa-arrow-right-from-bracket w-4"></i>Oturumu Kapat</a>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { railSections } from '@/data/navigation'
import { useNavigationStore } from '@/stores/navigation'
import { useTenantStore } from '@/stores/tenant'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import TenantSwitcher from './TenantSwitcher.vue'

const nav = useNavigationStore()
const tenant = useTenantStore()
const auth = useAuthStore()
const toast = useToast()
const router = useRouter()

const userDropdownOpen = ref(false)

function navigateTo(path) {
  userDropdownOpen.value = false
  router.push(path)
}

async function handleLogout() {
  userDropdownOpen.value = false
  await auth.logout()
  router.push('/login')
}

// Close on outside click
document.addEventListener('click', (e) => {
  if (!e.target.closest('.rounded-full') && !e.target.closest('[class*="absolute bottom"]')) {
    userDropdownOpen.value = false
  }
})
</script>
