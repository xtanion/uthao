"""Telling a reporter's phone that something happened to their report.

Activity rows are the outbox. Whatever writes one commits as it always has; the
commit schedules a run here, which claims the rows nobody has pushed yet and
hands them to Expo. The `push` cron runs the same thing, so a row a restart
dropped on the floor still goes out, provided it is not stale by then.

A row is claimed before it is sent, so a crash between the two loses that push
rather than sending it twice. The feed still has it; a duplicate buzz is the
worse mistake.
"""
import asyncio
import logging
import re
import weakref
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

import httpx
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from .config import get_settings
from .db import sessionmaker
from .enums import ActivityType, Category, Status
from .models import ActivityEvent, PushToken, User, utcnow

log = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"^Expo(nent)?PushToken\[[A-Za-z0-9_\-]+\]$")
# Matches the channel the app creates on Android.
CHANNEL_ID = "activity"
# Expo's own limit per request.
EXPO_CHUNK = 100

# The same words the app uses, so the buzz and the feed row agree.
STATUS_LABELS = {
    Status.REPORTED: "Reported",
    Status.COMMUNITY_VERIFIED: "Confirmed",
    Status.SUBMITTED_TO_AUTHORITY: "Raised",
    Status.AUTHORITY_ACKNOWLEDGED: "Acknowledged",
    Status.IN_PROGRESS: "Work started",
    Status.RESOLUTION_CLAIMED: "Fix claimed",
    Status.RESOLVED: "Fixed",
    Status.REOPENED: "Reopened",
    Status.DUPLICATE: "Duplicate",
    Status.REMOVED: "Removed",
}

CATEGORY_LABELS = {
    Category.POTHOLE_ROAD: "Pothole / Road",
    Category.GARBAGE: "Garbage",
    Category.FOOTPATH: "Footpath",
    Category.STREETLIGHT: "Streetlight",
    Category.WATER_DRAINAGE: "Water / Drainage",
    Category.MANHOLE: "Manhole",
    Category.TRAFFIC_INFRASTRUCTURE: "Traffic infrastructure",
    Category.FALLEN_TREE: "Fallen tree",
    Category.PUBLIC_PROPERTY: "Public property",
    Category.OTHER: "Other",
}


@dataclass
class PushMessage:
    to: str
    title: str
    body: str
    data: dict
    badge: int | None = None

    def payload(self) -> dict:
        body = {
            "to": self.to,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "sound": "default",
            "channelId": CHANNEL_ID,
            "priority": "high",
        }
        if self.badge is not None:
            body["badge"] = self.badge
        return body


@dataclass
class PushReport:
    claimed: int = 0
    sent: int = 0
    failed: int = 0
    dropped_tokens: int = 0

    def __str__(self) -> str:
        return (
            f"claimed={self.claimed} sent={self.sent} failed={self.failed} "
            f"dropped_tokens={self.dropped_tokens}"
        )


class PushSender:
    async def send(self, messages: list[PushMessage]) -> list[str | None]:
        """One entry per message, in order: None when accepted, otherwise the
        error code Expo gave, such as DeviceNotRegistered."""
        raise NotImplementedError


class ExpoPushSender(PushSender):
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport

    async def send(self, messages: list[PushMessage]) -> list[str | None]:
        settings = get_settings()
        headers = {"accept": "application/json", "content-type": "application/json"}
        if settings.expo_access_token:
            headers["authorization"] = f"Bearer {settings.expo_access_token}"

        outcomes: list[str | None] = []
        async with httpx.AsyncClient(timeout=15, transport=self.transport) as client:
            for start in range(0, len(messages), EXPO_CHUNK):
                chunk = messages[start : start + EXPO_CHUNK]
                response = await client.post(
                    settings.expo_push_url,
                    json=[message.payload() for message in chunk],
                    headers=headers,
                )
                response.raise_for_status()
                tickets = response.json().get("data") or []
                for index in range(len(chunk)):
                    ticket = tickets[index] if index < len(tickets) else {}
                    if ticket.get("status") == "ok":
                        outcomes.append(None)
                    else:
                        details = ticket.get("details") or {}
                        outcomes.append(details.get("error") or ticket.get("message") or "unknown")
        return outcomes


_sender: PushSender | None = None


def get_sender() -> PushSender:
    return _sender or ExpoPushSender()


def set_sender(sender: PushSender | None) -> None:
    global _sender
    _sender = sender


def compose(activity: ActivityEvent) -> tuple[str, str]:
    issue = activity.issue
    title = issue.title.strip() or CATEGORY_LABELS.get(issue.category, "Your report")
    if activity.type == ActivityType.SUPPORT_RECEIVED:
        who = activity.actor.display_name if activity.actor else "Someone"
        return title, f"{who} independently saw this"
    if activity.type == ActivityType.AUTHORITY_REPLIED:
        return title, "The authority replied to your report"
    if activity.to_status == Status.COMMUNITY_VERIFIED:
        return title, "Enough neighbours confirmed this to verify it"
    status = activity.to_status or issue.status
    return title, f"Status moved to {STATUS_LABELS.get(status, status.value)}"


