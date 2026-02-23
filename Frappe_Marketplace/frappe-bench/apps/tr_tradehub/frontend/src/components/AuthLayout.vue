<script setup>
defineProps({
  successMessage: {
    type: String,
    default: null,
  },
  errorMessage: {
    type: String,
    default: null,
  },
  warningMessage: {
    type: String,
    default: null,
  },
})
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900 px-4 py-8">
    <div class="w-full max-w-md">
      <!-- Logo / Title -->
      <div class="text-center mb-6">
        <h1 class="text-3xl font-bold text-gray-900 dark:text-white">
          TR TradeHub
        </h1>
        <p class="mt-2 text-gray-600 dark:text-gray-400">
          <slot name="subtitle">Yönetim Paneli</slot>
        </p>
      </div>

      <!-- Card -->
      <div class="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 sm:p-8">
        <!-- Success Alert -->
        <div
          v-if="successMessage"
          role="alert"
          class="p-4 mb-4 text-sm text-green-800 rounded-lg bg-green-50 dark:bg-gray-700 dark:text-green-400"
        >
          {{ successMessage }}
        </div>

        <!-- Error Alert -->
        <div
          v-if="errorMessage"
          role="alert"
          class="p-4 mb-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-700 dark:text-red-400"
        >
          {{ errorMessage }}
        </div>

        <!-- Warning Alert -->
        <div
          v-if="warningMessage"
          role="alert"
          class="p-4 mb-4 text-sm text-yellow-800 rounded-lg bg-yellow-50 dark:bg-gray-700 dark:text-yellow-400"
        >
          {{ warningMessage }}
        </div>

        <!-- Form Content -->
        <slot></slot>
      </div>

      <!-- Footer (navigation links) -->
      <div class="mt-4 text-center text-sm text-gray-600 dark:text-gray-400">
        <slot name="footer"></slot>
      </div>
    </div>
  </div>
</template>
