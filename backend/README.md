# backend

FastAPI service. Implements `docs/api-contract.md`. Photos live in Cloudflare R2.

## Running

```bash
uv sync
cp .env.example .env
uv run uvicorn app.main:app --reload
```

That is enough to point the app at it:

```bash
cd ../mobile && EXPO_PUBLIC_API_URL=http://127.0.0.1:8000 npm start
```

With no R2 credentials set, uploads go to `MEDIA_ROOT` on disk and are served
from `/media` behind an expiring HMAC link. The client code path is identical to
production — a short-lived signed URL to a derived thumbnail — so local runs
exercise the real thing. The service logs a warning while in that mode.

With no SMS provider configured, the OTP is written to the log. Set
`OTP_DEBUG_CODE=123456` to accept a fixed code for any number, which matches
what `npm run demo` does on the app side.

```bash
uv run pytest
```

## Mock data

```bash
uv run python scripts/seed.py --reset
```

Fills the database with about forty Mumbai reports around Bandra East, backed
by other residents, a few moved along the workflow, and every one with a photo.
It goes through the service layer rather than writing rows directly, so the
photos take the same path a real upload does — EXIF stripped, thumbnail
derived, object stored — and what the app renders is what it would render in
production. The images themselves are generated, not photographs: a colour per
category so the grid reads as varied.

Point the app at it with `EXPO_PUBLIC_DEMO=false` and
`EXPO_PUBLIC_API_URL=http://127.0.0.1:8000`, and set `OTP_DEBUG_CODE` so any
phone number signs in.

## Migrations

Alembic. The app runs `alembic upgrade head` at startup, so a checkout needs no
extra step:

```bash
uv run alembic upgrade head       # or just start the app
uv run alembic revision --autogenerate -m "what changed"
uv run alembic check              # fails when models and migrations disagree
```

Turn `AUTO_MIGRATE=false` on wherever more than one worker can boot at once —
concurrent upgrades on the same database are a race — and make the upgrade a
deploy step instead.

Autogenerate drafts a migration; it does not finish one. `0002_comments` is the
standing example: it emitted `comment_count` as a bare `NOT NULL`, which cannot
be applied to a table that already has rows, so the revision carries a server
default to backfill and drops it afterwards. Read what it writes.

The test suite builds its schema with `create_all` because that is fast, which
means the migrations could drift from the models without a single test noticing.
`tests/test_migrations.py` is what notices: it migrates an empty database and
asserts `compare_metadata` finds nothing, migrates a populated one to check the
backfill, and walks a downgrade back.

## Scheduled work

Two jobs, run from the system's scheduler rather than in-process:

```cron
17 * * * *  cd /srv/fihy/backend && uv run python -m app.jobs escalate
30 4 * * *  cd /srv/fihy/backend && uv run python -m app.jobs check
50 4 * * *  cd /srv/fihy/backend && uv run python -m app.jobs prune
```

`uv run python -m app.jobs all` runs all three; an unknown name exits `2`.

**escalate** takes reports that have been confirmed for `ESCALATE_AFTER_HOURS`
and raises them with the body responsible. **check** asks what became of the
ones already raised. **prune** clears spent OTP rows: both tables hold verified
phone numbers, nothing reads them after the challenge is used or the rate-limit
hour is up, and left alone they grow without bound.

There is deliberately no in-process scheduler. Under more than one web worker
every tick would fire once per worker, which for a job that sends letters to a
municipal body is the wrong kind of mistake to make quietly. The jobs are safe
to run repeatedly and safe to interrupt: each report is claimed by an insert
that a unique constraint arbitrates, so two overlapping runs cannot both send.

## Deploying

```bash
docker build -t fihy-backend backend
```

One worker per container; scale with replicas. That is why `AUTO_MIGRATE` must
be `false` in a deployment — several workers racing the same upgrade is the
footgun it exists to avoid — and why the crons run from the scheduler rather
than in-process. Run `alembic upgrade head` as a release step before the new
containers start.

The app refuses to boot outside `development`/`test` if `SECRET_KEY` is still
the default, or if R2 is not configured. The second one matters more than it
looks: without it photos are written to the container's own disk and disappear
on the next deploy, and a service that quietly loses evidence is worse than one
that will not start.

