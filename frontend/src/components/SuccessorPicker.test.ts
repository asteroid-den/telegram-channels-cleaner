import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import type { Channel, ChatAdmin } from '@/api/types'
import { i18n } from '@/i18n'

import SuccessorPicker from './SuccessorPicker.vue'

const channel = {
  id: 1,
  title: 'My chat',
  kind: 'channel',
  role: 'owner',
  members_count: 10,
} as unknown as Channel
const admins = [
  { id: 7, first_name: 'Ann', last_name: null, username: null, can_promote: true },
] as unknown as ChatAdmin[]

function picker() {
  return mount(SuccessorPicker, {
    props: { channel, admins: undefined },
    global: { plugins: [i18n] },
  })
}

beforeEach(() => setActivePinia(createPinia()))

describe('SuccessorPicker', () => {
  it('keeps what was picked while the admins loaded', async () => {
    const wrapper = picker()
    const dialog = wrapper.find('[role="dialog"]')
    // Loading: "leave" first, then "delete"
    await dialog.trigger('keydown', { key: 'ArrowDown' })
    await wrapper.setProps({ admins })
    await dialog.trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('delete')).toHaveLength(1)
    expect(wrapper.emitted('transfer')).toBeUndefined()
  })

  it('picks the usual heir once the admins come, if nothing was picked', async () => {
    const wrapper = picker()
    await wrapper.setProps({ admins })
    await wrapper.find('[role="dialog"]').trigger('keydown', { key: 'Enter' })
    expect(wrapper.emitted('transfer')?.[0]).toEqual([admins[0]])
  })

  it('does not call a list that failed to load "nobody to hand it to"', () => {
    const wrapper = mount(SuccessorPicker, {
      props: { channel, admins: null },
      global: { plugins: [i18n] },
    })
    expect(wrapper.text()).not.toContain(i18n.global.t('owner.introNoAdmins'))
  })
})
