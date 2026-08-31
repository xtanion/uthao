"""Raising a confirmed report with the body responsible for it.

Two separate things, both swappable, both no-ops until configured:

  * a *drafter* turns a report and what people said about it into a letter;
  * a *channel* delivers that letter somewhere and can be asked about it later.

They are split because they fail differently. A drafter that is not configured
means no letter and nothing happens. A channel that is not configured means the
letter exists, is stored, and is readable by a person - but nothing is claimed
to have been sent, and the report's status does not move. Saying a complaint
reached a municipal body when it did not is the one failure this file exists to
avoid.
"""
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .models import Authority, AuthorityContactPoint
from .mail import (
    Attachment,
    OutboundEmail,
    build_message_id,
    get_transport,
    reply_address,
)
from .enums import ContactChannel, ContactPointKind, Status

log = logging.getLogger(__name__)

SYSTEM = """You write short formal complaints to municipal authorities in \
India on behalf of residents who have reported a civic problem.

Write the body of the letter only. Four short paragraphs at most:
- what the problem is and exactly where;
- that residents have independently confirmed it, with how many and since when;
- the risk to people using that place, only if the report states facts that \
show one;
- a request to inspect and repair.

Use plain, courteous, unemotional language. An official should be able to act \
on it without rereading. Do not invent a ward number, a department, an officer, \
a deadline, a statute, or any fact the report does not contain. Do not estimate \
costs. Do not threaten escalation, press coverage, or legal action.

Reply with the letter body. No subject line, no salutation, no sign-off, no \
placeholders in square brackets."""


@dataclass(frozen=True)
class ConcernRequest:
    issue_id: str
    # The name the app already shows publicly. Not the phone number: sending a
    # resident's contact details to a government office is a separate thing to
    # ask them for, and nothing here has asked.
    reporter_name: str
    title: str
    description: str
    category: str
    severity: str
    locality: str | None
    latitude: float
    longitude: float
    confirmed_on: str
    photo_support_count: int
    seen_count: int
    voices: list[str]
    photos: list[Attachment] = field(default_factory=list)


@dataclass(frozen=True)
class AuthorityContact:
    name: str
    email: str | None
    # Set when the body publishes somewhere to complain that is not an inbox.
    # Nothing sends to these yet; they are carried so a letter that cannot be
    # posted still knows where it should have gone.
    channel: ContactChannel = ContactChannel.NONE
    portal_url: str | None = None
    helpline: str | None = None

    @property
    def reachable_by_email(self) -> bool:
        return self.channel is ContactChannel.EMAIL and bool(self.email)


@dataclass(frozen=True)
class AuthorityUpdate:
    """What a channel says has happened since the letter went out."""

    status: Status
    detail: str | None = None


def render(request: ConcernRequest) -> str:
    where = request.locality or f"{request.latitude:.5f}, {request.longitude:.5f}"
    lines = [
        f"Problem: {request.title}",
        f"Category: {request.category}",
        f"Reported severity: {request.severity}",
        f"Location: {where} (coordinates {request.latitude:.5f}, {request.longitude:.5f})",
        f"Independently confirmed by {request.photo_support_count} residents with "
        f"photographs, and seen by {request.seen_count} in total.",
        f"Confirmed on {request.confirmed_on}.",
    ]
    if request.description:
        lines.append(f"\nThe person who reported it wrote: {request.description}")
    if request.voices:
        lines.append("\nResidents who went and looked since wrote:")
        lines.extend(f"- {voice}" for voice in request.voices)
    return "\n".join(lines)


def subject_for(request: ConcernRequest) -> str:
    """Built here rather than by the model: a subject line should be uniform
    across every letter, and carry the reference an official will quote back."""
    where = f" at {request.locality}" if request.locality else ""
    return (
        f"Civic complaint: {request.title.rstrip('.')}{where} "
        f"(ref {request.issue_id[:8]})"
    )[:300]


class ConcernDrafter:
    async def draft(self, request: ConcernRequest) -> str | None:
        raise NotImplementedError


class NullConcernDrafter(ConcernDrafter):
    async def draft(self, request: ConcernRequest) -> str | None:
        return None


class ClaudeConcernDrafter(ConcernDrafter):
    def __init__(self, settings: Settings) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.ai_summary_model

    async def draft(self, request: ConcernRequest) -> str | None:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4000,
            system=SYSTEM,
            # Higher effort than the summary: this one is read by somebody who
            # can refuse it, and it goes out with a resident's name behind it.
            output_config={"effort": "medium"},
            messages=[{"role": "user", "content": render(request)}],
        )
        if response.stop_reason == "refusal":
            log.warning(
                "concern refused for issue %s (%s)",
                request.issue_id,
                response.stop_details.category if response.stop_details else None,
            )
            return None
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return text or None


