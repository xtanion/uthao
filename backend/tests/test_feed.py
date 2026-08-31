import uuid
from datetime import datetime, timedelta, timezone

from tests.conftest import auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
OTHERS = ["+919876500001", "+919876500002", "+919876500003"]
LAT, LNG = 19.0612, 72.8371


def report_id() -> str:
    return str(uuid.uuid4())


async def age(issue_id: str, days: float) -> None:
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.models import Issue

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.created_at = datetime.now(timezone.utc) - timedelta(days=days)
        await session.commit()


async def back(client, sender, issue_id: str, people: int) -> None:
    for phone in OTHERS[:people]:
        token = await sign_in(client, sender, phone)
        await client.post(
            f"/issues/{issue_id}/supports",
            headers=auth(token),
            data={"body": "Saw it."},
            files=[("photos", ("p.jpg", jpeg_bytes(300, 220), "image/jpeg"))],
        )


async def feed(client, **params):
    response = await client.get("/issues/feed", params={"lat": LAT, "lng": LNG, **params})
    assert response.status_code == 200, response.text
    return response.json()


async def test_an_empty_map_is_an_empty_page_not_an_error(client):
    """With nothing reported anywhere there is genuinely nothing to show, and
    the ladder having run out is reported as a null radius."""
    body = await feed(client)

    assert body["items"] == []
    assert body["next_cursor"] is None
    assert body["radius_m"] is None


async def test_the_feed_is_public(client, sender):
    token = await sign_in(client, sender, REPORTER)
    await create_issue(client, token, report_id=report_id())

    body = await feed(client)

    assert len(body["items"]) == 1
    assert body["items"][0]["confirmed_by_me"] is False


async def test_nothing_nearby_widens_rather_than_showing_nothing(client, sender):
    """The whole point: somewhere quiet still opens to something."""
    token = await sign_in(client, sender, REPORTER)
    # ~8 km away, far outside the first rung.
    await create_issue(
        client, token, report_id=report_id(), title="A long way from here", latitude=LAT + 0.072
    )

    body = await feed(client)

    assert len(body["items"]) == 1
    assert body["widened"] is True
    assert body["radius_m"] is None or body["radius_m"] >= 10_000


async def test_it_does_not_widen_when_there_is_enough_close_by(client, sender):
    token = await sign_in(client, sender, REPORTER)
    for i in range(3):
        await create_issue(
            client,
            token,
            report_id=report_id(),
            title=f"Close report number {i} here",
            latitude=LAT + i * 0.0002,
        )

    body = await feed(client, limit=3)

    assert body["widened"] is False
    assert body["radius_m"] == 500


async def test_closer_outranks_further_all_else_equal(client, sender):
    token = await sign_in(client, sender, REPORTER)
    far = (await create_issue(client, token, report_id=report_id(), title="The far one here", latitude=LAT + 0.003)).json()["id"]
    near = (await create_issue(client, token, report_id=report_id(), title="The near one here", latitude=LAT)).json()["id"]

    body = await feed(client)

    assert [i["id"] for i in body["items"]] == [near, far]


async def test_fresher_outranks_older_at_the_same_place(client, sender):
    token = await sign_in(client, sender, REPORTER)
    old = (await create_issue(client, token, report_id=report_id(), title="The old one here")).json()["id"]
    new = (await create_issue(client, token, report_id=report_id(), title="The new one here")).json()["id"]
    await age(old, 40)

    body = await feed(client)

    assert [i["id"] for i in body["items"]] == [new, old]


async def test_backing_lifts_a_report_over_an_unbacked_neighbour(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    plain = (await create_issue(client, reporter, report_id=report_id(), title="Nobody backed this one")).json()["id"]
    backed = (await create_issue(client, reporter, report_id=report_id(), title="Several people backed this")).json()["id"]
    # Same spot and same age, so backing is the only thing between them.
    await back(client, sender, backed, 3)

    body = await feed(client)

    assert body["items"][0]["id"] == backed
    assert plain in [i["id"] for i in body["items"]]


async def test_distance_still_beats_backing_when_it_is_far_enough(client, sender):
    """Near matters most: a backed report two rings out should not outrank the
    thing on your own street."""
    reporter = await sign_in(client, sender, REPORTER)
    doorstep = (await create_issue(client, reporter, report_id=report_id(), title="Right here on this street")).json()["id"]
    distant = (await create_issue(client, reporter, report_id=report_id(), title="Backed but far away", latitude=LAT + 0.02)).json()["id"]
    await back(client, sender, distant, 3)

    body = await feed(client)

    assert [i["id"] for i in body["items"]][0] == doorstep
    assert distant in [i["id"] for i in body["items"]]


async def test_a_removed_report_never_appears(client, sender):
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.enums import Status
    from app.models import Issue

    token = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, token, report_id=report_id())).json()["id"]
    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.status = Status.REMOVED
        await session.commit()

    assert (await feed(client))["items"] == []


async def test_paging_walks_every_row_exactly_once(client, sender):
    token = await sign_in(client, sender, REPORTER)
    for index in range(25):
        await create_issue(
            client,
            token,
            report_id=report_id(),
            title=f"Report number {index:02d} on this stretch",
            latitude=LAT + index * 0.00003,
        )

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"limit": 7}
        if cursor:
            params["cursor"] = cursor
        body = await feed(client, **params)
        seen.extend(i["id"] for i in body["items"])
        cursor = body["next_cursor"]
        pages += 1
        if cursor is None:
            break
        assert pages < 12

    assert len(seen) == len(set(seen)) == 25


async def test_later_pages_stay_on_the_ring_the_first_page_settled_on(client, sender):
    token = await sign_in(client, sender, REPORTER)
    for index in range(6):
        await create_issue(
            client,
            token,
            report_id=report_id(),
            title=f"Distant report number {index} here",
            latitude=LAT + 0.05 + index * 0.00003,
        )

    first = await feed(client, limit=2)
    assert first["widened"] is True
    second = await feed(client, limit=2, cursor=first["next_cursor"])

    assert second["radius_m"] == first["radius_m"]
    assert not set(i["id"] for i in first["items"]) & set(
        i["id"] for i in second["items"]
    )


async def test_a_garbage_cursor_is_a_readable_422(client):
    response = await client.get(
        "/issues/feed", params={"lat": LAT, "lng": LNG, "cursor": "!!!nope"}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_a_report_on_another_continent_still_fills_the_screen(client, sender):
    """Past the last rung distance stops being a filter, because a blank home
    screen is worse than one that says where these came from."""
    token = await sign_in(client, sender, REPORTER)
    await create_issue(
        client,
        token,
        report_id=report_id(),
        title="Somewhere else entirely here",
        latitude=28.6139,
        longitude=77.2090,
    )

    body = await feed(client)

    assert len(body["items"]) == 1
    assert body["widened"] is True
    assert body["radius_m"] is None
