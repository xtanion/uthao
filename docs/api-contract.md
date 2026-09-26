# API contract

The mobile app codes against this. `backend/` implements it in FastAPI. Until it
exists, the app runs against an in-memory fake with the same shape
(`mobile/src/data/fakeIssues.ts`), selected with `EXPO_PUBLIC_DEMO=true`.

Base URL comes from `EXPO_PUBLIC_API_URL`. All bodies are JSON unless stated.
All timestamps are RFC 3339 UTC. All ids are strings.

## Conventions

- Auth: `Authorization: Bearer <access_token>` on everything except the two
  `/auth` endpoints and the two public reads.
- Errors: `{ "detail": "human readable message" }` with a normal HTTP status.
  The app surfaces `detail` verbatim, so write it for a person.
- Pagination: opaque `cursor`. The client never parses it. A `null`
  `next_cursor` means the end. Anything encoding offset, keyset, or a token is
  fine as long as it round-trips.

## Types

### Issue

```jsonc
{
  "id": "3f9c...",
  "title": "Cover missing on the footpath side",   // <= 140 chars
  "description": "Cover missing on the footpath side. Unlit after dark.",
  "category": "manhole",          // see enum below
  "severity": "high",             // low | medium | high
  "status": "community_verified", // see enum below
  "latitude": 19.0612,
  "longitude": 72.8371,
  "locality": "Bandra East",      // nullable, short place name for the card
  "confirmation_count": 7,
  "confirmed_by_me": false,       // false when unauthenticated
  "comment_count": 4,           // supports carrying words, whole thread
  "photo_count": 6,             // across the whole gallery
  "photo_support_count": 2,     // supports from others that carried a photo
  "confirmed_at": null,         // when it crossed the confirmation bar
  "contributions_open_at": null,// confirmed_at + 5 days; null until confirmed
  "photos": null,               // the gallery; only on GET /issues/{id}
  "ai_summary": null,           // nullable; absent when no key is configured
  "cover_url": null,              // nullable; signed, short-lived when present
  "created_at": "2026-08-20T09:12:00Z"
}
```

`category`: `pothole_road`, `garbage`, `footpath`, `streetlight`,
`water_drainage`, `manhole`, `traffic_infrastructure`, `fallen_tree`,
`public_property`, `other`

`status`: `reported`, `community_verified`, `submitted_to_authority`,
`authority_acknowledged`, `in_progress`, `resolution_claimed`, `resolved`,
`reopened`, `duplicate`, `removed`

### Page

```jsonc
{ "items": [ /* Issue */ ], "next_cursor": "eyJvIjoyMH0" }
```

## Endpoints

### `GET /issues/nearby`

Public. Ordered by distance ascending, with a stable tiebreak so paging cannot
repeat or drop a row.

| Query | Type | Default | Notes |
|---|---|---|---|
| `lat` | float | required | |
| `lng` | float | required | |
| `radius_m` | float | `500` | |
| `category` | enum | none | filter |
| `cursor` | string | none | from a previous `next_cursor` |
| `limit` | int | `20` | clamp server-side to 1..100 |

→ `200` Page

### `GET /issues/{id}`

Public. → `200` Issue, `404` if unknown or removed.

### `POST /issues`

Authenticated. `multipart/form-data`, because the photo is required.

| Field | Type | Notes |
|---|---|---|
| `client_report_id` | string (uuid) | idempotency key; a repeat returns the original |
| `title` | string | 3..140 |
| `description` | string | <= 2000, may be empty |
| `category` | enum | |
| `severity` | enum | |
| `latitude` | float | |
| `longitude` | float | |
| `photos` | file[] | at least one, JPEG |

→ `201` Issue. `422` with `detail` for validation failures.

Notes for the implementer:
- The client strips EXIF before upload, but **re-strip server-side**. Never
  trust the client for that; it is a privacy guarantee, not a nicety.
- Store originals privately. `cover_url` should be a short-lived signed URL to
  a derived thumbnail, never the raw upload.
- Repeating a `client_report_id` must return the existing issue, not a
  duplicate. The app retries queued drafts on reconnect.

### `POST /issues/{id}/confirmations`

> Still supported: this and its `DELETE` are the original names for a bare
> support. New clients should use `/supports`.

Authenticated. Idempotent — confirming twice is not an error.
Body: `{ "note": "optional, <= 1000 chars" }`
→ `200` Issue (with updated `confirmation_count` and `confirmed_by_me`)

### `DELETE /issues/{id}/confirmations`

Authenticated. → `200` Issue

Reporters must not be able to confirm their own issue; the value of the count
is that it is independent corroboration.

### `POST /auth/otp/request`

Body: `{ "phone": "+919876543210" }` → `204`

Rate limit per phone and per IP. Do not reveal whether the number is known.

### `POST /auth/otp/verify`

Body: `{ "phone": "+919876543210", "code": "123456" }`
→ `200 { "access_token": "...", "token_type": "bearer", "expires_in": 3600, "refresh_token": "..." }`
→ `401` with `detail` on a bad or expired code.

### `GET /me`

Authenticated. → `200 { "id": "...", "display_name": "...", "avatar_url": null }`

