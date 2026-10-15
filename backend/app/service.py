import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .cursor import FeedCursor, NearbyCursor, TimeCursor
from .enums import CLOSED_STATUSES, HIDDEN_STATUSES, ActivityType, Category, Severity, Status
from .geo import bounding_box, distance_m, squared_distance_m
from .images import ProcessedImage
from .models import (
    ActivityEvent,
    Escalation,
    FixDate,
    FixDateVote,
    Issue,
    IssuePhoto,
    OtpChallenge,
    OtpRequestLog,
    PushToken,
    Support,
    User,
    new_id,
    utcnow,
)
from .schemas import (
    FeedPage,
    ContributionsOut,
    DuplicateOut,
    DuplicatesOut,
    FixDateOut,
    FixDatesOut,
    IssueOut,
    IssueSummary,
    NotificationOut,
    NotificationPage,
    Page,
    PhotoOut,
    ProfileOut,
    ReporterOut,
    SupportOut,
    SupportPage,
)
from .storage import ObjectStore, get_store
from .summarize import NullSummarizer, SummaryRequest, get_summarizer
from .titles import NullTitler, TitleRequest, get_titler


log = logging.getLogger(__name__)


class TooManyWrites(Exception):
    pass


class ConflictError(Exception):
    pass


class SelfConfirmation(Exception):
    pass


class EmptySupport(Exception):
    pass


class NotTheAuthor(Exception):
    pass


def _like(term: str) -> str:
    """Escape the wildcards so a query of "50% off" is not a match-anything."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _keys(issue_id: str, photo_id: str) -> tuple[str, str]:
    prefix = f"issues/{issue_id}/{photo_id}"
    return f"{prefix}/original.jpg", f"{prefix}/thumb.jpg"


async def _confirmed_issue_ids(
    session: AsyncSession, viewer: User | None, issue_ids: list[str]
) -> set[str]:
    if viewer is None or not issue_ids:
        return set()
    rows = await session.scalars(
        select(Support.issue_id).where(
            Support.user_id == viewer.id,
            Support.issue_id.in_(issue_ids),
        )
    )
    return set(rows)


# Reports are geofenced to India, so a calendar day means a day there. Checking
# a date somebody picked against the UTC date rejects a valid "today" for
# anyone choosing it after half past six in the evening.
REPORTING_OFFSET = timedelta(hours=5, minutes=30)


def local_today() -> date:
    return (utcnow() + REPORTING_OFFSET).date()


def aware(moment: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; everything stored is UTC."""
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def photo_supports_needed(issue: Issue) -> int:
    """Photo-backed supports still wanted before this counts as confirmed.

    Zero once it is confirmed, so the app can render the prompt from this
    number alone rather than knowing the threshold.
    """
    if issue.confirmed_at is not None:
        return 0
    bar = get_settings().photo_supports_to_confirm
    return max(0, bar - issue.photo_support_count)


def contributions_open_at(issue: Issue) -> datetime | None:
    """When the report is handed back to the people who filed it.

    Null until it is confirmed, because nothing is owed to a report that
    nobody else has stood in front of.
    """
    confirmed = aware(issue.confirmed_at)
    if confirmed is None:
        return None
    return confirmed + timedelta(days=get_settings().contributions_after_days)


def contributions_are_open(issue: Issue) -> bool:
    opens = contributions_open_at(issue)
    if opens is None or issue.status in CLOSED_STATUSES:
        return False
    return utcnow() >= opens


def _cover_url(issue: Issue, store: ObjectStore) -> str | None:
    if not issue.photos:
        return None
    ttl = get_settings().signed_url_ttl_seconds
    return store.signed_url(issue.photos[0].thumbnail_key, ttl)


def _person(user: User, store: ObjectStore) -> ReporterOut:
    """A credited person, with their avatar signed for this response."""
    avatar_url = (
        store.signed_url(user.avatar_key, get_settings().signed_url_ttl_seconds)
        if user.avatar_key
        else None
    )
    return ReporterOut(
        id=user.id, display_name=user.display_name, avatar_url=avatar_url
    )


def _to_out(issue: Issue, confirmed: bool, store: ObjectStore) -> IssueOut:
    return IssueOut(
        id=issue.id,
        title=issue.title,
        description=issue.description,
        category=issue.category,
        severity=issue.severity,
        status=issue.status,
        latitude=issue.latitude,
        longitude=issue.longitude,
        locality=issue.locality,
        confirmation_count=issue.confirmation_count,
        confirmed_by_me=confirmed,
        comment_count=issue.comment_count,
        photo_count=issue.photo_count,
        photo_support_count=issue.photo_support_count,
        photo_supports_needed=photo_supports_needed(issue),
        confirmed_at=issue.confirmed_at,
        contributions_open_at=contributions_open_at(issue),
        ai_summary=issue.ai_summary,
        cover_url=_cover_url(issue, store),
        reporter=_person(issue.reporter, store),
        created_at=issue.created_at,
    )


async def serialize(
    session: AsyncSession,
    issue: Issue,
    viewer: User | None,
    store: ObjectStore,
    *,
    with_photos: bool = False,
) -> IssueOut:
    confirmed = await _confirmed_issue_ids(session, viewer, [issue.id])
    out = _to_out(issue, issue.id in confirmed, store)
    if with_photos:
        out.photos = await gallery(session, issue, store)
    return out


async def get_visible_issue(session: AsyncSession, issue_id: str) -> Issue | None:
    issue = await session.get(Issue, issue_id)
    if issue is None or issue.status in HIDDEN_STATUSES:
        return None
    return issue


