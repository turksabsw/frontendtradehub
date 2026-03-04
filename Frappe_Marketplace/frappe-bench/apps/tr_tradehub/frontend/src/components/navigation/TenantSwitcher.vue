<template>
  <div class="w-full flex-shrink-0 border-b sidebar-rail-border relative">
    <button
      class="w-full flex flex-col items-center justify-center h-[68px] gap-1 tenant-switcher-btn transition-all cursor-pointer"
      @click="tenant.toggleDropdown()"
    >
      <div
        class="w-9 h-9 rounded-xl flex items-center justify-center shadow-lg shadow-violet-500/20 bg-gradient-to-br"
        :class="tenant.activeTenant?.gradient || 'from-violet-500 to-indigo-600'"
      >
        <span class="text-white text-[11px] font-extrabold">{{ tenant.activeTenant?.initials }}</span>
      </div>
      <div class="flex items-center gap-0.5">
        <span class="text-[9px] font-semibold tenant-switcher-label truncate max-w-[58px]">{{ tenant.shortName }}</span>
        <i class="fas fa-chevron-down text-[7px] tenant-switcher-label"></i>
      </div>
    </button>
    <Transition name="dropdown">
      <div
        v-if="tenant.dropdownOpen"
        class="absolute top-full left-0 mt-1 ml-1 w-64 tenant-switcher-dropdown border rounded-xl shadow-2xl z-[100] overflow-hidden"
      >
        <div class="px-4 py-3 border-b tenant-switcher-dropdown-border">
          <p class="text-[10px] font-bold uppercase tracking-wider tenant-switcher-heading">Tenant Seçimi</p>
          <p class="text-[10px] tenant-switcher-subtext mt-0.5">Yetkili olduğunuz organizasyonlar</p>
        </div>
        <div class="py-1.5 max-h-60 overflow-y-auto panel-scroll">
          <button
            v-for="t in tenant.tenants"
            :key="t.id"
            class="tenant-item"
            :class="{ active: tenant.activeTenantId === t.id }"
            @click="handleSwitch(t.id, t.name)"
          >
            <div class="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 bg-gradient-to-br" :class="t.gradient">
              <span class="text-white text-[10px] font-bold">{{ t.initials }}</span>
            </div>
            <div class="flex-1 min-w-0 text-left">
              <p class="text-[12px] font-semibold tenant-switcher-item-name truncate">{{ t.name }}</p>
              <p class="text-[10px] tenant-switcher-subtext">{{ t.role }}</p>
            </div>
            <i v-show="tenant.activeTenantId === t.id" class="fas fa-check text-[10px] text-green-400"></i>
          </button>
        </div>
        <div class="px-4 py-2.5 border-t tenant-switcher-dropdown-border">
          <a href="#" class="flex items-center gap-2 text-[11px] text-[#6c5dd3] font-medium hover:text-white transition-colors">
            <i class="fas fa-plus text-[9px]"></i>Yeni Organizasyon Ekle
          </a>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { useTenantStore } from '@/stores/tenant'
import { useToast } from '@/composables/useToast'

const tenant = useTenantStore()
const toast = useToast()

function handleSwitch(tenantId, tenantName) {
  tenant.switchTenant(tenantId)
  toast.success(`${tenantName} organizasyonuna geçildi`)
}
</script>