## Open questions for the backend author

1. **Geofence.** The prototype restricted reports to a Mumbai bounding box.
   Decide whether that stays, widens to India, or moves to a config value.
2. **Comments.** `comment_count` is in the Issue shape and the UI renders it,
   but no comment endpoints exist yet. Ship it as a constant `0` until they do.
3. **Refresh tokens.** The app currently assumes a long-lived access token. If
   you want short-lived tokens plus refresh, say so and the client will add the
   interceptor.

## Added after the first draft

The endpoints above are the original surface. These were added for the search,
activity, and comment screens; everything above still behaves as documented.
Rationale and implementation notes live in `backend/README.md`.

### `GET /issues/nearby` — new optional query params

| Query | Type | Default | Notes |
|---|---|---|---|
| `q` | string | none | free text over title and description, <= 120 chars, case-insensitive |
| `severity` | enum | none | filter |
| `status` | enum | none | filter |

Wildcards in `q` are matched literally. These compose with `category` and with
the existing distance ordering and cursor, so a filtered page walks the same way
an unfiltered one does. Omitting them all leaves the endpoint unchanged.

### `GET /me/issues`

Authenticated. The signed-in reporter's own issues, newest first, cursor paged.
→ `200` Page

Includes issues whose status is `removed`: they are hidden from everyone else,
but the person who filed one should still see what became of it.

### Notification

```jsonc
{
  "id": "9f21...",
  "type": "support_received",        // support_received | status_changed
  "read": false,
  "actor_name": "Resident 0001",     // null when no person caused it
  "from_status": null,               // set on status_changed
  "to_status": null,                 // set on status_changed
  "issue": {                         // just enough to render the row
    "id": "3f9c...",
    "title": "Cover missing on the footpath side",
    "category": "manhole",
    "severity": "high",
    "status": "community_verified",
    "cover_url": null,               // signed, short-lived when present
    "confirmation_count": 7
  },
  "created_at": "2026-08-20T09:12:00Z"
}
```

### `GET /notifications`

Authenticated. Newest first, cursor paged. Only ever the caller's own rows.

| Query | Type | Default |
|---|---|---|
| `cursor` | string | none |
| `limit` | int | `20`, clamped 1..100 |

→ `200 { "items": [ /* Notification */ ], "next_cursor": null, "unread_count": 3 }`

`unread_count` is the total across the whole feed, not just the page, so the
badge does not need to page to be right.

A reporter is notified the first time someone else supports their issue, and
when enough supports move its status. Adding to a support you already made does
not notify again — it is the same act — and supporting your own issue notifies
nobody, so you never notify yourself.

### `POST /notifications/read`

Authenticated. Body `{ "ids": ["..."] }` marks those rows read; omit the body or
send `{}` to mark the whole feed read.
→ `200 { "unread_count": 0 }`

### Photo

```jsonc
{
  "id": "a09c...",
  "url": "https://...",            // signed, short-lived; the full image
  "thumbnail_url": "https://...",  // signed, short-lived
  "contributor": { "id": "5c02...", "display_name": "Resident 0001" },
  "from_report": true,             // false for one added with a support
  "created_at": "2026-08-20T09:12:00Z"
}
```

Every photo names whoever took it, whether it arrived with the original report
or with a later support. That is what lets the gallery credit each image.

### Support

One person backing one issue: optional words, optional photos. Replaces the
separate confirmation and comment shapes — someone standing in front of a broken
thing does one act, and splitting it made the person who photographed the
problem indistinguishable from the one who tapped a button.

```jsonc
{
  "id": "b71e...",
  "body": "Still open as of this morning.",  // nullable; <= 2000 chars, trimmed
  "photos": [ /* Photo */ ],                 // may be empty
  "author": { "id": "5c02...", "display_name": "Resident 0001" },
  "author_is_reporter": false,
  "mine": false,                             // false when unauthenticated
  "created_at": "2026-08-20T09:12:00Z"
}
```

`confirmation_count` counts supports from anyone but the reporter;
`comment_count` counts the ones carrying words.

### `GET /issues/duplicates`

Public. Reports near enough that a new one is probably the same thing. Called
before publishing, so the composer can offer to add the photo to what is already
there.

| Query | Type | Default |
|---|---|---|
| `lat`, `lng` | float | required |
| `category` | enum | none; omit to match any |
| `radius_m` | float | `DUPLICATE_RADIUS_M` (100), capped at `max_radius_m` |

→ `200 { "items": [{ "issue": Issue, "distance_m": 41.2 }], "radius_m": 100 }`

Same category only: a bin and a manhole on one corner are two problems. Resolved
and removed reports are excluded — a problem that came back is news, not a
repeat. Closest first, at most 10. Advisory only: nothing server-side refuses a
report for being near another one.

### `GET /issues/{id}/supports`

Public. Newest first, cursor paged.
→ `200 { "items": [ /* Support */ ], "next_cursor": null, "total": 4 }`
→ `404` if the issue is gone or removed

`total` is the whole thread. A thread reads oldest first; the client reverses a
page rather than the query paging backwards into rows that are still arriving.

### `POST /issues/{id}/supports`

