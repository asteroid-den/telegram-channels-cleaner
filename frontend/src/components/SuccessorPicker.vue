<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import type { Channel, ChatAdmin } from '@/api/types'
import { useKindI18n } from '@/composables/useKindI18n'

import ChannelAvatar from './ChannelAvatar.vue'

/** Telegram deletes chats only up to about this many members. */
const DELETE_LIMIT = 1000

const props = defineProps<{
  channel: Channel
  /** `undefined` while loading, `null` when Telegram didn't give the list. */
  admins: ChatAdmin[] | null | undefined
}>()
const emit = defineEmits<{
  transfer: [admin: ChatAdmin]
  leave: []
  delete: []
  cancel: []
  /** Nobody to hand it to: back of the deck, to come back once there is an admin. */
  later: []
}>()
const { t, tk } = useKindI18n(() => props.channel.kind)

type Choice = { kind: 'admin'; admin: ChatAdmin } | { kind: 'leave' } | { kind: 'delete' }

const tooLarge = computed(
  () => props.channel.members_count !== null && props.channel.members_count > DELETE_LIMIT,
)
const choices = computed<Choice[]>(() => [
  ...(props.admins ?? []).map((admin) => ({ kind: 'admin' as const, admin })),
  { kind: 'leave' },
  ...(tooLarge.value ? [] : [{ kind: 'delete' as const }]),
])
/** Telegram listed nobody (a list that failed to load is not "nobody"). */
const noAdmins = computed(() => !!props.admins && !props.admins.length)

const keyOf = (c: Choice) => (c.kind === 'admin' ? `admin:${c.admin.id}` : c.kind)
/**
 * What the user picked, by what it is: the admins may come in after "leave" was picked while they loaded, and an
 * index would then point at the first admin. Until a pick, the default.
 */
const chosen = ref<string | null>(null)
const selected = computed({
  get: () => {
    const at = choices.value.findIndex((c) => keyOf(c) === chosen.value)
    // The usual heir already has "add admins"; without admins the default is to leave
    return at >= 0 ? at : Math.max(0, props.admins?.findIndex((a) => a.can_promote) ?? -1)
  },
  set: (index: number) => {
    const c = choices.value[index]
    if (c) chosen.value = keyOf(c)
  },
})

const current = computed(() => choices.value[selected.value] ?? null)
const fullName = (a: ChatAdmin) => [a.first_name, a.last_name].filter(Boolean).join(' ')
const confirmLabel = computed(() => {
  const c = current.value
  if (!c) return ''
  if (c.kind === 'admin') return t('owner.queueTransfer')
  return c.kind === 'leave' ? t('owner.queueLeave') : t('owner.queueDelete')
})

function confirm() {
  const c = current.value
  if (!c) return
  if (c.kind === 'admin') emit('transfer', c.admin)
  else if (c.kind === 'leave') emit('leave')
  else emit('delete')
}

function onKey(e: KeyboardEvent) {
  const n = choices.value.length
  if (e.key === 'ArrowDown') selected.value = (selected.value + 1) % n
  else if (e.key === 'ArrowUp') selected.value = (selected.value - 1 + n) % n
  else if (e.key === 'Enter') confirm()
  else if (e.key === 'Escape') emit('cancel')
  else return
  e.preventDefault()
}

const dialog = ref<HTMLElement | null>(null)
onMounted(() => dialog.value?.focus())

const indexOf = (c: Choice) => choices.value.indexOf(c)
const adminChoices = computed(() => choices.value.filter((c) => c.kind === 'admin'))
const leaveChoice = computed(() => choices.value.find((c) => c.kind === 'leave')!)
const deleteChoice = computed(() => choices.value.find((c) => c.kind === 'delete') ?? null)
</script>

