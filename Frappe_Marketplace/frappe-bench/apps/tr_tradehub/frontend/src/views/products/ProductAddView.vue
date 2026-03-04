<template>
  <div>
    <!-- Header Row -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-6">
      <div class="flex items-center gap-3">
        <button @click="$router.push('/dashboard')" class="w-8 h-8 rounded-lg bg-gray-100 flex items-center justify-center text-gray-500 hover:bg-gray-200 transition-colors flex-shrink-0">
          <i class="fas fa-arrow-left text-xs"></i>
        </button>
        <div class="min-w-0">
          <h1 class="text-[15px] font-bold text-gray-900">Yeni Ürün Ekle</h1>
          <p class="text-xs text-gray-400">Ürün bilgilerini doldurun ve yayınlayın</p>
        </div>
      </div>
      <div class="flex items-center gap-2 flex-shrink-0 flex-wrap">
        <button class="hdr-btn-outlined" @click="$router.push('/dashboard')">İptal</button>
        <button class="hdr-btn-outlined" @click="saveDraft"><i class="fas fa-floppy-disk mr-1.5 text-xs"></i>Taslak</button>
        <button class="hdr-btn-primary" @click="submitForm"><i class="fas fa-check mr-1.5 text-xs"></i>Yayınla</button>
      </div>
    </div>

    <!-- Form Grid -->
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4 lg:gap-5">
      <!-- Left: Main content (2 cols) -->
      <div class="xl:col-span-2 space-y-5">
        <!-- Basic Info -->
        <div class="card">
          <h3 class="text-sm font-bold text-gray-900 mb-4"><i class="fas fa-cube text-violet-500 mr-2"></i>Temel Bilgiler</h3>
          <div class="space-y-4">
            <div>
              <label class="form-label">Ürün Adı <span class="text-red-500">*</span></label>
              <input v-model="form.name" type="text" class="form-input" placeholder="Örn: Endüstriyel Solvent Grade A - 20L">
            </div>
            <div>
              <label class="form-label">Kısa Açıklama <span class="text-red-500">*</span></label>
              <textarea v-model="form.shortDesc" class="form-input" rows="2" placeholder="Ürünün kısa açıklaması"></textarea>
            </div>
            <div>
              <label class="form-label">Detaylı Açıklama</label>
              <textarea v-model="form.description" class="form-input" rows="5" placeholder="Detaylı ürün açıklaması..."></textarea>
            </div>
          </div>
        </div>

        <!-- Images -->
        <div class="card">
          <h3 class="text-sm font-bold text-gray-900 mb-4"><i class="fas fa-images text-blue-500 mr-2"></i>Ürün Görselleri</h3>
          <div
            class="border-2 border-dashed border-gray-200 rounded-xl p-8 text-center hover:border-violet-400 transition-colors cursor-pointer"
            @click="$refs.fileInput.click()"
            @dragover.prevent
            @drop.prevent="handleDrop"
          >
            <input ref="fileInput" type="file" class="hidden" multiple accept="image/*" @change="handleFiles">
            <div class="w-12 h-12 mx-auto mb-3 rounded-xl bg-gray-50 flex items-center justify-center">
              <i class="fas fa-cloud-arrow-up text-xl text-gray-300"></i>
            </div>
            <p class="text-sm font-medium text-gray-600 mb-1">Görselleri sürükleyin veya tıklayın</p>
            <p class="text-xs text-gray-400">PNG, JPG, WEBP · Maks 10MB</p>
          </div>
          <!-- Preview -->
          <div v-if="form.images.length" class="flex gap-3 mt-4 flex-wrap">
            <div v-for="(img, i) in form.images" :key="i" class="relative w-20 h-20 rounded-lg overflow-hidden border border-gray-200">
              <img :src="img.preview" class="w-full h-full object-cover">
              <button @click="form.images.splice(i, 1)" class="absolute top-1 right-1 w-5 h-5 bg-red-500 text-white rounded-full flex items-center justify-center text-[10px]">
                <i class="fas fa-xmark"></i>
              </button>
            </div>
          </div>
        </div>

        <!-- Pricing & Stock -->
        <div class="card">
          <h3 class="text-sm font-bold text-gray-900 mb-4"><i class="fas fa-tag text-emerald-500 mr-2"></i>Fiyatlandırma & Stok</h3>
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <label class="form-label">Birim Fiyat (₺) <span class="text-red-500">*</span></label>
              <input v-model="form.price" type="number" class="form-input" placeholder="0.00">
            </div>
            <div>
              <label class="form-label">İndirimli Fiyat (₺)</label>
              <input v-model="form.discountPrice" type="number" class="form-input" placeholder="0.00">
            </div>
            <div>
              <label class="form-label">SKU <span class="text-red-500">*</span></label>
              <input v-model="form.sku" type="text" class="form-input" placeholder="CHM-0042">
            </div>
            <div>
              <label class="form-label">Barkod</label>
              <input v-model="form.barcode" type="text" class="form-input" placeholder="8690000000000">
            </div>
            <div>
              <label class="form-label">Stok <span class="text-red-500">*</span></label>
              <input v-model="form.stock" type="number" class="form-input" placeholder="0">
            </div>
            <div>
              <label class="form-label">Min. Sipariş Adedi</label>
              <input v-model="form.minOrder" type="number" class="form-input" value="1">
            </div>
          </div>

          <!-- Price Tiers -->
          <div class="mt-5 pt-4 border-t border-gray-100">
            <div class="flex items-center justify-between mb-3">
              <h4 class="text-xs font-bold text-gray-500 uppercase tracking-wide">Toplu Fiyat Kademeleri</h4>
              <button @click="addTier" class="text-[11px] font-medium text-violet-600 hover:text-violet-700">
                <i class="fas fa-plus mr-1"></i>Kademe Ekle
              </button>
            </div>
            <div class="space-y-2">
              <div v-for="(tier, i) in form.priceTiers" :key="i" class="tier-row">
                <input v-model="tier.min" type="number" placeholder="Min" class="form-input-sm w-24">
                <span class="text-xs text-gray-400">-</span>
                <input v-model="tier.max" type="number" placeholder="Max" class="form-input-sm w-24">
                <input v-model="tier.price" type="number" placeholder="Fiyat ₺" class="form-input-sm w-28">
                <input v-model="tier.discount" type="number" placeholder="%" class="form-input-sm w-20">
                <button @click="form.priceTiers.splice(i, 1)" class="text-gray-400 hover:text-red-500">
                  <i class="fas fa-xmark text-xs"></i>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Shipping -->
        <div class="card">
          <h3 class="text-sm font-bold text-gray-900 mb-4"><i class="fas fa-truck-fast text-orange-500 mr-2"></i>Kargo & Teslimat</h3>
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <label class="form-label">Kargo Ağırlığı (kg)</label>
              <input v-model="form.weight" type="number" class="form-input" placeholder="0.00">
            </div>
            <div>
              <label class="form-label">Teslimat Süresi (Gün)</label>
              <input v-model="form.deliveryDays" type="number" class="form-input" value="3">
            </div>
            <div>
              <label class="form-label">Kargo Tipi</label>
              <select v-model="form.shippingType" class="form-input">
                <option>Ücretsiz Kargo</option>
                <option>Sabit Ücret</option>
                <option>Ağırlık Bazlı</option>
              </select>
            </div>
            <div>
              <label class="form-label">Incoterm</label>
              <select v-model="form.incoterm" class="form-input">
                <option>EXW</option><option>FOB</option><option>CIF</option><option selected>DDP</option><option>DAP</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Sidebar -->
      <div class="space-y-5">
        <!-- Status -->
        <div class="card">
          <h3 class="text-sm font-bold text-gray-900 mb-4"><i class="fas fa-circle-check text-emerald-500 mr-2"></i>Yayın Durumu</h3>
          <div class="space-y-3">
            <div>
              <label class="form-label">Durum</label>
              <select v-model="form.status" class="form-input">
                <option>Taslak</option><option selected>Aktif</option><option>Pasif</option>
              </select>
            </div>
            <div>
              <label class="form-label">Görünürlük</label>
              <select v-model="form.visibility" class="form-input">
                <option>Herkese Açık</option><option>Sadece B2B</option><option>Premium</option>
              </select>
            </div>
          </div>
        </div>

        <!-- Category -->
        <div class="card">
          <h3 class="text-sm font-bold text-gray-900 mb-4"><i class="fas fa-folder-tree text-amber-500 mr-2"></i>Kategori & Marka</h3>
          <div class="space-y-3">
            <div>
              <label class="form-label">Kategori <span class="text-red-500">*</span></label>
              <select v-model="form.category" class="form-input">
                <option value="">Seçin</option>
                <option>Kimyasallar</option><option>Solventler</option><option>Reçineler</option><option>Yapıştırıcılar</option><option>Endüstriyel</option>
              </select>
            </div>
            <div>
              <label class="form-label">Marka</label>
              <select v-model="form.brand" class="form-input">
                <option>Anadolu Kimya</option>
              </select>
            </div>
            <div>
              <label class="form-label">Etiketler</label>
              <input v-model="form.tags" type="text" class="form-input" placeholder="endüstriyel, solvent, 20L">
            </div>
          </div>
        </div>

        <!-- Certifications -->
        <div class="card">
          <h3 class="text-sm font-bold text-gray-900 mb-4"><i class="fas fa-shield-check text-teal-500 mr-2"></i>Sertifikalar</h3>
          <div class="space-y-2">
            <label v-for="cert in certOptions" :key="cert" class="flex items-center gap-2">
              <input type="checkbox" class="form-checkbox rounded text-violet-600" :value="cert" v-model="form.certifications">
              <span class="text-xs text-gray-700">{{ cert }}</span>
            </label>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useToast } from '@/composables/useToast'

