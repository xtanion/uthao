"""Push notifications, with Expo swapped for a recorder.

Nothing here reaches the network.
"""
import json
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select, update

from app import push
from app.db import sessionmaker
from app.models import ActivityEvent, PushToken, utcnow
from tests.conftest import auth, create_issue, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
TOKEN = "ExponentPushToken[reporter-phone]"
OTHER_TOKEN = "ExponentPushToken[second-phone]"


def report_id() -> str:
    return str(uuid.uuid4())


class Recorder(push.PushSender):
    def __init__(self, outcome: str | None = None, explode: bool = False) -> None:
        self.outcome = outcome
        self.explode = explode
        self.sent: list[push.PushMessage] = []

    async def send(self, messages):
        if self.explode:
            raise RuntimeError("expo is down")
        self.sent.extend(messages)
        return [self.outcome for _ in messages]


@pytest.fixture
def recorder(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PUSH_ENABLED", "true")
    get_settings.cache_clear()
    recording = Recorder()
    push.set_sender(recording)
    yield recording
    push.set_sender(None)
    monkeypatch.delenv("PUSH_ENABLED", raising=False)
    get_settings.cache_clear()


async def register(client, token: str, push_token: str = TOKEN, platform: str = "ios"):
    return await client.put(
        "/me/push-tokens",
        headers=auth(token),
        json={"token": push_token, "platform": platform},
    )


async def backed_issue(client, sender) -> tuple[str, str]:
    """A report the neighbour has backed, so the reporter has one activity row."""
    reporter = await sign_in(client, sender, REPORTER)
    assert (await register(client, reporter)).status_code == 204
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    response = await client.post(
        f"/issues/{issue_id}/supports", headers=auth(neighbour), data={"body": "Saw it too"}
    )
    assert response.status_code in (200, 201), response.text
    await push.drain()
    return reporter, issue_id


async def tokens() -> list[PushToken]:
    async with sessionmaker()() as session:
        return list((await session.scalars(select(PushToken))).all())


async def test_a_support_is_pushed_to_the_reporter(client, sender, recorder):
    _, issue_id = await backed_issue(client, sender)

    assert len(recorder.sent) == 1
    message = recorder.sent[0]
    assert message.to == TOKEN
    assert message.title == "Cover missing on the footpath side"
    assert message.body == "Hooman 0001 independently saw this"
    assert message.data["issue_id"] == issue_id
    assert message.badge == 1
    assert message.payload()["channelId"] == push.CHANNEL_ID


async def test_a_pushed_row_is_not_pushed_again(client, sender, recorder):
    await backed_issue(client, sender)

    result = await push.deliver_pending()

    assert result.claimed == 0
    assert len(recorder.sent) == 1


async def test_with_no_device_the_row_is_still_claimed(client, sender, recorder):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(f"/issues/{issue_id}/supports", headers=auth(neighbour), data={"body": "x"})
    await push.drain()

    assert recorder.sent == []
    await register(client, reporter)
    assert (await push.deliver_pending()).claimed == 0, "registering later does not replay history"


async def test_stale_activity_stays_in_the_feed_only(client, sender, recorder, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("PUSH_ENABLED", "false")
    get_settings.cache_clear()
    reporter = await sign_in(client, sender, REPORTER)
    await register(client, reporter)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(f"/issues/{issue_id}/supports", headers=auth(neighbour), data={"body": "x"})
    async with sessionmaker()() as session:
        await session.execute(
            update(ActivityEvent).values(created_at=utcnow() - timedelta(days=1))
        )
        await session.commit()

    monkeypatch.setenv("PUSH_ENABLED", "true")
    get_settings.cache_clear()
    assert (await push.deliver_pending()).claimed == 0
    assert recorder.sent == []


async def test_a_dead_device_is_forgotten(client, sender, recorder):
    recorder.outcome = "DeviceNotRegistered"
    await backed_issue(client, sender)

    assert await tokens() == []


async def test_other_refusals_keep_the_token(client, sender, recorder):
    recorder.outcome = "MessageRateExceeded"
    await backed_issue(client, sender)

    assert [row.token for row in await tokens()] == [TOKEN]


async def test_expo_being_down_does_not_break_the_request(client, sender, recorder):
    recorder.explode = True
    reporter, _ = await backed_issue(client, sender)

    feed = await client.get("/notifications", headers=auth(reporter))
    assert feed.json()["unread_count"] == 1


async def test_a_token_moves_to_whoever_signed_in_last(client, sender, recorder):
    first = await sign_in(client, sender, REPORTER)
    second = await sign_in(client, sender, NEIGHBOUR)
    await register(client, first)
    await register(client, second, platform="android")

    rows = await tokens()
    assert len(rows) == 1
    me = (await client.get("/me", headers=auth(second))).json()
    assert rows[0].user_id == me["id"]
    assert rows[0].platform == "android"


async def test_a_malformed_token_is_refused(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    assert (await register(client, reporter, push_token="not-a-token")).status_code == 422
    assert (await register(client, reporter, platform="web")).status_code == 422


async def test_signing_out_stops_the_pushes(client, sender, recorder):
    reporter = await sign_in(client, sender, REPORTER)
    await register(client, reporter)
    await register(client, reporter, push_token=OTHER_TOKEN)

    response = await client.delete(f"/me/push-tokens/{TOKEN}", headers=auth(reporter))

    assert response.status_code == 204
    assert [row.token for row in await tokens()] == [OTHER_TOKEN]


async def test_nobody_else_can_unregister_your_device(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await register(client, reporter)

    await client.delete(f"/me/push-tokens/{TOKEN}", headers=auth(neighbour))

    assert [row.token for row in await tokens()] == [TOKEN]


async def test_closing_the_account_forgets_its_devices(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    await register(client, reporter)

    assert (await client.delete("/me", headers=auth(reporter))).status_code == 204
    assert await tokens() == []


async def test_the_expo_sender_reads_tickets_in_order(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("EXPO_ACCESS_TOKEN", "secret")
    get_settings.cache_clear()
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"status": "ok", "id": "a"},
                    {
                        "status": "error",
                        "message": "not registered",
                        "details": {"error": "DeviceNotRegistered"},
                    },
                ]
            },
        )

    sender = push.ExpoPushSender(transport=httpx.MockTransport(respond))
    messages = [
        push.PushMessage(to=TOKEN, title="t", body="b", data={}),
        push.PushMessage(to=OTHER_TOKEN, title="t", body="b", data={}, badge=3),
    ]
    try:
        outcomes = await sender.send(messages)
    finally:
        monkeypatch.delenv("EXPO_ACCESS_TOKEN", raising=False)
        get_settings.cache_clear()

    assert outcomes == [None, "DeviceNotRegistered"]
    assert seen[0].headers["authorization"] == "Bearer secret"
    body = json.loads(seen[0].content)
    assert [item["to"] for item in body] == [TOKEN, OTHER_TOKEN]
    assert "badge" not in body[0] and body[1]["badge"] == 3
