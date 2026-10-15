import uuid

from tests.conftest import auth, create_issue, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"
LAT, LNG = 19.0612, 72.8371


def report_id() -> str:
    return str(uuid.uuid4())


async def user_id(client, token):
    response = await client.get("/me", headers=auth(token))
    return response.json()["id"]


async def set_status(issue_id: str, status: str) -> None:
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.models import Issue

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.status = status
        await session.commit()


async def test_a_fresh_profile_is_all_zeroes(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await client.get(f"/users/{await user_id(client, token)}")

    body = response.json()
    assert response.status_code == 200
    assert body["display_name"] == "Hooman 3210"
    assert body["avatar_url"] is None
    assert body["reputation"] == 0
    assert body["contributions"] == {
        "posts": 0,
        "upvotes_received": 0,
        "supports_given": 0,
        "comments_written": 0,
        "resolutions": 0,
    }
    assert body["joined_at"].endswith("Z")


async def test_reputation_counts_upvotes_posts_and_resolutions(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, reporter)
    first = (await create_issue(client, reporter, report_id=report_id(), title="The first report here")).json()["id"]
    second = (await create_issue(client, reporter, report_id=report_id(), title="The second report here")).json()["id"]
    third = (await create_issue(client, reporter, report_id=report_id(), title="The third report here")).json()["id"]

    for phone in (NEIGHBOUR, THIRD):
        token = await sign_in(client, sender, phone)
        await client.post(f"/issues/{first}/confirmations", headers=auth(token), json={})
    await set_status(second, "resolved")

    body = (await client.get(f"/users/{mine}")).json()

    assert body["contributions"]["posts"] == 3
    assert body["contributions"]["upvotes_received"] == 2
    assert body["contributions"]["resolutions"] == 1
    # 2 upvotes + 3 posts * 2 + 1 resolution * 5
    assert body["reputation"] == 2 + 6 + 5
    assert third


async def test_supports_given_counts_the_ones_you_made(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    first = (await create_issue(client, reporter, report_id=report_id(), title="The first report here")).json()["id"]
    second = (await create_issue(client, reporter, report_id=report_id(), title="The second report here")).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)
    for issue_id in (first, second):
        await client.post(
            f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
        )

    body = (await client.get(f"/users/{theirs}")).json()

    assert body["contributions"]["supports_given"] == 2
    # Supporting is not the same as being supported.
    assert body["contributions"]["upvotes_received"] == 0
    assert body["reputation"] == 0


async def test_withdrawing_support_lowers_both_sides(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, reporter)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)
    await client.post(f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={})

    await client.delete(f"/issues/{issue_id}/confirmations", headers=auth(neighbour))

    assert (await client.get(f"/users/{mine}")).json()["contributions"]["upvotes_received"] == 0
    assert (await client.get(f"/users/{theirs}")).json()["contributions"]["supports_given"] == 0


async def test_comments_are_counted(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)

    posted = await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "Still like this as of this morning."},
    )
    assert posted.status_code in (200, 201), posted.text

    body = (await client.get(f"/users/{theirs}")).json()
    assert body["contributions"]["comments_written"] == 1
    # A support that carries words is one support and one comment; the words
    # are visible contribution but carry no reputation weight of their own.
    assert body["contributions"]["supports_given"] == 1
    assert body["reputation"] == 0


async def test_a_removed_post_stops_counting(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, reporter)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    assert (await client.get(f"/users/{mine}")).json()["contributions"]["posts"] == 1

    await set_status(issue_id, "removed")

    body = (await client.get(f"/users/{mine}")).json()
    assert body["contributions"]["posts"] == 0
    assert body["reputation"] == 0


async def test_an_unknown_profile_is_404(client):
    response = await client.get(f"/users/{uuid.uuid4().hex}")

    assert response.status_code == 404
    assert response.json()["detail"] == "That profile is not available."