async def register(
    session: AsyncSession, *, user: User, token: str, platform: str
) -> None:
    """Idempotent. A token already on file moves to whoever is signed in now,
    because it is the device that owns it, not the account."""
    for attempt in range(2):
        existing = await session.scalar(select(PushToken).where(PushToken.token == token))
        if existing is not None:
            existing.user_id = user.id
            existing.platform = platform
            existing.updated_at = utcnow()
        else:
            session.add(PushToken(user_id=user.id, token=token, platform=platform))
        try:
            await session.commit()
            return
        except IntegrityError:
            # Two registrations of one token raced; the second becomes an update.
            await session.rollback()
            if attempt:
                raise


async def unregister(session: AsyncSession, *, user: User, token: str) -> None:
    await session.execute(
        delete(PushToken).where(PushToken.token == token, PushToken.user_id == user.id)
    )
    await session.commit()


_locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = (
    weakref.WeakKeyDictionary()
)


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _locks.get(loop)
    if lock is None:
        lock = _locks[loop] = asyncio.Lock()
    return lock


async def deliver_pending() -> PushReport:
    settings = get_settings()
    report = PushReport()
    if not settings.push_enabled:
        return report
    async with _lock():
        while await _deliver_batch(report) >= settings.push_batch_size:
            pass
    if report.claimed:
        log.info("push: %s", report)
    return report


async def _deliver_batch(report: PushReport) -> int:
    settings = get_settings()
    cutoff = utcnow() - timedelta(hours=settings.push_max_age_hours)

    async with sessionmaker()() as session:
        candidates = list(
            (
                await session.scalars(
                    select(ActivityEvent.id)
                    .where(ActivityEvent.pushed_at.is_(None), ActivityEvent.created_at >= cutoff)
                    .order_by(ActivityEvent.created_at)
                    .limit(settings.push_batch_size)
                )
            ).all()
        )
        if not candidates:
            return 0

        claimed = list(
            (
                await session.execute(
                    update(ActivityEvent)
                    .where(ActivityEvent.id.in_(candidates), ActivityEvent.pushed_at.is_(None))
                    .values(pushed_at=utcnow())
                    .returning(ActivityEvent.id)
                    .execution_options(synchronize_session=False)
                )
            ).scalars()
        )
        await session.commit()
        report.claimed += len(claimed)
        if not claimed:
            return len(candidates)

        activities = list(
            (
                await session.scalars(
                    select(ActivityEvent)
                    .where(ActivityEvent.id.in_(claimed))
                    .order_by(ActivityEvent.created_at)
                )
            ).all()
        )
        recipients = {activity.user_id for activity in activities}
        tokens: dict[str, list[str]] = defaultdict(list)
        for row in (
            await session.scalars(select(PushToken).where(PushToken.user_id.in_(recipients)))
        ).all():
            tokens[row.user_id].append(row.token)
        if not tokens:
            return len(candidates)

        unread = dict(
            (
                await session.execute(
                    select(ActivityEvent.user_id, func.count())
                    .where(
                        ActivityEvent.user_id.in_(list(tokens)),
                        ActivityEvent.read_at.is_(None),
                    )
                    .group_by(ActivityEvent.user_id)
                )
            ).all()
        )

        messages = []
        for activity in activities:
            title, body = compose(activity)
            for token in tokens.get(activity.user_id, []):
                messages.append(
                    PushMessage(
                        to=token,
                        title=title,
                        body=body,
                        data={"issue_id": activity.issue_id, "notification_id": activity.id},
                        badge=int(unread.get(activity.user_id, 0)),
                    )
                )

        try:
            outcomes = await get_sender().send(messages)
        except Exception:
            log.exception("could not push %d message(s)", len(messages))
            report.failed += len(messages)
            return len(candidates)

        dead = set()
        for message, outcome in zip(messages, outcomes):
            if outcome is None:
                report.sent += 1
                continue
            report.failed += 1
            if outcome == "DeviceNotRegistered":
                dead.add(message.to)
            else:
                log.warning("push to %s refused: %s", message.to, outcome)
        if dead:
            await session.execute(delete(PushToken).where(PushToken.token.in_(dead)))
            await session.commit()
            report.dropped_tokens += len(dead)

    return len(candidates)


_tasks: set[asyncio.Task] = set()


def schedule() -> None:
    if not get_settings().push_enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_run())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _run() -> None:
    try:
        await deliver_pending()
    except Exception:
        log.exception("push run failed")


async def drain() -> None:
    """Waits for scheduled runs, so a process exiting does not cut one off."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


@event.listens_for(Session, "after_flush")
def _note_activity(session: Session, _context) -> None:
    if any(isinstance(row, ActivityEvent) for row in session.new):
        session.info["push_pending"] = True


@event.listens_for(Session, "after_commit")
def _push_after_commit(session: Session) -> None:
    if session.info.pop("push_pending", False):
        schedule()


@event.listens_for(Session, "after_rollback")
def _forget_on_rollback(session: Session) -> None:
    session.info.pop("push_pending", None)
