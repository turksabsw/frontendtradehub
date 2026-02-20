<template>
  <AuthLayout
    :error-message="auth.error"
    :success-message="auth.successMessage"
    :warning-message="expiredWarning"
  >
    <template #subtitle>Hesabınıza giriş yapın</template>

    <form @submit.prevent="handleLogin" class="space-y-5">

      <!-- E-posta -->
      <div>
        <label for="email" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">
          E-posta
        </label>
        <input
          id="email"
          v-model="email"
          type="email"
          required
          autocomplete="username"
          placeholder="ornek@sirket.com"
          :disabled="auth.isLoading"
          class="bg-gray-50 border border-gray-300 text-gray-900 rounded-lg
                 focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5
                 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400
                 dark:text-white disabled:opacity-50"
        />
      </div>

      <!-- Şifre -->
      <div>
        <label for="password" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">
          Şifre
        </label>
        <input
          id="password"
          v-model="password"
          type="password"
          required
          autocomplete="current-password"
          placeholder="••••••••"
          :disabled="auth.isLoading"
          class="bg-gray-50 border border-gray-300 text-gray-900 rounded-lg
                 focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5
                 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400
                 dark:text-white disabled:opacity-50"
        />
      </div>

      <!-- Şifremi Unuttum linki -->
      <div class="flex justify-end">
        <router-link
          :to="{ name: 'ForgotPassword' }"
          class="text-sm text-blue-700 hover:underline dark:text-blue-500"
        >
          Şifremi unuttum
        </router-link>
      </div>

      <!-- Giriş Butonu -->
      <button
        type="submit"
        :disabled="auth.isLoading || !email || !password"
        class="w-full text-white bg-blue-700 hover:bg-blue-800
               focus:ring-4 focus:outline-none focus:ring-blue-300
               font-medium rounded-lg text-sm px-5 py-2.5 text-center
               dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-800
               disabled:opacity-50 disabled:cursor-not-allowed
               flex items-center justify-center gap-2"
      >
        <svg v-if="auth.isLoading" class="animate-spin h-5 w-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        {{ auth.isLoading ? 'Giriş yapılıyor...' : 'Giriş Yap' }}
      </button>
    </form>

    <template #footer>
      <p class="text-sm text-gray-600 dark:text-gray-400">
        Hesabınız yok mu?
        <router-link
          :to="{ name: 'Register' }"
          class="text-blue-700 hover:underline dark:text-blue-500 font-medium"
        >
          Kayıt Ol
        </router-link>
      </p>
    </template>
  </AuthLayout>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AuthLayout from '@/components/AuthLayout.vue'

const route = useRoute()
const auth = useAuthStore()

const email = ref('')
const password = ref('')

const expiredWarning = computed(() =>
  route.query.expired ? 'Oturumunuzun süresi doldu. Lütfen tekrar giriş yapın.' : null
)

async function handleLogin() {
  try {
    await auth.login(email.value, password.value)
  } catch {
    password.value = ''
  }
}
</script>
