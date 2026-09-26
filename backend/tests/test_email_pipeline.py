"""Letters out, replies in. Nothing here touches SMTP or a model."""
import hashlib
import hmac
import json
import time
import uuid

import pytest
from sqlalchemy import select

from app import authority as authority_module
from app import mail as mail_module
from app.authority import AuthorityUpdate, ConcernRequest, ConcernDrafter, ReplyReader
from app.enums import EscalationState, MessageDirection, Status
from app.jobs import escalate_confirmed
from app.mail import MailTransport, OutboundEmail, compose, token_from_address
from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"
SECRET = "test-inbound-secret"


def report_id() -> str:
    return str(uuid.uuid4())


class Drafter(ConcernDrafter):
    async def draft(self, request: ConcernRequest) -> str | None:
        self.last = request
        return "There is an open manhole. Please inspect and repair."


class Post(MailTransport):
    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []

    async def send(self, message: OutboundEmail) -> str | None:
        self.sent.append(message)
        return message.message_id


class Reader(ReplyReader):
    def __init__(self, update: AuthorityUpdate | None = None) -> None:
        self.update = update
        self.seen: list[tuple[str, str]] = []

    async def read(self, subject, body):
        self.seen.append((subject, body))
        return self.update


@pytest.fixture
def posted(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    monkeypatch.setenv("MAIL_FROM_DOMAIN", "mail.fihy.test")
    monkeypatch.setenv("MAIL_REPLY_DOMAIN", "mail.fihy.test")
    monkeypatch.setenv("AUTHORITY_EMAIL", "ward@example.gov.in")
    monkeypatch.setenv("DEFAULT_AUTHORITY", "H West Ward Office")
    monkeypatch.setenv("INBOUND_MAIL_SECRET", SECRET)
    get_settings.cache_clear()

    transport, reader = Post(), Reader()
    authority_module.set_drafter(Drafter())
    authority_module.set_channel(None)
    authority_module.set_reply_reader(reader)
    mail_module.set_transport(transport)
    yield transport, reader
    authority_module.set_drafter(None)
    authority_module.set_reply_reader(None)
    mail_module.set_transport(None)
    for key in (
        "ESCALATE_AFTER_HOURS", "MAIL_FROM_DOMAIN", "MAIL_REPLY_DOMAIN",
        "AUTHORITY_EMAIL", "DEFAULT_AUTHORITY", "INBOUND_MAIL_SECRET",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


async def confirmed_issue(client, sender) -> str:
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    for phone in (NEIGHBOUR, THIRD):
        token = await sign_in(client, sender, phone)
        await client.post(
            f"/issues/{issue_id}/supports",
            headers=auth(token),
            data={"body": f"Still open, {phone}.", **HERE},
            files=[("photos", ("p.jpg", jpeg_bytes(320, 240), "image/jpeg"))],
        )
    return issue_id


async def escalation_for(issue_id):
    from app.db import sessionmaker
    from app.models import Escalation

    async with sessionmaker()() as session:
        return await session.scalar(
            select(Escalation).where(Escalation.issue_id == issue_id)
        )


async def status_of(issue_id):
    from app.db import sessionmaker
    from app.models import Issue

    async with sessionmaker()() as session:
        return (await session.scalar(select(Issue).where(Issue.id == issue_id))).status


def signed(payload: dict, at: float | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(payload).encode()
    timestamp = str(int(time.time() if at is None else at))
    signature = hmac.new(
        SECRET.encode(), timestamp.encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return raw, {
        "content-type": "application/json",
        "x-fihy-signature": signature,
        "x-fihy-timestamp": timestamp,
    }


# --- outbound --------------------------------------------------------------


async def test_the_letter_carries_the_reporter_not_their_address(client, sender, posted):
    transport, _ = posted
    await confirmed_issue(client, sender)

    await escalate_confirmed()

    message = transport.sent[0]
    assert message.to == "ward@example.gov.in"
    assert message.sender_name == "Resident 3210 (via fihy)"
    # Never their own address: this server cannot pass DMARC for it.
    assert message.sender.startswith("r.")
    assert message.sender.endswith("@mail.fihy.test")
    assert message.reply_to == message.sender


async def test_the_reply_address_is_the_correlation_key(client, sender, posted):
    transport, _ = posted
    issue_id = await confirmed_issue(client, sender)

    await escalate_confirmed()

    escalation = await escalation_for(issue_id)
    assert escalation.reply_token
    assert token_from_address(transport.sent[0].reply_to) == escalation.reply_token
    assert escalation.message_id == transport.sent[0].message_id
    assert escalation.recipient == "ward@example.gov.in"


async def test_the_photographs_go_with_it(client, sender, posted):
    transport, _ = posted
    await confirmed_issue(client, sender)

    await escalate_confirmed()

    message = transport.sent[0]
    assert len(message.attachments) == 3, "the report's own, plus two supports"
    assert all(a.content[:2] == b"\xff\xd8" for a in message.attachments), "real JPEGs"
    assert {a.credit for a in message.attachments} == {
        "Resident 3210", "Resident 0001", "Resident 0002",
    }
    assert "photographed by Resident 0001" in message.body


async def test_the_letter_reads_as_a_letter(client, sender, posted):
    transport, _ = posted
    issue_id = await confirmed_issue(client, sender)

    await escalate_confirmed()

    body = transport.sent[0].body
    assert body.startswith("To the H West Ward Office,")
    assert "Please inspect and repair." in body
    assert "Reported by Resident 3210" in body
    assert issue_id[:8] in body
    assert "Replying to this email reaches them" in body


async def test_no_phone_number_leaves_the_system(client, sender, posted):
    """Sending a resident's contact details to a government office is a
    separate thing to ask them for, and nothing has asked."""
    transport, _ = posted
    await confirmed_issue(client, sender)

    await escalate_confirmed()

    message = transport.sent[0]
    assert REPORTER not in message.body
    assert REPORTER.lstrip("+") not in message.body


async def test_the_attachment_cap_holds(client, sender, posted, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("MAX_LETTER_ATTACHMENTS", "1")
    get_settings.cache_clear()
    transport, _ = posted
    await confirmed_issue(client, sender)

    await escalate_confirmed()

    assert len(transport.sent[0].attachments) == 1
    monkeypatch.delenv("MAX_LETTER_ATTACHMENTS", raising=False)
    get_settings.cache_clear()


async def test_the_outbound_letter_is_kept_on_the_thread(client, sender, posted):
    issue_id = await confirmed_issue(client, sender)

    await escalate_confirmed()

    escalation = await escalation_for(issue_id)
    assert len(escalation.messages) == 1
    assert escalation.messages[0].direction == MessageDirection.OUTBOUND


async def test_a_composed_message_has_the_right_headers(client, sender, posted):
    transport, _ = posted
    await confirmed_issue(client, sender)
    await escalate_confirmed()

    mail = compose(transport.sent[0])

    assert mail["To"] == "ward@example.gov.in"
    assert mail["Reply-To"].startswith("r.")
    assert "Resident 3210 (via fihy)" in mail["From"]
    assert mail["Message-ID"]
    assert mail.is_multipart(), "the photographs are attached"


async def test_with_no_authority_email_nothing_is_sent(client, sender, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    monkeypatch.setenv("MAIL_REPLY_DOMAIN", "mail.fihy.test")
    monkeypatch.setenv("AUTHORITY_EMAIL", "")
    get_settings.cache_clear()
    authority_module.set_drafter(Drafter())
    authority_module.set_channel(None)
    transport = Post()
    mail_module.set_transport(transport)
    try:
        issue_id = await confirmed_issue(client, sender)
        result = await escalate_confirmed()

        assert result.drafted == 1
        assert result.sent == 0
        assert transport.sent == []
        assert await status_of(issue_id) == Status.COMMUNITY_VERIFIED
    finally:
        authority_module.set_drafter(None)
        mail_module.set_transport(None)
        for key in ("ESCALATE_AFTER_HOURS", "MAIL_REPLY_DOMAIN", "AUTHORITY_EMAIL"):
            monkeypatch.delenv(key, raising=False)
        get_settings.cache_clear()


# --- inbound ---------------------------------------------------------------


async def test_a_reply_lands_on_the_right_report(client, sender, posted):
    transport, reader = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    reader.update = AuthorityUpdate(status=Status.AUTHORITY_ACKNOWLEDGED, detail="logged")

    raw, headers = signed({
        "to": transport.sent[0].reply_to,
        "sender": "ward@example.gov.in",
        "subject": "Re: Civic complaint",
        "body": "Your complaint is registered as BMC/2026/8871.",
    })
    response = await client.post("/webhooks/inbound-mail", content=raw, headers=headers)

    assert response.status_code == 204
    assert await status_of(issue_id) == Status.AUTHORITY_ACKNOWLEDGED
    escalation = await escalation_for(issue_id)
    inbound = [m for m in escalation.messages if m.direction == MessageDirection.INBOUND]
    assert len(inbound) == 1
    assert "BMC/2026/8871" in inbound[0].body


async def test_the_reporter_is_told_there_was_a_reply(client, sender, posted):
    transport, reader = posted
    reporter = await sign_in(client, sender, REPORTER)
    await confirmed_issue(client, sender)
    await escalate_confirmed()

    raw, headers = signed({
        "to": transport.sent[0].reply_to,
        "sender": "ward@example.gov.in",
        "subject": "Re: Civic complaint",
        "body": "Noted.",
    })
    await client.post("/webhooks/inbound-mail", content=raw, headers=headers)

    feed = await client.get("/notifications", headers=auth(reporter))
    kinds = [row["type"] for row in feed.json()["items"]]
    assert "authority_replied" in kinds


async def test_a_reply_nobody_can_place_is_still_kept(client, sender, posted):
    """An auto-reply moves nothing, but the person who complained should still
    get to read what came back."""
    transport, reader = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    reader.update = None

    raw, headers = signed({
        "to": transport.sent[0].reply_to,
        "sender": "noreply@example.gov.in",
        "subject": "Out of office",
        "body": "This mailbox is not monitored.",
    })
    await client.post("/webhooks/inbound-mail", content=raw, headers=headers)

    assert await status_of(issue_id) == Status.SUBMITTED_TO_AUTHORITY
    escalation = await escalation_for(issue_id)
    assert any(m.direction == MessageDirection.INBOUND for m in escalation.messages)


async def test_a_reply_cannot_remove_a_report(client, sender, posted):
    transport, reader = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    reader.update = AuthorityUpdate(status=Status.REMOVED)

    raw, headers = signed({
        "to": transport.sent[0].reply_to,
        "sender": "ward@example.gov.in",
        "subject": "Re",
        "body": "Closing this.",
    })
    await client.post("/webhooks/inbound-mail", content=raw, headers=headers)

    assert await status_of(issue_id) == Status.SUBMITTED_TO_AUTHORITY


async def test_an_unsigned_post_is_refused(client, sender, posted):
    transport, _ = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()

    response = await client.post(
        "/webhooks/inbound-mail",
        json={"to": transport.sent[0].reply_to, "sender": "x@y.z", "subject": "", "body": "Fixed."},
    )

    assert response.status_code == 401
    assert await status_of(issue_id) == Status.SUBMITTED_TO_AUTHORITY


async def test_a_wrongly_signed_post_is_refused(client, sender, posted):
    transport, _ = posted
    await confirmed_issue(client, sender)
    await escalate_confirmed()
    raw, headers = signed({"to": transport.sent[0].reply_to, "sender": "x@y.z",
                           "subject": "", "body": "Fixed."})

    response = await client.post(
        "/webhooks/inbound-mail",
        content=raw,
        headers={**headers, "x-fihy-signature": "0" * 64},
    )

    assert response.status_code == 401


async def test_an_old_post_cannot_be_replayed(client, sender, posted):
    """A bounce captured once used to stay valid forever, and replaying it
    sent a report that had reached BMC back to community_verified."""
    transport, _ = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    raw, headers = signed(
        {"to": transport.sent[0].reply_to, "delivered": False},
        at=time.time() - 3600,
    )

    response = await client.post("/webhooks/mail-events", content=raw, headers=headers)

    assert response.status_code == 401
    assert await status_of(issue_id) == Status.SUBMITTED_TO_AUTHORITY


async def test_a_captured_post_cannot_be_redated(client, sender, posted):
    """The time is inside the signature, so freshening the header breaks it."""
    transport, _ = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    raw, headers = signed(
        {"to": transport.sent[0].reply_to, "delivered": False},
        at=time.time() - 3600,
    )

    response = await client.post(
        "/webhooks/mail-events",
        content=raw,
        headers={**headers, "x-fihy-timestamp": str(int(time.time()))},
    )

    assert response.status_code == 401
    assert await status_of(issue_id) == Status.SUBMITTED_TO_AUTHORITY


async def test_the_same_reply_twice_is_one_reply(client, sender, posted):
    transport, _ = posted
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    raw, headers = signed({
        "to": transport.sent[0].reply_to,
        "sender": "ward@example.gov.in",
        "subject": "Re: Civic complaint",
        "body": "Noted.",
        "message_id": "<8871@bmc.example.gov.in>",
    })

    for _ in range(2):
        response = await client.post("/webhooks/inbound-mail", content=raw, headers=headers)
        assert response.status_code == 204

    escalation = await escalation_for(issue_id)
    inbound = [m for m in escalation.messages if m.direction == MessageDirection.INBOUND]
    assert len(inbound) == 1
    feed = await client.get("/notifications", headers=auth(reporter))
    kinds = [row["type"] for row in feed.json()["items"]]
    assert kinds.count("authority_replied") == 1


async def test_a_reply_to_an_unknown_address_is_ignored(client, sender, posted):
    raw, headers = signed({
        "to": "r.deadbeefdeadbeef@mail.fihy.test",
        "sender": "someone@example.com",
        "subject": "Hello",
        "body": "Wrong address.",
    })

    response = await client.post("/webhooks/inbound-mail", content=raw, headers=headers)

    assert response.status_code == 204, "accepted and dropped, not retried forever"


# --- delivery --------------------------------------------------------------


async def test_a_bounce_stops_the_report_claiming_it_arrived(client, sender, posted):
    transport, _ = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    assert await status_of(issue_id) == Status.SUBMITTED_TO_AUTHORITY

    raw, headers = signed({
        "to": transport.sent[0].reply_to,
        "delivered": False,
        "detail": "550 no such mailbox",
    })
    await client.post("/webhooks/mail-events", content=raw, headers=headers)

    assert await status_of(issue_id) == Status.COMMUNITY_VERIFIED
    escalation = await escalation_for(issue_id)
    assert escalation.state == EscalationState.BOUNCED
    assert escalation.bounced_at is not None
    assert "550" in escalation.detail


async def test_a_delivery_is_recorded(client, sender, posted):
    transport, _ = posted
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()

    raw, headers = signed({"to": transport.sent[0].reply_to, "delivered": True})
    await client.post("/webhooks/mail-events", content=raw, headers=headers)

    escalation = await escalation_for(issue_id)
    assert escalation.delivered_at is not None
    assert escalation.state == EscalationState.SENT
    assert await status_of(issue_id) == Status.SUBMITTED_TO_AUTHORITY
