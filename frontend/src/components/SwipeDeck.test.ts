import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Channel } from '@/api/types'
import { i18n } from '@/i18n'

import SwipeDeck from './SwipeDeck.vue'

const channel = (id: number) =>
  ({ id, title: `chat ${id}`, decision: null, full_loaded: true, pulse: [] }) as unknown as Channel

beforeEach(() => setActivePinia(createPinia()))

describe('SwipeDeck', () => {
  it('sends the decision of a card in flight when the deck goes away', () => {
    const decided: unknown[][] = []
    const wrapper = mount(SwipeDeck, {
      props: {
        items: [channel(1), channel(2)],
        returning: null,
        onDecide: (...args: unknown[]) => decided.push(args),
      },
      global: { plugins: [i18n], stubs: { ChannelCard: true } },
    })
    ;(wrapper.vm as unknown as { fling: (d: string) => boolean }).fling('keep')
    // Enter for the review before the card has flown away
    wrapper.unmount()
    expect(decided).toEqual([['keep', 1]])
  })
})