`/health` touches the database and answers `503` when it cannot, so a pod whose
connection pool has died stops taking traffic. `/docs`, `/redoc`, and
`/openapi.json` are closed outside development unless `PUBLIC_DOCS=true`.

## Layout

```
app/config.py     settings, all overridable by environment
app/models.py     SQLAlchemy tables
app/schemas.py    request and response bodies
app/service.py    issue reads, writes, supports, duplicates
app/otp.py        challenge lifecycle and rate limits
app/images.py     JPEG validation, EXIF stripping, thumbnails
app/storage.py    R2, and the on-disk stand-in
app/geo.py        geofence and distance
app/cursor.py     the opaque paging cursor
app/routers/      one module per group of endpoints
app/summarize.py  the AI summary, and the no-op it defaults to
app/authority.py  drafting a concern, reading the reply, choosing a channel
app/mail.py       composing and sending the letter, and the reply address
app/inbound.py    what comes back: replies, bounces, deliveries
app/jobs.py       the two crons, and the CLI that runs them
app/migrations.py applying alembic from inside the app
migrations/       the revisions themselves
```

`sqlite+aiosqlite` is the default so a checkout runs with nothing installed.
Postgres works unchanged: set `DATABASE_URL=postgresql+asyncpg://...` and
`uv sync --extra postgres`. Nothing in the query layer is SQLite-specific.

## Answers to the contract's open questions

**1. Geofence.** Widened from the prototype's Mumbai box to all of India, and
moved into config: `GEOFENCE_MIN_LATITUDE` and its three siblings, with
`GEOFENCE_ENABLED=false` to switch it off entirely. Out-of-box reports get a
`422` naming the country, which is a message a person can act on. Reads are not
geofenced — only reports are.

**2. Comments.** Built, then merged. A comment is no longer its own row: it is
a `Support` that happens to carry words. `comment_count` counts supports with a
body, `confirmation_count` counts supports from anyone but the reporter. See
**Supports** below for why.

**3. Refresh tokens.** The app now uses them. It stores both halves and retries
a `401` once behind a single-flight refresh, so shortening
`ACCESS_TOKEN_TTL_SECONDS` is a config change rather than a client change. The
30-day default stands until there is a reason to move it.

## Beyond the contract

`docs/api-contract.md` describes the original surface. These were added for the
search and activity screens and are recorded in the contract's own
"Added after the first draft" section:

| Route | Why |
|---|---|
| `GET /issues/nearby?q=&severity=&status=` | Search. Optional, so existing callers are unaffected. |
| `GET /me/issues` | The reporter's own issues, newest first. Nothing else could list them. |
| `GET /notifications` | Activity feed plus an unread count. |
| `POST /notifications/read` | Marks the feed, or named rows, read. |
| `GET /issues/duplicates` | Reports within `DUPLICATE_RADIUS_M`, same category, so the composer can offer to join one. |
| `GET /issues/{id}/supports` | The thread: words and photos together. Public, cursor paged. |
| `POST /issues/{id}/supports` | Back a report, optionally with words and photos. Multipart. |
| `DELETE /issues/{id}/supports` | Withdraw, taking your photos with it. |
| `GET /issues/{id}/photos` | The gallery, every photo credited to whoever took it. |
| `GET /issues/{id}/fix-dates` | The poll. Readable before it opens. |
| `POST /issues/{id}/fix-dates` | Offer a day. One per person per report. |
| `POST`/`DELETE /issues/{id}/fix-dates/{id}/votes` | Back a day, or pull out. |
| `POST /auth/token/refresh` | Now used by the app; see open question 3. |

**Activity.** `activity_events` holds one row per thing that happened to an
issue somebody reported. Two kinds exist: `confirmation_received`, which
carries the actor so the app can name them, and `status_changed`, which carries
no actor because the crowd moved it rather than any one person. Rows are
written where the change happens — a new confirmation, or a status transition
in `_recount` — so nothing polls or reconciles. The recipient is always the
reporter, and a confirmer never notifies themselves.

