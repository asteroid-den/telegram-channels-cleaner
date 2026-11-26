<script setup lang="ts">
import { useEventListener } from '@vueuse/core'
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import type { ArchiveFilter, ChatKind, RoleFilter, SortMode } from '@/api/types'
import { useNarrow } from '@/composables/useNarrow'
import { useDeckStore } from '@/stores/deck'

import AppIcon from './AppIcon.vue'

const { t } = useI18n()
const deck = useDeckStore()
const narrow = useNarrow()

const open = ref(false)
// Esc closes the menu wherever the focus is
useEventListener(window, 'keydown', (e) => {
  if (open.value && e.key === 'Escape') open.value = false
})

const KINDS: ChatKind[] = ['channel', 'supergroup']
const ROLES: RoleFilter[] = ['member', 'managed']
const ARCHIVES: ArchiveFilter[] = ['all', 'active', 'archived']
const SORTS: SortMode[] = ['dead', 'unread']

const roleTotal = (r: RoleFilter) =>
  deck.counts.role_totals[r].channel + deck.counts.role_totals[r].supergroup

const isDefault = computed(
  () => deck.prefs.archive === 'all' && deck.prefs.sort === 'dead' && !deck.prefs.reverse,
)

function reset() {
  void deck.setPrefs({ sort: 'dead', reverse: false, archive: 'all' })
}
</script>

