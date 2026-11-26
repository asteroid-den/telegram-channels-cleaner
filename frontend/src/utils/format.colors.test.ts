import { describe, expect, it } from 'vitest'

import { colorIndexOf, userpicColors } from './format'

describe("Telegram's avatar colours", () => {
  it('takes a channel by its own id, without the -100', () => {
    expect(colorIndexOf(-1001234567890)).toBe(1234567890 % 7)
  })
  it('takes a user by their id', () => {
    expect(colorIndexOf(777000111)).toBe(777000111 % 7)
  })
  it('maps an index to Telegram Desktop’s palette', () => {
    expect(userpicColors(0)).toEqual(['#ff845e', '#d45246']) // red
    expect(userpicColors(1)).toEqual(['#febb5b', '#f68136']) // orange
    expect(userpicColors(6)).toEqual(['#ff8aac', '#d95574']) // pink
  })
})
