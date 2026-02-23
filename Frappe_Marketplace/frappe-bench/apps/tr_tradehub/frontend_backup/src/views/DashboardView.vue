<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-900">
    <!-- Navbar -->
    <nav class="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
      <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between h-16 items-center">
          <!-- Brand -->
          <div class="text-xl font-bold text-gray-900 dark:text-white">
            TR TradeHub
          </div>

          <!-- User Info + Logout -->
          <div class="flex items-center gap-4">
            <span class="text-sm text-gray-700 dark:text-gray-300">
              {{ auth.fullName || auth.user }}
            </span>
            <button
              @click="auth.logout()"
              class="text-sm font-medium text-red-600 hover:text-red-800 dark:text-red-500 dark:hover:text-red-400"
            >
              Çıkış Yap
            </button>
          </div>
        </div>
      </div>
    </nav>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      <h1 class="text-2xl font-bold text-gray-900 dark:text-white mb-6">
        Dashboard
      </h1>

      <!-- Welcome Card -->
      <div class="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
        <p class="text-gray-700 dark:text-gray-300">
          Hoş geldiniz, {{ auth.fullName || auth.user }}! Oturum başarıyla açıldı.
        </p>
      </div>
    </main>
  </div>
</template>

<script setup>
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>