<template>
  <div class="relative shrink-0">
    <!-- While the menu is open a click anywhere else only closes it: this catches the pointer
         before the deck (swipe, side zones) can read it as a decision -->
    <div
      v-if="open"
      class="fixed inset-0 z-30 max-md:bg-black/55"
      aria-hidden="true"
      @click="open = false"
    />

    <button
      class="relative z-40 flex h-[30px] items-center gap-2 rounded-lg border border-border-2 px-3 text-[12.5px] transition-colors hover:bg-surface-2"
      :class="open ? 'bg-surface-3' : ''"
      :aria-label="t('settings.title')"
      :aria-expanded="open"
      aria-haspopup="true"
      @click="open = !open"
    >
      <span class="font-semibold">{{ t(`settings.kind.${deck.kind}`) }}</span>
      <span class="text-faint">·</span>
      <template v-if="deck.role === 'managed'">
        <span>{{ t('settings.role.managed') }}</span>
        <span class="text-faint">·</span>
      </template>
      <span>{{ t(`settings.archiveShort.${deck.prefs.archive}`) }}</span>
      <span class="text-faint max-md:hidden">·</span>
      <span class="max-md:hidden">{{ t(`settings.sort.${deck.prefs.sort}`) }}</span>
      <AppIcon
        v-if="deck.prefs.reverse"
        name="arrows"
        :size="12"
        class="text-muted max-md:hidden"
      />
      <AppIcon
        name="chevron"
        :size="12"
        class="text-faint transition-transform"
        :class="open ? 'rotate-180' : ''"
      />
      <span
        v-if="deck.counts.pending_other > 0"
        class="absolute top-[3px] right-[3px] h-[7px] w-[7px] rounded-full bg-accent"
        :title="t('settings.pendingElsewhere')"
      />
    </button>

    <Transition
      :enter-from-class="narrow ? 'translate-y-full' : 'opacity-0 -translate-y-1'"
      :leave-to-class="narrow ? 'translate-y-full' : 'opacity-0 -translate-y-1'"
      :enter-active-class="narrow ? 'transition duration-250 ease-out' : 'transition duration-150'"
      :leave-active-class="narrow ? 'transition duration-200 ease-in' : 'transition duration-100'"
    >
      <div
        v-if="open"
        class="sheet-narrow absolute left-0 z-40 mt-2 w-[330px] rounded-xl border border-border-2 bg-surface p-3.5 shadow-card"
        role="group"
        :aria-label="t('settings.title')"
        data-hotkeys-off
      >
        <section class="mb-3.5">
          <h2 class="label mb-2">{{ t('settings.kindTitle') }}</h2>
          <div
            class="grid grid-cols-2 overflow-hidden rounded-lg border border-border-2 text-[12.5px]"
          >
            <button
              v-for="k in KINDS"
              :key="k"
              class="relative border-r border-border-2 px-2 py-2 transition-colors last:border-r-0"
              :class="deck.kind === k ? 'bg-text text-bg' : 'text-muted hover:text-text'"
              :aria-pressed="deck.kind === k"
              @click="deck.setKind(k)"
            >
              {{ t(`settings.kind.${k}`) }}
              <span
                v-if="deck.kind !== k && deck.counts.pending_other > 0"
                class="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle"
              />
              <span
                class="mt-0.5 block text-[11px]"
                :class="deck.kind === k ? 'opacity-60' : 'text-faint'"
              >
                {{ deck.counts.kind_totals[k] }}
                <template v-if="deck.kind !== k && deck.counts.pending_other > 0">
                  · {{ t('settings.waiting', { n: deck.counts.pending_other }) }}
                </template>
              </span>
            </button>
          </div>
        </section>

        <section class="mb-3.5">
          <h2 class="label mb-2">{{ t('settings.roleTitle') }}</h2>
          <div
            class="grid grid-cols-2 overflow-hidden rounded-lg border border-border-2 text-[12.5px]"
          >
            <button
              v-for="r in ROLES"
              :key="r"
              class="border-r border-border-2 px-2 py-2 transition-colors last:border-r-0"
              :class="deck.role === r ? 'bg-text text-bg' : 'text-muted hover:text-text'"
              :title="t(`settings.roleLong.${r}`)"
              :aria-pressed="deck.role === r"
              @click="deck.setRole(r)"
            >
              {{ t(`settings.role.${r}`) }}
              <span
                class="mt-0.5 block text-[11px]"
                :class="deck.role === r ? 'opacity-60' : 'text-faint'"
                :title="`${t('settings.kind.channel')} | ${t('settings.kind.supergroup')}`"
              >
                {{ roleTotal(r) }}
                <span class="italic">
                  ({{ deck.counts.role_totals[r].channel }} |
                  {{ deck.counts.role_totals[r].supergroup }})
                </span>
              </span>
            </button>
          </div>
        </section>

        <section class="mb-3.5">
          <h2 class="label mb-2">{{ t('settings.archiveTitle') }}</h2>
          <div
            class="grid grid-cols-3 overflow-hidden rounded-lg border border-border-2 text-[12.5px]"
          >
            <button
              v-for="a in ARCHIVES"
              :key="a"
              class="border-r border-border-2 px-2 py-1.5 transition-colors last:border-r-0"
              :class="deck.prefs.archive === a ? 'bg-text text-bg' : 'text-muted hover:text-text'"
              :title="t(`settings.archiveLong.${a}`)"
              :aria-pressed="deck.prefs.archive === a"
              @click="deck.setArchive(a)"
            >
              {{ t(`settings.archiveShort.${a}`) }}
              <span
                class="ml-0.5 text-[11px] italic"
                :class="deck.prefs.archive === a ? 'opacity-60' : 'text-faint'"
              >
                {{ deck.counts.archive_totals[a] }}
              </span>
            </button>
          </div>
        </section>

        <section>
          <h2 class="label mb-2">{{ t('settings.sortTitle') }}</h2>
          <div
            class="grid grid-cols-2 overflow-hidden rounded-lg border border-border-2 text-[12.5px]"
          >
            <button
              v-for="s in SORTS"
              :key="s"
              class="border-r border-border-2 px-2 py-1.5 transition-colors last:border-r-0"
              :class="deck.prefs.sort === s ? 'bg-text text-bg' : 'text-muted hover:text-text'"
              :title="t(s === 'dead' ? 'header.sortDead' : 'header.sortUnread')"
              :aria-pressed="deck.prefs.sort === s"
              @click="deck.setSort(s)"
            >
              {{ t(`settings.sort.${s}`) }}
            </button>
          </div>
          <label
            class="mt-2.5 flex cursor-pointer items-center justify-between text-[13px] text-muted"
          >
            {{ t('header.reverse') }}
            <button
              role="switch"
              class="relative h-[17px] w-[30px] rounded-full border border-border-2 transition-colors"
              :class="deck.prefs.reverse ? 'bg-accent' : 'bg-surface-3'"
              :aria-checked="deck.prefs.reverse"
              :aria-label="t('header.reverse')"
              @click="deck.toggleReverse()"
            >
              <span
                class="absolute top-[2px] left-[2px] h-[11px] w-[11px] rounded-full bg-text transition-transform"
                :class="deck.prefs.reverse ? 'translate-x-[13px]' : 'opacity-60'"
              />
            </button>
          </label>
        </section>

        <button
          class="-mx-3.5 mt-3.5 -mb-3.5 w-[calc(100%+28px)] border-t border-border px-3.5 py-2.5 text-left text-[12.5px] text-accent hover:underline disabled:cursor-default disabled:text-faint disabled:no-underline"
          :disabled="isDefault"
          @click="reset"
        >
          {{ t('settings.reset') }}
        </button>
      </div>
    </Transition>
  </div>
</template>
