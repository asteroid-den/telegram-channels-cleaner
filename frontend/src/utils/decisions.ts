import type { Decision } from '@/api/types'
import type { IconName } from '@/components/AppIcon.vue'

/** The colour a decision is shown in, everywhere: the bar, chips, stamps, badges, tags. */
export type Tone = 'success' | 'danger' | 'warn' | 'accent' | 'muted'

export interface DecisionMeta {
  tone: Tone
  icon: IconName
  /** The action's name (`actions.*`). */
  label: string
  /** Its letter in the trail (`counts.trail`, the backend's TRAIL_CODES); "later" leaves none. */
  code: string | null
  /** Done by the apply job, so pending until then; the others are final at once. */
  applied: boolean
}

/**
 * Every decision in one place. A `Record` over `Decision`: a new one doesn't compile until it is described here, and
 * every view that shows decisions picks it up from here.
 */
export const DECISIONS: Record<Decision, DecisionMeta> = {
  keep: { tone: 'success', icon: 'check', label: 'actions.keep', code: 'k', applied: false },
  unsubscribe: {
    tone: 'danger',
    icon: 'x',
    label: 'actions.unsubscribe',
    code: 'u',
    applied: true,
  },
  skip: { tone: 'muted', icon: 'skip', label: 'actions.skip', code: null, applied: false },
  mute: { tone: 'warn', icon: 'bellOff', label: 'actions.mute', code: 'm', applied: true },
  archive: { tone: 'accent', icon: 'archive', label: 'actions.archive', code: 'a', applied: true },
  transfer: { tone: 'danger', icon: 'user', label: 'actions.transfer', code: 't', applied: true },
  delete: { tone: 'danger', icon: 'trash', label: 'actions.delete', code: 'd', applied: true },
  free_link: { tone: 'accent', icon: 'link', label: 'actions.freeLink', code: 'l', applied: true },
}

/** The trail's letters back to their decisions. */
export const DECISION_BY_CODE: Record<string, Decision> = Object.fromEntries(
  Object.entries(DECISIONS)
    .filter(([, meta]) => meta.code)
    .map(([decision, meta]) => [meta.code, decision]),
)

// Whole class names, so Tailwind finds them in this file

/** A soft background with the tone's text: tags and chips with words in them. */
export const SOFT: Record<Tone, string> = {
  success: 'bg-success-soft text-success',
  danger: 'bg-danger-soft text-danger',
  warn: 'bg-warn-soft text-warn',
  accent: 'bg-accent-soft text-accent',
  muted: 'bg-surface-3 text-muted',
}

/** A plain fill: the progress bar's runs, the apply screen's badges. */
export const FILL: Record<Tone, string> = {
  success: 'bg-success',
  danger: 'bg-danger',
  warn: 'bg-warn',
  accent: 'bg-accent',
  muted: 'bg-faint',
}

/** A fill that stands out on top of a card or an avatar: the "+1" chip, the loupe's badges. */
export const STRONG: Record<Tone, string> = {
  ...FILL,
  danger: 'bg-danger-strong',
}

/** An outline with the tone's text: the stamps on a card. */
export const OUTLINE: Record<Tone, string> = {
  success: 'border-success text-success',
  danger: 'border-danger text-danger',
  warn: 'border-warn text-warn',
  accent: 'border-accent text-accent',
  muted: 'border-muted text-muted',
}

/** Shorthands for a decision's own classes. */
export const soft = (decision: Decision) => SOFT[DECISIONS[decision].tone]
export const fill = (decision: Decision) => FILL[DECISIONS[decision].tone]
export const strong = (decision: Decision) => STRONG[DECISIONS[decision].tone]
export const outline = (decision: Decision) => OUTLINE[DECISIONS[decision].tone]
