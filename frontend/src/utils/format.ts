export function compactNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: 'compact', maximumFractionDigits: 1 }).format(
    value,
  )
}

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['year', 365 * 24 * 3600],
  ['month', 30 * 24 * 3600],
  ['week', 7 * 24 * 3600],
  ['day', 24 * 3600],
  ['hour', 3600],
  ['minute', 60],
]

export function relativeTime(iso: string, locale: string, now = Date.now()): string {
  const seconds = (new Date(iso).getTime() - now) / 1000
  const rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto', style: 'short' })
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.trunc(seconds / size), unit)
  }
  return rtf.format(0, 'minute')
}

/** Age as a bare amount, e.g. "10 мес." / "10 mths" — for figures labelled elsewhere. */
export function ageShort(iso: string, locale: string, now = Date.now()): string {
  const seconds = Math.max(0, (now - new Date(iso).getTime()) / 1000)
  const unitFmt = (unit: string, n: number) =>
    new Intl.NumberFormat(locale, { style: 'unit', unit, unitDisplay: 'short' }).format(n)
  for (const [unit, size] of UNITS) {
    if (seconds >= size) return unitFmt(unit, Math.floor(seconds / size))
  }
  return unitFmt('minute', 1)
}

/** Short month names for the pulse axis: [26 weeks ago, 13 weeks ago, now]. */
export function pulseAxis(locale: string, now = new Date()): string[] {
  const fmt = new Intl.DateTimeFormat(locale, { month: 'short' })
  return [26, 13, 0].map((w) => fmt.format(new Date(now.getTime() - w * 7 * 86_400_000)))
}

export function fullDate(iso: string, locale: string): string {
  return new Date(iso).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' })
}

export function initials(title: string): string {
  const words = title.split(/\s+/).filter((w) => /[\p{L}\p{N}]/u.test(w[0] ?? ''))
  return (
    words
      .slice(0, 2)
      .map((w) => w[0])
      .join('')
      .toUpperCase() || '?'
  )
}

/**
 * Telegram Desktop's empty-avatar gradients (lib_ui colors.palette, historyPeerNUserpicBg → Bg2), in its own order:
 * red, green, yellow (unused), blue, purple, pink, sea, orange.
 */
const USERPIC: readonly (readonly [string, string])[] = [
  ['#ff845e', '#d45246'],
  ['#9ad164', '#46ba43'],
  ['#e5ca77', '#e5ca77'],
  ['#5caffa', '#408acf'],
  ['#b694f9', '#6c61df'],
  ['#ff8aac', '#d95574'],
  ['#5bcbe3', '#359ad4'],
  ['#febb5b', '#f68136'],
]
/** Colour index (red, orange, violet, green, cyan, blue, pink) → palette entry, as Telegram Desktop maps it. */
const TO_USERPIC = [0, 7, 4, 1, 6, 3, 5]
/** Bot API ids of channels and supergroups are -100 followed by the channel's own id. */
const CHANNEL_ID_OFFSET = -1_000_000_000_000

/** Telegram's colour index of a peer that picked none: its own id (users as they are, chats without -100) % 7. */
export function colorIndexOf(id: number): number {
  const bare = id <= CHANNEL_ID_OFFSET ? CHANNEL_ID_OFFSET - id : Math.abs(id)
  return bare % 7
}

/** The two stops of the gradient Telegram draws behind a peer's initials. */
export function userpicColors(colorIndex: number): readonly [string, string] {
  return USERPIC[TO_USERPIC[colorIndex % 7]!]!
}
