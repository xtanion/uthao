import io
import uuid

from PIL import Image

from tests.conftest import HERE, auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"


def report_id() -> str:
    return str(uuid.uuid4())


async def an_issue(client, token) -> str:
    response = await create_issue(client, token, report_id=report_id())
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def support(client, token, issue_id, body=None, photos=0, at=HERE):
    """A bare support still sends body="" so the request carries a form; the
    server strips it back to nothing. `at` is where the phone says it is, and
    None sends no location at all."""
    data = {"body": body if body is not None else "", **(at or {})}
    files = [
        ("photos", (f"p{i}.jpg", jpeg_bytes(320, 240), "image/jpeg"))
        for i in range(photos)
    ]
    return await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(token),
        data=data,
        **({"files": files} if files else {}),
    )


async def thread(client, issue_id, token=None, **params):
    response = await client.get(
        f"/issues/{issue_id}/supports",
        headers=auth(token) if token else {},
        params=params,
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_a_bare_support_is_a_confirmation(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id)

    assert response.status_code == 200, response.text
    assert response.json()["confirmation_count"] == 1
    assert response.json()["comment_count"] == 0


async def test_words_make_it_a_comment_too(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id, body="Still open.")

    body = response.json()
    assert body["confirmation_count"] == 1
    assert body["comment_count"] == 1, "one act, counted on both meters"


async def test_a_photo_counts_as_corroboration(client, sender):
    """The answer to 'does adding a photo confirm it': yes. Standing in front
    of the thing with a camera is stronger evidence than tapping a button."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id, photos=1)

    body = response.json()
    assert body["confirmation_count"] == 1
    assert body["photo_count"] == 2, "the report's own photo plus this one"


async def test_the_reporter_photo_does_not_confirm_their_own_issue(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)

    response = await support(client, reporter, issue_id, body="Still there today.", photos=1)

    body = response.json()
    assert response.status_code == 200, response.text
    assert body["confirmation_count"] == 0, "you cannot corroborate yourself"
    assert body["comment_count"] == 1, "but your words are still readable"
    assert body["photo_count"] == 2


async def test_a_bare_support_on_your_own_issue_is_refused(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)

    response = await support(client, reporter, issue_id)

    assert response.status_code == 403
    assert "cannot confirm it" in response.json()["detail"]


async def test_supporting_twice_adds_rather_than_failing(client, sender):
    """Someone who already backed a report and then photographs it should not
    be told they already did that."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await support(client, neighbour, issue_id)
    second = await support(client, neighbour, issue_id, body="Photo attached.", photos=1)

    body = second.json()
    assert body["confirmation_count"] == 1, "still one person"
    assert body["comment_count"] == 1
    assert body["photo_count"] == 2
    assert (await thread(client, issue_id))["total"] == 1


async def test_withdrawing_takes_the_photos_with_it(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await support(client, neighbour, issue_id, body="Here it is.", photos=2)

    withdrawn = await client.delete(
        f"/issues/{issue_id}/supports", headers=auth(neighbour)
    )

    body = withdrawn.json()
    assert body["confirmation_count"] == 0
    assert body["comment_count"] == 0
    assert body["photo_count"] == 1, "the reporter's own photo stays"


async def test_the_gallery_credits_every_photo(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await support(client, neighbour, issue_id, photos=1)

    response = await client.get(f"/issues/{issue_id}/photos")

    photos = response.json()
    assert response.status_code == 200
    assert len(photos) == 2
    assert [p["from_report"] for p in photos] == [True, False], "report first"
    assert photos[0]["contributor"]["display_name"] == "Resident 3210"
    assert photos[1]["contributor"]["display_name"] == "Resident 0001"
    assert photos[0]["contributor"]["id"] != photos[1]["contributor"]["id"]
    assert all(p["url"] and p["thumbnail_url"] for p in photos)


async def test_the_detail_read_carries_the_gallery(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await support(client, neighbour, issue_id, photos=1)

    detail = await client.get(f"/issues/{issue_id}")

    assert len(detail.json()["photos"]) == 2


async def test_the_feed_leaves_the_gallery_out(client, sender):
    """Signing a link per photo per card is work the feed does not need."""
    reporter = await sign_in(client, sender, REPORTER)
    await an_issue(client, reporter)

    feed = await client.get("/issues/nearby", params={"lat": 19.0612, "lng": 72.8371})

    assert feed.json()["items"][0]["photos"] is None
    assert feed.json()["items"][0]["cover_url"]


async def test_the_thread_shows_words_and_photos_together(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await support(client, neighbour, issue_id, body="Look at this.", photos=2)

    page = await thread(client, issue_id, neighbour)

    row = page["items"][0]
    assert row["body"] == "Look at this."
    assert len(row["photos"]) == 2
    assert row["author"]["display_name"] == "Resident 0001"
    assert row["author_is_reporter"] is False
    assert row["mine"] is True


async def test_the_reporter_is_marked_in_their_own_thread(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await support(client, neighbour, issue_id, body="Still there?")
    await support(client, reporter, issue_id, body="Checked today.")

    page = await thread(client, issue_id, reporter)

    by_body = {row["body"]: row for row in page["items"]}
    assert by_body["Checked today."]["author_is_reporter"] is True
    assert by_body["Still there?"]["author_is_reporter"] is False


async def test_mine_is_false_for_a_signed_out_reader(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await support(client, neighbour, issue_id, body="Mine.")

    page = await thread(client, issue_id)

    assert page["items"][0]["mine"] is False


async def test_supporting_notifies_the_reporter_once(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await support(client, neighbour, issue_id)
    await support(client, neighbour, issue_id, body="And here is a note.")

    feed = await client.get("/notifications", headers=auth(reporter))
    rows = feed.json()["items"]
    assert [r["type"] for r in rows] == ["support_received"], "one act, one telling"
    assert rows[0]["actor_name"] == "Resident 0001"


async def test_supporting_your_own_issue_notifies_nobody(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)

    await support(client, reporter, issue_id, body="Following up myself.")

    feed = await client.get("/notifications", headers=auth(reporter))
    assert feed.json()["items"] == []


async def test_signing_in_is_required(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)

    response = await client.post(
        f"/issues/{issue_id}/supports", data={"body": "Anonymous."}
    )

    assert response.status_code == 401


async def test_a_non_jpeg_in_a_support_is_refused(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    buffer = io.BytesIO()
    Image.new("RGB", (60, 60), (10, 20, 30)).save(buffer, format="PNG")
    response = await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data=HERE,
        files=[("photos", ("bad.png", buffer.getvalue(), "image/png"))],
    )

    assert response.status_code == 422
    assert (await client.get(f"/issues/{issue_id}")).json()["photo_count"] == 1


async def test_supporting_a_missing_issue(client, sender):
    reporter = await sign_in(client, sender, REPORTER)

    response = await support(client, reporter, uuid.uuid4().hex, body="Hello.")

    assert response.status_code == 404


async def test_the_thread_pages_newest_first_without_repeating(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    for i in range(5):
        token = await sign_in(client, sender, f"+91987650{i:04d}")
        assert (
            await support(client, token, issue_id, body=f"Note {i}")
        ).status_code == 200

    seen = []
    cursor = None
    for _ in range(5):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = await thread(client, issue_id, **params)
        seen.extend(row["body"] for row in page["items"])
        cursor = page["next_cursor"]
        if not cursor:
            break

    assert seen == [f"Note {i}" for i in reversed(range(5))]
    assert len(set(seen)) == 5


async def test_the_total_is_the_whole_thread_not_the_page(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    for i in range(4):
        token = await sign_in(client, sender, f"+91987651{i:04d}")
        await support(client, token, issue_id, body=f"Note {i}")

    page = await thread(client, issue_id, limit=2)

    assert len(page["items"]) == 2
    assert page["total"] == 4


async def test_enough_supports_still_promote_the_issue(client, sender):
    """CONFIRMATIONS_TO_VERIFY is 2 in the test settings."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)

    for phone in (NEIGHBOUR, THIRD):
        token = await sign_in(client, sender, phone)
        response = await support(client, token, issue_id, photos=1)

    assert response.json()["status"] == "community_verified"


async def test_a_photo_only_support_counts_as_support(client, sender):
    """It is the strongest kind of backing there is: somebody stood there with a
    camera. Counting only the ones carrying text left the best evidence out."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id, photos=1)

    body = response.json()
    assert body["comment_count"] == 1
    assert body["confirmation_count"] == 1


async def test_one_person_counts_once_however_much_they_bring(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await support(client, neighbour, issue_id, body="Words.", photos=2)
    detail = await client.get(f"/issues/{issue_id}")

    assert detail.json()["comment_count"] == 1
    assert detail.json()["confirmation_count"] == 1


async def test_a_bare_support_is_seen_but_not_support(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await support(client, neighbour, issue_id)
    detail = await client.get(f"/issues/{issue_id}")

    assert detail.json()["confirmation_count"] == 1, "they saw it"
    assert detail.json()["comment_count"] == 0, "but brought nothing to it"


async def test_withdrawing_drops_both_tallies(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await support(client, neighbour, issue_id, photos=1)

    await client.delete(f"/issues/{issue_id}/supports", headers=auth(neighbour))

    detail = await client.get(f"/issues/{issue_id}")
    assert detail.json()["comment_count"] == 0
    assert detail.json()["confirmation_count"] == 0


# --- standing there --------------------------------------------------------

AWAY = {"latitude": "19.0712", "longitude": "72.8371"}  # about 1.1 km north
DOWN_THE_ROAD = {"latitude": "19.0622", "longitude": "72.8371"}  # about 110 m


async def test_photos_from_somewhere_else_do_not_count(client, sender):
    """Two people in the same place with a camera is what status, escalation
    and the poll rest on. A photo sent from across town is not that."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id, photos=1, at=AWAY)

    assert response.status_code == 422
    assert "150 m" in response.json()["detail"]
    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["photo_support_count"] == 0
    assert detail["photo_count"] == 1, "nothing was stored"


async def test_photos_need_a_location(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id, photos=1, at=None)

    assert response.status_code == 422
    assert "location" in response.json()["detail"]


async def test_a_few_doors_down_still_counts(client, sender):
    """GPS drifts on both phones, so the bar is wider than the duplicate radius."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id, photos=1, at=DOWN_THE_ROAD)

    assert response.status_code == 200, response.text
    assert response.json()["photo_support_count"] == 1


async def test_words_and_a_bare_support_need_no_location(client, sender):
    """Neither moves the status, so neither needs anyone standing there."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    third = await sign_in(client, sender, THIRD)

    assert (await support(client, neighbour, issue_id, at=None)).status_code == 200
    worded = await support(client, third, issue_id, body="Walked past it today.", at=AWAY)

    assert worded.status_code == 200, worded.text
    assert worded.json()["confirmation_count"] == 2


async def test_half_a_location_is_refused(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = await an_issue(client, reporter)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(
        client, neighbour, issue_id, photos=1, at={"latitude": HERE["latitude"]}
    )

    assert response.status_code == 422
