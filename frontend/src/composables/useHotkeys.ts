import { onBeforeUnmount, onMounted } from 'vue'

export type HotkeyMap = Record<string, (e: KeyboardEvent) => void>

type KeyInfo = Pick<KeyboardEvent, 'key' | 'code' | 'ctrlKey' | 'metaKey'>

/**
 * Name of a key press as used in a HotkeyMap: `m`, `ArrowLeft`, `mod+z`…
 *
 * Letters are taken from the physical key (`KeyM` → `m`), so shortcuts keep working on
 * non-latin layouts where `e.key` would be `ь` or `ф`.
 */
export function hotkeyName(e: KeyInfo): string {
  let key: string
  if (/^Key[A-Z]$/.test(e.code)) key = e.code.slice(3).toLowerCase()
  else key = e.key.length === 1 ? e.key.toLowerCase() : e.key
  return e.ctrlKey || e.metaKey ? `mod+${key}` : key
}

/**
 * Global hotkeys. Keys are `KeyboardEvent.key` values (letters by physical position),
 * optionally prefixed with `mod+` (Ctrl on Linux/Windows, Cmd on macOS).
 * Ignored while typing in form fields. A held key acts once, unless its name is in `repeat`: a decision a second
 * from a key left down is a deck sorted by accident.
 */
export function useHotkeys(map: HotkeyMap, opts: { repeat?: string[] } = {}) {
  function onKey(e: KeyboardEvent) {
    // A dialog already acted on it (Enter in the picker): by now the dialog may be gone, Vue having updated
    // the page between the two listeners, so `data-hotkeys-off` below can't be relied on for this
    if (e.defaultPrevented) return
    const target = e.target
    if (
      target instanceof Element &&
      target.closest('input, textarea, select, [contenteditable="true"]')
    )
      return
    if (e.altKey) return
    // Enter/Space on a focused control must press that control, not trigger a shortcut.
    if (
      (e.key === 'Enter' || e.key === ' ') &&
      target instanceof Element &&
      target.closest('button, a, summary, [role="button"], [role="menuitem"], [role="tab"]')
    )
      return
    // An open menu or dialog owns the keyboard.
    if (document.querySelector('[data-hotkeys-off]')) return
    const name = hotkeyName(e)
    const handler = map[name]
    if (!handler) return
    e.preventDefault()
    if (e.repeat && !opts.repeat?.includes(name)) return
    handler(e)
  }
  onMounted(() => window.addEventListener('keydown', onKey))
  onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
}
