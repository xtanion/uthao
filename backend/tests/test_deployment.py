"""Account deletion, write limits, pruning, and the boot guards."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.jobs import prune_otp
from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"


def report_id() -> str:
    return str(uuid.uuid4())


async def photo_support(client, token, issue_id, body=""):
    return await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(token),
        data={"body": body, **HERE},
        files=[("photos", ("p.jpg", jpeg_bytes(320, 240), "image/jpeg"))],
    )


async def load_user(user_id):
    from app.db import sessionmaker
    from app.models import User

    async with sessionmaker()() as session:
        return await session.scalar(select(User).where(User.id == user_id))


async def me(client, token):
    return (await client.get("/me", headers=auth(token))).json()["id"]


# --- account deletion ------------------------------------------------------


async def test_deleting_an_account_ends_the_session(client, sender):
    token = await sign_in(client, sender, REPORTER)

    assert (await client.delete("/me", headers=auth(token))).status_code == 204

    # The token is still cryptographically valid for another 30 days.
    assert (await client.get("/me", headers=auth(token))).status_code == 401


async def test_a_deleted_account_cannot_refresh_its_way_back_in(client, sender):
    await client.post("/auth/otp/request", json={"phone": REPORTER})
    verified = await client.post(
        "/auth/otp/verify", json={"phone": REPORTER, "code": sender.codes[REPORTER]}
    )
    tokens = verified.json()
    await client.delete("/me", headers=auth(tokens["access_token"]))

    response = await client.post(
        "/auth/token/refresh", json={"refresh_token": tokens["refresh_token"]}
    )

    assert response.status_code == 401


async def test_the_phone_number_is_gone_and_reusable(client, sender):
    token = await sign_in(client, sender, REPORTER)
    old = await me(client, token)
    await client.delete("/me", headers=auth(token))

    row = await load_user(old)
    assert row.phone == f"deleted:{old}"
    assert row.display_name == "Removed resident"
    assert row.deleted_at is not None

    # And the number can start a fresh account, which it could not if the row
    # still held it.
    again = await sign_in(client, sender, REPORTER)
    assert await me(client, again) != old


async def test_their_support_stays_so_nobody_elses_report_weakens(client, sender):
    """The point of anonymising rather than cascading: two people really did
    photograph that manhole, and one of them leaving does not undo it."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    for phone in (NEIGHBOUR, THIRD):
        token = await sign_in(client, sender, phone)
        await photo_support(client, token, issue_id, body=f"Seen, {phone}.")
    leaver = await sign_in(client, sender, NEIGHBOUR)

    await client.delete("/me", headers=auth(leaver))

    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["photo_support_count"] == 2
    assert detail["status"] == "community_verified"
    assert detail["confirmed_at"] is not None


