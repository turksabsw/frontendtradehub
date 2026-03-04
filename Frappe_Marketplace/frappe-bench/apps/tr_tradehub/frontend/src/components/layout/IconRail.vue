<template>
  <div class="fixed top-0 left-0 z-50 w-[82px] h-screen sidebar-rail flex flex-col items-center border-r sidebar-rail-border">
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

    <!-- Bottom: Yardım + Linkler + Ayarlar + Hesap -->
    <div class="w-full flex flex-col items-center gap-1 py-3 border-t sidebar-rail-border">
      <button class="rail-icon" @click="toast.info('Yardım merkezi açılıyor...')">
        <i class="fas fa-circle-question"></i>
        <span class="rail-label">Yardım</span>
      </button>
      <button
        class="rail-icon"
        @click.stop="quickLinksOpen = !quickLinksOpen; themeDropdownOpen = false; userDropdownOpen = false; notifications.panelOpen = false"
        title="Hızlı Bağlantılar"
      >
        <i class="fas fa-grip"></i>
        <span class="rail-label">Linkler</span>
      </button>
      <button
        class="rail-icon"
        @click.stop="themeDropdownOpen = !themeDropdownOpen; userDropdownOpen = false; quickLinksOpen = false; notifications.panelOpen = false"
        title="Tema Ayarları"
      >
        <i class="fas fa-gear"></i>
        <span class="rail-label">Ayarlar</span>
      </button>
      <button
        class="rail-icon rail-avatar-btn"
        @click.stop="userDropdownOpen = !userDropdownOpen; themeDropdownOpen = false; quickLinksOpen = false; notifications.panelOpen = false"
      >
        <div
          class="w-9 h-9 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white text-[11px] font-bold ring-2 ring-transparent hover:ring-[#6c5dd3]/50 transition-all"
        >
          {{ tenant.activeTenant?.initials || 'AK' }}
        </div>
        <span class="rail-label">Hesap</span>
      </button>
    </div>

    <!-- User Dropdown (Profile Menu) -->
    <Transition name="dropdown">
      <div
        v-if="userDropdownOpen"
        class="absolute bottom-2 left-[88px] w-[260px] bg-white border border-gray-200 rounded-xl shadow-xl shadow-black/10 z-[60]"
        @click.stop
      >
        <!-- Profile Header -->
        <div class="p-4 flex items-center gap-3 border-b border-gray-100">
          <div class="w-11 h-11 rounded-full bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
            {{ tenant.activeTenant?.initials || 'AK' }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="text-sm font-semibold text-gray-800 truncate">{{ tenant.activeTenant?.name || 'Admin' }}</p>
              <span class="text-[9px] font-bold uppercase bg-violet-100 text-violet-600 px-1.5 py-0.5 rounded flex-shrink-0">Pro</span>
            </div>
            <p class="text-[11px] text-gray-400 truncate mt-0.5">{{ auth.user?.email || 'admin@tradehub.com' }}</p>
          </div>
        </div>
        <!-- Menu Items -->
        <div class="py-1.5">
          <a href="#" class="dd-item" @click.prevent="navigateTo('/settings/profile')">
            Profilim
          </a>
          <a href="#" class="dd-item" @click.prevent="navigateTo('/projects')">
            <span class="flex-1">Projelerim</span>
            <span class="text-[10px] font-bold bg-red-100 text-red-500 px-1.5 py-0.5 rounded-full leading-none">3</span>
          </a>
          <div class="relative group/sub">
            <a href="#" class="dd-item" @click.prevent="navigateTo('/subscription')">
              <span class="flex-1">Aboneliğim</span>
              <i class="fas fa-chevron-right text-[9px] text-gray-300"></i>
            </a>
            <!-- Subscription Submenu -->
            <div class="sub-menu">
              <a href="#" class="dd-item" @click.prevent="navigateTo('/subscription/referrals')">
                <i class="fas fa-user-plus text-[11px] w-5 text-center text-gray-400"></i>
                Referanslar
              </a>
              <a href="#" class="dd-item" @click.prevent="navigateTo('/subscription/billing')">
                <i class="fas fa-file-invoice text-[11px] w-5 text-center text-gray-400"></i>
                Faturalar
              </a>
              <a href="#" class="dd-item" @click.prevent="navigateTo('/subscription/payments')">
                <i class="fas fa-credit-card text-[11px] w-5 text-center text-gray-400"></i>
                Ödemeler
              </a>
              <a href="#" class="dd-item" @click.prevent="navigateTo('/subscription/statements')">
                <i class="fas fa-receipt text-[11px] w-5 text-center text-gray-400"></i>
                Ekstreler
                <i class="fas fa-circle-info text-[9px] text-gray-300 ml-auto"></i>
              </a>
              <div class="dd-item justify-between cursor-default">
                <div class="flex items-center gap-2">
                  <i class="fas fa-bell text-[11px] w-5 text-center text-gray-400"></i>
                  <span>Bildirimler</span>
                </div>
                <label class="relative inline-flex items-center cursor-pointer">
                  <input type="checkbox" checked class="sr-only peer">
                  <div class="w-8 h-4 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:bg-violet-500"></div>
                </label>
              </div>
            </div>
          </div>
          <a href="#" class="dd-item" @click.prevent="navigateTo('/statements')">
            Hesap Özetlerim
          </a>
        </div>
        <div class="border-t border-gray-100 py-1.5">
          <div class="dd-item justify-between cursor-default">
            <span>Dil</span>
            <span class="text-xs text-gray-400 flex items-center gap-1">Türkçe 🇹🇷</span>
          </div>
          <a href="#" class="dd-item" @click.prevent="navigateTo('/settings')">
            Hesap Ayarları
          </a>
        </div>
        <div class="border-t border-gray-100 py-1.5">
          <a href="#" class="dd-item text-red-500" @click.prevent="handleLogout">
            Oturumu Kapat
          </a>
        </div>
      </div>
    </Transition>

    <!-- Quick Links Dropdown -->
    <Transition name="dropdown">
      <div
        v-if="quickLinksOpen"
        class="absolute bottom-[160px] left-[88px] w-[340px] bg-white border border-gray-200 rounded-lg shadow-2xl shadow-black/12 z-[60] overflow-hidden"
        @click.stop
      >
        <div class="flex flex-col items-center justify-center py-6 bg-cover bg-center bg-no-repeat relative" style="background-image: url('/src/assets/media/menu-header-bg.png')">
          <div class="absolute inset-0 bg-gradient-to-r from-blue-600/60 to-blue-800/60"></div>
          <h3 class="text-white font-semibold text-base relative z-10">Quick Links</h3>
          <span class="relative z-10 inline-block mt-2 text-[11px] bg-blue-500 text-white px-3 py-1 rounded-md font-medium">25 pending tasks</span>
        </div>
        <div class="grid grid-cols-2">
          <a href="#" class="flex flex-col items-center gap-3 py-6 border-r border-b border-gray-100 bg-white hover:bg-gray-50 transition-colors" @click.prevent="navigateTo('/app/finance')">
            <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center">
              <i class="fas fa-euro-sign text-blue-600 text-xl"></i>
            </div>
            <div class="text-center">
              <p class="text-sm font-semibold text-gray-800">Accounting</p>
              <p class="text-[11px] text-gray-400 mt-0.5">eCommerce</p>
            </div>
          </a>
          <a href="#" class="flex flex-col items-center gap-3 py-6 border-b border-gray-100 bg-white hover:bg-gray-50 transition-colors" @click.prevent="navigateTo('/settings')">
            <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center">
              <i class="fas fa-shield-halved text-blue-600 text-xl"></i>
            </div>
            <div class="text-center">
              <p class="text-sm font-semibold text-gray-800">Administration</p>
              <p class="text-[11px] text-gray-400 mt-0.5">Console</p>
            </div>
          </a>
          <a href="#" class="flex flex-col items-center gap-3 py-6 border-r border-gray-100 bg-white hover:bg-gray-50 transition-colors" @click.prevent="navigateTo('/projects')">
            <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center">
              <i class="fas fa-folder-open text-blue-600 text-xl"></i>
            </div>
            <div class="text-center">
              <p class="text-sm font-semibold text-gray-800">Projects</p>
              <p class="text-[11px] text-gray-400 mt-0.5">Pending Tasks</p>
            </div>
          </a>
          <a href="#" class="flex flex-col items-center gap-3 py-6 bg-white hover:bg-gray-50 transition-colors" @click.prevent="navigateTo('/app/customers')">
            <div class="w-12 h-12 rounded-xl bg-blue-50 flex items-center justify-center">
              <i class="fas fa-users text-blue-600 text-xl"></i>
            </div>
            <div class="text-center">
              <p class="text-sm font-semibold text-gray-800">Customers</p>
              <p class="text-[11px] text-gray-400 mt-0.5">Latest cases</p>
            </div>
          </a>
        </div>
        <div class="px-4 py-3 border-t border-gray-100 text-center">
          <a href="#" class="text-sm font-medium text-gray-500 hover:text-blue-600 transition-colors" @click.prevent="navigateTo('/dashboard')">
            View All <i class="fas fa-chevron-right text-[9px] ml-0.5"></i>
          </a>
        </div>
      </div>
    </Transition>

    <!-- Theme Dropdown -->
    <Transition name="dropdown">
      <div
        v-if="themeDropdownOpen"
        class="absolute bottom-[110px] left-[88px] w-[160px] bg-white border border-gray-200 rounded-xl shadow-xl shadow-black/10 z-[60] overflow-hidden py-1.5"
        @click.stop
      >
        <button
          class="dd-item w-full"
          :class="{ 'text-violet-600 font-semibold bg-violet-50': currentTheme === 'light' }"
          @click="handleSetTheme('light')"
        >
          <i class="fas fa-sun text-amber-400 w-5 text-center text-[13px]"></i>
          <span>Açık</span>
        </button>
        <button
          class="dd-item w-full"
          :class="{ 'text-violet-600 font-semibold bg-violet-50': currentTheme === 'dark' }"
          @click="handleSetTheme('dark')"
        >
          <i class="fas fa-moon text-indigo-400 w-5 text-center text-[13px]"></i>
          <span>Koyu</span>
        </button>
        <button
          class="dd-item w-full"
          :class="{ 'text-violet-600 font-semibold bg-violet-50': currentTheme === 'system' }"
          @click="handleSetTheme('system')"
        >
          <i class="fas fa-desktop text-gray-400 w-5 text-center text-[13px]"></i>
          <span>Sistem</span>
        </button>
      </div>
    </Transition>
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
import TenantSwitcher from './TenantSwitcher.vue'

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

// Close on outside click
function handleOutsideClick(e) {
  // Don't close if clicking inside a dropdown or a rail button
  const clickedInsideDropdown = e.target.closest('[class*="absolute bottom"]') ||
                                 e.target.closest('[class*="absolute bottom-"]')
  const clickedRailButton = e.target.closest('.rail-icon') ||
                             e.target.closest('.rail-avatar-btn')

  if (!clickedInsideDropdown && !clickedRailButton) {
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