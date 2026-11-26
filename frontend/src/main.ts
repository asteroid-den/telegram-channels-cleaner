import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { i18n } from './i18n'
import { router } from './router'
import { useAuthStore } from './stores/auth'
import { paired } from './stores/network'
import { useUiStore } from './stores/ui'
import './style.css'

async function boot() {
  const pinia = createPinia()
  const app = createApp(App).use(pinia).use(i18n)
  useUiStore(pinia) // applies theme + locale before first paint
  // A phone that isn't paired gets nothing but the pairing screen: the API answers it 401 until then
  const stranger = !(await paired())
  // Resolve the auth state first so the very first route is already the right one.
  if (!stranger) await useAuthStore(pinia).waitReady()
  app.use(router)
  if (stranger && !location.pathname.startsWith('/pair')) await router.replace({ name: 'pair' })
  await router.isReady()
  app.mount('#app')
}

void boot()