async def test_their_words_survive_credited_to_nobody(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await photo_support(client, neighbour, issue_id, body="A branch is stuck in it.")

    await client.delete("/me", headers=auth(neighbour))

    thread = (await client.get(f"/issues/{issue_id}/supports")).json()
    row = thread["items"][0]
    assert row["body"] == "A branch is stuck in it."
    assert row["author"]["display_name"] == "Removed resident"


async def test_their_own_reports_stay(client, sender):
    """Other people added photographs and replies to them."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    await client.delete("/me", headers=auth(reporter))

    detail = await client.get(f"/issues/{issue_id}")
    assert detail.status_code == 200
    assert detail.json()["reporter"]["display_name"] == "Removed resident"


async def test_their_notification_feed_is_destroyed(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await photo_support(client, neighbour, issue_id)
    assert (await client.get("/notifications", headers=auth(reporter))).json()["items"]
    mine = await me(client, reporter)

    await client.delete("/me", headers=auth(reporter))

    from app.db import sessionmaker
    from app.models import ActivityEvent

    async with sessionmaker()() as session:
        left = await session.scalars(
            select(ActivityEvent).where(ActivityEvent.user_id == mine)
        )
        assert list(left) == []


async def test_they_are_unnamed_as_an_actor_elsewhere(client, sender):
    """The event belongs to the recipient, but naming this person on it does
    not, so the row stays and the reference goes."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await photo_support(client, neighbour, issue_id)

    await client.delete("/me", headers=auth(neighbour))

    feed = (await client.get("/notifications", headers=auth(reporter))).json()
    row = next(r for r in feed["items"] if r["type"] == "support_received")
    assert row["actor_name"] is None


async def test_their_offer_to_turn_up_is_withdrawn(client, sender):
    from tests.test_fix_dates import a_confirmed_issue, open_the_window, propose
    from datetime import date

    issue_id = await a_confirmed_issue(client, sender)
    await open_the_window(issue_id)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await propose(client, neighbour, issue_id, date.today() + timedelta(days=3))

    await client.delete("/me", headers=auth(neighbour))

    board = (await client.get(f"/issues/{issue_id}/fix-dates")).json()
    assert board["items"] == [], "they are not coming"


async def test_signing_in_is_required_to_delete(client):
    assert (await client.delete("/me")).status_code == 401


# --- write limits ----------------------------------------------------------


async def test_reports_are_capped_per_hour(client, sender, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("REPORTS_PER_USER_PER_HOUR", "2")
    get_settings.cache_clear()
    try:
        token = await sign_in(client, sender, REPORTER)
        for i in range(2):
            fine = await create_issue(
                client, token, report_id=report_id(), title=f"Report {i} on this road"
            )
            assert fine.status_code == 201

        refused = await create_issue(client, token, report_id=report_id())

        assert refused.status_code == 429
        assert "2 reports in an hour" in refused.json()["detail"]
    finally:
        monkeypatch.delenv("REPORTS_PER_USER_PER_HOUR", raising=False)
        get_settings.cache_clear()


async def test_supports_are_capped_per_hour(client, sender, monkeypatch):
    from app.config import get_settings

    reporter = await sign_in(client, sender, REPORTER)
    ids = [
        (await create_issue(client, reporter, report_id=report_id(), title=f"Report {i} here")).json()["id"]
        for i in range(3)
    ]
    monkeypatch.setenv("SUPPORTS_PER_USER_PER_HOUR", "2")
    get_settings.cache_clear()
    try:
        neighbour = await sign_in(client, sender, NEIGHBOUR)
        for issue_id in ids[:2]:
            assert (await photo_support(client, neighbour, issue_id)).status_code == 200

        refused = await photo_support(client, neighbour, ids[2])

        assert refused.status_code == 429
    finally:
        monkeypatch.delenv("SUPPORTS_PER_USER_PER_HOUR", raising=False)
        get_settings.cache_clear()


async def test_the_cap_is_per_person(client, sender, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("REPORTS_PER_USER_PER_HOUR", "1")
    get_settings.cache_clear()
    try:
        first = await sign_in(client, sender, REPORTER)
        await create_issue(client, first, report_id=report_id())
        assert (await create_issue(client, first, report_id=report_id())).status_code == 429

        second = await sign_in(client, sender, NEIGHBOUR)
        assert (await create_issue(client, second, report_id=report_id())).status_code == 201
    finally:
        monkeypatch.delenv("REPORTS_PER_USER_PER_HOUR", raising=False)
        get_settings.cache_clear()


# --- pruning ---------------------------------------------------------------


async def test_spent_otp_rows_are_pruned(client, sender):
    from app.db import sessionmaker
    from app.models import OtpChallenge, OtpRequestLog

    await sign_in(client, sender, REPORTER)
    async with sessionmaker()() as session:
        assert (await session.scalars(select(OtpChallenge))).all()
        old = datetime.now(timezone.utc) - timedelta(days=30)
        for row in (await session.scalars(select(OtpChallenge))).all():
            row.created_at = old
        for row in (await session.scalars(select(OtpRequestLog))).all():
            row.created_at = old
        await session.commit()

    result = await prune_otp()

    assert result.considered >= 2
    async with sessionmaker()() as session:
        assert (await session.scalars(select(OtpChallenge))).all() == []
        assert (await session.scalars(select(OtpRequestLog))).all() == []


async def test_recent_otp_rows_are_left_alone(client, sender):
    from app.db import sessionmaker
    from app.models import OtpChallenge

    await sign_in(client, sender, REPORTER)

    await prune_otp()

    async with sessionmaker()() as session:
        assert (await session.scalars(select(OtpChallenge))).all(), "still inside the window"


# --- boot guards -----------------------------------------------------------


def test_a_deployment_without_r2_refuses_to_start(monkeypatch):
    """Photos would go to the container's own disk and vanish on the next
    deploy, which is worse than not starting."""
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "a-real-secret-key-for-this-test-only")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="R2 is not configured"):
            create_app()
    finally:
        for key in ("ENVIRONMENT", "SECRET_KEY", "R2_ACCESS_KEY_ID"):
            monkeypatch.delenv(key, raising=False)
        get_settings.cache_clear()


def test_the_docs_are_closed_outside_development(monkeypatch):
    from app.config import get_settings
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "a-real-secret-key-for-this-test-only")
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert app.docs_url is None
        assert app.openapi_url is None
    finally:
        for key in (
            "ENVIRONMENT", "SECRET_KEY", "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY",
        ):
            monkeypatch.delenv(key, raising=False)
        get_settings.cache_clear()


async def test_health_reports_the_database(client):
    body = (await client.get("/health")).json()

    assert body["status"] == "ok"
    assert body["database"] == "up"
    assert body["storage"] == "local"
    assert body["mail"] == "off"