const router = useRouter()
const toast = useToast()

const certOptions = ['ISO 9001', 'CE Belgesi', 'REACH Uyumlu', 'TSE Belgesi']

const form = reactive({
  name: '',
  shortDesc: '',
  description: '',
  price: null,
  discountPrice: null,
  sku: '',
  barcode: '',
  stock: null,
  minOrder: 1,
  weight: null,
  deliveryDays: 3,
  shippingType: 'Ücretsiz Kargo',
  incoterm: 'DDP',
  status: 'Aktif',
  visibility: 'Herkese Açık',
  category: '',
  brand: 'Anadolu Kimya',
  tags: '',
  certifications: [],
  images: [],
  priceTiers: [
    { min: 10, max: 49, price: null, discount: 5 },
    { min: 50, max: 99, price: null, discount: 10 },
  ],
})

function addTier() {
  form.priceTiers.push({ min: null, max: null, price: null, discount: null })
}

function handleFiles(e) {
  const files = e.target.files
  for (const file of files) {
    form.images.push({ file, preview: URL.createObjectURL(file) })
  }
}

function handleDrop(e) {
  const files = e.dataTransfer.files
  for (const file of files) {
    if (file.type.startsWith('image/')) {
      form.images.push({ file, preview: URL.createObjectURL(file) })
    }
  }
}

function saveDraft() {
  toast.info('Taslak kaydedildi')
}

function submitForm() {
  if (!form.name || !form.price || !form.sku || !form.stock) {
    toast.error('Zorunlu alanları doldurun')
    return
  }
  toast.success('Ürün başarıyla yayınlandı!')
  setTimeout(() => router.push('/dashboard'), 1200)
}
</script>
