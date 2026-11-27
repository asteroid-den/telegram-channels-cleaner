import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { api } from '@/api/client'
import { i18n, storeLocale, type Locale } from '@/i18n'

export type Theme = 'dark' | 'light'
const THEME_KEY = 'cc.theme'

function readTheme(): Theme {
  try {
    return localStorage.getItem(THEME_KEY) === 'light' ? 'light' : 'dark'
  } catch {
    return 'dark'
  }
}

export interface Toast {
  id: number
  kind: 'error' | 'info'
  text: string
}

export const useUiStore = defineStore('ui', () => {
  const theme = ref<Theme>(readTheme())
  const locale = ref<Locale>(i18n.global.locale.value as Locale)
  const mock = ref(false)
  const toasts = ref<Toast[]>([])
  /** The deck's search (Ctrl+K, or the header's button on a phone) */
  const searching = ref(false)
  let toastSeq = 0

  function applyTheme() {
    document.documentElement.dataset.theme = theme.value
    // The header's colour (--surface), for the phone browser's own bar around it
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute('content', theme.value === 'dark' ? '#121318' : '#ffffff')
  }
  applyTheme()
  storeLocale(locale.value)

  watch(theme, (value) => {
    applyTheme()
    try {
      localStorage.setItem(THEME_KEY, value)
    } catch {
      /* ignore */
    }
  })

  watch(locale, (value) => {
    i18n.global.locale.value = value
    storeLocale(value)
  })

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark'
  }

  function toggleLocale() {
    locale.value = locale.value === 'en' ? 'ru' : 'en'
  }

  function toast(text: string, kind: Toast['kind'] = 'error') {
    const id = ++toastSeq
    toasts.value.push({ id, kind, text })
    setTimeout(() => dismiss(id), 5000)
  }

  function dismiss(id: number) {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }

  async function loadHealth() {
    try {
      const health = await api.get<{ mock: boolean }>('/api/health')
      mock.value = health.mock
    } catch {
      /* backend not up yet */
    }
  }

  return {
    searching,
    theme,
    locale,
    mock,
    toasts,
    toggleTheme,
    toggleLocale,
    toast,
    dismiss,
    loadHealth,
  }
})
