import uuid
from datetime import date, datetime, timedelta, timezone

from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
OTHERS = ["+919876500001", "+919876500002", "+919876500003", "+919876500004"]


def report_id() -> str:
    return str(uuid.uuid4())


async def open_poll(client, sender) -> tuple[str, str]:
    """A confirmed report whose contributions window has already passed."""
    from sqlalchemy import select

    from app.config import get_settings
    from app.db import sessionmaker
    from app.models import Issue

    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    bar = get_settings().photo_supports_to_confirm
    for phone in OTHERS[:bar]:
        token = await sign_in(client, sender, phone)
        await client.post(
            f"/issues/{issue_id}/supports",
            headers=auth(token),
            data={"body": "Saw it too.", **HERE},
            files=[("photos", ("p.jpg", jpeg_bytes(400, 300), "image/jpeg"))],
        )

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        assert issue.confirmed_at is not None
        issue.confirmed_at = datetime.now(timezone.utc) - timedelta(days=30)
        await session.commit()

    board = await client.get(f"/issues/{issue_id}/fix-dates")
    assert board.json()["open"] is True, board.text
    return issue_id, reporter


def soon(days: int = 3) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


async def test_a_day_can_carry_a_time(client, sender):
    issue_id, _ = await open_poll(client, sender)
    token = await sign_in(client, sender, OTHERS[0])

    response = await client.post(
        f"/issues/{issue_id}/fix-dates",
        headers=auth(token),
        json={"fix_on": soon(), "fix_time": "09:30"},
    )

    row = response.json()["items"][0]
    assert response.status_code == 200, response.text
    assert row["fix_on"] == soon()
    assert row["fix_time"] == "09:30"


async def test_a_day_without_a_time_is_still_allowed(client, sender):
    issue_id, _ = await open_poll(client, sender)
    token = await sign_in(client, sender, OTHERS[0])

    response = await client.post(
        f"/issues/{issue_id}/fix-dates", headers=auth(token), json={"fix_on": soon()}
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["fix_time"] is None


async def test_agreeing_to_a_day_keeps_the_hour_that_was_set(client, sender):
    issue_id, _ = await open_poll(client, sender)
    first = await sign_in(client, sender, OTHERS[0])
    await client.post(
        f"/issues/{issue_id}/fix-dates",
        headers=auth(first),
        json={"fix_on": soon(), "fix_time": "07:00"},
    )

    second = await sign_in(client, sender, OTHERS[1])
    response = await client.post(
        f"/issues/{issue_id}/fix-dates",
        headers=auth(second),
        json={"fix_on": soon(), "fix_time": "18:45"},
    )

    board = response.json()
    # One day, not two, and the hour belongs to whoever put the day up.
    assert len(board["items"]) == 1
    assert board["items"][0]["fix_time"] == "07:00"
    assert board["items"][0]["vote_count"] == 2


async def test_going_names_the_people_who_said_yes(client, sender):
    issue_id, _ = await open_poll(client, sender)
    proposer = await sign_in(client, sender, OTHERS[0])
    await client.post(
        f"/issues/{issue_id}/fix-dates",
        headers=auth(proposer),
        json={"fix_on": soon(), "fix_time": "10:00"},
    )
    row_id = (await client.get(f"/issues/{issue_id}/fix-dates")).json()["items"][0]["id"]

    for phone in OTHERS[1:3]:
        token = await sign_in(client, sender, phone)
        await client.post(
            f"/issues/{issue_id}/fix-dates/{row_id}/votes", headers=auth(token), json={}
        )

    row = (await client.get(f"/issues/{issue_id}/fix-dates")).json()["items"][0]
    names = {person["display_name"] for person in row["going"]}
    assert row["vote_count"] == 3
    assert len(row["going"]) == 3
    # The proposer counts as going, and every name carries an id to link on.
    assert "Resident 0001" in names
    assert all(person["id"] for person in row["going"])


async def test_withdrawing_removes_you_from_going(client, sender):
    issue_id, _ = await open_poll(client, sender)
    proposer = await sign_in(client, sender, OTHERS[0])
    await client.post(
        f"/issues/{issue_id}/fix-dates",
        headers=auth(proposer),
        json={"fix_on": soon()},
    )
    row_id = (await client.get(f"/issues/{issue_id}/fix-dates")).json()["items"][0]["id"]
    other = await sign_in(client, sender, OTHERS[1])
    await client.post(
        f"/issues/{issue_id}/fix-dates/{row_id}/votes", headers=auth(other), json={}
    )

    await client.delete(
        f"/issues/{issue_id}/fix-dates/{row_id}/votes", headers=auth(other)
    )

    row = (await client.get(f"/issues/{issue_id}/fix-dates")).json()["items"][0]
    assert row["vote_count"] == 1
    assert [p["display_name"] for p in row["going"]] == ["Resident 0001"]


async def test_going_is_present_but_empty_before_anyone_says_yes(client, sender):
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.models import FixDate, FixDateVote

    issue_id, _ = await open_poll(client, sender)
    token = await sign_in(client, sender, OTHERS[0])
    await client.post(
        f"/issues/{issue_id}/fix-dates", headers=auth(token), json={"fix_on": soon()}
    )

    # Strip the proposer's implicit vote to reach the empty case.
    async with sessionmaker()() as session:
        row = await session.scalar(select(FixDate).where(FixDate.issue_id == issue_id))
        for vote in list(row.votes):
            await session.delete(vote)
        row.vote_count = 0
        await session.commit()

    board = (await client.get(f"/issues/{issue_id}/fix-dates")).json()
    assert board["items"][0]["going"] == []


async def test_a_bad_time_is_rejected_readably(client, sender):
    issue_id, _ = await open_poll(client, sender)
    token = await sign_in(client, sender, OTHERS[0])

    response = await client.post(
        f"/issues/{issue_id}/fix-dates",
        headers=auth(token),
        json={"fix_on": soon(), "fix_time": "half past nine"},
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
