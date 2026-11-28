<script setup lang="ts">
import { onClickOutside, onKeyStroke } from '@vueuse/core'
import { computed, ref, useTemplateRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

import { useAuthStore } from '@/stores/auth'
import { useDeckStore } from '@/stores/deck'
import { onComputer } from '@/stores/network'
import { useUiStore } from '@/stores/ui'

import type { Account } from '@/api/types'

import AppIcon, { type IconName } from './AppIcon.vue'
import ChannelAvatar from './ChannelAvatar.vue'
import PhoneAccessDialog from './PhoneAccessDialog.vue'

const { t } = useI18n()
const auth = useAuthStore()
const deck = useDeckStore()
const ui = useUiStore()
const router = useRouter()

const open = ref(false)
const phoneOpen = ref(false)
const root = useTemplateRef<HTMLElement>('root')
onClickOutside(root, () => (open.value = false))
// Its own keys while open (the deck's are off meanwhile): Esc closes it, the arrows walk its items
onKeyStroke('Escape', () => open.value && (open.value = false))
function onMenuKey(e: KeyboardEvent) {
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  const items = [...(root.value?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])]
  if (!items.length) return
  e.preventDefault()
  const at = items.indexOf(document.activeElement as HTMLElement)
  const step = e.key === 'ArrowDown' ? 1 : -1
  items[(at + step + items.length) % items.length]!.focus()
}

const user = computed(() => auth.state.user)
const name = computed(() => user.value?.first_name ?? '')
const avatar = computed(() => auth.accounts.find((account) => account.active)?.avatar_url ?? null)

// Fresh counts each time the menu opens: decisions were made since
watch(open, (isOpen) => {
  if (isOpen) void auth.loadAccounts().catch(() => undefined)
})

function fullName(account: Account) {
  return [account.first_name, account.last_name].filter(Boolean).join(' ')
}

function switchTo(account: Account) {
  if (!account.active) void run(() => auth.switchTo(account))
  else open.value = false
}

async function run(action: () => Promise<unknown> | unknown) {
  open.value = false
  try {
    await action()
  } catch (err) {
    ui.toast(t('login.errors.generic', { msg: err instanceof Error ? err.message : String(err) }))
  }
}

const items: { icon: IconName; label: string; danger?: boolean; action: () => unknown }[] = [
  // Phones are paired from the computer the app runs on, not from another phone
  ...(onComputer
    ? [{ icon: 'smartphone' as const, label: 'phone.menu', action: () => (phoneOpen.value = true) }]
    : []),
  { icon: 'refresh', label: 'account.resync', action: () => deck.resync() },
  { icon: 'chart', label: 'account.results', action: () => router.push('/results') },
  { icon: 'undo', label: 'account.resetKeeps', action: () => deck.reset('keep') },
  {
    icon: 'trash',
    label: 'account.resetAll',
    action: () => confirm(t('account.resetConfirm')) && deck.reset(null),
  },
]

const logouts = computed<{ label: string; danger?: boolean; action: () => unknown }[]>(() => [
  {
    label: t('account.logoutNamed', { name: name.value }),
    action: () => confirm(t('account.logoutConfirm', { name: name.value })) && logout(false),
  },
  {
    label: t('account.logoutWipe'),
    danger: true,
    action: () => confirm(t('account.logoutWipeConfirm', { name: name.value })) && logout(true),
  },
])

async function logout(wipe: boolean) {
  await auth.logout(wipe)
  deck.clear()
}
</script>

