<template>
  <div>
    <!-- Page Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div>
        <h1 class="text-[15px] font-bold text-gray-900">{{ doctypeLabel }}</h1>
        <p class="text-xs text-gray-400">{{ totalCount }} kayıt bulundu</p>
      </div>
      <div class="flex items-center gap-2">
        <button class="hdr-btn-outlined" @click="refreshList">
          <i class="fas fa-refresh mr-1.5 text-xs"></i>Yenile
        </button>
        <button class="hdr-btn-primary" @click="showCreateModal = true">
          <i class="fas fa-plus mr-1.5 text-xs"></i>Yeni Ekle
        </button>
      </div>
    </div>

    <!-- Filters Bar -->
    <div class="card mb-5 !p-3">
      <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 flex-wrap">
        <div class="relative flex-1 min-w-0 sm:min-w-[200px]">
          <i class="fas fa-magnifying-glass absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-xs"></i>
          <input
            v-model="searchQuery"
            type="text"
            :placeholder="`${doctypeLabel} ara...`"
            class="w-full pl-9 pr-3 py-2 text-[13px] bg-gray-50 border border-gray-200 rounded-lg outline-none focus:ring-2 focus:ring-violet-500/20 focus:border-violet-400 transition-all"
          >
        </div>
        <select v-model="statusFilter" class="form-input-sm w-auto">
          <option value="">Tüm Durumlar</option>
          <option value="Active">Aktif</option>
          <option value="Draft">Taslak</option>
          <option value="Disabled">Pasif</option>
        </select>
        <select v-model="sortBy" class="form-input-sm w-auto">
          <option value="modified desc">Son Düzenlenen</option>
          <option value="creation desc">Son Oluşturulan</option>
          <option value="name asc">İsim (A-Z)</option>
        </select>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="card text-center py-12">
      <i class="fas fa-spinner fa-spin text-2xl text-violet-500"></i>
      <p class="text-sm text-gray-400 mt-3">Yükleniyor...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="items.length === 0" class="card text-center py-12">
      <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-gray-50 flex items-center justify-center">
        <i class="fas fa-inbox text-2xl text-gray-300"></i>
      </div>
      <h3 class="text-sm font-bold text-gray-700 mb-1">Henüz kayıt yok</h3>
      <p class="text-xs text-gray-400 mb-4">İlk {{ doctypeLabel }} kaydınızı oluşturun</p>
      <button class="hdr-btn-primary" @click="showCreateModal = true">
        <i class="fas fa-plus mr-1.5 text-xs"></i>Yeni Ekle
      </button>
    </div>

    <!-- List Table -->
    <div v-else class="card p-0 overflow-hidden">
      <div class="overflow-x-auto">
        <table class="w-full">
          <thead>
            <tr class="border-b border-gray-100">
              <th class="tbl-th w-8"><input type="checkbox" class="form-checkbox rounded text-violet-600"></th>
              <th class="tbl-th">İsim</th>
              <th class="tbl-th">Durum</th>
              <th class="tbl-th">Oluşturulma</th>
              <th class="tbl-th">Düzenleme</th>
              <th class="tbl-th w-12"></th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in items"
              :key="item.name"
              class="tbl-row border-b border-gray-50 cursor-pointer"
              @click="openDoc(item.name)"
            >
              <td class="tbl-td" @click.stop><input type="checkbox" class="form-checkbox rounded text-violet-600"></td>
              <td class="tbl-td font-semibold text-gray-900">{{ item.name }}</td>
              <td class="tbl-td">
                <span class="badge" :class="getStatusClass(item.docstatus)">
                  {{ getStatusLabel(item.docstatus) }}
                </span>
              </td>
              <td class="tbl-td text-gray-400">{{ formatDate(item.creation) }}</td>
              <td class="tbl-td text-gray-400">{{ formatDate(item.modified) }}</td>
              <td class="tbl-td">
                <button class="text-gray-400 hover:text-gray-600" @click.stop>
                  <i class="fas fa-ellipsis-vertical"></i>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="flex items-center justify-between px-5 py-3 border-t border-gray-100">
        <span class="text-xs text-gray-400">{{ items.length }} / {{ totalCount }} kayıt</span>
        <div class="flex items-center gap-1">
          <button
            class="hdr-btn text-xs"
            :disabled="currentPage === 1"
            @click="currentPage--; loadData()"
          >
            <i class="fas fa-chevron-left"></i>
          </button>
          <span class="text-xs text-gray-600 px-2">{{ currentPage }}</span>
          <button
            class="hdr-btn text-xs"
            :disabled="items.length < pageSize"
            @click="currentPage++; loadData()"
          >
            <i class="fas fa-chevron-right"></i>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '@/utils/api'

const route = useRoute()
const router = useRouter()

const items = ref([])
const totalCount = ref(0)
const loading = ref(false)
const searchQuery = ref('')
const statusFilter = ref('')
const sortBy = ref('modified desc')
const currentPage = ref(1)
const pageSize = 20
const showCreateModal = ref(false)

const doctype = computed(() => {
  // Convert slug back to DocType name: "rfq-quote" -> "RFQ Quote"
  const slug = route.params.doctype || ''
  return slug.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
})

const doctypeLabel = computed(() => doctype.value || 'Döküman')

async function loadData() {
  loading.value = true
  try {
    const filters = []
    if (searchQuery.value) {
      filters.push(['name', 'like', `%${searchQuery.value}%`])
    }
    if (statusFilter.value) {
      filters.push(['status', '=', statusFilter.value])
    }

    const res = await api.getList(doctype.value, {
      filters,
      order_by: sortBy.value,
      limit_start: (currentPage.value - 1) * pageSize,
      limit_page_length: pageSize,
    })
    items.value = res.data || []

    const countRes = await api.getCount(doctype.value, filters)
    totalCount.value = countRes.message || 0
  } catch (err) {
    // Offline / dev mode: show empty state
    items.value = []
    totalCount.value = 0
  } finally {
    loading.value = false
  }
}

function refreshList() {
  currentPage.value = 1
  loadData()
}

function openDoc(name) {
  const slug = doctype.value.toLowerCase().replace(/\s+/g, '-')
  router.push(`/app/${slug}/${encodeURIComponent(name)}`)
}

function getStatusClass(docstatus) {
  const map = { 0: 'bg-amber-50 text-amber-600', 1: 'bg-emerald-50 text-emerald-600', 2: 'bg-red-50 text-red-600' }
  return map[docstatus] || 'bg-gray-50 text-gray-600'
}

function getStatusLabel(docstatus) {
  const map = { 0: 'Taslak', 1: 'Onaylı', 2: 'İptal' }
  return map[docstatus] || 'Bilinmiyor'
}

function formatDate(dt) {
  if (!dt) return '-'
  return new Date(dt).toLocaleDateString('tr-TR')
}

// Watch for route changes (switching DocTypes)
watch(() => route.params.doctype, () => {
  currentPage.value = 1
  loadData()
})

// Debounced search
let searchTimeout
watch(searchQuery, () => {
  clearTimeout(searchTimeout)
  searchTimeout = setTimeout(() => {
    currentPage.value = 1
    loadData()
  }, 400)
})

watch([statusFilter, sortBy], () => {
  currentPage.value = 1
  loadData()
})

onMounted(loadData)
</script>
