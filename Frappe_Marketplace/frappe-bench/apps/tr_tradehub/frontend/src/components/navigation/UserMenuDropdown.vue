<template>
  <Transition name="dropdown">
    <div
      v-if="open"
      class="absolute bottom-2 left-[78px] w-[260px] bg-white border border-gray-200 rounded-xl shadow-xl shadow-black/10 z-[60]"
      @click.stop
    >
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
      <div class="py-1.5">
        <a href="#" class="dd-item" @click.prevent="emit('navigate', '/settings/profile')">Profilim</a>
        <a href="#" class="dd-item" @click.prevent="emit('navigate', '/projects')">
          <span class="flex-1">Projelerim</span>
          <span class="text-[10px] font-bold bg-red-100 text-red-500 px-1.5 py-0.5 rounded-full leading-none">3</span>
        </a>
        <div class="relative group/sub">
          <a href="#" class="dd-item" @click.prevent="emit('navigate', '/subscription')">
            <span class="flex-1">Aboneliğim</span>
            <i class="fas fa-chevron-right text-[9px] text-gray-300"></i>
          </a>
          <div class="sub-menu">
            <a href="#" class="dd-item" @click.prevent="emit('navigate', '/subscription/referrals')"><i class="fas fa-user-plus text-[11px] w-5 text-center text-gray-400"></i>Referanslar</a>
            <a href="#" class="dd-item" @click.prevent="emit('navigate', '/subscription/billing')"><i class="fas fa-file-invoice text-[11px] w-5 text-center text-gray-400"></i>Faturalar</a>
            <a href="#" class="dd-item" @click.prevent="emit('navigate', '/subscription/payments')"><i class="fas fa-credit-card text-[11px] w-5 text-center text-gray-400"></i>Ödemeler</a>
            <a href="#" class="dd-item" @click.prevent="emit('navigate', '/subscription/statements')">
              <i class="fas fa-receipt text-[11px] w-5 text-center text-gray-400"></i>Ekstreler
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
        <a href="#" class="dd-item" @click.prevent="emit('navigate', '/statements')">Hesap Özetlerim</a>
      </div>
      <div class="border-t border-gray-100 py-1.5">
        <div class="dd-item justify-between cursor-default">
          <span>Dil</span>
          <span class="text-xs text-gray-400 flex items-center gap-1">Türkçe 🇹🇷</span>
        </div>
        <a href="#" class="dd-item" @click.prevent="emit('navigate', '/settings')">Hesap Ayarları</a>
      </div>
      <div class="border-t border-gray-100 py-1.5">
        <a href="#" class="dd-item text-red-500" @click.prevent="emit('logout')">Oturumu Kapat</a>
      </div>
    </div>
  </Transition>
</template>

<script setup>
import { useTenantStore } from '@/stores/tenant'
import { useAuthStore } from '@/stores/auth'

defineProps({ open: { type: Boolean, default: false } })
const emit = defineEmits(['navigate', 'logout'])

const tenant = useTenantStore()
const auth = useAuthStore()
</script>
