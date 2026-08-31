"""Scheduled work.

Run these from the system's own scheduler rather than in-process:

    uv run python -m app.jobs escalate     # hourly
    uv run python -m app.jobs check        # daily
    uv run python -m app.jobs prune        # daily
    uv run python -m app.jobs all

They are written to be safe to run more than once and safe to interrupt: each
report is claimed by an insert that a unique constraint arbitrates, so two
overlapping runs cannot both send the same letter. What they are not safe
against is being run as an in-process loop under several web workers, which is
why there is no scheduler here.
"""
import asyncio
import logging
import sys
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .authority import (
    AuthorityUpdate,
    ConcernRequest,
    EmailAuthorityChannel,
    get_channel,
    get_drafter,
    subject_for,
)
from .mail import Attachment, new_reply_token
from .routing import route_report
from .config import get_settings
from .db import dispose, sessionmaker
from .enums import (
    AUTHORITY_STATUSES,
    IN_FLIGHT_STATUSES,
    ActivityType,
    EscalationState,
    Status,
)
from .models import (
    ActivityEvent,
    Escalation,
    EscalationMessage,
    Issue,
    IssuePhoto,
    OtpChallenge,
    OtpRequestLog,
    Support,
    User,
    utcnow,
)
from .enums import MessageDirection
from .storage import get_store
from .service import aware

log = logging.getLogger(__name__)


@dataclass
class Report:
    considered: int = 0
    drafted: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    moved: int = 0

    def __str__(self) -> str:
        return (
            f"considered={self.considered} drafted={self.drafted} sent={self.sent} "
            f"failed={self.failed} skipped={self.skipped} moved={self.moved}"
        )


def _record(session: AsyncSession, issue: Issue, was: Status) -> None:
    """A status change the crowd did not cause still belongs in the reporter's
    feed; it is the only way they learn their report went somewhere."""
    if issue.status == was:
        return
    session.add(
        ActivityEvent(
            user_id=issue.reporter_id,
            issue_id=issue.id,
            type=ActivityType.STATUS_CHANGED,
            from_status=was,
            to_status=issue.status,
        )
    )


async def _voices(session: AsyncSession, issue: Issue) -> list[str]:
    rows = await session.scalars(
        select(Support.body)
        .where(
            Support.issue_id == issue.id,
            Support.user_id != issue.reporter_id,
            Support.body.is_not(None),
            Support.body != "",
        )
        .order_by(Support.created_at.asc())
        .limit(20)
    )
    return list(rows)


async def _evidence(session: AsyncSession, issue: Issue) -> list[Attachment]:
    """The photographs, which are the reason any of this carries weight.

    Originals rather than thumbnails: an official is being asked to look at the
    thing, and a 800px crop is not evidence.
    """
    settings = get_settings()
    store = get_store()
    photos = list(
        (
            await session.scalars(
                select(IssuePhoto)
                .where(IssuePhoto.issue_id == issue.id)
                .order_by(IssuePhoto.created_at.asc())
                .limit(settings.max_letter_attachments)
            )
        ).all()
    )
    attachments: list[Attachment] = []
    for index, photo in enumerate(photos, start=1):
        content = await store.get(photo.original_key)
        if content is None:
            continue
        who = await session.get(User, photo.contributor_id)
        attachments.append(
            Attachment(
                filename=f"evidence-{index}.jpg",
                content=content,
                credit=who.display_name if who else "a resident",
            )
        )
    return attachments


async def _claim(session: AsyncSession, issue: Issue, authority: str) -> Escalation | None:
    """Insert first, draft second.

    The unique constraint on issue_id is the lock: whichever run inserts owns
    the report, and the other gets an IntegrityError and moves on. Claiming
    before spending a model call also means a crash mid-draft costs nothing but
    a row in `drafted`.
    """
    claim = Escalation(
        issue_id=issue.id,
        authority=authority,
        subject="",
        body="",
        reply_token=new_reply_token(),
        state=EscalationState.DRAFTED,
    )
    session.add(claim)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return None
    return claim


