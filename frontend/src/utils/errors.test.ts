import { describe, expect, it } from 'vitest'

import { actionErrorKind } from './errors'

describe('actionErrorKind', () => {
  it('recognises channels that are no longer reachable', () => {
    expect(actionErrorKind('CHANNEL_PRIVATE')).toBe('gone')
    expect(actionErrorKind('[400 CHANNEL_INVALID] The channel is invalid')).toBe('gone')
  })
  it('recognises flood limits', () => {
    expect(actionErrorKind('Too many flood waits')).toBe('flood')
  })
  it('recognises refusals of the owner actions', () => {
    expect(actionErrorKind('PASSWORD_HASH_INVALID')).toBe('password_invalid')
    expect(actionErrorKind('PASSWORD_MISSING')).toBe('password_missing')
    expect(actionErrorKind('SESSION_TOO_FRESH_X')).toBe('too_fresh')
    expect(actionErrorKind('PASSWORD_TOO_FRESH_X')).toBe('too_fresh')
    expect(actionErrorKind('CHANNEL_TOO_LARGE')).toBe('too_large')
  })
  it('falls back to unknown', () => {
    expect(actionErrorKind('boom')).toBe('unknown')
    expect(actionErrorKind(null)).toBe('unknown')
  })
})
