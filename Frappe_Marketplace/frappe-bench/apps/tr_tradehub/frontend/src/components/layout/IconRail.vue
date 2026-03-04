<template>
  <div class="w-[72px] h-screen sticky top-0 z-50 sidebar-rail flex flex-col items-center border-r sidebar-rail-border flex-shrink-0">
    <TenantSwitcher />

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

    <div class="w-full flex flex-col items-center gap-1 py-3 border-t sidebar-rail-border">
      <button class="rail-icon" @click="toast.info('Yardım merkezi açılıyor...')">
        <i class="fas fa-circle-question"></i>
        <span class="rail-label">Yardım</span>
      </button>
      <button
        class="rail-icon"
        @click.stop="quickLinksOpen = !quickLinksOpen; themeDropdownOpen = false; userDropdownOpen = false; notifications.panelOpen = false"
      >
        <i class="fas fa-grip"></i>
        <span class="rail-label">Linkler</span>
      </button>
      <button
        class="rail-icon"
        @click.stop="themeDropdownOpen = !themeDropdownOpen; userDropdownOpen = false; quickLinksOpen = false; notifications.panelOpen = false"
      >
        <i class="fas fa-gear"></i>
        <span class="rail-label">Ayarlar</span>
      </button>
      <button
        class="rail-icon rail-avatar-btn"
        @click.stop="userDropdownOpen = !userDropdownOpen; themeDropdownOpen = false; quickLinksOpen = false; notifications.panelOpen = false"
      >
        <div class="w-9 h-9 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white text-[11px] font-bold ring-2 ring-transparent hover:ring-[#6c5dd3]/50 transition-all">
          {{ tenant.activeTenant?.initials || 'AK' }}
        </div>
        <span class="rail-label">Hesap</span>
      </button>
    </div>

    <!-- Dropdown Components -->
    <UserMenuDropdown
      :open="userDropdownOpen"
      @navigate="navigateTo"
      @logout="handleLogout"
    />
    <QuickLinksDropdown
      :open="quickLinksOpen"
      @navigate="navigateTo"
    />
    <ThemeDropdown
      :open="themeDropdownOpen"
      :current-theme="currentTheme"
      @set-theme="handleSetTheme"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { railSections } from '@/data/navigation'
import { useNavigationStore } from '@/stores/navigation'
import { useTenantStore } from '@/stores/tenant'
import { useAuthStore } from '@/stores/auth'
import { useToast } from '@/composables/useToast'
import { useTheme } from '@/composables/useTheme'
import { useNotificationStore } from '@/stores/notification'
import TenantSwitcher from '@/components/navigation/TenantSwitcher.vue'
import UserMenuDropdown from '@/components/navigation/UserMenuDropdown.vue'
import QuickLinksDropdown from '@/components/navigation/QuickLinksDropdown.vue'
import ThemeDropdown from '@/components/navigation/ThemeDropdown.vue'

const nav = useNavigationStore()
const tenant = useTenantStore()
const auth = useAuthStore()
const toast = useToast()
const router = useRouter()
const { currentTheme, setTheme } = useTheme()
const notifications = useNotificationStore()

const userDropdownOpen = ref(false)
const themeDropdownOpen = ref(false)
const quickLinksOpen = ref(false)

function closeAllDropdowns() {
  userDropdownOpen.value = false
  themeDropdownOpen.value = false
  quickLinksOpen.value = false
  notifications.panelOpen = false
}

function handleSetTheme(theme) {
  setTheme(theme)
  closeAllDropdowns()
  toast.info(`Tema: ${theme === 'light' ? 'Açık' : theme === 'dark' ? 'Koyu' : 'Sistem'}`)
}

function navigateTo(path) {
  closeAllDropdowns()
  router.push(path)
}

async function handleLogout() {
  closeAllDropdowns()
  await auth.logout()
  router.push('/login')
}

function handleOutsideClick(e) {
  const inside = e.target.closest('[class*="absolute bottom"]') || e.target.closest('[class*="absolute bottom-"]')
  const rail = e.target.closest('.rail-icon') || e.target.closest('.rail-avatar-btn')
  if (!inside && !rail) closeAllDropdowns()
}

onMounted(() => document.addEventListener('click', handleOutsideClick))
onUnmounted(() => document.removeEventListener('click', handleOutsideClick))
</script>