import uuid
from datetime import date, timedelta

from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"
FOURTH = "+919876500003"


def report_id() -> str:
    return str(uuid.uuid4())


async def photo_support(client, token, issue_id, body=""):
    return await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(token),
        data={"body": body, **HERE},
        files=[("photos", ("p.jpg", jpeg_bytes(320, 240), "image/jpeg"))],
    )


async def a_confirmed_issue(client, sender, phones=(NEIGHBOUR, THIRD)) -> str:
    """Two people other than the reporter, each with a photo."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    for phone in phones:
        token = await sign_in(client, sender, phone)
        assert (await photo_support(client, token, issue_id)).status_code == 200
    return issue_id


async def open_the_window(issue_id: str, days_ago: float = 6) -> None:
    """Wind the confirmation back so the contributions window has elapsed."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db import sessionmaker
    from app.models import Issue

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.confirmed_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
        await session.commit()


async def hand_to_the_authority(issue_id: str) -> None:
    """Where the escalation job leaves a report it has written to BMC about."""
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.enums import Status
    from app.models import Issue

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.status = Status.SUBMITTED_TO_AUTHORITY
        await session.commit()


async def poll(client, issue_id, token=None):
    response = await client.get(
        f"/issues/{issue_id}/fix-dates", headers=auth(token) if token else {}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def propose(client, token, issue_id, when: date):
    return await client.post(
        f"/issues/{issue_id}/fix-dates",
        headers=auth(token),
        json={"fix_on": when.isoformat()},
    )


# --- the clock -------------------------------------------------------------


async def test_one_photo_support_is_not_yet_confirmed(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    body = (await photo_support(client, neighbour, issue_id)).json()

    assert body["photo_support_count"] == 1
    assert body["confirmed_at"] is None
    assert body["contributions_open_at"] is None


async def test_the_second_photo_support_starts_the_clock(client, sender):
    issue_id = await a_confirmed_issue(client, sender)

    detail = (await client.get(f"/issues/{issue_id}")).json()

    assert detail["photo_support_count"] == 2
    assert detail["status"] == "community_verified"
    assert detail["confirmed_at"], "the moment it crossed is recorded"
    assert detail["contributions_open_at"] > detail["confirmed_at"]


async def test_the_reporters_own_photos_do_not_confirm(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    for _ in range(2):
        await photo_support(client, reporter, issue_id, body="Another angle.")

    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["photo_support_count"] == 0
    assert detail["confirmed_at"] is None


async def test_losing_the_evidence_stops_the_clock(client, sender):
    """A report that loses a photo support loses its head start too."""
    issue_id = await a_confirmed_issue(client, sender)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await client.delete(f"/issues/{issue_id}/supports", headers=auth(neighbour))

    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["photo_support_count"] == 1
    assert detail["confirmed_at"] is None
    assert detail["status"] == "reported"


async def test_reconfirming_restarts_the_clock(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    first = (await client.get(f"/issues/{issue_id}")).json()["confirmed_at"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.delete(f"/issues/{issue_id}/supports", headers=auth(neighbour))

    fourth = await sign_in(client, sender, FOURTH)
    await photo_support(client, fourth, issue_id)

    again = (await client.get(f"/issues/{issue_id}")).json()["confirmed_at"]
    assert again >= first, "the window counts from the new crossing"


async def test_a_report_with_the_authority_keeps_its_clock(client, sender):
    """A withdrawn photo does not un-send a report, so the days people have
    committed to stay up and nobody is asked to corroborate it again."""
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    await hand_to_the_authority(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    when = date.today() + timedelta(days=3)
    assert (await propose(client, neighbour, issue_id, when)).status_code == 200

    third = await sign_in(client, sender, THIRD)
    await client.delete(f"/issues/{issue_id}/supports", headers=auth(third))

    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["status"] == "submitted_to_authority"
    assert detail["confirmed_at"] is not None
    assert detail["photo_supports_needed"] == 0
    board = await poll(client, issue_id)
    assert board["open"] is True
    assert [row["fix_on"] for row in board["items"]] == [when.isoformat()]


# --- the poll --------------------------------------------------------------


async def test_the_poll_is_shut_before_the_window(client, sender):
    issue_id = await a_confirmed_issue(client, sender)

    board = await poll(client, issue_id)

    assert board["open"] is False
    assert board["opens_at"], "readable, so people can see what is coming"
    assert board["items"] == []


async def test_proposing_before_the_window_is_refused(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await propose(client, neighbour, issue_id, date.today() + timedelta(days=2))

    assert response.status_code == 409
    assert "not open" in response.json()["detail"]


async def test_a_day_is_proposed_and_counts_as_a_vote(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    when = date.today() + timedelta(days=3)

    response = await propose(client, neighbour, issue_id, when)

    board = response.json()
    assert response.status_code == 200, response.text
    assert board["open"] is True
    assert len(board["items"]) == 1
    row = board["items"][0]
    assert row["fix_on"] == when.isoformat()
    assert row["vote_count"] == 1, "putting a day up is saying you will be there"
    assert row["voted_by_me"] is True
    assert row["mine"] is True
    assert board["proposed_by_me"] is True
    assert board["remaining_slots"] == 4


async def test_one_proposal_per_person(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await propose(client, neighbour, issue_id, date.today() + timedelta(days=3))

    second = await propose(client, neighbour, issue_id, date.today() + timedelta(days=4))

    assert second.status_code == 409
    assert "already put a day forward" in second.json()["detail"]


async def test_proposing_a_day_already_up_backs_it_instead(client, sender):
    """Two people wanting the same Saturday is agreement, not a collision."""
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    third = await sign_in(client, sender, THIRD)
    when = date.today() + timedelta(days=3)
    await propose(client, neighbour, issue_id, when)

    board = (await propose(client, third, issue_id, when)).json()

    assert len(board["items"]) == 1
    assert board["items"][0]["vote_count"] == 2
    assert board["proposed_by_me"] is False, "their one proposal is unspent"


async def test_voting_is_unlimited(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    third = await sign_in(client, sender, THIRD)
    await propose(client, neighbour, issue_id, date.today() + timedelta(days=3))
    await propose(client, third, issue_id, date.today() + timedelta(days=4))

    fourth = await sign_in(client, sender, FOURTH)
    board = await poll(client, issue_id, fourth)
    for row in board["items"]:
        response = await client.post(
            f"/issues/{issue_id}/fix-dates/{row['id']}/votes", headers=auth(fourth)
        )
        assert response.status_code == 200, response.text

    final = await poll(client, issue_id, fourth)
    assert [r["vote_count"] for r in final["items"]] == [2, 2]
    assert all(r["voted_by_me"] for r in final["items"])
    assert final["proposed_by_me"] is False


async def test_a_vote_can_be_taken_back(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    third = await sign_in(client, sender, THIRD)
    board = (await propose(client, neighbour, issue_id, date.today() + timedelta(days=3))).json()
    row_id = board["items"][0]["id"]
    await client.post(f"/issues/{issue_id}/fix-dates/{row_id}/votes", headers=auth(third))

    dropped = await client.delete(
        f"/issues/{issue_id}/fix-dates/{row_id}/votes", headers=auth(third)
    )

    assert dropped.json()["items"][0]["vote_count"] == 1


async def test_the_proposer_pulling_out_takes_the_day_with_them(client, sender):
    """A day nobody is coming to is noise, and they have just said they are not
    coming either."""
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    board = (await propose(client, neighbour, issue_id, date.today() + timedelta(days=3))).json()
    row_id = board["items"][0]["id"]

    dropped = await client.delete(
        f"/issues/{issue_id}/fix-dates/{row_id}/votes", headers=auth(neighbour)
    )

    assert dropped.json()["items"] == []
    assert dropped.json()["proposed_by_me"] is False, "their proposal is free again"


async def test_five_days_is_the_ceiling(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)

    for i in range(5):
        token = await sign_in(client, sender, f"+91987660{i:04d}")
        response = await propose(client, token, issue_id, date.today() + timedelta(days=i + 1))
        assert response.status_code == 200, response.text
    assert response.json()["remaining_slots"] == 0

    sixth = await sign_in(client, sender, "+919876609999")
    refused = await propose(client, sixth, issue_id, date.today() + timedelta(days=9))

    assert refused.status_code == 409
    assert "already 5 days" in refused.json()["detail"]


async def test_a_day_that_has_gone_is_refused(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await propose(client, neighbour, issue_id, date.today() - timedelta(days=1))

    assert response.status_code == 409
    assert "already gone" in response.json()["detail"]


async def test_days_come_back_soonest_first(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    for i, offset in enumerate((9, 2, 5)):
        token = await sign_in(client, sender, f"+91987661{i:04d}")
        await propose(client, token, issue_id, date.today() + timedelta(days=offset))

    board = await poll(client, issue_id)

    days = [row["fix_on"] for row in board["items"]]
    assert days == sorted(days)


async def test_signing_in_is_required_to_propose(client, sender):
    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)

    response = await client.post(
        f"/issues/{issue_id}/fix-dates",
        json={"fix_on": (date.today() + timedelta(days=2)).isoformat()},
    )

    assert response.status_code == 401


async def test_voting_on_a_day_from_another_report(client, sender):
    first = await a_confirmed_issue(client, sender)
    await open_the_window(first)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    board = (await propose(client, neighbour, first, date.today() + timedelta(days=3))).json()
    other = await a_confirmed_issue(client, sender, phones=(THIRD, FOURTH))
    await open_the_window(other)

    response = await client.post(
        f"/issues/{other}/fix-dates/{board['items'][0]['id']}/votes",
        headers=auth(neighbour),
    )

    assert response.status_code == 404