async def test_a_profile_is_public(client, sender):
    token = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, token)
    await create_issue(client, token, report_id=report_id())

    response = await client.get(f"/users/{mine}")

    assert response.status_code == 200
    assert response.json()["contributions"]["posts"] == 1


async def test_user_issues_lists_their_posts_newest_first(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, reporter)
    await create_issue(client, reporter, report_id=report_id(), title="Their first report here")
    await create_issue(client, reporter, report_id=report_id(), title="Their second report here")
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await create_issue(client, neighbour, report_id=report_id(), title="Somebody elses report")

    response = await client.get(f"/users/{mine}/issues")

    titles = [item["title"] for item in response.json()["items"]]
    assert titles == ["Their second report here", "Their first report here"]


async def test_a_removed_post_is_hidden_from_visitors_but_not_the_author(
    client, sender
):
    reporter = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, reporter)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    await set_status(issue_id, "removed")

    stranger = await client.get(f"/users/{mine}/issues")
    author = await client.get(f"/users/{mine}/issues", headers=auth(reporter))

    assert stranger.json()["items"] == []
    assert [i["id"] for i in author.json()["items"]] == [issue_id]


async def test_supports_lists_what_they_backed_most_recent_first(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    first = (await create_issue(client, reporter, report_id=report_id(), title="The first report here")).json()["id"]
    second = (await create_issue(client, reporter, report_id=report_id(), title="The second report here")).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)
    await client.post(f"/issues/{first}/confirmations", headers=auth(neighbour), json={})
    await client.post(f"/issues/{second}/confirmations", headers=auth(neighbour), json={})

    response = await client.get(f"/users/{theirs}/supports")

    assert [i["title"] for i in response.json()["items"]] == [
        "The second report here",
        "The first report here",
    ]


async def test_supports_reflects_the_viewers_own_flag(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)
    await client.post(f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={})

    anonymous = await client.get(f"/users/{theirs}/supports")
    themselves = await client.get(f"/users/{theirs}/supports", headers=auth(neighbour))

    assert anonymous.json()["items"][0]["confirmed_by_me"] is False
    assert themselves.json()["items"][0]["confirmed_by_me"] is True


async def test_withdrawing_support_removes_it_from_the_tab(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)
    await client.post(f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={})

    await client.delete(f"/issues/{issue_id}/confirmations", headers=auth(neighbour))

    assert (await client.get(f"/users/{theirs}/supports")).json()["items"] == []


async def test_a_removed_issue_drops_out_of_supports(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)
    await client.post(f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={})

    await set_status(issue_id, "removed")

    assert (await client.get(f"/users/{theirs}/supports")).json()["items"] == []


async def test_both_tabs_page_without_repeating(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, reporter)
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
    theirs = await user_id(client, neighbour)
    for issue_id in ids:
        await client.post(
            f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
        )

    for path in (f"/users/{mine}/issues", f"/users/{theirs}/supports"):
        seen: list[str] = []
        cursor = None
        while True:
            params = {"limit": 4}
            if cursor:
                params["cursor"] = cursor
            page = (await client.get(path, params=params)).json()
            seen.extend(item["id"] for item in page["items"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(seen) == len(set(seen)) == 9, path


async def test_a_garbage_cursor_is_a_readable_422(client, sender):
    token = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, token)

    response = await client.get(f"/users/{mine}/issues", params={"cursor": "!!!nope"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_issues_carry_their_reporter_everywhere(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    mine = await user_id(client, reporter)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    theirs = await user_id(client, neighbour)
    await client.post(f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={})

    detail = await client.get(f"/issues/{issue_id}")
    nearby = await client.get("/issues/nearby", params={"lat": LAT, "lng": LNG})
    supports = await client.get(f"/users/{theirs}/supports")

    for body in (detail.json(), nearby.json()["items"][0], supports.json()["items"][0]):
        assert body["reporter"] == {"id": mine, "display_name": "Hooman 3210", "avatar_url": None}
