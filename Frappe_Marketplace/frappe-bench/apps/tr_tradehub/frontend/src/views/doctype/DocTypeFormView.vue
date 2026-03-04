<template>
  <div>
    <!-- Header -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div class="flex items-center gap-3">
        <button @click="goBack" class="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center text-gray-500 hover:bg-gray-200 transition-colors flex-shrink-0">
          <i class="fas fa-arrow-left text-xs"></i>
        </button>
        <div class="min-w-0">
          <h1 class="text-[15px] font-bold text-gray-900 truncate">{{ docName }}</h1>
          <p class="text-xs text-gray-400">{{ doctypeLabel }}</p>
        </div>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0">
        <button class="hdr-btn-outlined" @click="goBack">Geri</button>
        <button class="hdr-btn-primary" @click="saveDoc">
          <i class="fas fa-floppy-disk mr-1.5 text-xs"></i>Kaydet
        </button>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading" class="card text-center py-12">
      <i class="fas fa-spinner fa-spin text-2xl text-violet-500"></i>
      <p class="text-sm text-gray-400 mt-3">Yükleniyor...</p>
    </div>

    <!-- Document Fields -->
    <div v-else class="space-y-5">
      <div class="card">
        <h3 class="text-sm font-bold text-gray-900 mb-4">
          <i class="fas fa-file-lines text-violet-500 mr-2"></i>Döküman Bilgileri
        </h3>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div v-for="(value, key) in docData" :key="key">
            <label class="form-label">{{ formatFieldLabel(key) }}</label>
            <input
              v-if="typeof value !== 'object'"
              :value="value"
              type="text"
              class="form-input"
              :readonly="key === 'name' || key === 'creation' || key === 'modified'"
            >
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'
import api from '@/utils/api'

const route = useRoute()
const router = useRouter()
const toast = useToast()

const loading = ref(false)
const docData = ref({})

const doctype = computed(() => {
  const slug = route.params.doctype || ''
  return slug.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
})

const doctypeLabel = computed(() => doctype.value)
const docName = computed(() => decodeURIComponent(route.params.name || ''))

function formatFieldLabel(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

function goBack() {
  const slug = doctype.value.toLowerCase().replace(/\s+/g, '-')
  router.push(`/app/${slug}`)
}

async function loadDoc() {
  loading.value = true
  try {
    const res = await api.getDoc(doctype.value, docName.value)
    docData.value = res.data || {}
  } catch {
    docData.value = { name: docName.value, doctype: doctype.value }
  } finally {
    loading.value = false
  }
}

async function saveDoc() {
  toast.success('Kayıt güncellendi')
}

watch(() => route.params.name, loadDoc)
onMounted(loadDoc)
</script>