async def escalate_confirmed(limit: int | None = None) -> Report:
    """Raise confirmed reports with the body responsible for them."""
    settings = get_settings()
    report = Report()
    drafter = get_drafter()
    channel = get_channel(default=None)
    cutoff = utcnow() - timedelta(hours=settings.escalate_after_hours)

    async with sessionmaker()() as session:
        already = select(Escalation.issue_id)
        candidates = list(
            (
                await session.scalars(
                    select(Issue)
                    .where(
                        Issue.status == Status.COMMUNITY_VERIFIED,
                        Issue.confirmed_at.is_not(None),
                        Issue.confirmed_at <= cutoff,
                        Issue.id.not_in(already),
                    )
                    .order_by(Issue.confirmed_at.asc())
                    .limit(limit or settings.escalate_batch_size)
                )
            ).all()
        )

        for issue in candidates:
            report.considered += 1
            routing = await route_report(
                session,
                title=issue.title,
                description=issue.description,
                category=issue.category,
                latitude=issue.latitude,
                longitude=issue.longitude,
            )
            contact = routing.contact
            claim = await _claim(session, issue, contact.name)
            if claim is None:
                report.skipped += 1
                continue
            claim.recipient = contact.email
            claim.routed_category = routing.category.value
            claim.routed_desk = routing.desk
            if routing.reclassified:
                # The reporter's category is left alone: it is what they chose
                # and what the app shows. Only the letter is routed on this.
                log.info(
                    "issue %s reported as %s, routed as %s",
                    issue.id,
                    issue.category.value,
                    routing.category.value,
                )

            reporter = await session.get(User, issue.reporter_id)
            confirmed = aware(issue.confirmed_at)
            request = ConcernRequest(
                issue_id=issue.id,
                reporter_name=reporter.display_name if reporter else "a resident",
                title=issue.title,
                description=issue.description,
                category=issue.category.value,
                severity=issue.severity.value,
                locality=issue.locality,
                latitude=issue.latitude,
                longitude=issue.longitude,
                confirmed_on=confirmed.date().isoformat() if confirmed else "",
                photo_support_count=issue.photo_support_count,
                seen_count=issue.confirmation_count,
                voices=await _voices(session, issue),
                photos=await _evidence(session, issue),
            )

            try:
                body = await drafter.draft(request)
            except Exception:
                log.exception("could not draft a concern for %s", issue.id)
                body = None

            if not body:
                # No letter, so nothing was claimed on anyone's behalf. Drop the
                # claim so a later run can try again.
                await session.delete(claim)
                await session.flush()
                report.skipped += 1
                continue

            claim.subject = subject_for(request)
            claim.body = body
            report.drafted += 1

            # A channel set explicitly (a test, or a future portal adapter)
            # wins; otherwise each report gets an email channel bound to its own
            # reply address.
            post = channel or EmailAuthorityChannel(claim.reply_token, contact)
            try:
                reference = await post.send(claim.subject, body, request)
            except Exception as exc:
                log.exception("could not send the concern for %s", issue.id)
                claim.state = EscalationState.FAILED
                claim.detail = str(exc)[:2000]
                report.failed += 1
                await session.commit()
                continue

            if reference is None:
                # The draft is kept and readable, but nothing was delivered, so
                # the report is not marked as having reached anybody.
                report.failed += 1
                await session.commit()
                continue

            claim.state = EscalationState.SENT
            claim.reference = reference
            claim.message_id = getattr(post, "message_id", None)
            claim.sent_at = utcnow()
            session.add(
                EscalationMessage(
                    escalation_id=claim.id,
                    direction=MessageDirection.OUTBOUND,
                    sender=contact.email or "",
                    subject=claim.subject,
                    body=claim.body,
                    message_id=claim.message_id,
                )
            )
            was = issue.status
            issue.status = Status.SUBMITTED_TO_AUTHORITY
            _record(session, issue, was)
            report.sent += 1
            report.moved += 1
            await session.commit()

        await session.commit()
    log.info("escalate: %s", report)
    return report


async def check_submitted(limit: int | None = None) -> Report:
    """Ask what became of the reports already raised."""
    settings = get_settings()
    report = Report()
    channel = get_channel()

    async with sessionmaker()() as session:
        rows = list(
            (
                await session.scalars(
                    select(Escalation)
                    .join(Issue, Issue.id == Escalation.issue_id)
                    .where(
                        Escalation.state == EscalationState.SENT,
                        Escalation.reference.is_not(None),
                        Issue.status.in_(list(IN_FLIGHT_STATUSES)),
                    )
                    .order_by(Escalation.checked_at.asc().nulls_first())
                    .limit(limit or settings.check_batch_size)
                )
            ).all()
        )

        for escalation in rows:
            report.considered += 1
            try:
                update: AuthorityUpdate | None = await channel.check(escalation.reference)
            except Exception:
                log.exception("could not check %s", escalation.reference)
                report.failed += 1
                continue

            escalation.checked_at = utcnow()
            if update is None:
                report.skipped += 1
                continue

            if update.status not in AUTHORITY_STATUSES:
                # An authority can move a report forward. It cannot remove one,
                # call it a duplicate, or send it backwards.
                log.warning(
                    "channel returned %s for %s, which is not theirs to set",
                    update.status,
                    escalation.issue_id,
                )
                report.skipped += 1
                continue

            escalation.detail = update.detail
            issue = escalation.issue
            if issue.status != update.status:
                was = issue.status
                issue.status = update.status
                _record(session, issue, was)
                report.moved += 1
        await session.commit()
    log.info("check: %s", report)
    return report


async def prune_otp(limit: int | None = None) -> Report:
    """Both OTP tables hold verified phone numbers and nothing reads them once
    the challenge is spent or the rate-limit hour is up. Left alone they grow
    without bound and keep numbers indefinitely, which is the thing retention
    limits exist to stop."""
    settings = get_settings()
    report = Report()
    cutoff = utcnow() - timedelta(hours=settings.otp_retention_hours)

    async with sessionmaker()() as session:
        challenges = await session.execute(
            delete(OtpChallenge).where(OtpChallenge.created_at < cutoff)
        )
        logs = await session.execute(
            delete(OtpRequestLog).where(OtpRequestLog.created_at < cutoff)
        )
        await session.commit()
        report.considered = (challenges.rowcount or 0) + (logs.rowcount or 0)
        report.moved = report.considered
    log.info("prune: %s", report)
    return report


JOBS = {
    "escalate": escalate_confirmed,
    "check": check_submitted,
    "prune": prune_otp,
}


async def _main(names: list[str]) -> int:
    logging.basicConfig(level=logging.INFO)
    chosen = list(JOBS) if not names or names == ["all"] else names
    unknown = [name for name in chosen if name not in JOBS]
    if unknown:
        print(f"unknown job(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"available: {', '.join(JOBS)}, all", file=sys.stderr)
        return 2
    try:
        for name in chosen:
            print(f"{name}: {await JOBS[name]()}")
    finally:
        await dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
