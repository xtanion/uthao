import uuid

from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"
LAT, LNG = 19.0612, 72.8371


def report_id() -> str:
    return str(uuid.uuid4())


async def feed(client, token, **params):
    response = await client.get("/notifications", headers=auth(token), params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_confirmation_notifies_the_reporter(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )

    body = await feed(client, reporter)
    assert body["unread_count"] == 1
    row = body["items"][0]
    assert row["type"] == "support_received"
    assert row["read"] is False
    assert row["actor_name"] == "Resident 0001"
    assert row["issue"]["id"] == issue_id
    assert row["issue"]["title"] == "Cover missing on the footpath side"
    assert row["created_at"].endswith("Z")


async def test_the_confirmer_is_not_notified(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )

    assert (await feed(client, neighbour))["items"] == []


async def test_reaching_the_threshold_notifies_a_status_change(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    for phone in (NEIGHBOUR, THIRD):
        token = await sign_in(client, sender, phone)
        await client.post(
            f"/issues/{issue_id}/supports",
            headers=auth(token),
            data={"body": "", **HERE},
            files=[("photos", ("p.jpg", jpeg_bytes(320, 240), "image/jpeg"))],
        )

    body = await feed(client, reporter)
    kinds = [row["type"] for row in body["items"]]
    assert kinds.count("support_received") == 2
    assert kinds.count("status_changed") == 1

    change = next(r for r in body["items"] if r["type"] == "status_changed")
    assert change["from_status"] == "reported"
    assert change["to_status"] == "community_verified"
    assert change["actor_name"] is None


async def test_confirming_twice_notifies_once(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    for _ in range(3):
        await client.post(
            f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
        )

    body = await feed(client, reporter)
    assert len(body["items"]) == 1


async def test_newest_first(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    first = (await create_issue(client, reporter, report_id=report_id(), title="The first report here")).json()["id"]
    second = (await create_issue(client, reporter, report_id=report_id(), title="The second report here")).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await client.post(f"/issues/{first}/confirmations", headers=auth(neighbour), json={})
    await client.post(f"/issues/{second}/confirmations", headers=auth(neighbour), json={})

    body = await feed(client, reporter)
    assert [row["issue"]["id"] for row in body["items"]] == [second, first]


async def test_marking_the_feed_read_clears_the_unread_count(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )

    response = await client.post("/notifications/read", headers=auth(reporter), json={})

    assert response.status_code == 200
    assert response.json() == {"unread_count": 0}
    body = await feed(client, reporter)
    assert body["unread_count"] == 0
    assert body["items"][0]["read"] is True


async def test_marking_one_row_read_leaves_the_others(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    first = (await create_issue(client, reporter, report_id=report_id(), title="The first report here")).json()["id"]
    second = (await create_issue(client, reporter, report_id=report_id(), title="The second report here")).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(f"/issues/{first}/confirmations", headers=auth(neighbour), json={})
    await client.post(f"/issues/{second}/confirmations", headers=auth(neighbour), json={})

    rows = (await feed(client, reporter))["items"]
    response = await client.post(
        "/notifications/read", headers=auth(reporter), json={"ids": [rows[0]["id"]]}
    )

    assert response.json() == {"unread_count": 1}


async def test_an_empty_id_list_marks_nothing(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )

    response = await client.post(
        "/notifications/read", headers=auth(reporter), json={"ids": []}
    )

    assert response.json() == {"unread_count": 1}


async def test_one_reporter_never_sees_anothers_feed(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )

    other = await sign_in(client, sender, THIRD)

    assert (await feed(client, other)) == {
        "items": [],
        "next_cursor": None,
        "unread_count": 0,
    }
    marked = await client.post("/notifications/read", headers=auth(other), json={})
    assert marked.json() == {"unread_count": 0}
    assert (await feed(client, reporter))["unread_count"] == 1


async def test_the_feed_pages_without_repeating(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    ids = [
        (
            await create_issue(
                client,
                reporter,
                report_id=report_id(),
                title=f"Report number {index:02d} on this stretch",
                latitude=LAT + index * 0.00002,
            )
        ).json()["id"]
        for index in range(9)
    ]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    for issue_id in ids:
        await client.post(
            f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
        )

    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 4}
        if cursor:
            params["cursor"] = cursor
        body = await feed(client, reporter, **params)
        seen.extend(row["id"] for row in body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 9


async def test_the_feed_requires_a_token(client):
    assert (await client.get("/notifications")).status_code == 401
    assert (await client.post("/notifications/read", json={})).status_code == 401


async def test_a_garbage_cursor_is_a_readable_422(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await client.get(
        "/notifications", headers=auth(token), params={"cursor": "!!!nope"}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_my_issues_lists_only_my_own_newest_first(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    await create_issue(client, reporter, report_id=report_id(), title="My first report here")
    await create_issue(client, reporter, report_id=report_id(), title="My second report here")
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await create_issue(client, neighbour, report_id=report_id(), title="Not mine at all")

    response = await client.get("/me/issues", headers=auth(reporter))

    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["My second report here", "My first report here"]


async def test_my_issues_shows_a_report_that_was_removed(client, sender):
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.enums import Status
    from app.models import Issue

    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.status = Status.REMOVED
        await session.commit()

    response = await client.get("/me/issues", headers=auth(reporter))

    assert [item["id"] for item in response.json()["items"]] == [issue_id]
    assert (await client.get(f"/issues/{issue_id}")).status_code == 404


async def test_my_issues_pages_without_repeating(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    for index in range(9):
        await create_issue(
            client,
            reporter,
            report_id=report_id(),
            title=f"My report number {index:02d} here",
        )

    seen: list[str] = []
    cursor = None
    while True:
        params = {"limit": 4}
        if cursor:
            params["cursor"] = cursor
        page = (
            await client.get("/me/issues", headers=auth(reporter), params=params)
        ).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 9


async def test_my_issues_requires_a_token(client):
    assert (await client.get("/me/issues")).status_code == 401
