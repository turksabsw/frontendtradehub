import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useTenantStore = defineStore('tenant', () => {
  const tenants = ref([
    { id: 'anadolu', initials: 'AK', name: 'Anadolu Kimya Ltd.', role: 'Ana Hesap · Admin', gradient: 'from-violet-500 to-indigo-600' },
    { id: 'delta', initials: 'DK', name: 'Delta Kimya A.Ş.', role: 'Yönetici', gradient: 'from-blue-500 to-cyan-500' },
    { id: 'mega', initials: 'MY', name: 'Mega Yapı San.', role: 'Editör', gradient: 'from-amber-500 to-orange-500' },
    { id: 'atlas', initials: 'AM', name: 'Atlas Metal San.', role: 'Görüntüleyici', gradient: 'from-emerald-500 to-teal-500' },
  ])

  const activeTenantId = ref('anadolu')
  const dropdownOpen = ref(false)

  const activeTenant = computed(() =>
    tenants.value.find(t => t.id === activeTenantId.value)
  )

  const shortName = computed(() => {
    const name = activeTenant.value?.name || ''
    return name.length > 10 ? name.substring(0, 9) + '.' : name
  })

  function switchTenant(tenantId) {
    activeTenantId.value = tenantId
    dropdownOpen.value = false
  }

  function toggleDropdown() {
    dropdownOpen.value = !dropdownOpen.value
  }

  function closeDropdown() {
    dropdownOpen.value = false
  }

  return {
    tenants,
    activeTenantId,
    activeTenant,
    shortName,
    dropdownOpen,
    switchTenant,
    toggleDropdown,
    closeDropdown,
  }
})
