import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'

import { hotkeyName, useHotkeys } from './useHotkeys'

const press = (key: string, code: string, mod = false) => ({
  key,
  code,
  ctrlKey: mod,
  metaKey: false,
})

describe('hotkeyName', () => {
  it('uses the physical key for letters on a Russian layout', () => {
    expect(hotkeyName(press('ь', 'KeyM'))).toBe('m')
    expect(hotkeyName(press('ф', 'KeyA'))).toBe('a')
    expect(hotkeyName(press('я', 'KeyZ', true))).toBe('mod+z')
  })

  it('keeps named keys as they are', () => {
    expect(hotkeyName(press('ArrowLeft', 'ArrowLeft'))).toBe('ArrowLeft')
    expect(hotkeyName(press('Enter', 'Enter', true))).toBe('mod+Enter')
    expect(hotkeyName(press('Escape', 'Escape'))).toBe('Escape')
  })

  it('lowercases latin letters', () => {
    expect(hotkeyName(press('M', 'KeyM'))).toBe('m')
  })
})

describe('useHotkeys', () => {
  it('acts once for a held key, unless the key may repeat', () => {
    const decide = vi.fn()
    const step = vi.fn()
    const wrapper = mount(
      defineComponent({
        setup() {
          useHotkeys({ ArrowRight: decide, 'mod+ArrowLeft': step }, { repeat: ['mod+ArrowLeft'] })
          return () => null
        },
      }),
    )
    const hold = (init: KeyboardEventInit) => {
      window.dispatchEvent(new KeyboardEvent('keydown', init))
      window.dispatchEvent(new KeyboardEvent('keydown', { ...init, repeat: true }))
    }
    hold({ key: 'ArrowRight', code: 'ArrowRight' })
    hold({ key: 'ArrowLeft', code: 'ArrowLeft', ctrlKey: true })
    expect(decide).toHaveBeenCalledTimes(1)
    expect(step).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