**Supports.** Confirmations, comments, and photo uploads used to be three
tables and three acts. They are one now, because someone standing in front of a
broken thing does one thing: they agree it is there, and they may say something
or take a picture while doing it. Splitting that made the person who had
photographed the problem indistinguishable from the one who tapped a button.

A `Support` is one row per person per issue with an optional `body` and
optional photos. Supporting twice is not an error — it updates the row, which is
what someone adding a photo to something they already backed expects. Both
tallies fall out of it: `confirmation_count` counts supports from anyone but the
reporter, `comment_count` counts the ones carrying words. Both are recomputed
from rows rather than incremented, so neither can drift.

The reporter may support their own issue, and it does not corroborate anything.
That sounds contradictory and is not: the reporter needs somewhere to post a
follow-up photo or reply, and `_recount` leaves their row out of
`confirmation_count`. A *bare* support from the reporter — no words, no photos —
is still a `403`, because that is the old "you cannot confirm your own report"
rule and it still holds.

A support carrying photos has to come with the phone's location, within
`SUPPORT_RADIUS_M` (150 m) of the report, or it is a `422`. Photo supports are
what move a report to `community_verified`, and from there escalation and the
fix-date poll, so "two people standing in the same place with a camera" has to
be checked somewhere. 150 m is the duplicate radius plus room for two phones'
GPS error. Words and bare supports need no location, since neither moves
anything, and the location is checked and dropped rather than stored.

Withdrawing a support deletes its photos too. They were offered as part of
backing the report, so they leave with the backing; the reporter's own photos,
which have no `support_id`, are untouched.

**Photos and attribution.** `issue_photos.contributor_id` names whoever took
each image, and `support_id` says where it came from: null for the original
report, set for one that arrived with a support. That is one table and one
query for the gallery, and every image can be credited without a join through
two shapes. `cover_url` stays on every read; the full `photos` array is on the
detail read only, because signing a link per photo per card is work the feed
does not need.

**Duplicates.** `GET /issues/duplicates` answers "has someone already reported
this" before anything is filed. Same category only — a bin and a manhole on one
corner are two problems, and merging them would lose one. Resolved reports are
excluded, because a problem that came back is news rather than a repeat. The
`distance_m` on each candidate is what lets the sheet say "40 m away" instead of
just asserting a match. Nothing is enforced server-side: two people filing the
same pothole is a worse outcome than one person filing a real second problem, so
the check informs the composer and never blocks a write.

**What confirms a report.** Not a count of taps. A report is confirmed when
`photo_supports_to_confirm` people *other than the reporter* have supported it
**with a photo** — two, by default, because one other person standing in the
same place with a camera is corroboration in a way that a button is not. The
plain `confirmation_count` is still the "seen" tally and still shown; it just no
longer decides anything.

`confirmed_at` records the moment the bar was crossed, and it is stored rather
than derived. A derived one could not survive a withdrawal: when a photo support
is taken back the count drops, the status reverses, and `confirmed_at` clears —
so a report that loses its evidence loses its head start too. Crossing again
sets a new moment, restarting the clock.

**Contributions and the fix-date poll.** `contributions_open_at` is
`confirmed_at` plus `contributions_after_days` (5). Past that, with nothing
resolved, the report is handed back to the people who filed it and a poll opens:
which day are we going to go and fix this.

One proposal per person per report, because proposing a day is a commitment and
nobody is in two places at once. Voting is unlimited, because agreeing to turn
up on a day somebody else picked costs nothing to say and is the whole point.
Five days per report is the ceiling; past that the poll stops being a decision.

Two rules fall out of treating it as a turnout rather than a ballot. Proposing a
day that is already on the board is *agreement*, so it becomes a vote and leaves
that person's own proposal unspent. And a proposer taking their vote back
deletes the day: nobody is coming to it, including them.

Dates are compared against India time, not UTC. `REPORTING_OFFSET` exists
because checking a calendar day somebody picked against the UTC date rejects a
valid "today" for anyone choosing it after half past six in the evening.