<template>
  <!-- data-hotkeys-off: while open, the deck's own keys stay quiet -->
  <div
    data-hotkeys-off
    class="fixed inset-0 z-50 flex items-center justify-center bg-bg/70 p-4 backdrop-blur-[2px]"
    @pointerdown.self="emit('cancel')"
  >
    <div
      ref="dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="t('owner.title', { title: channel.title })"
      tabindex="-1"
      class="w-full max-w-[560px] overflow-hidden rounded-2xl border border-border-2 bg-surface shadow-card"
      @keydown="onKey"
    >
      <header class="px-5 pt-5 pb-4">
        <h2 class="font-display text-lg font-semibold">
          {{ t('owner.title', { title: channel.title }) }}
        </h2>
        <p class="mt-1 text-[13px] text-muted">
          {{ noAdmins ? tk('owner.introNoAdmins') : t('owner.intro') }}
        </p>
      </header>

      <div role="radiogroup" class="border-t border-border">
        <template v-if="!noAdmins">
          <h3 class="section">
            {{ tk('owner.admins') }}<template v-if="admins"> · {{ admins.length }}</template>
          </h3>
          <template v-if="admins === undefined">
            <div v-for="i in 2" :key="i" class="row"><div class="skeleton h-9 w-full" /></div>
          </template>
          <button
            v-for="c in adminChoices"
            :key="c.kind === 'admin' ? c.admin.id : ''"
            role="radio"
            :aria-checked="indexOf(c) === selected"
            class="row"
            :class="indexOf(c) === selected ? 'chosen' : ''"
            @click="selected = indexOf(c)"
            @dblclick="confirm"
          >
            <span class="dot" />
            <template v-if="c.kind === 'admin'">
              <ChannelAvatar :id="c.admin.id" :title="fullName(c.admin)" :src="null" :size="32" />
              <span class="min-w-0 text-left">
                <span class="block truncate font-medium">{{ fullName(c.admin) }}</span>
                <span class="block truncate text-[12.5px] text-muted">
                  <template v-if="c.admin.username">@{{ c.admin.username }}</template>
                  <template v-if="c.admin.username && c.admin.can_promote"> · </template>
                  <template v-if="c.admin.can_promote">{{ t('owner.canPromote') }}</template>
                </span>
              </span>
            </template>
          </button>
        </template>
        <p v-if="admins === null" class="px-5 py-3 text-[13px] text-warn">
          {{ t('owner.loadFailed') }}
        </p>

        <h3 class="section">{{ t('owner.noTransfer') }}</h3>
        <button
          role="radio"
          :aria-checked="indexOf(leaveChoice) === selected"
          class="row"
          :class="indexOf(leaveChoice) === selected ? 'chosen' : ''"
          @click="selected = indexOf(leaveChoice)"
          @dblclick="confirm"
        >
          <span class="dot" />
          <span class="text-left">
            <span class="block font-medium text-warn">{{ tk('owner.leave') }}</span>
            <span class="block text-[12.5px] text-muted">{{ t('owner.leaveHint') }}</span>
          </span>
        </button>
        <button
          v-if="deleteChoice"
          role="radio"
          :aria-checked="indexOf(deleteChoice) === selected"
          class="row"
          :class="indexOf(deleteChoice) === selected ? 'chosen' : ''"
          @click="selected = indexOf(deleteChoice)"
          @dblclick="confirm"
        >
          <span class="dot" />
          <span class="text-left">
            <span class="block font-medium text-danger">{{ tk('owner.delete') }}</span>
            <span class="block text-[12.5px] text-muted">
              {{
                channel.members_count === null
                  ? tk('owner.deleteHintUnknown')
                  : tk('owner.deleteHint', { n: channel.members_count })
              }}
            </span>
          </span>
        </button>
        <div v-else class="row cursor-default opacity-55">
          <span class="dot" />
          <span class="text-left">
            <span class="block font-medium">{{ tk('owner.delete') }}</span>
            <span class="block text-[12.5px] text-muted">{{ tk('owner.deleteTooLarge') }}</span>
          </span>
        </div>
      </div>

      <footer class="flex justify-end gap-2 border-t border-border px-5 py-3.5">
        <button v-if="noAdmins || admins === null" class="btn" @click="emit('later')">
          {{ t('actions.skip') }}
        </button>
        <button v-else class="btn" @click="emit('cancel')">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="!current" @click="confirm">
          {{ confirmLabel }}
        </button>
      </footer>
    </div>
  </div>
</template>

<style scoped>
/* focused only to take the keys: the rows show where the choice is */
[role='dialog']:focus-visible {
  outline: none;
}
.section {
  padding: 0.75rem 1.25rem 0.375rem;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--faint);
}
.row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 1.25rem;
  border-top: 1px solid var(--border);
  font-size: 14px;
  cursor: pointer;
  box-shadow: inset 3px 0 0 transparent;
}
.row:hover {
  background: var(--surface-2);
}
.row.chosen {
  background: var(--surface-2);
  box-shadow: inset 3px 0 0 var(--accent);
}
.dot {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  border-radius: 9999px;
  border: 1.5px solid var(--border-2);
}
.chosen .dot {
  border: 4px solid var(--accent);
}
.btn {
  border-radius: 10px;
  border: 1px solid var(--border-2);
  padding: 0.5rem 0.9rem;
  font-size: 13px;
  font-weight: 600;
}
.btn:hover {
  background: var(--surface-2);
}
.btn.primary {
  border-color: transparent;
  background: var(--text);
  color: var(--bg);
}
.btn.primary:disabled {
  opacity: 0.4;
}
</style>
