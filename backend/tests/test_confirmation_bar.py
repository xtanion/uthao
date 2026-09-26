import uuid

from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
OTHERS = ["+919876500001", "+919876500002", "+919876500003"]


def report_id() -> str:
    return str(uuid.uuid4())


async def support(client, token, issue_id, with_photo: bool):
    files = (
        [("photos", ("p.jpg", jpeg_bytes(500, 400), "image/jpeg"))]
        if with_photo
        else None
    )
    return await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(token),
        data={"body": "Saw this too.", **HERE},
        files=files,
    )


async def test_a_fresh_report_needs_the_full_bar(client, sender):
    from app.config import get_settings

    token = await sign_in(client, sender, REPORTER)
    body = (await create_issue(client, token, report_id=report_id())).json()

    assert body["photo_support_count"] == 0
    assert body["photo_supports_needed"] == get_settings().photo_supports_to_confirm
    assert body["confirmed_at"] is None


async def test_only_photo_backed_support_moves_the_bar(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    bare = await sign_in(client, sender, OTHERS[0])

    before = (await client.get(f"/issues/{issue_id}")).json()["photo_supports_needed"]
    await support(client, bare, issue_id, with_photo=False)
    after = (await client.get(f"/issues/{issue_id}")).json()

    assert after["photo_supports_needed"] == before
    assert after["photo_support_count"] == 0
    # A bare support still counts as backing, just not as confirmation.
    assert after["comment_count"] >= 1


async def test_the_bar_counts_down_and_reaches_zero_on_confirmation(client, sender):
    from app.config import get_settings

    bar = get_settings().photo_supports_to_confirm
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    seen = []
    for phone in OTHERS[:bar]:
        token = await sign_in(client, sender, phone)
        await support(client, token, issue_id, with_photo=True)
        seen.append((await client.get(f"/issues/{issue_id}")).json())

    assert [row["photo_supports_needed"] for row in seen] == list(
        range(bar - 1, -1, -1)
    )
    assert seen[-1]["confirmed_at"] is not None
    assert seen[-1]["photo_support_count"] == bar


async def test_needed_stays_zero_once_confirmed(client, sender):
    from app.config import get_settings

    bar = get_settings().photo_supports_to_confirm
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    for phone in OTHERS[: bar + 1]:
        token = await sign_in(client, sender, phone)
        await support(client, token, issue_id, with_photo=True)

    body = (await client.get(f"/issues/{issue_id}")).json()

    assert body["photo_supports_needed"] == 0
    assert body["photo_support_count"] >= bar


async def test_the_reporters_own_photos_do_not_confirm_it(client, sender):
    from app.config import get_settings

    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    await support(client, reporter, issue_id, with_photo=True)

    body = (await client.get(f"/issues/{issue_id}")).json()
    assert body["photo_supports_needed"] == get_settings().photo_supports_to_confirm
    assert body["confirmed_at"] is None
