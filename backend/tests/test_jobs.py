"""The crons, with the drafter and the channel swapped for fakes.

Nothing here calls a model or sends anything.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app import authority as authority_module
from app.authority import AuthorityChannel, AuthorityUpdate, ConcernDrafter, ConcernRequest
from app.enums import EscalationState, Status
from app.jobs import check_submitted, escalate_confirmed
from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"


def report_id() -> str:
    return str(uuid.uuid4())


class Drafter(ConcernDrafter):
    def __init__(self, text: str | None = "There is an open manhole. Please inspect.") -> None:
        self.text = text
        self.seen: list[ConcernRequest] = []

    async def draft(self, request: ConcernRequest) -> str | None:
        self.seen.append(request)
        return self.text


class Channel(AuthorityChannel):
    name = "fake"

    def __init__(self, reference: str | None = "TICKET-1", update: AuthorityUpdate | None = None):
        self.reference = reference
        self.update = update
        self.sent: list[tuple[str, str]] = []
        self.checked: list[str] = []

    async def send(self, subject, body, request):
        self.sent.append((subject, body))
        return self.reference

    async def check(self, reference):
        self.checked.append(reference)
        return self.update


class Exploding(AuthorityChannel):
    async def send(self, subject, body, request):
        raise RuntimeError("the portal is down")

    async def check(self, reference):
        raise RuntimeError("the portal is down")


@pytest.fixture
def wired(monkeypatch):
    """A drafter and a channel that both work, and no waiting period."""
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    get_settings.cache_clear()
    drafter, channel = Drafter(), Channel()
    authority_module.set_drafter(drafter)
    authority_module.set_channel(channel)
    yield drafter, channel
    authority_module.set_drafter(None)
    authority_module.set_channel(None)
    monkeypatch.delenv("ESCALATE_AFTER_HOURS", raising=False)
    get_settings.cache_clear()


async def confirmed_issue(client, sender, phones=(NEIGHBOUR, THIRD)) -> str:
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    for phone in phones:
        token = await sign_in(client, sender, phone)
        await client.post(
            f"/issues/{issue_id}/supports",
            headers=auth(token),
            data={"body": f"Still open, {phone}.", **HERE},
            files=[("photos", ("p.jpg", jpeg_bytes(320, 240), "image/jpeg"))],
        )
    return issue_id


async def load(issue_id):
    from app.db import sessionmaker
    from app.models import Escalation, Issue

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        escalation = await session.scalar(
            select(Escalation).where(Escalation.issue_id == issue_id)
        )
        return issue.status, escalation


# --- escalate --------------------------------------------------------------


async def test_a_confirmed_report_is_raised(client, sender, wired):
    drafter, channel = wired
    issue_id = await confirmed_issue(client, sender)

    result = await escalate_confirmed()

    assert (result.considered, result.sent, result.moved) == (1, 1, 1)
    status, escalation = await load(issue_id)
    assert status == Status.SUBMITTED_TO_AUTHORITY
    assert escalation.state == EscalationState.SENT
    assert escalation.reference == "TICKET-1"
    assert escalation.sent_at is not None
    assert escalation.body == "There is an open manhole. Please inspect."
    assert "Civic complaint" in escalation.subject
    assert issue_id[:8] in escalation.subject


async def test_the_draft_sees_the_evidence(client, sender, wired):
    drafter, _ = wired
    await confirmed_issue(client, sender)

    await escalate_confirmed()

    request = drafter.seen[0]
    assert request.photo_support_count == 2
    assert request.seen_count == 2
    assert len(request.voices) == 2
    assert request.confirmed_on


async def test_an_unconfirmed_report_is_left_alone(client, sender, wired):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(f"/issues/{issue_id}/confirmations", headers=auth(neighbour))

    result = await escalate_confirmed()

    assert result.considered == 0
    assert (await load(issue_id))[0] == Status.REPORTED


async def test_a_report_waits_out_the_window_first(client, sender, monkeypatch):
    """Confirmed an hour ago, and the community may still be adding to it."""
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "24")
    get_settings.cache_clear()
    authority_module.set_drafter(Drafter())
    authority_module.set_channel(Channel())
    try:
        await confirmed_issue(client, sender)
        assert (await escalate_confirmed()).considered == 0
    finally:
        authority_module.set_drafter(None)
        authority_module.set_channel(None)
        monkeypatch.delenv("ESCALATE_AFTER_HOURS", raising=False)
        get_settings.cache_clear()


async def test_running_twice_raises_it_once(client, sender, wired):
    _, channel = wired
    await confirmed_issue(client, sender)

    first = await escalate_confirmed()
    second = await escalate_confirmed()

    assert first.sent == 1
    assert second.considered == 0, "already raised, so not a candidate"
    assert len(channel.sent) == 1


async def test_with_no_channel_nothing_is_claimed_to_have_been_sent(client, sender, monkeypatch):
    """The default. A letter with nowhere to go must not move the status."""
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    get_settings.cache_clear()
    authority_module.set_drafter(Drafter())
    authority_module.set_channel(None)
    try:
        issue_id = await confirmed_issue(client, sender)
        result = await escalate_confirmed()

        assert result.drafted == 1
        assert result.sent == 0
        assert result.failed == 1
        status, escalation = await load(issue_id)
        assert status == Status.COMMUNITY_VERIFIED, "it reached nobody"
        assert escalation.state == EscalationState.DRAFTED
        assert escalation.body, "the draft is kept so a person can read it"
    finally:
        authority_module.set_drafter(None)
        monkeypatch.delenv("ESCALATE_AFTER_HOURS", raising=False)
        get_settings.cache_clear()


async def test_with_no_drafter_the_claim_is_released(client, sender, monkeypatch):
    """So a later run, once a key is configured, can pick it up."""
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    get_settings.cache_clear()
    authority_module.set_drafter(Drafter(text=None))
    authority_module.set_channel(Channel())
    try:
        issue_id = await confirmed_issue(client, sender)
        result = await escalate_confirmed()

        assert result.drafted == 0
        assert result.skipped == 1
        status, escalation = await load(issue_id)
        assert status == Status.COMMUNITY_VERIFIED
        assert escalation is None, "nothing half-written is left behind"

        authority_module.set_drafter(Drafter())
        assert (await escalate_confirmed()).sent == 1
    finally:
        authority_module.set_drafter(None)
        authority_module.set_channel(None)
        monkeypatch.delenv("ESCALATE_AFTER_HOURS", raising=False)
        get_settings.cache_clear()


async def test_a_channel_that_throws_is_recorded_not_lost(client, sender, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    get_settings.cache_clear()
    authority_module.set_drafter(Drafter())
    authority_module.set_channel(Exploding())
    try:
        issue_id = await confirmed_issue(client, sender)
        result = await escalate_confirmed()

        assert result.failed == 1
        status, escalation = await load(issue_id)
        assert status == Status.COMMUNITY_VERIFIED
        assert escalation.state == EscalationState.FAILED
        assert "portal is down" in escalation.detail
    finally:
        authority_module.set_drafter(None)
        authority_module.set_channel(None)
        monkeypatch.delenv("ESCALATE_AFTER_HOURS", raising=False)
        get_settings.cache_clear()


async def test_the_reporter_is_told_it_was_raised(client, sender, wired):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await confirmed_issue(client, sender)

    await escalate_confirmed()

    feed = await client.get("/notifications", headers=auth(reporter))
    moves = [
        row
        for row in feed.json()["items"]
        if row["type"] == "status_changed"
        and row["to_status"] == "submitted_to_authority"
    ]
    assert len(moves) == 1
    assert moves[0]["issue"]["id"] == issue_id


async def test_the_batch_is_capped(client, sender, wired):
    _, channel = wired
    for i in range(3):
        reporter = await sign_in(client, sender, REPORTER)
        issue_id = (
            await create_issue(client, reporter, report_id=report_id(), title=f"Report {i} here")
        ).json()["id"]
        for phone in (NEIGHBOUR, THIRD):
            token = await sign_in(client, sender, phone)
            await client.post(
                f"/issues/{issue_id}/supports",
                headers=auth(token),
                data={"body": "", **HERE},
                files=[("photos", ("p.jpg", jpeg_bytes(320, 240), "image/jpeg"))],
            )

    result = await escalate_confirmed(limit=2)

    assert result.sent == 2
    assert len(channel.sent) == 2
    assert (await escalate_confirmed(limit=2)).sent == 1


# --- check -----------------------------------------------------------------


async def test_a_claimed_fix_moves_the_report(client, sender, wired):
    _, channel = wired
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    channel.update = AuthorityUpdate(status=Status.RESOLVED, detail="Repaired 12 Sept.")

    result = await check_submitted()

    assert (result.considered, result.moved) == (1, 1)
    status, escalation = await load(issue_id)
    assert status == Status.RESOLVED
    assert escalation.detail == "Repaired 12 Sept."
    assert escalation.checked_at is not None


async def test_no_news_moves_nothing(client, sender, wired):
    _, channel = wired
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()
    channel.update = None

    result = await check_submitted()

    assert result.skipped == 1
    assert result.moved == 0
    status, escalation = await load(issue_id)
    assert status == Status.SUBMITTED_TO_AUTHORITY
    assert escalation.checked_at is not None, "asked, and told nothing"


async def test_an_authority_cannot_remove_a_report(client, sender, wired):
    """Forward is theirs to set. Removing one, or calling it a duplicate, is
    moderation, and a municipal portal does not get to do that here."""
    _, channel = wired
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()

    for forbidden in (Status.REMOVED, Status.DUPLICATE, Status.REPORTED):
        channel.update = AuthorityUpdate(status=forbidden)
        result = await check_submitted()
        assert result.moved == 0, forbidden
        assert (await load(issue_id))[0] == Status.SUBMITTED_TO_AUTHORITY


async def test_progress_is_followed_through(client, sender, wired):
    _, channel = wired
    issue_id = await confirmed_issue(client, sender)
    await escalate_confirmed()

    for step in (
        Status.AUTHORITY_ACKNOWLEDGED,
        Status.IN_PROGRESS,
        Status.RESOLUTION_CLAIMED,
        Status.RESOLVED,
    ):
        channel.update = AuthorityUpdate(status=step)
        await check_submitted()
        assert (await load(issue_id))[0] == step


async def test_a_finished_report_is_not_asked_about_again(client, sender, wired):
    _, channel = wired
    await confirmed_issue(client, sender)
    await escalate_confirmed()
    channel.update = AuthorityUpdate(status=Status.RESOLVED)
    await check_submitted()

    result = await check_submitted()

    assert result.considered == 0


async def test_a_report_that_never_sent_is_not_checked(client, sender, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    get_settings.cache_clear()
    channel = Channel(reference=None)
    authority_module.set_drafter(Drafter())
    authority_module.set_channel(channel)
    try:
        await confirmed_issue(client, sender)
        await escalate_confirmed()

        assert (await check_submitted()).considered == 0
        assert channel.checked == []
    finally:
        authority_module.set_drafter(None)
        authority_module.set_channel(None)
        monkeypatch.delenv("ESCALATE_AFTER_HOURS", raising=False)
        get_settings.cache_clear()


async def test_a_check_that_throws_does_not_stop_the_batch(client, sender, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ESCALATE_AFTER_HOURS", "0")
    get_settings.cache_clear()
    authority_module.set_drafter(Drafter())
    authority_module.set_channel(Channel())
    try:
        await confirmed_issue(client, sender)
        await escalate_confirmed()
        authority_module.set_channel(Exploding())

        result = await check_submitted()

        assert result.failed == 1
        assert result.moved == 0
    finally:
        authority_module.set_drafter(None)
        authority_module.set_channel(None)
        monkeypatch.delenv("ESCALATE_AFTER_HOURS", raising=False)
        get_settings.cache_clear()
