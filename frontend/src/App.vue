<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import ConnectionBanner from '@/components/ConnectionBanner.vue'
import ToastStack from '@/components/ToastStack.vue'
import { useAuthStore } from '@/stores/auth'
import { useConnectionStore } from '@/stores/connection'
import { useDeckStore } from '@/stores/deck'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const deck = useDeckStore()
const ui = useUiStore()
const connection = useConnectionStore()
const router = useRouter()
const { t } = useI18n()
const route = useRoute()

onMounted(() => {
  void ui.loadHealth()
  // The pairing screen asks for nothing else: a phone there isn't let in yet
  if (route.name === 'pair') return
  auth.connect()
  connection.start(auth.reconnect)
})

// Keep the route in line with the auth state (login elsewhere, logout, revoked session…).
watch(
  () => [auth.ready, auth.authorized] as const,
  ([ready, authorized]) => {
    if (!ready || route.name === 'pair') return
    if (!authorized && route.name !== 'login') void router.replace({ name: 'login' })
    if (authorized && (route.name === 'login' || !route.name)) void router.replace({ name: 'deck' })
  },
  { immediate: true },
)

// Another account took over (switched, or after a logout): the deck on screen was the last one's
let shownUser: number | null = null
watch(
  () => auth.state.user?.id,
  (id) => {
    if (id === undefined) return
    if (shownUser !== null && id !== shownUser) {
      deck.clear()
      if (route.name === 'deck') void deck.load()
      else void router.replace({ name: 'deck' })
    }
    shownUser = id
  },
  // The user is often known before this component is: without it the first switch after a page load went unnoticed
  { immediate: true },
)
</script>

<template>
  <div class="flex min-h-full flex-col">
    <AppHeader v-if="!route.meta.bare" />
    <main class="relative flex flex-1 flex-col">
      <ConnectionBanner />
      <div
        v-if="auth.switchingTo"
        class="absolute inset-0 z-30 flex flex-col items-center justify-center gap-3 bg-bg/80 text-sm text-muted"
      >
        <div class="h-7 w-7 animate-spin rounded-full border-2 border-border border-t-accent" />
        {{ t('account.switching', { name: auth.switchingTo }) }}
      </div>
      <RouterView v-slot="{ Component }">
        <Transition
          mode="out-in"
          enter-from-class="opacity-0 translate-y-2"
          leave-to-class="opacity-0"
          enter-active-class="transition duration-200 ease-out"
          leave-active-class="transition duration-150"
        >
          <component :is="Component" />
        </Transition>
      </RouterView>
    </main>
    <ToastStack />
  </div>
</template>
