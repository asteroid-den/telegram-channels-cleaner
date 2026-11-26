/**
 * The API's types, named as the UI uses them. Generated from the server's OpenAPI schema
 * (`schema.d.ts`, see `npm run api:types`); only the names and a few narrowings live here.
 */
import type { components } from './schema'

type Schemas = components['schemas']

export type AuthStatus = Schemas['AuthStateResponse']['status']
export type TgUser = Schemas['User']
/** Also what the auth event stream sends, which has no `ok`. */
export type AuthState = Omit<Schemas['AuthStateResponse'], 'ok'>

export type Decision = Schemas['Decision']
export type ActionDecision = Extract<Decision, 'unsubscribe' | 'mute' | 'archive'>
export type FinalDecision = Exclude<Decision, 'skip'>
export type SortMode = Schemas['SortMode']
export type ChatKind = Schemas['ChatKind']
export type ChatRole = Schemas['ChatRole']
export type RoleFilter = Schemas['RoleFilter']
export type ArchiveFilter = Schemas['ArchiveFilter']

export type Pulse = Schemas['Pulse']
export type Channel = Schemas['Channel']
export type SyncState = Schemas['SyncState']

/** OpenAPI has no enum-keyed maps: the keys are spelled out here. */
export type DeckCounts = Omit<
  Schemas['DeckCounts'],
  'kind_totals' | 'role_totals' | 'archive_totals' | 'by_decision'
> & {
  kind_totals: Record<ChatKind, number>
  role_totals: Record<RoleFilter, Record<ChatKind, number>>
  archive_totals: Record<ArchiveFilter, number>
  by_decision: Record<FinalDecision, number>
}

export type ChannelsResponse = Omit<Schemas['DeckResponse'], 'counts'> & { counts: DeckCounts }

export type ApplyItemStatus = Schemas['ApplyItem']['status']
export type ApplyItem = Schemas['ApplyItem']
/** Also what the apply event stream sends, which has no `ok`. */
export type ApplyState = Omit<Schemas['ApplyStateResponse'], 'ok'>

export type Stats = Schemas['StatsResponse']
export type Prefs = Schemas['DeckPrefsRequest']
export type ErrorBody = Schemas['ErrorResponse']
export type Account = Schemas['Account']
export type ChatAdmin = Schemas['ChatAdmin']
export type AccountsResponse = Schemas['AccountsResponse']
/** Also what the network event stream sends, which has no `ok`. */
export type NetworkState = Omit<Schemas['NetworkResponse'], 'ok'>
export type Device = Schemas['Device']
export type PairingState = Schemas['PairingResponse']
