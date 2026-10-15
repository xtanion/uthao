from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy import and_, case, func, literal, select, true, union, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from .authority import authority_row_for
from .config import get_settings
from .enums import HIDDEN_STATUSES, IN_FLIGHT_STATUSES, ActivityType, MessageDirection, Status
from .models import (
    ActivityEvent,
    Authority,
    Escalation,
    EscalationMessage,
    Issue,
    IssuePhoto,
    Support,
    User,
    utcnow,
)
from .schemas import (
    ContributionsOut,
    StatsArea,
    StatsCategory,
    StatsContributor,
    StatsContributorsOut,
    StatsOut,
    StatsPoint,
    StatsTotals,
    StatsWeek,
)
from .service import REPORTING_OFFSET, aware, local_today, reputation
from .storage import ObjectStore

WEEKS = 12
TOP_CONTRIBUTORS = 5
POINTS_PER_KIND = 300

# A duplicate's evidence lives on the report it duplicates, so counting both
# would count one pothole twice.
UNCOUNTED = frozenset({*HIDDEN_STATUSES, Status.DUPLICATE})

RAISED = frozenset({*IN_FLIGHT_STATUSES, Status.RESOLVED, Status.REOPENED})
CONFIRMED = frozenset({*RAISED, Status.COMMUNITY_VERIFIED})


@dataclass(frozen=True)
class Area:
    """One authority's box, or everywhere when there are no authorities."""

    authority: Authority | None = None

    def out(self) -> StatsArea | None:
        row = self.authority
        if row is None:
            return None
        return StatsArea(
            slug=row.slug,
            city=row.city,
            min_latitude=row.min_latitude,
            max_latitude=row.max_latitude,
            min_longitude=row.min_longitude,
            max_longitude=row.max_longitude,
        )

    def contains(self):
        return true() if self.authority is None else _in_box(self.authority)


class UnknownArea(Exception):
    pass


def _in_box(row: Authority | type[Authority]):
    return and_(
        Issue.latitude.between(row.min_latitude, row.max_latitude),
        Issue.longitude.between(row.min_longitude, row.max_longitude),
    )


async def areas(session: AsyncSession) -> list[tuple[Authority, int]]:
    """Cities with at least one counted report, busiest first."""
    reports = func.count(Issue.id)
    rows = await session.execute(
        select(Authority, reports)
        .join(Issue, and_(Issue.status.not_in(list(UNCOUNTED)), _in_box(Authority)))
        .where(Authority.active.is_(True))
        .group_by(Authority.id)
    )
    tallies = [(row, int(count)) for row, count in rows.all()]
    return sorted(tallies, key=lambda pair: (-pair[1], pair[0].city))


