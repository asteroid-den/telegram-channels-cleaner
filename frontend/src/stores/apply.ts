import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, subscribe } from '@/api/client'
import type { ApplyItem, ApplyState } from '@/api/types'

const IDLE: ApplyState = {
  job_id: null,
  status: 'idle',
  total: 0,
  done: 0,
  failed: 0,
  current: null,
  flood_wait_until: null,
  items: [],
  held_transfers: 0,
  held_deletions: 0,
}

export const useApplyStore = defineStore('apply', () => {
  const state = ref<ApplyState>({ ...IDLE })
  const cancelling = ref(false)
  let stop: (() => void) | null = null

  const running = computed(() => state.value.status === 'running')
  const progress = computed(() =>
    state.value.total ? (state.value.done + state.value.failed) / state.value.total : 0,
  )

  function item(channelId: number): ApplyItem | undefined {
    return state.value.items.find((i) => i.channel_id === channelId)
  }

  function connect() {
    if (stop) return
    stop = subscribe('/api/apply/events', {
      snapshot: (s: ApplyState) => (state.value = s),
      started: (s: ApplyState) => (state.value = s),
      item_started: (e: { channel_id: number }) => {
        state.value.current = e.channel_id
        const it = item(e.channel_id)
        if (it) it.status = 'running'
      },
      item_done: (e: { channel_id: number; done: number; failed: number }) => {
        const it = item(e.channel_id)
        if (it) it.status = 'done'
        state.value.done = e.done
        state.value.failed = e.failed
      },
      item_failed: (e: { channel_id: number; error: string; done: number; failed: number }) => {
        const it = item(e.channel_id)
        if (it) {
          it.status = 'failed'
          it.error = e.error
        }
        state.value.done = e.done
        state.value.failed = e.failed
      },
      flood_wait: (e: { until: number }) => (state.value.flood_wait_until = e.until),
      flood_wait_over: () => (state.value.flood_wait_until = null),
      finished: (s: ApplyState) => {
        state.value = s
        cancelling.value = false
      },
    })
  }

  function disconnect() {
    stop?.()
    stop = null
  }

  async function start() {
    cancelling.value = false
    state.value = await api.post<ApplyState>('/api/apply')
  }

  async function cancel() {
    cancelling.value = true
    await api.post('/api/apply/cancel')
  }

  return { state, cancelling, running, progress, connect, disconnect, start, cancel }
})
