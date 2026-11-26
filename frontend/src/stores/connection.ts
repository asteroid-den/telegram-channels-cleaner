import { defineStore } from 'pinia'
import { ref } from 'vue'

import { heard } from '@/api/client'

import { onComputer } from './network'

/** No event (pings come every 3 s) for this long: ask the server directly whether it is there. */
const QUIET_MS = 7000
const CHECK_EVERY_MS = 3000
const CHECK_TIMEOUT_MS = 2500
const BACK_SHOWN_MS = 2500

/**
 * Whether the server answers. On a phone it is the computer, which may sleep, leave the network or stop the app;
 * the phone itself may sleep and come back with a dead stream. Decisions live on the server, so nothing is lost:
 * the UI only has to say so and hold the buttons until it is back.
 */
export const useConnectionStore = defineStore('connection', () => {
  const offline = ref(false)
  /** "Back online" for a moment after being offline. */
  const back = ref(false)
  let backTimer: ReturnType<typeof setTimeout> | undefined
  let checking = false
  let reconnect: () => void = () => undefined

  async function reachable(): Promise<boolean> {
    // A phone asks about itself: it may have been disconnected on the computer in the meantime
    const url = onComputer ? '/api/health' : '/api/pairing'
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(CHECK_TIMEOUT_MS) })
      if (!onComputer && response.status === 401) {
        location.replace('/pair')
        return true
      }
      return response.ok
    } catch {
      return false
    }
  }

  async function check() {
    if (checking) return
    checking = true
    const quiet = Date.now() - heard.at > QUIET_MS
    try {
      const ok = await reachable()
      if (!ok) {
        offline.value = true
        back.value = false
        return
      }
      const wasOffline = offline.value
      heard.at = Date.now()
      if (wasOffline) {
        offline.value = false
        back.value = true
        clearTimeout(backTimer)
        backTimer = setTimeout(() => (back.value = false), BACK_SHOWN_MS)
      }
      // The server is there but the stream went quiet: it died on the way (a sleep, a network change)
      if (quiet || wasOffline) reconnect()
    } finally {
      checking = false
    }
  }

  function start(onReconnect: () => void) {
    reconnect = onReconnect
    setInterval(() => {
      if (offline.value || Date.now() - heard.at > QUIET_MS) void check()
    }, CHECK_EVERY_MS)
    // Unlocked phone, a tab come back to: ask now instead of waiting for the silence to add up
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') void check()
    })
  }

  return { offline, back, start, check }
})
