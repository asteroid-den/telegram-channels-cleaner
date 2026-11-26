import { createRouter, createWebHistory } from 'vue-router'

import { useAuthStore } from '@/stores/auth'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    // The phone's pairing screen: open to a browser the app doesn't know yet, without the header
    {
      path: '/pair/:token?',
      name: 'pair',
      component: () => import('@/views/PairView.vue'),
      meta: { bare: true },
    },
    { path: '/', name: 'deck', component: () => import('@/views/DeckView.vue') },
    { path: '/review', name: 'review', component: () => import('@/views/ReviewView.vue') },
    { path: '/apply', name: 'apply', component: () => import('@/views/ApplyView.vue') },
    { path: '/results', name: 'results', component: () => import('@/views/ResultsView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach((to) => {
  if (to.name === 'pair') return true
  const auth = useAuthStore()
  if (!auth.authorized && to.name !== 'login') return { name: 'login' }
  if (auth.authorized && to.name === 'login') return { name: 'deck' }
  return true
})
