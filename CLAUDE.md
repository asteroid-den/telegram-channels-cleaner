# Channels Cleaner — notes for Claude

Local tool: Kurigram userbot + FastAPI + Vue UI. The user logs in to Telegram (QR or phone, 2FA),
the app pulls every broadcast channel they're subscribed to, shows them as Tinder-like cards
(swipe/keys: keep, unsubscribe, later, mute, archive), and applies the queued actions after a
review screen. Runs on the user's own machine only (127.0.0.1, no auth, not a server/VPS app); phones in the same
network can be let in on demand (paired by QR, see Safety).

Talk to the user in **Russian**. Code, comments, commits and README are in English.

## Repo state (as of 2026-11-26)

- **Released and public** (since 2026-11-17). Repo `asteroid-den/telegram-channels-cleaner` (was
  `channels-cleaner-userbot`); PyPI `telegram-channels-cleaner` 1.0.2–1.7.0, image
  `ghcr.io/asteroid-den/telegram-channels-cleaner` (amd64+arm64, public). 1.0.0/1.0.1 shipped as
  `channels-cleaner`; that PyPI project is gone. Their user data dir was `channels-cleaner`: `config.py` moves it to
  `telegram-channels-cleaner` on first start. Tag `v0.9.0` = the old generic UI (local only).
- **Commit only after the user's OK** for that change set (prepare, run the checks, show, wait); push only on
  their word too.
- PRs don't bump `__version__`: it is set in its own commit (`chore: bump version to X.Y.Z`) right before a release,
  then the user tags and pushes the tag. 1.5.1/1.5.2 were never tagged: everything after 1.5.0 ships as 1.6.0.
- Work goes through branches + PRs into `main` (merge commits). Push only when the user says so
  for that push; **never push tags** — the user tags releases (`release.yml` checks the tag
  against `__version__`, publishes to PyPI via trusted publishing, then GHCR).
