<template>
  <div class="min-h-screen flex items-center justify-center bg-[#0f0f12] px-4">
    <div class="w-full max-w-md">
      <!-- Logo -->
      <div class="text-center mb-8">
        <div class="w-14 h-14 bg-gradient-to-br from-violet-500 to-indigo-600 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-lg shadow-violet-500/20">
          <i class="fas fa-bolt text-white text-2xl"></i>
        </div>
        <h1 class="text-2xl font-extrabold text-white tracking-tight">TradeHub</h1>
        <p class="text-sm text-gray-500 mt-1">B2B Marketplace Satıcı Paneli</p>
      </div>

      <!-- Login Card -->
      <div class="bg-[#1c1c26] border border-[#26263a] rounded-2xl p-8">
        <h2 class="text-lg font-bold text-white mb-1">Hoş Geldiniz</h2>
        <p class="text-sm text-gray-500 mb-6">Hesabınıza giriş yapın</p>

        <div v-if="error" class="mb-4 p-3 bg-red-500/10 border border-red-500/20 rounded-lg">
          <p class="text-xs text-red-400">{{ error }}</p>
        </div>

        <div class="space-y-4">
          <div>
            <label class="block text-xs font-semibold text-gray-400 mb-1.5">E-posta</label>
            <input
              v-model="email"
              type="email"
              placeholder="admin@tradehub.com"
              class="w-full px-4 py-3 bg-[#0f0f12] border border-[#26263a] text-white text-sm rounded-xl outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 transition-all placeholder:text-gray-600"
              @keydown.enter="handleLogin"
            >
          </div>
          <div>
            <label class="block text-xs font-semibold text-gray-400 mb-1.5">Şifre</label>
            <input
              v-model="password"
              type="password"
              placeholder="••••••••"
              class="w-full px-4 py-3 bg-[#0f0f12] border border-[#26263a] text-white text-sm rounded-xl outline-none focus:border-violet-500 focus:ring-2 focus:ring-violet-500/20 transition-all placeholder:text-gray-600"
              @keydown.enter="handleLogin"
            >
          </div>
          <div class="flex items-center justify-between">
            <label class="flex items-center gap-2">
              <input type="checkbox" v-model="remember" class="form-checkbox rounded text-violet-600 bg-transparent border-[#26263a]">
              <span class="text-xs text-gray-500">Beni hatırla</span>
            </label>
            <a href="#" class="text-xs text-violet-500 hover:text-violet-400 font-medium">Şifremi unuttum</a>
          </div>
          <button
            @click="handleLogin"
            :disabled="loading"
            class="w-full py-3 bg-gradient-to-r from-violet-600 to-indigo-600 text-white text-sm font-semibold rounded-xl hover:from-violet-500 hover:to-indigo-500 transition-all shadow-lg shadow-violet-500/20 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <i v-if="loading" class="fas fa-spinner fa-spin mr-2"></i>
            {{ loading ? 'Giriş yapılıyor...' : 'Giriş Yap' }}
          </button>
        </div>
      </div>

      <!-- Footer -->
      <p class="text-center text-[11px] text-gray-600 mt-6">
        2026 TradeHub B2B Marketplace · Tüm hakları saklıdır
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const email = ref('')
const password = ref('')
const remember = ref(false)
const loading = ref(false)
const error = ref('')

async function handleLogin() {
  if (!email.value || !password.value) {
    error.value = 'E-posta ve şifre gereklidir'
    return
  }
  loading.value = true
  error.value = ''
  try {
    await auth.login(email.value, password.value)
    // Navigate to the redirect target or dashboard
    const redirectTo = route.query.redirect || '/dashboard'
    router.push(redirectTo)
  } catch (err) {
    error.value = err.message || 'Giriş başarısız. Bilgilerinizi kontrol edin.'
  } finally {
    loading.value = false
  }
}
</script>