<template>
  <!-- On the root: the arrows also start from the button that opened the menu -->
  <div ref="root" class="relative" @keydown="open && onMenuKey($event)">
    <button
      class="flex h-[30px] shrink-0 items-center gap-2 rounded-lg border border-border-2 pr-2 pl-1 text-[12.5px] text-muted hover:text-text max-md:px-1"
      :aria-label="t('account.menu')"
      :aria-expanded="open"
      @click="open = !open"
    >
      <ChannelAvatar v-if="user" :id="user.id" :title="name" :src="avatar" :size="22" />
      <span class="max-w-32 truncate max-md:hidden">{{ name }}</span>
      <AppIcon name="chevron" :size="12" class="opacity-70 max-md:hidden" />
    </button>
    <Transition
      enter-from-class="opacity-0 -translate-y-1"
      leave-to-class="opacity-0 -translate-y-1"
      enter-active-class="transition duration-150"
      leave-active-class="transition duration-100"
    >
      <div
        v-if="open"
        class="absolute right-0 z-40 mt-2 w-80 max-w-[calc(100vw-24px)] overflow-hidden rounded-xl border border-border-2 bg-surface p-1 shadow-card"
        role="menu"
        data-hotkeys-off
      >
        <div
          class="px-3 pt-2 pb-1 text-[11px] font-semibold tracking-[0.07em] text-faint uppercase"
        >
          {{ t('account.accounts') }}
        </div>
        <button
          v-for="account in auth.accounts"
          :key="account.id"
          role="menuitemradio"
          :aria-checked="account.active"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-surface-2"
          @click="switchTo(account)"
        >
          <ChannelAvatar
            :id="account.id"
            :title="fullName(account)"
            :src="account.avatar_url"
            :size="30"
          />
          <span class="min-w-0 flex-1">
            <span class="block truncate text-sm">{{ fullName(account) }}</span>
            <span class="block truncate text-xs text-faint">
              <template v-if="account.username">@{{ account.username }} · </template>
              {{ t('account.chats', account.chats) }}
            </span>
          </span>
          <AppIcon v-if="account.active" name="check" :size="16" class="shrink-0 text-accent" />
          <span
            v-else-if="account.pending"
            class="shrink-0 rounded-full bg-danger/10 px-2 py-0.5 text-[11px] font-semibold text-danger"
            :title="t('account.pendingThere', account.pending)"
            >{{ account.pending }}</span
          >
        </button>
        <button
          role="menuitem"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm text-accent hover:bg-surface-2"
          @click="run(() => auth.addAccount())"
        >
          <AppIcon name="plus" :size="16" class="shrink-0" />
          {{ t('account.add') }}
        </button>
        <div class="mx-2 my-1 h-px bg-border" />
        <button
          v-for="item in items"
          :key="item.label"
          role="menuitem"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2"
          :class="item.danger ? 'text-danger' : ''"
          @click="run(item.action)"
        >
          <AppIcon :name="item.icon" :size="16" class="shrink-0 opacity-80" />
          {{ t(item.label) }}
        </button>
        <!-- On a phone the header has no room for these two -->
        <div class="md:hidden">
          <div class="mx-2 my-1 h-px bg-border" />
          <button
            role="menuitem"
            class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2"
            @click="ui.toggleLocale()"
          >
            <AppIcon name="globe" :size="16" class="shrink-0 opacity-80" />
            {{ t('header.language') }}
            <span class="ml-auto font-mono text-xs text-faint uppercase">{{ ui.locale }}</span>
          </button>
          <button
            role="menuitem"
            class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2"
            @click="ui.toggleTheme()"
          >
            <AppIcon
              :name="ui.theme === 'dark' ? 'sun' : 'moon'"
              :size="16"
              class="shrink-0 opacity-80"
            />
            {{ t('header.theme') }}
          </button>
        </div>
        <div class="mx-2 my-1 h-px bg-border" />
        <button
          v-for="item in logouts"
          :key="item.label"
          role="menuitem"
          class="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2"
          :class="item.danger ? 'text-danger' : ''"
          @click="run(item.action)"
        >
          <AppIcon name="logout" :size="16" class="shrink-0 opacity-80" />
          {{ item.label }}
        </button>
      </div>
    </Transition>
    <!-- The backdrop fades in and out; the dialog animates its own panel -->
    <Transition
      enter-from-class="opacity-0"
      enter-active-class="transition-opacity duration-150 ease-out"
      leave-to-class="opacity-0"
      leave-active-class="transition-opacity duration-150 ease-in"
    >
      <PhoneAccessDialog v-if="phoneOpen" @close="phoneOpen = false" />
    </Transition>
  </div>
</template>