async def area_for(
    session: AsyncSession,
    *,
    slug: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Area:
    """A chosen city, else the viewer's own, else the busiest one."""
    if slug:
        row = await session.scalar(
            select(Authority).where(Authority.slug == slug, Authority.active.is_(True))
        )
        if row is None:
            raise UnknownArea(slug)
        return Area(row)
    if latitude is not None and longitude is not None:
        row = await authority_row_for(session, latitude, longitude)
        if row is not None:
            return Area(row)
    busiest = await areas(session)
    return Area(busiest[0][0]) if busiest else Area()


def _counted(area: Area):
    return and_(Issue.status.not_in(list(UNCOUNTED)), area.contains())


def _tally(statuses):
    return func.coalesce(func.sum(case((Issue.status.in_(list(statuses)), 1), else_=0)), 0)


async def _totals(session: AsyncSession, area: Area) -> StatsTotals:
    # One round trip: every figure is a scalar subquery of the same select.
    stages = (
        select(
            func.count(),
            _tally(CONFIRMED),
            _tally(RAISED),
            _tally({Status.RESOLVED}),
        )
        .select_from(Issue)
        .where(_counted(area))
        .subquery()
    )
    photos = (
        select(func.count())
        .select_from(IssuePhoto)
        .join(Issue, IssuePhoto.issue_id == Issue.id)
        .where(_counted(area))
        .scalar_subquery()
    )
    people = union(
        select(Issue.reporter_id.label("user_id")).where(_counted(area)),
        select(Support.user_id.label("user_id"))
        .join(Issue, Support.issue_id == Issue.id)
        .where(_counted(area)),
    ).subquery()
    contributors = select(func.count()).select_from(people).scalar_subquery()
    emails = (
        select(func.count())
        .select_from(EscalationMessage)
        .join(Escalation, EscalationMessage.escalation_id == Escalation.id)
        .join(Issue, Escalation.issue_id == Issue.id)
        .where(EscalationMessage.direction == MessageDirection.OUTBOUND, _counted(area))
        .scalar_subquery()
    )
    reported, confirmed, raised, resolved, photos, contributors, emails = (
        await session.execute(select(*stages.c, photos, contributors, emails))
    ).one()

    return StatsTotals(
        reported=int(reported or 0),
        confirmed=int(confirmed or 0),
        raised=int(raised or 0),
        resolved=int(resolved or 0),
        photos=int(photos or 0),
        contributors=int(contributors or 0),
        emails_sent=int(emails or 0),
    )


class Period(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"


def period_start(period: Period, today: date | None = None) -> datetime:
    """Calendar periods in India time, returned as the UTC instant they begin."""
    today = today or local_today()
    first = {
        Period.DAY: today,
        Period.MONTH: today.replace(day=1),
        Period.YEAR: today.replace(month=1, day=1),
    }[period]
    return datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc) - REPORTING_OFFSET


def _fixed_at():
    # Reports resolved without a status event (seeded, or set by hand) fall
    # back to the row's last update.
    events = (
        select(
            ActivityEvent.issue_id,
            func.max(ActivityEvent.created_at).label("at"),
        )
        .where(
            ActivityEvent.type == ActivityType.STATUS_CHANGED,
            ActivityEvent.to_status == Status.RESOLVED,
        )
        .group_by(ActivityEvent.issue_id)
        .subquery()
    )
    return events, func.coalesce(events.c.at, Issue.updated_at)


async def _weeks(session: AsyncSession, area: Area) -> list[StatsWeek]:
    today = local_today()
    first = today - timedelta(days=today.weekday(), weeks=WEEKS - 1)
    since = datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc) - REPORTING_OFFSET
    events, fixed_at = _fixed_at()

    def bucket(moment: datetime) -> int:
        return ((moment + REPORTING_OFFSET).date() - first).days // 7

    reported = [0] * WEEKS
    resolved = [0] * WEEKS
    filed = select(literal(False).label("fixed"), Issue.created_at.label("at")).where(
        _counted(area), Issue.created_at >= since
    )
    fixed = (
        select(literal(True).label("fixed"), fixed_at.label("at"))
        .outerjoin(events, events.c.issue_id == Issue.id)
        .where(Issue.status == Status.RESOLVED, area.contains(), fixed_at >= since)
    )
    for was_fixed, moment in (await session.execute(union_all(filed, fixed))).all():
        index = bucket(aware(moment))
        if 0 <= index < WEEKS:
            (resolved if was_fixed else reported)[index] += 1

    return [
        StatsWeek(
            week_start=first + timedelta(weeks=i),
            reported=reported[i],
            resolved=resolved[i],
        )
        for i in range(WEEKS)
    ]


async def _categories(session: AsyncSession, area: Area) -> list[StatsCategory]:
    fixed = func.sum(case((Issue.status == Status.RESOLVED, 1), else_=0))
    rows = await session.execute(
        select(Issue.category, func.count(), fixed)
        .where(_counted(area))
        .group_by(Issue.category)
    )
    items = [
        StatsCategory(category=category, total=total, resolved=int(resolved or 0))
        for category, total, resolved in rows.all()
    ]
    return sorted(items, key=lambda c: (-c.total, c.category))