**Raising a report with an authority.** Two swappable pieces, split because
they fail differently. A *drafter* turns a report and what people said about it
into a letter; a *channel* delivers it and can be asked about it later. With no
`ANTHROPIC_API_KEY` there is no letter and nothing happens. With no channel
configured the letter is written, stored, and readable — but nothing is claimed
to have been sent, and **the report's status does not move**. Saying a complaint
reached a municipal body when it did not is the single failure `authority.py`
exists to avoid, and `test_with_no_channel_nothing_is_claimed_to_have_been_sent`
is what holds it.

The claim comes before the model call. `escalations` has a unique constraint on
`issue_id`, so the insert is the lock: whichever run gets the row owns the
report and the other moves on. It also means a crash mid-draft costs a row
rather than a duplicate letter. A draft that comes back empty releases the claim
so a later run can retry once a key is configured.

The subject line is built in code, not by the model — every letter should look
the same to whoever receives them, and it carries the reference an official will
quote back. Only the body is written.

`check` maps whatever the channel reports onto `AUTHORITY_STATUSES`. An
authority can move a report forward; it cannot remove one, call it a duplicate,
or send it backwards. Anything else is logged and ignored.

Both jobs write a `status_changed` event, because being told your report reached
somebody is the whole reason to have filed it.

**Letters go out from fihy, not from the reporter.** They cannot go out *as*
them. A message carrying their address in `From`, sent from this server, fails
DMARC alignment and is rejected — Gmail enforces this strictly. So the letter
carries their name and fihy's domain:

```
From:     "Resident 3210 (via fihy)" <r.7f3a91c4e2b8@mail.fihy.in>
Reply-To: r.7f3a91c4e2b8@mail.fihy.in
```

Sending genuinely as them would need OAuth `gmail.send`, which is reachable —
it is a *sensitive* scope, so app verification but no security assessment. What
is not reachable is reading the reply: `gmail.readonly` is *restricted*, which
means an annual third-party assessment in the tens of thousands of dollars. So
the reply has to come back to fihy either way, which makes `Reply-To` a fihy
address regardless, which makes `From` largely cosmetic.

**No phone number leaves the system.** The letter carries the display name the
app already shows publicly. Sending a resident's contact details to a
government office is a separate thing to ask them for, and nothing has asked.
Adding it would make the complaint stronger and needs a consent flag first.

**The reply address is the correlation key.** `escalations.reply_token` is 24
random hex, unique-indexed, and it is the envelope sender as well as the
`Reply-To` — so a bounce comes back to the same place a reply does and lands on
the right report. An address survives a mail client mangling the subject or
dropping the threading headers, which `Message-ID` and the `(ref abc12345)`
subject token do not; those are kept as second and third keys.

**Replies are a push, not a poll.** `check()` on the email channel always
returns None, because an emailed complaint has no endpoint to poll. What comes
back arrives at `POST /webhooks/inbound-mail`, HMAC-signed with
`INBOUND_MAIL_SECRET` — the address is unguessable but the endpoint is not, and
without a signature anyone who learned an address could post a fake resolution
and close a real problem. Both webhooks carry `X-Fihy-Timestamp` (Unix seconds)
and `X-Fihy-Signature`, the hex HMAC-SHA256 of `<timestamp>.<raw body>`. A post
more than `WEBHOOK_TOLERANCE_SECONDS` (300) from now is refused, so a captured
one cannot be replayed later; inside the window, a reply whose `message_id` is
already on the thread is dropped, which also absorbs provider retries. `ClaudeReplyReader` turns the reply into one of
`acknowledged` / `in_progress` / `claimed` / `none`, defaulting to `none`,
because saying work is finished when the reply does not say so closes a problem
that is still there. Anything unclassifiable is still stored and still shown: a
complaint made for somebody that they cannot afterwards read is not much of a
complaint.

**A bounce is not a delay.** `POST /webhooks/mail-events` with
`delivered: false` moves the escalation to `BOUNCED` and the report back to
`community_verified`. The address is wrong; retrying will not fix it, and the
report should stop claiming to have reached anybody.

**Summaries.** `app/summarize.py` follows the `otp.set_sender` shape: an
interface, a Claude implementation, and a no-op default. With no
`ANTHROPIC_API_KEY` the field is null and the app hides the block, so a checkout
still runs with no account anywhere.

