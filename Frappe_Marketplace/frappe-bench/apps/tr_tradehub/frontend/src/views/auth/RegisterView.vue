<template>
  <AuthLayout
    :error-message="auth.error"
    :success-message="auth.successMessage"
  >
    <template #subtitle>Yeni hesap oluşturun</template>

    <!-- Kayıt Formu -->
    <form v-if="!registrationComplete" @submit.prevent="handleRegister" class="space-y-5">

      <!-- Ad Soyad -->
      <div>
        <label for="fullName" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">
          Ad Soyad
        </label>
        <input
          id="fullName"
          v-model="fullName"
          type="text"
          required
          autocomplete="name"
          placeholder="Adınız Soyadınız"
          :disabled="auth.isLoading"
          class="bg-gray-50 border border-gray-300 text-gray-900 rounded-lg
                 focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5
                 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400
                 dark:text-white disabled:opacity-50"
        />
      </div>

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
          autocomplete="email"
          placeholder="ornek@sirket.com"
          :disabled="auth.isLoading"
          class="bg-gray-50 border border-gray-300 text-gray-900 rounded-lg
                 focus:ring-blue-500 focus:border-blue-500 block w-full p-2.5
                 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400
                 dark:text-white disabled:opacity-50"
        />
      </div>

      <!-- Kayıt Ol Butonu -->
      <button
        type="submit"
        :disabled="auth.isLoading || !fullName || !email"
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
        {{ auth.isLoading ? 'Kayıt yapılıyor...' : 'Kayıt Ol' }}
      </button>
    </form>

    <!-- Kayıt Tamamlandı -->
    <div v-else class="text-center space-y-4">
      <p class="text-gray-700 dark:text-gray-300">
        Kayıt işleminiz tamamlandı. E-postanıza gönderilen bağlantıyla şifrenizi oluşturabilirsiniz.
      </p>
      <router-link
        :to="{ name: 'Login' }"
        class="inline-block w-full text-white bg-blue-700 hover:bg-blue-800
               focus:ring-4 focus:outline-none focus:ring-blue-300
               font-medium rounded-lg text-sm px-5 py-2.5 text-center
               dark:bg-blue-600 dark:hover:bg-blue-700 dark:focus:ring-blue-800"
      >
        Giriş Sayfasına Dön
      </router-link>
    </div>

    <template #footer>
      <p class="text-sm text-gray-600 dark:text-gray-400">
        Zaten hesabınız var mı?
        <router-link
          :to="{ name: 'Login' }"
          class="text-blue-700 hover:underline dark:text-blue-500 font-medium"
        >
          Giriş Yap
        </router-link>
      </p>
    </template>
  </AuthLayout>
</template>

<script setup>
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import AuthLayout from '@/layouts/AuthLayout.vue'

const auth = useAuthStore()

const fullName = ref('')
const email = ref('')
const registrationComplete = ref(false)

async function handleRegister() {
  try {
    await auth.register(email.value, fullName.value)
    registrationComplete.value = true
  } catch {
    // Hata auth store tarafından yönetiliyor
  }
}
</script>