async def _points(session: AsyncSession, area: Area) -> list[StatsPoint]:
    # Capped per kind so a busy city cannot crowd the fixed ones off the map.
    def kind(resolved: bool):
        condition = (
            Issue.status == Status.RESOLVED if resolved else Issue.status != Status.RESOLVED
        )
        newest = (
            select(Issue.latitude, Issue.longitude, Issue.created_at)
            .where(_counted(area), condition)
            .order_by(Issue.created_at.desc())
            .limit(POINTS_PER_KIND)
            .subquery()
        )
        return select(
            literal(resolved).label("resolved"),
            newest.c.latitude,
            newest.c.longitude,
            newest.c.created_at,
        )

    both = union_all(kind(True), kind(False)).subquery()
    rows = await session.execute(
        select(both.c.resolved, both.c.latitude, both.c.longitude).order_by(
            both.c.resolved.desc(), both.c.created_at.desc()
        )
    )
    return [
        StatsPoint(latitude=lat, longitude=lng, resolved=bool(resolved))
        for resolved, lat, lng in rows.all()
    ]


async def top_contributors(
    session: AsyncSession, *, store: ObjectStore, period: Period, area: Area
) -> StatsContributorsOut:
    """The profile's reputation formula, with each act counted in the period
    it happened: a report when filed, a backing when given, a fix when fixed."""
    since = period_start(period)
    visible = and_(Issue.status.not_in(list(HIDDEN_STATUSES)), area.contains())
    events, fixed_at = _fixed_at()

    posted = (
        select(literal("posts").label("kind"), Issue.reporter_id, func.count())
        .where(visible, Issue.created_at >= since)
        .group_by(Issue.reporter_id)
    )
    fixed = (
        select(literal("resolutions").label("kind"), Issue.reporter_id, func.count())
        .outerjoin(events, events.c.issue_id == Issue.id)
        .where(Issue.status == Status.RESOLVED, area.contains(), fixed_at >= since)
        .group_by(Issue.reporter_id)
    )
    backed = (
        select(literal("upvotes").label("kind"), Issue.reporter_id, func.count(Support.id))
        .join(Support, Support.issue_id == Issue.id)
        .where(visible, Support.user_id != Issue.reporter_id, Support.created_at >= since)
        .group_by(Issue.reporter_id)
    )
    counts: dict[str, dict[str, int]] = {"posts": {}, "resolutions": {}, "upvotes": {}}
    for kind, user_id, count in (
        await session.execute(union_all(posted, fixed, backed))
    ).all():
        counts[kind][user_id] = count
    posts, resolutions, upvotes = counts["posts"], counts["resolutions"], counts["upvotes"]

    scored = []
    for user_id in posts.keys() | resolutions.keys() | upvotes.keys():
        tally = ContributionsOut(
            posts=posts.get(user_id, 0),
            upvotes_received=upvotes.get(user_id, 0),
            supports_given=0,
            comments_written=0,
            resolutions=resolutions.get(user_id, 0),
        )
        scored.append((reputation(tally), tally, user_id))
    scored.sort(key=lambda row: (-row[0], -row[1].resolutions, -row[1].posts, row[2]))

    # Spare candidates, since deleted accounts are dropped from the board.
    candidates = scored[: TOP_CONTRIBUTORS * 2]
    users = {
        user.id: user
        for user in await session.scalars(
            select(User).where(
                User.id.in_([user_id for *_, user_id in candidates]),
                User.deleted_at.is_(None),
            )
        )
    }
    ttl = get_settings().signed_url_ttl_seconds
    board: list[StatsContributor] = []
    for score, tally, user_id in candidates:
        user = users.get(user_id)
        if user is None or score == 0:
            continue
        board.append(
            StatsContributor(
                id=user.id,
                display_name=user.display_name,
                avatar_url=store.signed_url(user.avatar_key, ttl) if user.avatar_key else None,
                reputation=score,
                reports=tally.posts,
                resolutions=tally.resolutions,
            )
        )
        if len(board) == TOP_CONTRIBUTORS:
            break
    return StatsContributorsOut(period=period.value, since=since, area=area.out(), items=board)


async def stats(session: AsyncSession, area: Area) -> StatsOut:
    return StatsOut(
        area=area.out(),
        totals=await _totals(session, area),
        weeks=await _weeks(session, area),
        categories=await _categories(session, area),
        points=await _points(session, area),
        generated_at=utcnow(),
    )