Generation happens in a `BackgroundTasks` callback, after the response has gone
out — nobody waits on a model call to publish a report, and a failure is logged
and dropped rather than failing the write. The rewrite rule is in
`summary_is_due` and balances two things: ten replies in a minute should not
mean ten model calls, but the first reply to a fresh report is the most worth
having and a plain time debounce would swallow it, because writing the summary
at report time starts the clock. So words the summary has never seen go in
immediately, and every rewrite after that waits out
`AI_SUMMARY_MIN_INTERVAL_SECONDS`. `ai_summary_voices` records how many replies
the current summary was written from, which is what tells "nothing new to say"
apart from "has not caught up yet".

**Search.** `q` matches title and description case-insensitively via `ilike`,
which SQLAlchemy renders portably on both backends. Wildcards in the query are
escaped, so searching `50%` looks for a literal percent sign rather than
matching every row — `test_wildcards_in_a_query_are_taken_literally` pins that.
Filters compose with the existing distance ordering and cursor, so a filtered
search pages exactly like an unfiltered one.

**Two cursor shapes.** Distance-ordered reads keyset on
`(squared_distance, id)`; the newest-first reads (`/me/issues`,
`/notifications`) keyset on `(created_at, id)` and use `TimeCursor`. That one
carries an ISO string rather than an epoch float, because a float cannot
round-trip microseconds at current timestamps and a page boundary that shifts
by a microsecond drops or repeats a row.

**Reputation.** `upvotes_received + posts*2 + resolutions*5`, with the weights
named in `service.py` rather than inlined. Backing someone else's report counts
once, filing one yourself counts double, and seeing one through to resolved
counts most. Comments appear in the tallies but carry no weight, so the score
cannot be farmed with chatter. Nothing is stored: every number is counted from
rows on read, so a score cannot drift from what actually happened. A removed
report stops counting immediately.

**"Resolution" is an assumption.** With no authority integration, a resolution
is defined as *an issue you reported that reached `resolved`*. Only the database
can put an issue in that state today, so the number is real but currently
unreachable in normal use. If resolutions should instead credit whoever *fixed*
the problem, that is a different model and this is the line to change.

**Issues carry their reporter.** `IssueOut.reporter` is `{id, display_name}` —
enough to credit a card and link to a profile, and deliberately not the avatar,
which would mean signing a URL for every row of every feed.

## Decisions worth knowing about

**EXIF.** Uploads are decoded, orientation is baked in, and the pixels are
copied into a fresh image before re-encoding. Copying is what makes the
guarantee absolute: no EXIF, no GPS, no maker notes, no ICC profile can survive
it. The stored "original" is stripped too — the raw upload is never persisted
anywhere. `tests/test_images.py` asserts this on a fixture that carries GPS
tags.

**Photos.** Every upload is stored twice under
`issues/{issue_id}/{photo_id}/`: `original.jpg` capped at 1920px and
`thumb.jpg` at 800px. Both objects are private. `cover_url` is a presigned GET
on the first photo's thumbnail, good for `SIGNED_URL_TTL_SECONDS` (default 10
minutes), so a URL that leaks out of a screenshot stops working on its own.

**Distance and paging.** `GET /issues/nearby` orders by an equirectangular
approximation of distance, expressed as pure arithmetic — `cos(lat)` folds into
a Python constant because the query centre is fixed for the scan. That keeps the
expression identical on SQLite and Postgres with no extensions, and it is
accurate well past the 50km radius cap. A bounding-box prefilter makes the
`(latitude, longitude)` index usable. The cursor is a base64 keyset of
`(squared_distance, id)`; the id tiebreak is what stops paging from repeating
or dropping a row when issues sit equidistant, which the equidistant-paging test
covers.

**Idempotency.** `client_report_id` is unique per reporter, so two people can
generate the same UUID without colliding. A repeat returns the original issue
untouched, even if the retry carries different fields. A concurrent retry loses
the insert race and gets the original rather than a duplicate. Photos are
validated before anything is written and uploaded after the row is claimed, so a
rejected photo leaves no issue behind and a failed upload leaves no row.