class AuthorityChannel:
    """Where a letter goes, and how to ask what became of it."""

    name = "none"

    async def send(self, subject: str, body: str, request: ConcernRequest) -> str | None:
        """Returns a reference when it was accepted, None when it was not."""
        raise NotImplementedError

    async def check(self, reference: str) -> AuthorityUpdate | None:
        """None means nothing is known, which is not the same as no change."""
        raise NotImplementedError


class LoggingAuthorityChannel(AuthorityChannel):
    """The default. Writes the letter to the log and delivers nothing.

    Returning None is the point: the caller treats that as "not sent", so no
    report is ever marked submitted to an authority that never received it.
    """

    name = "log"

    async def send(self, subject: str, body: str, request: ConcernRequest) -> str | None:
        log.warning(
            "no authority channel configured; not sending.\nSubject: %s\n%s",
            subject,
            body,
        )
        return None

    async def check(self, reference: str) -> AuthorityUpdate | None:
        return None


def settings_contact() -> AuthorityContact:
    """The fallback, and what a deployment with an empty table still does."""
    settings = get_settings()
    email = settings.authority_email or None
    return AuthorityContact(
        name=settings.default_authority,
        email=email,
        channel=ContactChannel.EMAIL if email else ContactChannel.NONE,
    )


async def authority_for(
    session: AsyncSession,
    latitude: float,
    longitude: float,
    category: str | None = None,
) -> AuthorityContact:
    """Which body owns the problem, and how to reach them.

    Matched on the coordinates rather than `locality`, which is a free-text
    string the client supplies and nothing validates. Overlapping boxes
    resolve to the smallest, so a city sitting inside a state-wide row is the
    one that gets the letter.

    With a category, a departmental desk is preferred over the front door: a
    pothole reaches the roads engineer rather than a general inbox, which is
    the difference between a complaint that is routed and one that is
    forwarded.

    Falls back to AUTHORITY_EMAIL, which is what a deployment that has not
    seeded the table still has.
    """
    row = await authority_row_for(session, latitude, longitude)
    if row is None:
        return settings_contact()

    desk = None
    if category:
        desk = await session.scalar(
            select(AuthorityContactPoint).where(
                AuthorityContactPoint.authority_id == row.id,
                AuthorityContactPoint.kind == ContactPointKind.DEPARTMENT,
                AuthorityContactPoint.key == category,
                AuthorityContactPoint.active.is_(True),
            )
        )
    return contact_from(row, desk)


async def authority_row_for(
    session: AsyncSession, latitude: float, longitude: float
) -> Authority | None:
    """The body whose box covers this point, smallest first."""
    rows = (
        await session.scalars(
            select(Authority).where(
                Authority.active.is_(True),
                Authority.min_latitude <= latitude,
                Authority.max_latitude >= latitude,
                Authority.min_longitude <= longitude,
                Authority.max_longitude >= longitude,
            )
        )
    ).all()
    return min(rows, key=lambda a: a.area) if rows else None


async def desks_for(
    session: AsyncSession, authority_id: str, kind: ContactPointKind
) -> list[AuthorityContactPoint]:
    return list(
        (
            await session.scalars(
                select(AuthorityContactPoint).where(
                    AuthorityContactPoint.authority_id == authority_id,
                    AuthorityContactPoint.kind == kind,
                    AuthorityContactPoint.active.is_(True),
                )
                # Stable, so the catalogue the model is shown does not reorder
                # between runs for no reason.
                .order_by(AuthorityContactPoint.key)
            )
        ).all()
    )


def contact_from(
    row: Authority, desk: AuthorityContactPoint | None
) -> AuthorityContact:
    """The body's name still goes on the letter; the desk is who opens it.

    "To the Chief Engineer (Roads)" from a resident would be odd, and the
    corporation is the one answerable for the road either way.
    """
    return AuthorityContact(
        name=row.name,
        email=desk.email if desk else row.email,
        channel=ContactChannel.EMAIL if desk else row.channel,
        portal_url=row.portal_url,
        helpline=row.helpline,
    )


def letter(request: ConcernRequest, body: str, contact: AuthorityContact) -> str:
    """The drafted body, wrapped in the parts a person should not improvise."""
    credits = ""
    if request.photos:
        lines = "\n".join(
            f"  {n}. {photo.filename} - photographed by {photo.credit}"
            for n, photo in enumerate(request.photos, start=1)
        )
        credits = f"\n\nPhotographs attached:\n{lines}"
    return (
        f"To the {contact.name},\n\n"
        f"{body}{credits}\n\n"
        f"Reported by {request.reporter_name} and confirmed by "
        f"{request.photo_support_count} other residents with photographs.\n"
        f"Reference {request.issue_id[:8]}.\n\n"
        "This complaint was submitted through fihy on behalf of the residents "
        "named above. Replying to this email reaches them."
    )