- History was rewritten once to drop co-author trailers (PR #1 closed by the force-push).
- Next on the plan: phone access (pairing QR + cookie, mobile layout with mockups first). Done before it:
  README with mock-mode screenshots, public repo, supergroups, archive filter, settings menu, managed chats.
- Commit author email = personal gmail from global git config (already public); keep it.
- `mockups/` — static HTML mockups. Ignored via `.git/info/exclude`, not committed.
- `data/` — local sessions/DB/media (gitignored). Contains the user's mock DB from earlier runs.

Code style: ruff ALL (120 cols), pyright, blank lines around blocks (see the user memory on tooling).
No leading underscores, as in mercury: this is an app, not a library, so module constants, helpers, methods and
attributes are plain names (tests too). Kept only where a property sits on the field (`_client`, `_profile` in the
gateways). Pydantic models set `from_attributes` themselves where they read the services' dataclasses.
Packages re-export what other packages use: `from channels_cleaner.services import ApplyService, deck`,
`from channels_cleaner.telegram import MockGateway, TgUser`, `from channels_cleaner.database import DAO, utc_now`.
Inside a package, modules import each other's submodules (a package import there would be circular). Left out on
purpose: KurigramGateway (imported lazily, so mock mode never loads Kurigram) and `api` (its modules are used as
modules, `errors.X` / `models.X`, and an `api/__init__` importing routers would close the api → context → services
cycle). The UI-only status Literals (AuthStatus, ApplyStatus, ItemStatus) live in `enums.py`, which breaks the
api.models ↔ services loop.
Commit style: small logical commits, conventional prefixes (`feat(api):`, `fix(ui):`, `design(tool):`…),
**no `Co-Authored-By` trailer** (the user removed them from history on 2026-11-17). Branches for iterations after v1.

## Commands

```bash
uv sync && npm --prefix frontend ci           # deps (Node 22.18+, nvm default is 22)
npm --prefix frontend run build               # builds into src/channels_cleaner/static (gitignored)
uv run telegram-channels-cleaner --mock                # fake Telegram; real account: drop --mock
uv run telegram-channels-cleaner --mock --dev          # API only; plus `npm --prefix frontend run dev` (:5173)
```
Checks (= CI): `uv run ruff check && uv run ruff format --check && uv run pyright && uv run pytest`;
`cd frontend && npm run lint && npm run format:check && npm run api:check && npm run test && npm run build`.
**After any change to an API model or route**: `uv run python -m channels_cleaner.api.openapi && npm --prefix frontend
run api:types`, commit both `frontend/openapi.json` and `frontend/src/api/schema.d.ts` (a test and CI check they're current).
**Before every commit with Python changes**: `python3 -I .local/unstick_blocks.py src/channels_cleaner tests`
then `uv run ruff format` — blank lines around if/for/while/try/with/match and before elif/else/except/finally
(user's style). `--check` only reports. `.local/` is local-only (in `.git/info/exclude`), not in the repo or CI.
Mock mode: QR auto-"scans" after ~4 s; phone code `12345`; `CC_MOCK_2FA=1` → password `mock`;
transfers of ownership always take `mock`.
Settings via `CC_*` env / `.env` (see `.env.example`): API id/hash (default = public TDesktop 2040),
data dir, host/port, mock knobs, apply delay range.

## Architecture

```
src/channels_cleaner/
  cli.py          port pre-check (friendly msg if our app already runs), opens browser only after
                  uvicorn started; browser.py opens it quietly (xdg-open/open/os.startfile)
  logs.py         console + data/logs/app.log (rotating, 4×1 MB, never DEBUG); uvicorn runs with log_config=None
                  so its records (request crashes too) go through the same handlers
  healthcheck.py  `python -m channels_cleaner.healthcheck` = the Docker HEALTHCHECK (GET /api/health on CC_PORT)
  app.py          FastAPI factory, error→HTTP mapping, SPA fallback for static/
  context.py      AppContext wires everything; boot task runs auth.start(); clears "skip" on start
  config.py       Settings (pydantic-settings, CC_ prefix)
  enums.py        StrEnums (ChatKind, ChatRole, MediaKind, Decision, DecisionStatus, JobStatus, SortMode,
                  ArchiveFilter, RoleFilter); values = lowercase names, the strings the DB/API/UI always had
  database/       SQLAlchemy 2.1 async over aiosqlite, laid out like mercury: models/ (one file per table,
                  data only), models_dao/ (one DAO class per model, combined in dao.DAO(session)), manager.py
                  (engine, WAL, 15 s busy timeout, async_sessionmaker(expire_on_commit=False)), types.py
                  (UtcDateTime), utils.py (query conditions), migrate.py + legacy.py (see below)
  migrations/     Alembic inside the package (`channels_cleaner:migrations`), applied on every start
  services/decisions.py  decide/undo: the reverts logic that used to live in db.set_decision
  events.py       in-process pub/sub → SSE (api/sse.py: snapshot event first, then live, pings)
  pulse.py        weekly post counts (26 weeks) from ≤100 post dates; unseen weeks = None
  telegram/
    gateway.py    Protocol; kurigram_gateway.py (real) and mock_gateway.py (generated channels)
    device_profiles.json  36 TDesktop-like profiles (user's 24 + 12 added); picked once per
                  session and persisted as data/sessions/<session>.device.json — never re-rolled
  services/       auth (state machine), sync, channels (lazy full info + pulse + media cache), network (phone access),
                  apply (sequential job, 1.5–3 s jitter, FloodWait sleep+retry, cancel), stats,
                  deck (prefs + the deck's counters, COUNT queries), decisions (decide/undo, owner-leave rule)
  api/routers/    /api endpoints, a module per area (health, auth, channels, decisions, apply, results =
                  prefs/stats/export), assembled in routers/__init__.py; each returns a model from
                  api/models.py (from_attributes), so /openapi.json is the whole contract. Named like get-gem:
                  bodies `…Request`, answers `…Response(OkResponse)` (`ok: true`), parts plain nouns (Channel,
                  DeckCounts, ApplyItem); route functions `get_…`/`post_…`/`put_…`/`delete_…`
  api/dependencies.py  ContextDep, DAODep, AccountIdDep (as mercury's DAODep/RuntimeDep)
  api/middlewares.py   LocalOnlyMiddleware; api/utils.py — the 200s of non-JSON routes for OpenAPI
  api/openapi.py  dumps it to frontend/openapi.json → openapi-typescript → frontend/src/api/schema.d.ts;
                  api/types.ts only names those types (and spells out enum-keyed maps OpenAPI can't express)
frontend/src/     Vue 3 + Vite + TS, Pinia, vue-router, vue-i18n (en/ru), Tailwind v4
  stores/         auth (SSE), deck (queue, undo history, prefetch 8 ahead), apply (SSE), ui
  components/     SwipeDeck (pointer swipe + fly-out), ChannelCard, PulseChart, AppHeader…
  views/          Login, Deck (3 columns), Review, Apply (avatar deck animation), Results
  utils/color.ts  dominant avatar colour → --ch/--ch2 CSS vars (useChannelColor composable)
```

Database (2026-11-20, replaced the hand-written aiosqlite layer):
- Routes take a `Dao` dependency (session per request) and commit after writes; services open their own
  `async with database.session()` per unit of work. DAO methods don't commit; three steps
  (`statement` → blank line → `result = await …execute` → `return`), like mercury.
- Enums: `type_annotation_map` maps `enum.Enum` to a non-native `sa.Enum` with `values_callable` — the DB keeps
  the lowercase values (not SQLAlchemy's default member names), no CHECK. Migrations spell enum values out as
  strings, one `sa.Enum` object per type.
- Time: `UtcDateTime` (TEXT, ISO 8601 with `+00:00`), aware UTC in Python, refuses naive datetimes. The stock
  DateTime on SQLite writes `2026-11-17 20:00:00` without the offset: mixed formats sort wrong, reads come back
  naive, the UI would show local times. The API now sends `…Z` (pydantic), the UI parses either.
- Writes are Core statements (sqlite upserts, bulk updates); they don't refresh objects already in the session's
  identity map, so every DAO select that returns ORM objects uses `populate_existing=True` — without it a second
  read in the same session could hand back a stale decision (flaky tests showed it; the map is weak-referenced).
- `decisions` has no id: ties on decided_at are ordered by `decisions.rowid` (utils.DECISION_ROWID).
  No foreign keys (the old schema had none); Channel.decision is a viewonly relationship with an explicit join.
- Migrations: `migrate.upgrade()` runs in a thread at startup. A database from before (has `schema_version`) is
  brought to legacy step 5, its tables renamed to `legacy_*`, Alembic creates the baseline revision
  (`685f08492209`), rows are copied over, `legacy_*` dropped — copied, not stamped, so every database has the same
  declared types and `alembic check` holds everywhere. Restartable at every step (tests/test_migrations.py).
  New revision: `uv run alembic revision --autogenerate -m "…"` (file name `YYYYMMDD_<rev>_<slug>.py`), batch mode
  (render_as_batch) because SQLite alters by copying tables; UtcDateTime renders as `sa.Text()`.

Safety (2026-11-20, after an audit run from the mercury session):
- `api/middlewares.py` LocalOnlyMiddleware: Host must be localhost/127.0.0.1/::1 (or the host given by name with
  --host); POST/PUT/DELETE need `Origin == http://<Host>` and `Sec-Fetch-Site` same-origin/none when present.
  Requests without them (curl, tests) pass. Tests use `base_url="http://localhost"`. Vite proxies with
  changeOrigin: false so Host and Origin stay the dev server's.
- Phone access (`services/network.py`, `/api/network` + `/api/pairing`): off by default. Turned on, a second uvicorn
  server (`LanServer`, no signal handlers, lifespan off) runs in the same loop on this machine's LAN address
  (`lan_address()`: the outgoing interface) and the same port, serving the same app wrapped by `mark_lan`, which puts
  the served address into the scope (`LAN_SCOPE`). The 127.0.0.1 listener is untouched and stays trusted, so Docker
  (bridge IPs) is unaffected; the toggle is unavailable when `--host` isn't loopback (`container`/`custom_host`).
  On the LAN listener the guard wants Host == that address and the `cc_device` cookie of a paired device (sha256 in
  `devices`, kept in memory, last visit written at most once a minute); strangers get only the SPA's GETs,
  `/api/health`, `GET /api/pairing`, `POST /api/pairing/claim` (else 401 `device_not_paired`). `/api/network/*` is
  `computer_only` (403 from the LAN). Pairing: the computer shows a QR link (2 min, one claim) + 4-digit code; the
  phone that claims it gets its cookie at once, valid only after the user approves it *on the computer* with the
  same code on both screens (a second claim: 409 `pairing_taken`). The enabled flag is an app-wide setting
  (`settings.account_id = 0`) and comes back on start. Disconnecting a device or turning access off kicks their
  open SSE streams at once (`network.kicked`); SSE pings every 3 s so a phone notices the computer went away.
- Apply: `start()` holds a lock from the check to the task (`running` is true meanwhile); `PUT /decisions` is
  409 while applying, like DELETE and reset; before each action the job re-reads the decision and skips it
  (failed, nothing written) if it changed; `mark_decision(expected=…)` updates only that pending decision.
- `./data` only when the cwd is this app's own checkout (pyproject name), never a `data/` of another project.
- Migrations: `migrate.backup()` copies the DB to `<name>.before-<version>` before any change; legacy steps run
  with their version row in one explicit transaction (executescript would commit on its own).

Errors, base as get-gem's: `api/errors.py` has `BaseError`, a class per HTTP status under it (`BadRequest`,
`NotFound`, `Conflict`, `TooManyRequests`, `BadGateway`…) that sets `CODE`, and one dataclass per error under those
with `TYPE` (snake case of the class name; what the UI acts on, `ApiError.type` in client.ts) and `MESSAGE`
(upper case as in mercury: `type` would shadow the builtin); fields go into the body
`{"ok": false, "type", "message", …fields}` (`reason` = what Telegram said, `retry_after`, `channel_id`, `details`).
Services and routes raise these classes directly; the gateway's own errors (telegram/types.py) stay HTTP-free and
are translated in `translate`, as are Starlette's 404/405, validation (422) and any other exception (500). The
guard builds its 403s from the same classes. Each route lists its errors in `responses=errors.error_responses(…)`
(plus `COMMON_ERRORS`: the guard's 403s, 422, 500) — in OpenAPI as `<Name>Error` models; the test client checks
every error answer against what its route lists (conftest `check_error_is_declared`, like mercury's jsonrpc
plugin). A test checks every class is complete and TYPEs are unique. "No picture" is `PictureNotFound` (JSON 404).
`kurigram_gateway.telegram_errors()`
maps FloodWait/RPCError/OSError/TimeoutError to the gateway's errors; downloads raise on network errors instead of
caching "no picture". Started offline, `context.boot` retries (2, 5, 10, 30, 60 s…) and publishes `connect_failed`;
the login screen shows it and clears it once connected.

Key behaviours / decisions (agreed with the user):
- Several accounts, one active at a time (2026-11-21, account menu = mockup A in `mockups/account-menu.html`).
  Each has its own session file: `account` (the one from before) or `session-<hex>`, kept in `accounts.session_name`;
  the latest `selected_at` is connected on start. `ctx.switch_session()` refuses while applying (409), stops and
  clears the sync, clears the flood cooldowns and has the gateway connect the other session; a login given up
  halfway is deleted (`forget_session`). Logout clears `session_name` (wipe deletes the account) and hands over to
  the next account, or opens a new session to log in. `/api/accounts` (list with chats/pending, `/{id}/activate`,
  `/add`). Mock mode: one state file and user per session (`MOCK_USERS`), each with chats of its own. The UI drops
  the deck when the user id changes (App.vue). Checked by the user on real accounts (2026-11-25), as were the raw
  GetFullChannel cards and the card drag in Firefox.
  The account's own photo (small size) is fetched after each login into `media/<id>/me.*` (removed when Telegram has
  none), served at `/api/accounts/{id}/avatar`, listed as `avatar_url` (`?v=` mtime); initials only without one.
  Mock: the last mock user has no photo.
- Broadcast channels and supergroups (`channels.kind`, migration 4); plain basic groups are not covered.
  Chats the user owns/admins are included with `channels.role` (member/admin/owner, migration 5) and have
  their own deck: `role=member|managed` next to `kind`/`archive` on every deck query; the settings menu's
  "Who you are there" block picks it. On an owned chat ← opens the successor picker (hand over and leave,
  leave without an owner, delete); `--allow-owner-leave` is gone (still parsed, ignored). Admins may leave, the
  review screen warns about lost rights. What Telegram does when a creator leaves is untested. Archive included (flagged). One sync pass covers both
  kinds (a per-kind sync would mark the other kind `gone`); the deck, trail, stats and export take
  `?kind=`, review/apply are shared across kinds (`counts.pending_other` drives the dot on the
  header switcher). Lists synced before supergroups/roles existed are re-synced once (`synced_scope` setting, bump `SCOPE_VERSION` whenever a sync learns to cover more).
  Wording that differs for groups lives under `group.*` in i18n (`useKindI18n().tk`).
- Archive filter (all / active / archived) lives in the deck prefs (`prefs.archive`, per account) and narrows
  the deck, trail and its counters for either kind; endpoints that return counts without `?archive=` read it
  from the saved prefs. Header: one wide settings button (`DeckSettings.vue`: kind, archive filter, sort, reverse,
  reset; counts come from `counts.kind_totals` / `archive_totals`) — the progress bar lives in DeckView, centred
  right above the deck (mockup D in `mockups/header-layout.html`). Switching kind is deliberately two clicks.
- Decisions: keep/skip are final immediately; unsubscribe/mute/archive are `pending` until the
  apply job. "Skip" = back of the deck, forgotten on next launch. Undo = DELETE decision.
- Owner actions (`OWNER_ACTIONS`, owner role only, checked in `decisions.check_allowed`): `transfer` (to one of
  `GET /channels/{id}/admins`, cached 10 min; `decisions.successor_id/_name`), `delete` (refused above
  `DELETE_LIMIT` members), `free_link` (drops the username). `POST /apply` takes `{password, confirm_deletions}`:
  without them transfers/deletions stay queued (`held_transfers/_deletions`). The password lives in
  `ApplyService.password` for the job only, never stored or logged. One refusal of it (wrong, missing, too fresh)
  fails the remaining transfers without asking Telegram again; `error_code`/`retry_after` on the item. A transfer
  that went through but whose leave failed becomes a failed `unsubscribe` (role admin), so a retry only leaves.
- Full info (raw GetFullChannel) and pulse (raw `messages.GetHistory`, limit 100, no parsing) are
  fetched lazily per card with a semaphore of 1; cached 72 h. Rows without pulse are refetched.
  Both invoke with `sleep_threshold=0`: a flood wait comes back at once instead of kurigram sleeping up to 30 s
  while holding the semaphore. A 4xx (CHANNEL_PRIVATE…) is `RequestRefusedError` → `channels.full_error` +
  `full_fetched_at`, answered 200 and not asked again until the TTL; a dropped connection stays a 502.
  A flood wait sets a per-kind cooldown in ChannelsService ("full", "media"): later cards get 429 at once without
  reaching Telegram; a flood on the history keeps the full info (pulse comes later). The UI's prefetch pauses as a
  whole until `retry_after`, then resumes by itself.
- Sort: "dead first" (never-posted, then oldest last post) or "most unread", each reversible;
  prefs stored per account in DB. Language/theme in localStorage, dark theme default.
- Kurigram: `connect()` manually (start() would prompt interactively), QR via built-in
  `pyrogram.qrlogin.QRLogin` (handles DC migration); after login → disconnect + `start()`.

## Design (mockup "B")

Flat panels + hairlines, data first. Fonts bundled via @fontsource: Jost (headings + verdict figure),
Onest (text), JetBrains Mono (numbers/keys). v1 token names kept (`surface`, `border`, `muted`,
`accent`, `danger`…) with new values, plus `ch`/`ch2` = current channel colour from its avatar.
Deck (deck-v2, chosen from mockups/deck-v2.html): no side columns. Header = deck settings button
+ summary pill (popover: counters, ETA, history+undo, next, Review); the progress bar (decided/total,
segmented by decision, '+1' chip flies in) sits centred above the deck. Fanned stack; card layout C (one verdict figure). Left/right of the
card are click zones (unsubscribe/keep) with cursor glow + card lean. Keycaps under the stage.
Progress bar = chronological trail of decisions (counts.trail, one letter each). Rewind: hover the
bar → TrailLoupe (15 fanned avatars), click to jump; Ctrl+←/→ step through decided cards; deck =
trail[cursor:] + undecided; edits are in place (decided_at kept); "Back to undecided" button.
Changing an applied mute/archive sets decisions.reverts → apply job unmutes/unarchives first.

The user rejected the retro "press" look; wants modern digital but not generic SaaS.
**For any visual change: render 2–3 mockups and let the user pick before implementing.**

## Verification tips / gotchas

- The desktop app's Browser pane is usually hidden → rAF/CSS transitions stall and screenshots
  are stale. Use headless system Chrome via Playwright instead:
  `uv run --no-project --with playwright python script.py` with
  `p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)`.
  Cached Playwright Firefox doesn't match the current Playwright version.
- Start test servers with `CC_DATA_DIR=<scratch dir> CC_NO_BROWSER=1 ... --mock --port 87xx`
  so the user's `data/` isn't touched. Stop with `kill $(lsof -t -i :PORT -sTCP:LISTEN)` —
  `pkill -f "telegram-channels-cleaner ..."` matches its own shell and kills the command (exit 144).
- User's browser is Firefox (snap); its GTK/sandbox warnings in the terminal are harmless.
- After the project folder is renamed, `.venv` scripts point to the old path ("Failed to spawn: pytest"):
  `uv sync --reinstall`.

## Open items

- Flood waits on big accounts: the cooldown and the paused prefetch handle them; lower PREFETCH_AHEAD if they
  still come often.
- What Telegram does when a creator leaves their own chat without a handover is untested.
- `deck.counts` runs ~14 small COUNT queries on each decision: fine at a few thousand chats.
- Base images in the Dockerfile are pinned by tag + digest and CI's Python to 3.12.16: no Dependabot, bump by
  hand (`docker buildx imagetools inspect <image>:<tag>`).
- Optional: bundle only latin+cyrillic font subsets; 5 moderate `npm audit` issues are dev-only.
