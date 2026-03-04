<template>
  <div class="fixed bottom-6 right-6 z-[100] flex flex-col gap-2">
    <TransitionGroup name="toast">
      <div
        v-for="t in toasts"
        :key="t.id"
        class="toast"
        :class="`toast-${t.type}`"
      >
        <i :class="t.icon"></i>
        <span class="text-xs text-gray-700 flex-1">{{ t.message }}</span>
        <button @click="remove(t.id)" class="text-gray-400 hover:text-gray-600">
          <i class="fas fa-xmark text-xs"></i>
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>

<script setup>
import { useToast } from '@/composables/useToast'
const { toasts, remove } = useToast()
</script>