class EmailAuthorityChannel(AuthorityChannel):
    """Sends the letter and returns the token replies will come back on.

    `check` never has anything to say: an emailed complaint has no endpoint to
    poll. What comes back arrives at the inbound webhook and is applied there,
    which is a push rather than a poll and is the better shape anyway.
    """

    name = "email"

    def __init__(self, reply_token: str, contact: AuthorityContact) -> None:
        self.reply_token = reply_token
        # Resolved by the caller, which is where the session lives. Passing it
        # in also means the row is read once per letter rather than twice.
        self.contact = contact
        self.message_id: str | None = None

    async def send(self, subject: str, body: str, request: ConcernRequest) -> str | None:
        settings = get_settings()
        contact = self.contact
        if not contact.reachable_by_email:
            # A portal-only body is not a misconfiguration, so this is not a
            # warning: there is simply no inbox to write to yet.
            log.info(
                "%s has no complaint address (%s); not sending",
                contact.name,
                contact.channel.value,
            )
            return None

        self.message_id = build_message_id(settings)
        reply_to = reply_address(self.reply_token, settings)
        message = OutboundEmail(
            to=contact.email,
            sender=reply_to,
            sender_name=f"{request.reporter_name} (via {settings.mail_from_name})",
            reply_to=reply_to,
            subject=subject,
            body=letter(request, body, contact),
            message_id=self.message_id,
            attachments=request.photos[: settings.max_letter_attachments],
        )
        return await get_transport().send(message)

    async def check(self, reference: str) -> AuthorityUpdate | None:
        return None


REPLY_SYSTEM = """You read replies from Indian municipal offices to civic \
complaints and say what stage the complaint has reached.

Answer with exactly one word from this list and nothing else:

acknowledged - they confirm receipt, log a ticket, or assign it to someone
in_progress  - work has started, an inspection is scheduled, or a crew is out
claimed      - they say the work is finished or the problem is resolved
none         - an auto-reply, a request for more detail, a rejection, a \
transfer to another department, or anything you cannot place

Choose `none` when unsure. Saying work is finished when the reply does not say \
so would close a real problem, so require the reply to state it plainly."""

_REPLY_STATUS = {
    "acknowledged": Status.AUTHORITY_ACKNOWLEDGED,
    "in_progress": Status.IN_PROGRESS,
    "claimed": Status.RESOLUTION_CLAIMED,
}


class ReplyReader:
    async def read(self, subject: str, body: str) -> AuthorityUpdate | None:
        raise NotImplementedError


class NullReplyReader(ReplyReader):
    """No key, so nothing is inferred. The reply is still stored and shown."""

    async def read(self, subject: str, body: str) -> AuthorityUpdate | None:
        return None


class ClaudeReplyReader(ReplyReader):
    def __init__(self, settings: Settings) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.ai_summary_model

    async def read(self, subject: str, body: str) -> AuthorityUpdate | None:
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1500,
            system=REPLY_SYSTEM,
            output_config={"effort": "low"},
            messages=[
                {"role": "user", "content": f"Subject: {subject}\n\n{body[:6000]}"}
            ],
        )
        if response.stop_reason == "refusal":
            return None
        word = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip().lower().strip(".")
        status = _REPLY_STATUS.get(word)
        if status is None:
            return None
        return AuthorityUpdate(status=status, detail=f"From their reply: {word}")


_reply_reader: ReplyReader | None = None


def get_reply_reader() -> ReplyReader:
    global _reply_reader
    if _reply_reader is None:
        settings = get_settings()
        _reply_reader = (
            ClaudeReplyReader(settings)
            if settings.ai_summary_configured
            else NullReplyReader()
        )
    return _reply_reader


def set_reply_reader(reader: ReplyReader | None) -> None:
    global _reply_reader
    _reply_reader = reader


_drafter: ConcernDrafter | None = None
_channel: AuthorityChannel | None = None


def get_drafter() -> ConcernDrafter:
    global _drafter
    if _drafter is None:
        settings = get_settings()
        if settings.ai_summary_configured:
            _drafter = ClaudeConcernDrafter(settings)
        else:
            log.info("no ANTHROPIC_API_KEY; concerns are not drafted")
            _drafter = NullConcernDrafter()
    return _drafter


def set_drafter(drafter: ConcernDrafter | None) -> None:
    global _drafter
    _drafter = drafter


def get_channel(default: AuthorityChannel | None = None) -> AuthorityChannel | None:
    """None means "no channel was set", which lets the escalate job build one
    per report - an email channel has to know its own reply address."""
    if _channel is None:
        return default
    return _channel


def set_channel(channel: AuthorityChannel | None) -> None:
    global _channel
    _channel = channel
