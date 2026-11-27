import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Channel, DeckCounts } from '@/api/types'

import { useDeckStore } from './deck'

/** A request the test answers when it wants to, so answers can come in any order. */
interface Call {
  method: string
  url: string
  body: unknown
  answer: (body: unknown, status?: number) => Promise<void>
}

let calls: Call[] = []

function counts(undecided: number, trail = ''): DeckCounts {
  return {
    total: 5,
    kind_totals: { channel: 5, supergroup: 0 },
    role_totals: { member: { channel: 5, supergroup: 0 }, managed: { channel: 0, supergroup: 0 } },
    archive_totals: { all: 5, active: 5, archived: 0 },
    undecided,
    pending: 0,
    pending_other: 0,
    by_decision: {
      keep: 0,
      unsubscribe: 0,
      mute: 0,
      archive: 0,
      transfer: 0,
      delete: 0,
      free_link: 0,
    },
    trail,
  }
}

const channel = (id: number, decision: Channel['decision'] = null) =>
  ({ id, title: `chat ${id}`, decision, full_loaded: true, pulse: [] }) as unknown as Channel

/** Lets every promise chain waiting on an answer run on. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

beforeEach(() => {
  setActivePinia(createPinia())
  calls = []
  vi.stubGlobal(
    'fetch',
    vi.fn(
      (url: string, init: RequestInit) =>
        new Promise<Response>((resolve) => {
          calls.push({
            method: init.method ?? 'GET',
            url,
            body: init.body ? JSON.parse(init.body as string) : undefined,
            answer: async (body, status = 200) => {
              resolve(new Response(JSON.stringify(body), { status }))
              await settle()
            },
          })
        }),
    ),
  )
})

afterEach(() => vi.unstubAllGlobals())

const writes = () => calls.filter((c) => c.method !== 'GET')

/** A deck of `queue` undecided cards after `trail` decided ones, as the server would list it. */
async function loaded(queue: Channel[], trail: Channel[] = []) {
  const deck = useDeckStore()
  deck.loaded = true // no prefs request
  const done = deck.load()
  await settle()
  const list = calls.find((c) => c.url.startsWith('/api/channels?'))!
  const decided = calls.find((c) => c.url.startsWith('/api/decisions/trail'))!
  await list.answer({ items: queue, counts: counts(queue.length), sync: null })
  await decided.answer({ items: trail })
  await done
  calls = []
  return deck
}