**Confirmations.** `POST`/`DELETE /issues/{id}/confirmations` still work: they
are the original contract's names for a bare support. A reporter confirming
their own issue gets a `403`; the count
is only worth reading if it is independent corroboration. Confirming twice is a
no-op that returns the current state, and so is withdrawing a confirmation that
was never made — the app retries both. The count is recomputed from the rows
rather than incremented, so it cannot drift. Reaching
`CONFIRMATIONS_TO_VERIFY` (default 3) moves `reported` to
`community_verified`, and dropping back below it reverses that. No other status
transition is automatic; the later ones need an authority integration.

**Errors.** FastAPI's default `422` body is a list of error objects, but the app
renders `detail` verbatim to a person. A handler in `main.py` flattens
validation failures into one sentence, so every error response on every path is
`{"detail": "<a sentence>"}`.

**Rate limits.** OTP requests are capped per phone and per IP per hour, and
reports and supports are capped per account per hour. All of them are counted
from rows in the database rather than an in-process counter, so the limit holds
across workers and restarts. `/auth/otp/request` answers `204` whether or not
the number is known.

The per-IP count is only as good as the address it counts. The app believes a
single header, `CLIENT_IP_HEADER`, which must be one the edge proxy overwrites:
`fly-client-ip` on Fly, `cf-connecting-ip` behind Cloudflare (and then only if
the origin cannot be reached around Cloudflare). Everything else a request
carries, `X-Forwarded-For` included, the caller could have set, so it is
ignored. Blank uses the connecting address, which is right with no proxy.

**Closing an account.** `DELETE /me` anonymises the row rather than cascading
it away, and the distinction is the whole design. A support is somebody else's
evidence: cascading this person's supports would drop the confirmation count on
reports other people filed, and could un-confirm a report that two residents
really did photograph. Deleting their reports would take the photographs and
replies other people added to them. Neither is this person's to take back.

So what goes is everything personal — the phone number, the display name, the
avatar, their notification feed, their outstanding offers to turn up somewhere,
and their rows in both OTP tables. What stays is the civic record, credited to
"Removed resident". They are also unnamed as the actor on other people's
notifications: the row belongs to the recipient, but the reference to this
person does not.

The phone becomes `deleted:<id>` rather than null, because the column is unique
and the number has to be free for a new account. Tokens outlive an account by
up to thirty days, so `deps.current_user` checks `deleted_at` on every request;
that check, not the deletion, is what ends the session.

## Not done yet

- **`locality` is always `null`.** The field is in the response and the card
  renders it, but nothing here reverse-geocodes. It needs a geocoder decision
  (a provider call at report time, or an offline ward boundary set) that is
  worth making deliberately.
- **SMS.** `otp.ConsoleOtpSender` logs the code. A provider slots in behind
  `otp.set_sender`.
- **No SMTP host and no ward addresses.** The email pipeline is built and
  tested; what it lacks is credentials and somewhere to write to. With
  `SMTP_HOST` or `AUTHORITY_EMAIL` empty, `NullMailTransport` logs the letter
  and returns nothing, which is treated as "not sent".
- **`authority_for` returns one address for everywhere.** Real routing needs
  ward boundaries, which is the same gap that leaves `locality` null.
- **No DIGIT adapter.** ~1,380 urban local bodies run DIGIT/mSeva, which has a
  real `/requests/_create`. It files under the *citizen's* identity via their
  own mobile OTP, so it needs a consent and token flow that does not exist.
  Maharashtra is not on that list, so it would not help Mumbai anyway.
- **Escalations are not exposed over the API.** A letter sent on a resident's
  behalf should be readable by them, and right now it is only in the database.
- **A reopened report is never raised again.** The unique constraint on
  `escalations.issue_id` is one per issue for all time.
- **Moderation.** There is no way to report a comment or an issue, no takedown,
  and no rate limit on writing either one. `removed` exists as a status and
  hides an issue from public reads, but nothing can set it.
- **Summaries do not look at photos.** Only the text is sent. On a civic report
  the photo is often the evidence, so this is the obvious next thing to try;
  it costs meaningfully more per call, which is why it is a decision rather
  than a default.
- **Duplicate detection is one radius and one category.** No fuzzy title match,
  no clustering of the reports it finds. Good enough to catch the same pothole;
  it will not notice that four reports along one street are one broken road. The screen is unbuilt.
