<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useDeckStore } from '@/stores/deck'
import { useUiStore } from '@/stores/ui'

import AccountMenu from './AccountMenu.vue'
import AppIcon from './AppIcon.vue'
import AppLogo from './AppLogo.vue'
import DeckSettings from './DeckSettings.vue'
import SummaryPill from './SummaryPill.vue'

const { t } = useI18n()
const ui = useUiStore()
const auth = useAuthStore()
const deck = useDeckStore()
const route = useRoute()

const onDeck = computed(() => auth.authorized && route.name === 'deck' && deck.loaded)
</script>

<template>
  <header
    class="relative z-30 flex h-14 shrink-0 items-center gap-4 border-b border-border bg-surface px-5"
  >
    <RouterLink
      to="/"
      :aria-label="t('app.name')"
      class="flex shrink-0 items-center gap-2.5 font-display text-[15px] font-bold"
    >
      <AppLogo />
      <span>{{ t('app.name') }}</span>
    </RouterLink>
    <span v-if="ui.mock" class="tag bg-warn-soft text-warn">MOCK</span>

    <DeckSettings v-if="onDeck" />

    <div class="flex-1" />
    <SummaryPill v-if="onDeck" />

    <button
      class="rounded-lg border border-border-2 px-2.5 py-1.5 font-mono text-[11.5px] text-muted uppercase hover:text-text"
      :title="t('header.language')"
      :aria-label="`${t('header.language')}: ${ui.locale.toUpperCase()}`"
      @click="ui.toggleLocale()"
    >
      {{ ui.locale }}
    </button>
    <button
      class="flex h-[30px] w-[30px] items-center justify-center rounded-lg border border-border-2 text-muted hover:text-text"
      :title="t('header.theme')"
      :aria-label="t('header.theme')"
      @click="ui.toggleTheme()"
    >
      <AppIcon :name="ui.theme === 'dark' ? 'sun' : 'moon'" :size="15" />
    </button>
    <AccountMenu v-if="auth.authorized" />
  </header>
</template>
