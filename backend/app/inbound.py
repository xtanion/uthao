"""What comes back.

An emailed complaint has nothing to poll, so the reply arrives here instead:
the mail provider posts it, the reply address says which report it belongs to,
and the reader decides whether it moves the report along.

Anything unrecognised is still stored. A reply nobody can classify is still a
reply the person who filed the complaint should get to read.
"""
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .authority import get_reply_reader
from .enums import (
    AUTHORITY_STATUSES,
    Status,
    ActivityType,
    EscalationState,
    MessageDirection,
)
from .mail import token_from_address
from .models import ActivityEvent, Escalation, EscalationMessage, utcnow

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboundMail:
    to: str
    sender: str
    subject: str
    body: str
    message_id: str | None = None


@dataclass(frozen=True)
class Delivery:
    """What the provider says happened to a message we handed it."""

    to: str
    delivered: bool
    detail: str | None = None


async def _find(session: AsyncSession, address: str) -> Escalation | None:
    token = token_from_address(address)
    if token is None:
        return None
    return await session.scalar(
        select(Escalation).where(Escalation.reply_token == token)
    )


async def record_reply(session: AsyncSession, mail: InboundMail) -> Escalation | None:
    """Store the reply, and move the report if it plainly says to."""
    escalation = await _find(session, mail.to)
    if escalation is None:
        log.warning("inbound mail for an unknown address: %s", mail.to)
        return None

    # Providers retry, and a signed post can be replayed inside the signing
    # window. The same email twice is still one reply, and must not notify the
    # reporter or move the report a second time.
    if mail.message_id and await session.scalar(
        select(EscalationMessage.id).where(
            EscalationMessage.escalation_id == escalation.id,
            EscalationMessage.message_id == mail.message_id,
        )
    ):
        return escalation

    session.add(
        EscalationMessage(
            escalation_id=escalation.id,
            direction=MessageDirection.INBOUND,
            sender=mail.sender,
            subject=mail.subject[:300],
            body=mail.body,
            message_id=mail.message_id,
        )
    )
    escalation.checked_at = utcnow()

    issue = escalation.issue
    session.add(
        ActivityEvent(
            user_id=issue.reporter_id,
            issue_id=issue.id,
            type=ActivityType.AUTHORITY_REPLIED,
        )
    )

    try:
        update = await get_reply_reader().read(mail.subject, mail.body)
    except Exception:
        log.exception("could not read the reply on %s", escalation.id)
        update = None

    if update is not None and update.status in AUTHORITY_STATUSES:
        escalation.detail = update.detail
        if issue.status != update.status:
            was = issue.status
            issue.status = update.status
            session.add(
                ActivityEvent(
                    user_id=issue.reporter_id,
                    issue_id=issue.id,
                    type=ActivityType.STATUS_CHANGED,
                    from_status=was,
                    to_status=issue.status,
                )
            )
    await session.commit()
    return escalation


async def record_delivery(
    session: AsyncSession, event: Delivery
) -> Escalation | None:
    """A bounce is not a delay. The address is wrong and retrying will not fix
    it, so the escalation stops claiming to have reached anybody."""
    escalation = await _find(session, event.to)
    if escalation is None:
        log.warning("delivery event for an unknown address: %s", event.to)
        return None

    if event.delivered:
        escalation.delivered_at = utcnow()
    else:
        escalation.bounced_at = utcnow()
        escalation.state = EscalationState.BOUNCED
        escalation.detail = event.detail
        issue = escalation.issue
        if issue.status == Status.SUBMITTED_TO_AUTHORITY:
            was = issue.status
            issue.status = Status.COMMUNITY_VERIFIED
            session.add(
                ActivityEvent(
                    user_id=issue.reporter_id,
                    issue_id=issue.id,
                    type=ActivityType.STATUS_CHANGED,
                    from_status=was,
                    to_status=issue.status,
                )
            )
    await session.commit()
    return escalation