async def nearby(
    session: AsyncSession,
    *,
    viewer: User | None,
    store: ObjectStore,
    latitude: float,
    longitude: float,
    radius_m: float,
    category: Category | None,
    severity: Severity | None,
    status: Status | None,
    query: str | None,
    cursor: NearbyCursor | None,
    limit: int,
) -> Page:
    distance = squared_distance_m(latitude, longitude)
    min_lat, max_lat, min_lng, max_lng = bounding_box(latitude, longitude, radius_m)

    statement = select(Issue, distance.label("distance")).where(
        Issue.status.not_in(list(HIDDEN_STATUSES)),
        Issue.latitude.between(min_lat, max_lat),
        Issue.longitude.between(min_lng, max_lng),
        distance <= radius_m * radius_m,
    )
    if category is not None:
        statement = statement.where(Issue.category == category)
    if severity is not None:
        statement = statement.where(Issue.severity == severity)
    if status is not None:
        statement = statement.where(Issue.status == status)
    if query:
        pattern = _like(query.strip())
        statement = statement.where(
            or_(
                Issue.title.ilike(pattern, escape="\\"),
                Issue.description.ilike(pattern, escape="\\"),
            )
        )
    if cursor is not None:
        # Keyset on (distance, id): the id tiebreak is what keeps paging from
        # repeating or dropping a row when several issues sit equidistant.
        statement = statement.where(
            or_(
                distance > cursor.squared_distance,
                and_(
                    distance == cursor.squared_distance,
                    Issue.id > cursor.issue_id,
                ),
            )
        )
    statement = statement.order_by(distance.asc(), Issue.id.asc()).limit(limit + 1)

    rows = (await session.execute(statement)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    issues = [row[0] for row in rows]
    confirmed = await _confirmed_issue_ids(session, viewer, [i.id for i in issues])
    items = [_to_out(issue, issue.id in confirmed, store) for issue in issues]

    next_cursor = None
    if has_more and rows:
        last_issue, last_distance = rows[-1]
        next_cursor = NearbyCursor(
            squared_distance=float(last_distance), issue_id=last_issue.id
        ).encode()
    return Page(items=items, next_cursor=next_cursor)


async def _within_hour(session: AsyncSession, model, column, user_id: str) -> int:
    since = utcnow() - timedelta(hours=1)
    return await _count(
        session,
        select(func.count())
        .select_from(model)
        .where(column == user_id, model.created_at >= since),
    )


async def check_write_budget(session: AsyncSession, user: User, *, kind: str) -> None:
    """Only OTP was ever rate limited, which left somebody signed in free to
    flood the feed. Counted from the rows rather than a counter, so it holds
    across workers and restarts the way the OTP limits do."""
    settings = get_settings()
    if kind == "report":
        used = await _within_hour(session, Issue, Issue.reporter_id, user.id)
        allowed = settings.reports_per_user_per_hour
        noun = "reports"
    else:
        used = await _within_hour(session, Support, Support.user_id, user.id)
        allowed = settings.supports_per_user_per_hour
        noun = "supports"
    if used >= allowed:
        raise TooManyWrites(
            f"That is {allowed} {noun} in an hour. Give it a little while."
        )


def _feed_score(latitude: float, longitude: float, pinned: datetime):
    """How worth showing a report is, as one number.

    Three pulls, all expressed in arithmetic and CASE so the same expression
    runs on SQLite and PostgreSQL: no date functions, no least(), nothing a
    dialect has an opinion about.

    Proximity is a curve rather than a cutoff - a report 700 m away is worth
    less than one at 200 m, not worthless. Freshness is bucketed because that
    is how a person reads a feed: today, this week, or old news. Backing is
    capped because the eighth photograph does not make a report twice as worth
    seeing as the fourth.
    """
    settings = get_settings()
    scale = settings.feed_near_scale_m * settings.feed_near_scale_m
    near = scale / (scale + squared_distance_m(latitude, longitude))

    fresh = case(
        (Issue.created_at >= pinned - timedelta(days=2), 1.0),
        (Issue.created_at >= pinned - timedelta(days=7), 0.65),
        (Issue.created_at >= pinned - timedelta(days=30), 0.35),
        else_=0.15,
    )

    cap = settings.feed_backing_cap
    backed = case(
        (Issue.photo_support_count >= cap, 1.0),
        else_=Issue.photo_support_count / float(cap),
    )

    return (
        settings.feed_weight_near * near
        + settings.feed_weight_fresh * fresh
        + settings.feed_weight_backed * backed
    )


async def feed(
    session: AsyncSession,
    *,
    viewer: User | None,
    store: ObjectStore,
    latitude: float,
    longitude: float,
    cursor: FeedCursor | None,
    limit: int,
) -> FeedPage:
    """The home feed: ranked, and widened until it has something to show.

    A blank home screen is the worst thing this app can do to somebody who has
    just installed it, and the honest reason for one is almost always that they
    are standing somewhere quiet rather than that nothing is wrong anywhere. So
    the radius climbs a ladder until the page fills, and the response says how
    far it had to reach so the app can be straight about it.
    """
    settings = get_settings()
    pinned = (
        TimeCursor.parse(cursor.pinned_at) if cursor else datetime.now(timezone.utc)
    )
    score = _feed_score(latitude, longitude, pinned)
    distance = squared_distance_m(latitude, longitude)

    rungs = [r for r in settings.feed_radius_ladder_m if r <= settings.max_radius_m]
    if cursor is not None:
        # Later pages stay on the ring the first page settled on, or the feed
        # would widen mid-scroll and repeat what it had already shown.
        rungs = [cursor.radius_m]

    rows: list = []
    used = rungs[-1] if rungs else settings.default_radius_m
    # 0 is the last rung and means no distance filter at all. Somebody far from
    # anywhere anyone has reported still gets a screen with something on it,
    # and `radius_m: null` is how the app knows to say where it came from.
    for radius in [*rungs, 0.0]:
        statement = select(Issue, score.label("score")).where(
            Issue.status.not_in(list(HIDDEN_STATUSES)),
        )
        if radius:
            min_lat, max_lat, min_lng, max_lng = bounding_box(
                latitude, longitude, radius
            )
            statement = statement.where(
                Issue.latitude.between(min_lat, max_lat),
                Issue.longitude.between(min_lng, max_lng),
                distance <= radius * radius,
            )
        if cursor is not None:
            statement = statement.where(
                or_(
                    score < cursor.score,
                    and_(score == cursor.score, Issue.id > cursor.issue_id),
                )
            )
        statement = statement.order_by(score.desc(), Issue.id.asc()).limit(limit + 1)
        rows = (await session.execute(statement)).all()
        used = radius
        # limit + 1 is fetched to detect a next page, so enough to fill this
        # one is len >= limit. Requiring more than that would widen past a
        # ring that was already exactly full.
        if len(rows) >= limit:
            break

    has_more = len(rows) > limit
    rows = rows[:limit]

    issues = [row[0] for row in rows]
    confirmed = await _confirmed_issue_ids(session, viewer, [i.id for i in issues])
    items = [_to_out(issue, issue.id in confirmed, store) for issue in issues]

    next_cursor = None
    if has_more and rows:
        last_issue, last_score = rows[-1]
        next_cursor = FeedCursor(
            score=float(last_score),
            issue_id=last_issue.id,
            pinned_at=TimeCursor.moment(pinned),
            radius_m=used,
        ).encode()

    return FeedPage(
        items=items,
        next_cursor=next_cursor,
        radius_m=used or None,
        widened=used == 0.0 or used > settings.feed_radius_ladder_m[0],
    )


async def create_issue(
    session: AsyncSession,
    *,
    reporter: User,
    store: ObjectStore,
    client_report_id: str,
    title: str,
    description: str,
    category: Category,
    severity: Severity,
    latitude: float,
    longitude: float,
    photos: list[ProcessedImage],
    locality: str | None = None,
) -> tuple[Issue, bool]:
    """Returns the issue and whether it was created by this call."""
    existing = await session.scalar(
        select(Issue).where(
            Issue.reporter_id == reporter.id,
            Issue.client_report_id == client_report_id,
        )
    )
    if existing is not None:
        return existing, False

    issue = Issue(
        id=new_id(),
        reporter_id=reporter.id,
        client_report_id=client_report_id,
        title=title,
        description=description,
        category=category,
        severity=severity,
        status=Status.REPORTED,
        latitude=latitude,
        longitude=longitude,
        locality=None,
        confirmation_count=0,
        comment_count=0,
        photo_count=len(photos),
        photo_support_count=0,
    )
    uploads: list[tuple[str, bytes]] = []
    for position, processed in enumerate(photos):
        photo_id = new_id()
        original_key, thumbnail_key = _keys(issue.id, photo_id)
        issue.photos.append(
            IssuePhoto(
                id=photo_id,
                contributor_id=reporter.id,
                position=position,
                original_key=original_key,
                thumbnail_key=thumbnail_key,
            )
        )
        uploads.append((original_key, processed.original))
        uploads.append((thumbnail_key, processed.thumbnail))

    session.add(issue)
    try:
        await session.flush()
    except IntegrityError:
        # A queued draft retried concurrently. The first writer wins and the
        # client gets the original issue, never a duplicate.
        await session.rollback()
        original = await session.scalar(
            select(Issue).where(
                Issue.reporter_id == reporter.id,
                Issue.client_report_id == client_report_id,
            )
        )
        if original is None:
            raise ConflictError("That report could not be saved. Try again.")
        return original, False

    try:
        for key, payload in uploads:
            await store.put_jpeg(key, payload)
    except Exception:
        await session.rollback()
        await store.delete([key for key, _ in uploads])
        raise

    await session.commit()
    await session.refresh(issue)
    return issue, True


async def _recount(session: AsyncSession, issue: Issue) -> None:
    """Every tally is derived from rows, so none of them can drift.

    A support from the reporter does not corroborate anything, so it is left
    out of confirmation_count while still being readable in the thread.
    """
    issue.confirmation_count = await _count(
        session,
        select(func.count())
        .select_from(Support)
        .where(Support.issue_id == issue.id, Support.user_id != issue.reporter_id),
    )
    # Anything a person actually put into the report: words, photos, or both.
    # A photo-only support is the strongest kind there is, so counting only the
    # ones carrying text would leave the best evidence out of the tally.
    carried_a_photo = (
        select(IssuePhoto.id).where(IssuePhoto.support_id == Support.id).exists()
    )
    issue.comment_count = await _count(
        session,
        select(func.count())
        .select_from(Support)
        .where(
            Support.issue_id == issue.id,
            or_(
                and_(Support.body.is_not(None), Support.body != ""),
                carried_a_photo,
            ),
        ),
    )
    issue.photo_count = await _count(
        session,
        select(func.count())
        .select_from(IssuePhoto)
        .where(IssuePhoto.issue_id == issue.id),
    )
    issue.photo_support_count = await _count(
        session,
        select(func.count())
        .select_from(Support)
        .where(
            Support.issue_id == issue.id,
            Support.user_id != issue.reporter_id,
            carried_a_photo,
        ),
    )

    threshold = get_settings().photo_supports_to_confirm
    confirmed = issue.photo_support_count >= threshold
    was = issue.status
    if confirmed and issue.status == Status.REPORTED:
        issue.status = Status.COMMUNITY_VERIFIED
    elif not confirmed and issue.status == Status.COMMUNITY_VERIFIED:
        issue.status = Status.REPORTED

    # The clock starts when the bar is crossed and restarts if it is crossed
    # again, so a report that loses its evidence loses its head start too.
    if confirmed and issue.confirmed_at is None:
        issue.confirmed_at = utcnow()
    elif not confirmed:
        issue.confirmed_at = None
    if issue.status != was:
        # No actor: the crowd moved it, not any one person.
        session.add(
            ActivityEvent(
                user_id=issue.reporter_id,
                issue_id=issue.id,
                type=ActivityType.STATUS_CHANGED,
                from_status=was,
                to_status=issue.status,
            )
        )


def _photo_out(photo: IssuePhoto, store: ObjectStore) -> PhotoOut:
    ttl = get_settings().signed_url_ttl_seconds
    return PhotoOut(
        id=photo.id,
        url=store.signed_url(photo.original_key, ttl),
        thumbnail_url=store.signed_url(photo.thumbnail_key, ttl),
        contributor=_person(photo.contributor, store),
        from_report=photo.support_id is None,
        created_at=photo.created_at,
    )


def _support_out(
    support: Support, issue: Issue, viewer: User | None, store: ObjectStore
) -> SupportOut:
    return SupportOut(
        id=support.id,
        body=support.body,
        photos=[_photo_out(photo, store) for photo in support.photos],
        author=_person(support.user, store),
        author_is_reporter=support.user_id == issue.reporter_id,
        mine=viewer is not None and support.user_id == viewer.id,
        created_at=support.created_at,
    )


async def gallery(
    session: AsyncSession, issue: Issue, store: ObjectStore
) -> list[PhotoOut]:
    """Every photo on the issue, oldest first: the original report leads and
    later contributions follow it, which is the order they were taken in."""
    photos = await session.scalars(
        select(IssuePhoto)
        .where(IssuePhoto.issue_id == issue.id)
        .order_by(IssuePhoto.created_at.asc(), IssuePhoto.position.asc())
    )
    return [_photo_out(photo, store) for photo in photos]


async def _attach_photos(
    issue: Issue,
    contributor: User,
    support: Support | None,
    photos: list[ProcessedImage],
    store: ObjectStore,
    start_position: int,
) -> list[tuple[str, bytes]]:
    uploads: list[tuple[str, bytes]] = []
    for offset, processed in enumerate(photos):
        photo_id = new_id()
        original_key, thumbnail_key = _keys(issue.id, photo_id)
        issue.photos.append(
            IssuePhoto(
                id=photo_id,
                contributor_id=contributor.id,
                support_id=support.id if support else None,
                position=start_position + offset,
                original_key=original_key,
                thumbnail_key=thumbnail_key,
            )
        )
        uploads.append((original_key, processed.original))
        uploads.append((thumbnail_key, processed.thumbnail))
    return uploads


async def add_support(
    session: AsyncSession,
    *,
    issue: Issue,
    user: User,
    store: ObjectStore,
    body: str | None,
    photos: list[ProcessedImage],
) -> Issue:
    """Back an issue, optionally with words and photos.

    Supporting twice is not an error: the second call updates the row and adds
    to it, which is what a person adding a photo to something they already
    backed expects.
    """
    is_reporter = issue.reporter_id == user.id
    if is_reporter and not body and not photos:
        # The old rule, kept: a bare +1 on your own report corroborates
        # nothing. Adding words or a photo to it is a different act, and fine.
        raise SelfConfirmation(
            "You reported this, so you cannot confirm it. Confirmations count "
            "because they come from someone else."
        )

    support = await session.scalar(
        select(Support).where(
            Support.issue_id == issue.id, Support.user_id == user.id
        )
    )
    first_time = support is None
    if support is None:
        support = Support(issue_id=issue.id, user_id=user.id, body=body or None)
        session.add(support)
        try:
            await session.flush()
        except IntegrityError:
            # Two taps racing. The first wins and the second reads it back.
            await session.rollback()
            support = await session.scalar(
                select(Support).where(
                    Support.issue_id == issue.id, Support.user_id == user.id
                )
            )
            if support is None:
                raise ConflictError("That could not be saved. Try again.") from None
            first_time = False
    if body:
        support.body = body

    uploads: list[tuple[str, bytes]] = []
    if photos:
        # Counted rather than read off support.photos: on a row that was just
        # added the collection is not loaded, and touching it would lazy-load
        # inside the async session.
        already = await _count(
            session,
            select(func.count())
            .select_from(IssuePhoto)
            .where(IssuePhoto.support_id == support.id),
        )
        uploads = await _attach_photos(
            issue, user, support, photos, store, already
        )
    await session.flush()

    if first_time and not is_reporter:
        session.add(
            ActivityEvent(
                user_id=issue.reporter_id,
                issue_id=issue.id,
                actor_id=user.id,
                type=ActivityType.SUPPORT_RECEIVED,
            )
        )

    try:
        for key, payload in uploads:
            await store.put_jpeg(key, payload)
    except Exception:
        await session.rollback()
        await store.delete([key for key, _ in uploads])
        raise

    await _recount(session, issue)
    await session.commit()
    await session.refresh(issue)
    return issue


async def remove_support(
    session: AsyncSession, issue: Issue, user: User, store: ObjectStore
) -> Issue:
    """Withdrawing takes the photos that came with it. They were offered as
    part of backing the report, so they leave with the backing."""
    support = await session.scalar(
        select(Support).where(
            Support.issue_id == issue.id, Support.user_id == user.id
        )
    )
    if support is not None:
        keys = [
            key
            for photo in support.photos
            for key in (photo.original_key, photo.thumbnail_key)
        ]
        await session.delete(support)
        await session.flush()
        await _recount(session, issue)
        await session.commit()
        if keys:
            await store.delete(keys)
    await session.refresh(issue)
    return issue


async def supports(
    session: AsyncSession,
    *,
    issue: Issue,
    viewer: User | None,
    store: ObjectStore,
    cursor: TimeCursor | None,
    limit: int,
) -> SupportPage:
    """Newest first, like every other paged read here."""
    statement = select(Support).where(Support.issue_id == issue.id)
    if cursor is not None:
        moment = TimeCursor.parse(cursor.created_at)
        statement = statement.where(
            or_(
                Support.created_at < moment,
                and_(Support.created_at == moment, Support.id < cursor.row_id),
            )
        )
    statement = statement.order_by(
        Support.created_at.desc(), Support.id.desc()
    ).limit(limit + 1)

    rows = list((await session.scalars(statement)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = TimeCursor(
            created_at=TimeCursor.moment(last.created_at), row_id=last.id
        ).encode()

    total = await _count(
        session,
        select(func.count()).select_from(Support).where(Support.issue_id == issue.id),
    )
    return SupportPage(
        items=[_support_out(row, issue, viewer, store) for row in rows],
        next_cursor=next_cursor,
        total=total,
    )


async def duplicates(
    session: AsyncSession,
    *,
    viewer: User | None,
    store: ObjectStore,
    latitude: float,
    longitude: float,
    category: Category | None,
    radius_m: float,
) -> DuplicatesOut:
    """Reports close enough that a new one is probably the same thing.

    Same category only: a pothole and an overflowing bin on the same corner are
    two problems, and merging them would lose one. Resolved reports are left
    out, because a problem that came back is news rather than a duplicate.
    """
    min_lat, max_lat, min_lng, max_lng = bounding_box(latitude, longitude, radius_m)
    distance = squared_distance_m(latitude, longitude)

    statement = select(Issue).where(
        Issue.status.not_in([*HIDDEN_STATUSES, Status.RESOLVED]),
        Issue.latitude.between(min_lat, max_lat),
        Issue.longitude.between(min_lng, max_lng),
        distance <= radius_m * radius_m,
    )
    if category is not None:
        statement = statement.where(Issue.category == category)
    statement = statement.order_by(distance.asc(), Issue.id.asc()).limit(10)

    issues = list((await session.scalars(statement)).all())
    confirmed = await _confirmed_issue_ids(session, viewer, [i.id for i in issues])
    return DuplicatesOut(
        items=[
            DuplicateOut(
                issue=_to_out(issue, issue.id in confirmed, store),
                distance_m=round(
                    distance_m(latitude, longitude, issue.latitude, issue.longitude), 1
                ),
            )
            for issue in issues
        ],
        radius_m=radius_m,
    )


async def set_display_name(
    session: AsyncSession, *, user: User, display_name: str
) -> User:
    user.display_name = display_name.strip()
    await session.commit()
    return user


async def set_avatar(
    session: AsyncSession, *, user: User, store: ObjectStore, image: ProcessedImage
) -> User:
    """Stores the derived thumbnail only.

    An avatar is never shown large, so keeping the full-size original would be
    holding a face at higher resolution than anything asks for. The upload has
    already been stripped of EXIF by the same pipeline reports go through.
    """
    previous = user.avatar_key
    key = f"avatars/{user.id}/{new_id()}.jpg"
    await store.put_jpeg(key, image.thumbnail)
    user.avatar_key = key
    await session.commit()
    if previous and previous != key:
        await store.delete([previous])
    return user


async def clear_avatar(
    session: AsyncSession, *, user: User, store: ObjectStore
) -> User:
    previous = user.avatar_key
    user.avatar_key = None
    await session.commit()
    if previous:
        await store.delete([previous])
    return user


async def escalation_for(session: AsyncSession, issue: Issue) -> Escalation | None:
    return await session.scalar(
        select(Escalation).where(Escalation.issue_id == issue.id)
    )


async def user_issues(
    session: AsyncSession,
    *,
    reporter_id: str,
    viewer: User | None,
    store: ObjectStore,
    cursor: TimeCursor | None,
    limit: int,
    include_hidden: bool,
    status: Status | None = None,
) -> Page:
    """One person's reports, newest first.

    include_hidden is for the author looking at their own: a removed report is
    hidden from everyone else, but the person who filed it should still see
    what became of it.
    """
    statement = select(Issue).where(Issue.reporter_id == reporter_id)
    if not include_hidden:
        statement = statement.where(Issue.status.not_in(list(HIDDEN_STATUSES)))
    if status is not None:
        statement = statement.where(Issue.status == status)
    if cursor is not None:
        moment = TimeCursor.parse(cursor.created_at)
        statement = statement.where(
            or_(
                Issue.created_at < moment,
                and_(Issue.created_at == moment, Issue.id < cursor.row_id),
            )
        )
    statement = statement.order_by(
        Issue.created_at.desc(), Issue.id.desc()
    ).limit(limit + 1)

    issues = list((await session.scalars(statement)).all())
    has_more = len(issues) > limit
    issues = issues[:limit]

    confirmed = await _confirmed_issue_ids(session, viewer, [i.id for i in issues])
    items = [_to_out(issue, issue.id in confirmed, store) for issue in issues]

    next_cursor = None
    if has_more and issues:
        last = issues[-1]
        next_cursor = TimeCursor(
            created_at=TimeCursor.moment(last.created_at), row_id=last.id
        ).encode()
    return Page(items=items, next_cursor=next_cursor)


async def refresh_summary(issue_id: str) -> None:
    """Rewrite an issue's summary from its report and its replies.

    Runs after the response has gone out, so a person publishing a report or a
    reply never waits on a model call. Anything that goes wrong here is logged
    and dropped: a missing summary is a blank block in the UI, not a failure of
    the thing the user actually asked for.
    """
    from .db import sessionmaker

    summarizer = get_summarizer()
    if isinstance(summarizer, NullSummarizer):
        return

    try:
        async with sessionmaker()() as session:
            issue = await session.get(Issue, issue_id)
            if issue is None or issue.status in HIDDEN_STATUSES:
                return
            bodies = await session.scalars(
                select(Support.body)
                .where(
                    Support.issue_id == issue.id,
                    Support.body.is_not(None),
                    Support.body != "",
                )
                .order_by(Support.created_at.asc())
                .limit(50)
            )
            voices = list(bodies)
            summary = await summarizer.summarize(
                SummaryRequest(
                    title=issue.title,
                    description=issue.description,
                    category=issue.category.value,
                    severity=issue.severity.value,
                    status=issue.status.value,
                    locality=issue.locality,
                    voices=voices,
                )
            )
            if summary is None:
                return
            issue.ai_summary = summary
            issue.ai_summary_at = utcnow()
            issue.ai_summary_voices = issue.comment_count
            await session.commit()
    except Exception:
        log.exception("could not summarize issue %s", issue_id)


def title_is_derived(title: str, description: str) -> bool:
    """Whether the title is just the caption clipped to fit, which is what the
    app sends. A title somebody wrote on its own is theirs and is left alone."""
    stem = title.strip().removesuffix("…").rstrip()
    return bool(stem) and description.strip().startswith(stem)


async def refresh_title(issue_id: str) -> None:
    """Replace a clipped-caption title with a written headline.

    Runs after the response, like the summary. It only swaps a title that is
    still the one the report was filed with, so nothing a person changed in the
    meantime is overwritten, and any failure leaves the clipped caption.
    """
    from .db import sessionmaker

    titler = get_titler()
    if isinstance(titler, NullTitler):
        return

    try:
        async with sessionmaker()() as session:
            issue = await session.get(Issue, issue_id)
            if issue is None or issue.status in HIDDEN_STATUSES:
                return
            original = issue.title
            title = await titler.title(
                TitleRequest(
                    description=issue.description,
                    category=issue.category.value,
                    locality=issue.locality,
                )
            )
            if title is None or title == original:
                return
            await session.refresh(issue)
            if issue.title != original:
                return
            issue.title = title
            await session.commit()
    except Exception:
        log.exception("could not write a title for issue %s", issue_id)


def summary_is_due(issue: Issue) -> bool:
    """Whether the summary is worth rewriting right now.

    Two things are being balanced. A report that ten people reply to within a
    minute should not be summarized ten times to say nearly the same thing. But
    the first reply to a fresh report is the most worth having, and a plain
    time debounce would swallow it, because writing the summary at report time
    starts the clock.

    So: new words that the summary has never seen go in immediately, and every
    rewrite after that waits out the interval.
    """
    if not get_settings().ai_summary_configured:
        return False
    if issue.ai_summary_at is None:
        return True
    if issue.comment_count <= issue.ai_summary_voices:
        return False
    if issue.ai_summary_voices == 0:
        return True
    written = issue.ai_summary_at
    if written.tzinfo is None:
        written = written.replace(tzinfo=timezone.utc)
    interval = get_settings().ai_summary_min_interval_seconds
    return (utcnow() - written).total_seconds() >= interval


class PollClosed(Exception):
    pass


class PollFull(Exception):
    pass


class AlreadyProposed(Exception):
    pass


# Enough to fill a list and a face stack. vote_count stays the truth.
GOING_SHOWN = 24


def _fix_date_out(
    row: FixDate, voted: set[str], viewer: User | None, store: ObjectStore
) -> FixDateOut:
    return FixDateOut(
        id=row.id,
        fix_on=row.fix_on,
        fix_time=row.fix_time,
        vote_count=row.vote_count,
        going=[
            _person(v.voter, store)
            for v in sorted(row.votes, key=lambda v: v.created_at, reverse=True)[
                :GOING_SHOWN
            ]
        ],
        voted_by_me=row.id in voted,
        proposed_by=_person(row.creator, store),
        mine=viewer is not None and row.created_by == viewer.id,
    )


async def _recount_votes(session: AsyncSession, row: FixDate) -> None:
    row.vote_count = await _count(
        session,
        select(func.count())
        .select_from(FixDateVote)
        .where(FixDateVote.fix_date_id == row.id),
    )


async def fix_dates(
    session: AsyncSession,
    *,
    issue: Issue,
    viewer: User | None,
    store: ObjectStore | None = None,
) -> FixDatesOut:
    """The poll. Readable before it opens so people can see what is coming."""
    rows = list(
        (
            await session.scalars(
                select(FixDate)
                .where(FixDate.issue_id == issue.id)
                .order_by(FixDate.fix_on.asc())
            )
        ).all()
    )
    voted: set[str] = set()
    if viewer is not None:
        voted = set(
            (
                await session.scalars(
                    select(FixDateVote.fix_date_id).where(
                        FixDateVote.issue_id == issue.id,
                        FixDateVote.user_id == viewer.id,
                    )
                )
            ).all()
        )
    settings = get_settings()
    return FixDatesOut(
        items=[_fix_date_out(row, voted, viewer, store or get_store()) for row in rows],
        open=contributions_are_open(issue),
        opens_at=contributions_open_at(issue),
        proposed_by_me=viewer is not None
        and any(row.created_by == viewer.id for row in rows),
        remaining_slots=max(0, settings.max_fix_dates_per_issue - len(rows)),
    )


async def propose_fix_date(
    session: AsyncSession,
    *,
    issue: Issue,
    user: User,
    fix_on: date,
    fix_time: time | None = None,
) -> FixDatesOut:
    """Offer a day.

    Somebody proposing a day that is already on the board is agreeing with it,
    not colliding with it, so that becomes a vote. It leaves their one proposal
    unspent, which is right: they have not put a new option up.
    """
    if not contributions_are_open(issue):
        raise PollClosed(
            "Contributions are not open on this report yet."
        )
    if fix_on < local_today():
        raise PollClosed("Pick a day that has not already gone.")

    existing = await session.scalar(
        select(FixDate).where(
            FixDate.issue_id == issue.id, FixDate.fix_on == fix_on
        )
    )
    if existing is not None:
        await _vote(session, existing, user)
        await session.commit()
        return await fix_dates(session, issue=issue, viewer=user)

    settings = get_settings()
    rows = await _count(
        session,
        select(func.count()).select_from(FixDate).where(FixDate.issue_id == issue.id),
    )
    if rows >= settings.max_fix_dates_per_issue:
        raise PollFull(
            f"There are already {settings.max_fix_dates_per_issue} days on this "
            "report. Back one of them instead."
        )
    mine = await session.scalar(
        select(FixDate).where(
            FixDate.issue_id == issue.id, FixDate.created_by == user.id
        )
    )
    if mine is not None:
        raise AlreadyProposed(
            "You have already put a day forward. You can back any of the "
            "others, or withdraw yours first."
        )

    row = FixDate(
        issue_id=issue.id, created_by=user.id, fix_on=fix_on, fix_time=fix_time
    )
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return await fix_dates(session, issue=issue, viewer=user)
    # Proposing a day is saying you will be there, so it counts as a vote.
    await _vote(session, row, user)
    await session.commit()
    return await fix_dates(session, issue=issue, viewer=user)


async def _vote(session: AsyncSession, row: FixDate, user: User) -> None:
    already = await session.scalar(
        select(FixDateVote).where(
            FixDateVote.fix_date_id == row.id, FixDateVote.user_id == user.id
        )
    )
    if already is None:
        session.add(
            FixDateVote(fix_date_id=row.id, issue_id=row.issue_id, user_id=user.id)
        )
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
    await _recount_votes(session, row)


async def vote_fix_date(
    session: AsyncSession, *, issue: Issue, user: User, fix_date_id: str, on: bool
) -> FixDatesOut | None:
    """Backing a day costs nothing to say, so there is no limit on how many."""
    if not contributions_are_open(issue):
        raise PollClosed("Contributions are not open on this report yet.")
    row = await session.get(FixDate, fix_date_id)
    if row is None or row.issue_id != issue.id:
        return None
    if on:
        await _vote(session, row, user)
    elif row.created_by == user.id:
        # A day nobody is coming to is noise on the board, and the person who
        # put it up has just said they are not coming either. Deleting the row
        # takes its votes with it, so the vote is not removed separately.
        await session.delete(row)
        await session.flush()
    else:
        await session.execute(
            delete(FixDateVote).where(
                FixDateVote.fix_date_id == row.id, FixDateVote.user_id == user.id
            )
        )
        await session.flush()
        await _recount_votes(session, row)
    await session.commit()
    return await fix_dates(session, issue=issue, viewer=user)


DELETED_NAME = "Former hooman"


async def delete_account(
    session: AsyncSession, *, user: User, store: ObjectStore
) -> None:
    """Close an account and destroy what identifies the person.

    Anonymised in place rather than cascaded away, and the distinction matters.
    A support is somebody else's evidence: cascading this person's supports
    would drop the confirmation count on reports other people filed, and could
    un-confirm a report that two people really did photograph. Deleting their
    reports would take the photographs and replies other residents added to
    them. Neither is this person's to take back.

    So what goes is everything personal: the phone number, the name, the
    avatar, their notification feed, and their outstanding offers to turn up
    somewhere. What stays is the civic record, credited to nobody.
    """
    if user.avatar_key:
        await store.delete([user.avatar_key])

    # Offers to be somewhere on a day. They are not coming; deleting the row
    # takes its votes with it.
    for row in (
        await session.scalars(select(FixDate).where(FixDate.created_by == user.id))
    ).all():
        await session.delete(row)
    await session.execute(delete(FixDateVote).where(FixDateVote.user_id == user.id))

    # Their own feed, and any event naming them as the actor in somebody
    # else's. The second is why this is not just a cascade: the row belongs to
    # the recipient, but the actor reference is personal data.
    await session.execute(delete(ActivityEvent).where(ActivityEvent.user_id == user.id))
    await session.execute(
        update(ActivityEvent)
        .where(ActivityEvent.actor_id == user.id)
        .values(actor_id=None)
    )

    await session.execute(delete(PushToken).where(PushToken.user_id == user.id))
    await session.execute(delete(OtpChallenge).where(OtpChallenge.phone == user.phone))
    await session.execute(delete(OtpRequestLog).where(OtpRequestLog.phone == user.phone))

    # Null rather than a tombstone: the unique index permits many nulls, so the
    # number is free for a new account, and nothing is left that looks like one.
    # Sign-in matches on equality, which a null never satisfies.
    user.phone = None
    user.display_name = DELETED_NAME
    user.avatar_key = None
    user.deleted_at = utcnow()
    await session.flush()

    # Counts derived from supports do not change - the supports stayed - but a
    # fix-date poll that lost a day needs recomputing.
    touched = (
        await session.scalars(
            select(Issue)
            .join(Support, Support.issue_id == Issue.id)
            .where(Support.user_id == user.id)
        )
    ).all()
    for issue in touched:
        await _recount(session, issue)
    await session.commit()


async def my_issues(
    session: AsyncSession,
    *,
    reporter: User,
    store: ObjectStore,
    cursor: TimeCursor | None,
    limit: int,
) -> Page:
    return await user_issues(
        session,
        reporter_id=reporter.id,
        viewer=reporter,
        store=store,
        cursor=cursor,
        limit=limit,
        include_hidden=True,
    )


async def user_supports(
    session: AsyncSession,
    *,
    user_id: str,
    viewer: User | None,
    store: ObjectStore,
    cursor: TimeCursor | None,
    limit: int,
) -> Page:
    """Issues this person corroborated, most recently supported first.

    Ordered by when they supported it rather than when the issue was filed, so
    the tab reads as their activity. Hidden issues drop out even though the
    support row survives, and a reporter's support of their own report is not
    corroboration so it never appears here.
    """
    statement = (
        select(Issue, Support.created_at, Support.id)
        .join(Support, Support.issue_id == Issue.id)
        .where(
            Support.user_id == user_id,
            Support.user_id != Issue.reporter_id,
            Issue.status.not_in(list(HIDDEN_STATUSES)),
        )
    )
    if cursor is not None:
        moment = TimeCursor.parse(cursor.created_at)
        statement = statement.where(
            or_(
                Support.created_at < moment,
                and_(
                    Support.created_at == moment,
                    Support.id < cursor.row_id,
                ),
            )
        )
    statement = statement.order_by(
        Support.created_at.desc(), Support.id.desc()
    ).limit(limit + 1)

    rows = (await session.execute(statement)).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    issues = [row[0] for row in rows]
    confirmed = await _confirmed_issue_ids(session, viewer, [i.id for i in issues])
    items = [_to_out(issue, issue.id in confirmed, store) for issue in issues]

    next_cursor = None
    if has_more and rows:
        _, supported_at, support_id = rows[-1]
        next_cursor = TimeCursor(
            created_at=TimeCursor.moment(supported_at), row_id=support_id
        ).encode()
    return Page(items=items, next_cursor=next_cursor)


async def _count(session: AsyncSession, statement) -> int:
    return int(await session.scalar(statement) or 0)


# Reputation weights. Backing someone else's report counts once; filing one
# yourself counts double; seeing one through to resolved counts most.
UPVOTE_POINTS = 1
POST_POINTS = 2
RESOLUTION_POINTS = 5


def reputation(contributions: ContributionsOut) -> int:
    return (
        contributions.upvotes_received * UPVOTE_POINTS
        + contributions.posts * POST_POINTS
        + contributions.resolutions * RESOLUTION_POINTS
    )


async def profile(
    session: AsyncSession, *, user: User, store: ObjectStore
) -> ProfileOut:
    """Public profile and the tallies behind the reputation score.

    Every number is counted from rows rather than stored, so none of them can
    drift out of step with what actually happened.
    """
    visible_issues = select(Issue.id).where(
        Issue.reporter_id == user.id,
        Issue.status.not_in(list(HIDDEN_STATUSES)),
    )

    posts = await _count(
        session, select(func.count()).select_from(visible_issues.subquery())
    )
    upvotes_received = await _count(
        session,
        select(func.count())
        .select_from(Support)
        .where(
            Support.issue_id.in_(visible_issues),
            Support.user_id != user.id,
        ),
    )
    supports_given = await _count(
        session,
        select(func.count())
        .select_from(Support)
        .where(Support.user_id == user.id),
    )
    comments_written = await _count(
        session,
        select(func.count())
        .select_from(Support)
        .where(
            Support.user_id == user.id,
            Support.body.is_not(None),
            Support.body != "",
        ),
    )
    resolutions = await _count(
        session,
        select(func.count())
        .select_from(Issue)
        .where(Issue.reporter_id == user.id, Issue.status == Status.RESOLVED),
    )

    contributions = ContributionsOut(
        posts=posts,
        upvotes_received=upvotes_received,
        supports_given=supports_given,
        comments_written=comments_written,
        resolutions=resolutions,
    )
    avatar_url = (
        store.signed_url(user.avatar_key, get_settings().signed_url_ttl_seconds)
        if user.avatar_key
        else None
    )
    return ProfileOut(
        id=user.id,
        display_name=user.display_name,
        avatar_url=avatar_url,
        reputation=reputation(contributions),
        contributions=contributions,
        joined_at=user.created_at,
    )


def _summarize(issue: Issue, store: ObjectStore) -> IssueSummary:
    return IssueSummary(
        id=issue.id,
        title=issue.title,
        category=issue.category,
        severity=issue.severity,
        status=issue.status,
        cover_url=_cover_url(issue, store),
        confirmation_count=issue.confirmation_count,
    )


async def unread_count(session: AsyncSession, user: User) -> int:
    total = await session.scalar(
        select(func.count())
        .select_from(ActivityEvent)
        .where(ActivityEvent.user_id == user.id, ActivityEvent.read_at.is_(None))
    )
    return int(total or 0)


async def notifications(
    session: AsyncSession,
    *,
    user: User,
    store: ObjectStore,
    cursor: TimeCursor | None,
    limit: int,
) -> NotificationPage:
    statement = select(ActivityEvent).where(ActivityEvent.user_id == user.id)
    if cursor is not None:
        moment = TimeCursor.parse(cursor.created_at)
        statement = statement.where(
            or_(
                ActivityEvent.created_at < moment,
                and_(
                    ActivityEvent.created_at == moment,
                    ActivityEvent.id < cursor.row_id,
                ),
            )
        )
    statement = statement.order_by(
        ActivityEvent.created_at.desc(), ActivityEvent.id.desc()
    ).limit(limit + 1)

    events = list((await session.scalars(statement)).all())
    has_more = len(events) > limit
    events = events[:limit]

    items = [
        NotificationOut(
            id=event.id,
            type=event.type,
            read=event.read_at is not None,
            actor_name=event.actor.display_name if event.actor else None,
            from_status=event.from_status,
            to_status=event.to_status,
            issue=_summarize(event.issue, store),
            created_at=event.created_at,
        )
        for event in events
    ]

    next_cursor = None
    if has_more and events:
        last = events[-1]
        next_cursor = TimeCursor(
            created_at=TimeCursor.moment(last.created_at), row_id=last.id
        ).encode()

    return NotificationPage(
        items=items,
        next_cursor=next_cursor,
        unread_count=await unread_count(session, user),
    )


async def mark_read(
    session: AsyncSession, user: User, ids: list[str] | None
) -> int:
    """Marks the given events read, or the whole feed when ids is None."""
    statement = (
        update(ActivityEvent)
        .where(ActivityEvent.user_id == user.id, ActivityEvent.read_at.is_(None))
        .values(read_at=utcnow())
    )
    if ids is not None:
        if not ids:
            return await unread_count(session, user)
        statement = statement.where(ActivityEvent.id.in_(ids))
    await session.execute(statement)
    await session.commit()
    return await unread_count(session, user)