Authenticated. **`multipart/form-data`**, because photos travel with it.

| Field | Type | Notes |
|---|---|---|
| `body` | string | optional, <= 2000 chars |
| `photos` | file[] | optional, JPEG, at most `MAX_PHOTOS_PER_REPORT` |
| `latitude`, `longitude` | float | where the phone is; required with `photos` |

→ `200` the updated Issue
→ `403` a bare support (no body, no photos) on your own report
→ `404` if the issue is gone, `422` on an unusable photo or an overlong body
→ `422` photos with no location, or from further than `SUPPORT_RADIUS_M` (150)
  from the report

Supporting twice updates the row and adds to it rather than failing — that is
what someone adding a photo to something they already backed expects. The
reporter may support their own issue to post a follow-up; it does not count
toward `confirmation_count`.

Photos count because they are taken where the problem is, so a support that
carries any must say where it was sent from. Words and a bare support need no
location: neither moves the status. The location is checked, not stored.

### `DELETE /issues/{id}/supports`

Authenticated. Withdraws, and deletes the photos that came with it — they were
offered as part of backing the report. The reporter's own photos are untouched.
→ `200` the updated Issue

### `GET /issues/{id}/photos`

Public. The gallery, oldest first: the original report leads and later
contributions follow.
→ `200 [ /* Photo */ ]`

`GET /issues/{id}` carries the same array as `photos`. Every other read leaves
it `null` and gives `cover_url` only — signing a link per photo per card is work
the feed does not need.

### FixDate

```jsonc
{
  "id": "d41a...",
  "fix_on": "2026-09-05",        // a day, not a moment
  "vote_count": 3,
  "voted_by_me": false,
  "proposed_by": { "id": "5c02...", "display_name": "Resident 0001" },
  "mine": false
}
```

### `GET /issues/{id}/fix-dates`

Public. The poll of days people have offered to go and fix it. Readable before
it opens, so people can see what is coming.

→ `200 { "items": [ /* FixDate */ ], "open": false, "opens_at": "...",
        "proposed_by_me": false, "remaining_slots": 5 }`

`open` is false until `contributions_open_at` has passed; writes are refused
until then. Days come back soonest first.

### `POST /issues/{id}/fix-dates`

Authenticated. Body `{ "fix_on": "2026-09-05" }`
→ `200` the whole board
→ `409` if the window is shut, the day has already gone, the report already has
five days, or the caller has already put one forward

One proposal per person per report. Proposing a day that is already on the board
is agreement rather than a collision: it becomes a vote and leaves that person's
own proposal unspent. Putting a day up counts as saying you will be there, so it
carries a vote.

Days are compared against India time, not UTC.

### `POST` / `DELETE /issues/{id}/fix-dates/{fix_date_id}/votes`

Authenticated. Back a day, or pull out. Both return the whole board.
→ `409` if the window is shut, `404` if that day is not on this report

Voting is unlimited — you can say yes to every day you are free. A proposer
pulling their own vote deletes the day, since nobody is coming to it.

### `POST /auth/token/refresh`

Authenticated by the token itself. Body `{ "refresh_token": "..." }`
→ `200` the same body as `/auth/otp/verify`, `401` with `detail` if the token is
bad, expired, or an access token.

The app uses this: `client.ts` retries a `401` once behind a single-flight
refresh, so several requests failing together spend one refresh token rather
than racing each other. A refresh that comes back `401` clears the stored pair
and the caller sees the original error.

## Profiles

A profile is a public record of contribution, so all three reads are public.
`Issue` gained a `reporter` field to make one reachable from any card:

```jsonc
"reporter": { "id": "8c1f...", "display_name": "Resident 3210" }
```

### `GET /users/{id}`

Public. → `200`, `404` if unknown.

```jsonc
{
  "id": "8c1f...",
  "display_name": "Resident 3210",
  "avatar_url": null,             // nullable; signed, short-lived when present
  "reputation": 19,
  "contributions": {
    "posts": 3,                   // excludes removed
    "upvotes_received": 13,       // confirmations on their reports
    "supports_given": 4,          // confirmations they made
    "comments_written": 0,
    "resolutions": 1              // their reports now `resolved`
  },
  "joined_at": "2026-01-14T09:12:00Z"
}
```

`reputation` = `upvotes_received` + `posts`×2 + `resolutions`×5. Every number is
counted from rows rather than stored, so none can drift. Commenting shows in
the tallies but carries no weight, so the score cannot be farmed with chatter.

### `GET /users/{id}/issues`

Public. That person's reports, newest first, cursor paged. → `200` Page

Removed reports are omitted, except for the reporter reading their own — they
are hidden from everyone else, but the author should still see what became of
one.

### `GET /users/{id}/supports`

Public. Issues they corroborated, **most recently supported first** — ordered by
when they confirmed, not when the issue was filed, so the tab reads as their
activity. Removed issues drop out even though the confirmation row survives.
→ `200` Page

Note for whoever picks this up: this exposes one person's full support history.
The aggregate count has always been public and corroboration is the point, but a
per-person list is a step further. If that turns out to be the wrong call, the
endpoint is the only thing to change.
