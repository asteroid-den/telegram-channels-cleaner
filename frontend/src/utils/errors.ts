/** What to show for a failed request: the API's own message (an ApiError), never "Error: …". */
export function errorText(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

export type ActionErrorKind =
  'gone' | 'flood' | 'password_invalid' | 'password_missing' | 'too_fresh' | 'too_large' | 'unknown'

/** What went wrong with an action, from the text Telegram gave (kept with a failed decision). */
export function actionErrorKind(raw: string | null): ActionErrorKind {
  if (!raw) return 'unknown'
  if (/PASSWORD_HASH_INVALID/i.test(raw)) return 'password_invalid'
  if (/PASSWORD_MISSING/i.test(raw)) return 'password_missing'
  if (/TOO_FRESH/i.test(raw)) return 'too_fresh'
  if (/CHANNEL_TOO_LARGE/i.test(raw)) return 'too_large'
  if (/CHANNEL_(PRIVATE|INVALID)|USER_NOT_PARTICIPANT|CHAT_ID_INVALID/i.test(raw)) return 'gone'
  if (/flood/i.test(raw)) return 'flood'
  return 'unknown'
}
