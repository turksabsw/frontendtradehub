<template>
  <div class="absolute top-full left-0 right-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-xl shadow-black/8 max-h-[400px] overflow-y-auto z-50">
    <template v-if="filteredResults.length === 0">
      <div class="p-6 text-center">
        <i class="fas fa-search text-gray-300 text-2xl mb-2"></i>
        <p class="text-sm text-gray-400">Sonuç bulunamadı</p>
      </div>
    </template>
    <template v-else>
      <template v-for="(items, category) in groupedResults" :key="category">
        <div class="search-result-category">{{ category }}</div>
        <div
          v-for="item in items"
          :key="item.label"
          class="search-result-item"
          @mousedown.prevent="handleClick(item)"
        >
          <div class="result-icon bg-violet-50 text-violet-500">
            <i :class="item.icon"></i>
          </div>
          <div class="result-text">
            <div class="title" v-html="highlight(item.label)"></div>
            <div class="subtitle">
              {{ item.doctype || item.report || '' }} &middot; {{ item.sectionTitle }}
            </div>
          </div>
        </div>
      </template>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { searchData } from '@/data/navigation'

const props = defineProps({
  query: { type: String, default: '' },
})

const emit = defineEmits(['select'])
const router = useRouter()

const filteredResults = computed(() => {
  const q = props.query.toLowerCase()
  if (q.length < 2) return []
  return searchData.filter(item =>
    item.label.toLowerCase().includes(q) ||
    (item.doctype || '').toLowerCase().includes(q) ||
    (item.report || '').toLowerCase().includes(q) ||
    (item.sectionTitle || '').toLowerCase().includes(q) ||
    (item.groupTitle || '').toLowerCase().includes(q)
  ).slice(0, 30)
})

const groupedResults = computed(() => {
  const groups = {}
  filteredResults.value.forEach(item => {
    const cat = item.sectionTitle || 'Diğer'
    if (!groups[cat]) groups[cat] = []
    groups[cat].push(item)
  })
  return groups
})

function highlight(text) {
  const q = props.query.toLowerCase()
  const idx = text.toLowerCase().indexOf(q)
  if (idx === -1) return text
  return (
    text.substring(0, idx) +
    '<mark class="bg-yellow-100 text-yellow-800 rounded px-0.5">' +
    text.substring(idx, idx + q.length) +
    '</mark>' +
    text.substring(idx + q.length)
  )
}

function handleClick(item) {
  emit('select', item)
  const slug = (item.doctype || item.report || '').toLowerCase().replace(/\s+/g, '-')
  if (item.route) {
    router.push(item.route)
  } else if (item.doctype) {
    router.push(`/app/${slug}`)
  } else if (item.report) {
    router.push(`/app/report/${slug}`)
  }
}
</script>