describe('deck store', () => {
  it('gives a decision to the card that flew, even if another came on top meanwhile', async () => {
    const deck = await loaded([channel(1), channel(2)])
    // Card 1 starts flying; meanwhile card 2 is put on top (a search, a reload in another order)
    deck.bringToTop(2)
    void deck.decide('keep', {}, 1)
    await settle()
    expect(writes()[0]!.url).toBe('/api/decisions/1')
    expect(deck.items.map((c) => c.id)).toEqual([2])
    expect(deck.trail.map((c) => c.id)).toEqual([1])
  })

  it('drops a decision for a card that is gone from the deck', async () => {
    const deck = await loaded([channel(1)])
    await deck.decide('keep', {}, 99)
    expect(writes()).toHaveLength(0)
    expect(deck.items.map((c) => c.id)).toEqual([1])
  })

  it('sends decisions one at a time, in the order made', async () => {
    const deck = await loaded([channel(1), channel(2)])
    void deck.decide('keep', {}, 1)
    void deck.decide('unsubscribe', {}, 2)
    await settle()
    expect(writes().map((c) => c.url)).toEqual(['/api/decisions/1'])
    await writes()[0]!.answer({ counts: counts(1, 'k') })
    expect(writes().map((c) => c.url)).toEqual(['/api/decisions/1', '/api/decisions/2'])
  })

  it('keeps the local counts until the last answer of a burst', async () => {
    const deck = await loaded([channel(1), channel(2)])
    void deck.decide('keep', {}, 1)
    void deck.decide('unsubscribe', {}, 2)
    await settle()
    expect(deck.counts.trail).toBe('ku')
    expect(deck.counts.undecided).toBe(0)
    // The first answer knows only the first decision: it must not take the second one off the bar
    await writes()[0]!.answer({ counts: counts(1, 'k') })
    expect(deck.counts.trail).toBe('ku')
    await writes()[1]!.answer({ counts: { ...counts(0, 'ku'), pending: 1 } })
    expect(deck.counts.pending).toBe(1)
  })

  it('takes back the refused decision, not the one made after it', async () => {
    const deck = await loaded([channel(1), channel(2), channel(3)])
    void deck.decide('keep', {}, 1)
    void deck.decide('unsubscribe', {}, 2)
    await settle()
    await writes()[0]!.answer({ ok: false, type: 'telegram_error', message: 'No' }, 502)
    await writes()[1]!.answer({ counts: counts(2, 'u') })
    expect(deck.items.map((c) => c.id)).toEqual([1, 3])
    expect(deck.trail.map((c) => c.id)).toEqual([2])
    expect(deck.history.map((h) => h.channel.id)).toEqual([2])
    expect(deck.counts.trail).toBe('u')
  })

  it('sends an undo after the decision it takes back', async () => {
    const deck = await loaded([channel(1), channel(2)])
    void deck.decide('keep', {}, 1)
    void deck.undo()
    await settle()
    expect(writes().map((c) => c.method)).toEqual(['PUT'])
    expect(deck.items.map((c) => c.id)).toEqual([1, 2])
    expect(deck.counts.trail).toBe('')
    await writes()[0]!.answer({ counts: counts(1, 'k') })
    expect(writes().map((c) => c.method)).toEqual(['PUT', 'DELETE'])
    await writes()[1]!.answer({ counts: counts(2, '') })
    expect(deck.counts.undecided).toBe(2)
  })

  it('holds an undo while a card is flying', async () => {
    const deck = await loaded([channel(1), channel(2)])
    void deck.decide('keep', {}, 1)
    await settle()
    deck.moving = true
    await deck.undo()
    expect(deck.history).toHaveLength(1)
  })

  it('undoes a changed decision on the right card after a reload reordered the trail', async () => {
    const deck = await loaded([channel(3)], [channel(1, 'keep'), channel(2, 'keep')])
    deck.jumpTo(0)
    void deck.decide('unsubscribe', {}, 1)
    await settle()
    await writes()[0]!.answer({ counts: counts(1, 'uk') })
    // A sync's reload lists the trail in another order
    const reload = deck.load()
    await settle()
    await calls
      .find((c) => c.url.startsWith('/api/channels?'))!
      .answer({
        items: [channel(3)],
        counts: counts(1, 'ku'),
        sync: null,
      })
    await calls
      .find((c) => c.url.startsWith('/api/decisions/trail'))!
      .answer({ items: [channel(2, 'keep'), channel(1, 'unsubscribe')] })
    await reload
    calls = []
    void deck.undo()
    await settle()
    expect(deck.trail.map((c) => [c.id, c.decision])).toEqual([
      [2, 'keep'],
      [1, 'keep'],
    ])
    expect(writes()[0]).toMatchObject({ url: '/api/decisions/1', body: { decision: 'keep' } })
  })

  it('lets only the latest load land', async () => {
    const deck = await loaded([channel(1)])
    const first = deck.load()
    await settle()
    const second = deck.load()
    await settle()
    const lists = calls.filter((c) => c.url.startsWith('/api/channels?'))
    const trails = calls.filter((c) => c.url.startsWith('/api/decisions/trail'))
    await lists[1]!.answer({ items: [channel(2)], counts: counts(1), sync: null })
    await trails[1]!.answer({ items: [] })
    await second
    await lists[0]!.answer({ items: [channel(1)], counts: counts(1), sync: null })
    await trails[0]!.answer({ items: [] })
    await first
    expect(deck.items.map((c) => c.id)).toEqual([2])
    expect(deck.loading).toBe(false)
  })

  it('notices a decision turned down because the queue is being applied', async () => {
    const deck = await loaded([channel(1)])
    void deck.decide('keep', {}, 1)
    await settle()
    await writes()[0]!.answer({ ok: false, type: 'apply_job_running', message: 'Wait' }, 409)
    expect(deck.applyRunning).toBe(true)
    expect(deck.items.map((c) => c.id)).toEqual([1])
  })
})
