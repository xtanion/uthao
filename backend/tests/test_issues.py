import uuid

from app.config import get_settings
from tests.conftest import HERE, auth, create_issue, jpeg_bytes, png_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"

# Bandra East, matching the contract's example issue.
LAT, LNG = 19.0612, 72.8371


def report_id() -> str:
    return str(uuid.uuid4())


async def test_creating_a_report_returns_the_contract_shape(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await create_issue(client, token, report_id=report_id())

    body = response.json()
    assert response.status_code == 201, body
    assert set(body) == {
        "id",
        "title",
        "description",
        "category",
        "severity",
        "status",
        "latitude",
        "longitude",
        "locality",
        "confirmation_count",
        "confirmed_by_me",
        "comment_count",
        "photo_count",
        "photo_support_count",
        "photo_supports_needed",
        "confirmed_at",
        "contributions_open_at",
        "ai_summary",
        "photos",
        "cover_url",
        "reporter",
        "created_at",
    }
    assert body["status"] == "reported"
    assert body["category"] == "manhole"
    assert body["severity"] == "high"
    assert body["confirmation_count"] == 0
    assert body["confirmed_by_me"] is False
    assert body["comment_count"] == 0
    assert body["photo_count"] == 1
    assert body["photo_support_count"] == 0
    assert body["confirmed_at"] is None
    assert body["contributions_open_at"] is None
    assert body["ai_summary"] is None
    assert body["reporter"]["display_name"] == "Resident 3210"
    assert body["reporter"]["id"]
    assert body["created_at"].endswith("Z")


async def test_the_cover_url_is_a_short_lived_link_to_a_derived_thumbnail(
    client, sender
):
    token = await sign_in(client, sender, REPORTER)
    created = await create_issue(
        client, token, report_id=report_id(), photo=jpeg_bytes(2400, 1800)
    )

    cover_url = created.json()["cover_url"]
    assert cover_url is not None
    assert "expires=" in cover_url and "signature=" in cover_url
    assert "original" not in cover_url

    fetched = await client.get(cover_url)
    assert fetched.status_code == 200
    assert fetched.headers["content-type"] == "image/jpeg"

    tampered = cover_url.replace("signature=", "signature=0")
    assert (await client.get(tampered)).status_code == 403


async def test_the_stored_image_has_no_exif(client, sender):
    import io

    from PIL import Image

    token = await sign_in(client, sender, REPORTER)
    created = await create_issue(
        client, token, report_id=report_id(), photo=jpeg_bytes(1600, 1200)
    )

    fetched = await client.get(created.json()["cover_url"])
    assert not dict(Image.open(io.BytesIO(fetched.content)).getexif())


async def test_repeating_a_client_report_id_returns_the_original(client, sender):
    token = await sign_in(client, sender, REPORTER)
    identifier = report_id()

    first = await create_issue(client, token, report_id=identifier)
    second = await create_issue(
        client, token, report_id=identifier, title="A different title entirely"
    )

    assert first.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["title"] == first.json()["title"]

    page = await client.get("/issues/nearby", params={"lat": LAT, "lng": LNG})
    assert len(page.json()["items"]) == 1


async def test_two_reporters_may_reuse_the_same_client_report_id(client, sender):
    identifier = report_id()
    reporter = await sign_in(client, sender, REPORTER)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    first = await create_issue(client, reporter, report_id=identifier)
    second = await create_issue(client, neighbour, report_id=identifier)

    assert first.json()["id"] != second.json()["id"]


async def test_creating_a_report_requires_a_token(client):
    response = await create_issue(client, "", report_id=report_id())

    assert response.status_code == 401
    assert isinstance(response.json()["detail"], str)


async def test_a_report_needs_at_least_one_photo(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await client.post(
        "/issues",
        headers=auth(token),
        data={
            "client_report_id": report_id(),
            "title": "Cover missing on the footpath side",
            "description": "",
            "category": "manhole",
            "severity": "high",
            "latitude": str(LAT),
            "longitude": str(LNG),
        },
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_a_non_jpeg_photo_is_rejected(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await create_issue(
        client, token, report_id=report_id(), photo=png_bytes(), photo_name="p.png"
    )

    assert response.status_code == 422
    assert "JPEG" in response.json()["detail"]


async def test_a_short_title_is_rejected_with_one_sentence(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await create_issue(client, token, report_id=report_id(), title="ab")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_a_non_uuid_client_report_id_is_rejected(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await create_issue(client, token, report_id="not-a-uuid")

    assert response.status_code == 422
    assert "UUID" in response.json()["detail"]


async def test_an_empty_description_is_allowed(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await create_issue(client, token, report_id=report_id(), description="")

    assert response.status_code == 201
    assert response.json()["description"] == ""


async def test_a_report_outside_the_geofence_is_rejected(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await create_issue(
        client, token, report_id=report_id(), latitude=48.8584, longitude=2.2945
    )

    assert response.status_code == 422
    assert "India" in response.json()["detail"]


async def test_reading_an_unknown_issue_is_404(client):
    response = await client.get(f"/issues/{uuid.uuid4().hex}")

    assert response.status_code == 404
    assert response.json()["detail"] == "That report is no longer available."


async def test_a_removed_issue_is_404_and_absent_from_nearby(client, sender):
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.enums import Status
    from app.models import Issue

    token = await sign_in(client, sender, REPORTER)
    created = await create_issue(client, token, report_id=report_id())
    issue_id = created.json()["id"]

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.status = Status.REMOVED
        await session.commit()

    assert (await client.get(f"/issues/{issue_id}")).status_code == 404
    page = await client.get("/issues/nearby", params={"lat": LAT, "lng": LNG})
    assert page.json()["items"] == []


async def test_reads_are_public_and_report_confirmed_by_me_as_false(client, sender):
    token = await sign_in(client, sender, REPORTER)
    created = await create_issue(client, token, report_id=report_id())

    response = await client.get(f"/issues/{created.json()['id']}")

    assert response.status_code == 200
    assert response.json()["confirmed_by_me"] is False


async def test_nearby_orders_by_distance_and_honours_the_radius(client, sender):
    token = await sign_in(client, sender, REPORTER)
    # Roughly 0, 110 m and 550 m north of the query point.
    offsets = {"here": 0.0, "near": 0.001, "far": 0.005}
    for name, offset in offsets.items():
        await create_issue(
            client,
            token,
            report_id=report_id(),
            title=f"Issue {name} on this stretch",
            latitude=LAT + offset,
        )

    inside = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "radius_m": 200}
    )
    titles = [item["title"] for item in inside.json()["items"]]
    assert titles == ["Issue here on this stretch", "Issue near on this stretch"]

    wider = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "radius_m": 1000}
    )
    assert len(wider.json()["items"]) == 3


async def test_the_default_radius_is_500_metres(client, sender):
    token = await sign_in(client, sender, REPORTER)
    await create_issue(client, token, report_id=report_id(), latitude=LAT)
    await create_issue(client, token, report_id=report_id(), latitude=LAT + 0.01)

    response = await client.get("/issues/nearby", params={"lat": LAT, "lng": LNG})

    assert get_settings().default_radius_m == 500
    assert len(response.json()["items"]) == 1


async def test_the_category_filter_applies(client, sender):
    token = await sign_in(client, sender, REPORTER)
    await create_issue(client, token, report_id=report_id(), category="manhole")
    await create_issue(client, token, report_id=report_id(), category="garbage")

    response = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "category": "garbage"}
    )

    items = response.json()["items"]
    assert [item["category"] for item in items] == ["garbage"]


async def test_an_unknown_category_is_rejected(client):
    response = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "category": "unicorns"}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_paging_walks_every_row_exactly_once(client, sender):
    token = await sign_in(client, sender, REPORTER)
    total = 25
    for index in range(total):
        await create_issue(
            client,
            token,
            report_id=report_id(),
            title=f"Issue number {index:02d} on this stretch",
            latitude=LAT + index * 0.00002,
        )

    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        params = {"lat": LAT, "lng": LNG, "radius_m": 2000, "limit": 7}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/issues/nearby", params=params)).json()
        seen.extend(item["id"] for item in page["items"])
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break
        assert pages < 10

    assert len(seen) == total
    assert len(set(seen)) == total


async def test_paging_is_stable_when_rows_are_equidistant(client, sender):
    token = await sign_in(client, sender, REPORTER)
    for index in range(9):
        await create_issue(
            client,
            token,
            report_id=report_id(),
            title=f"Identical spot number {index}",
            latitude=LAT,
            longitude=LNG,
        )

    seen: list[str] = []
    cursor = None
    while True:
        params = {"lat": LAT, "lng": LNG, "limit": 4}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/issues/nearby", params=params)).json()
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)) == 9


async def test_the_last_page_reports_a_null_cursor(client, sender):
    token = await sign_in(client, sender, REPORTER)
    for _ in range(3):
        await create_issue(client, token, report_id=report_id())

    response = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "limit": 100}
    )

    assert response.json()["next_cursor"] is None
    assert len(response.json()["items"]) == 3


async def test_the_limit_is_clamped_server_side(client, sender):
    token = await sign_in(client, sender, REPORTER)
    for index in range(4):
        await create_issue(
            client,
            token,
            report_id=report_id(),
            latitude=LAT + index * 0.00002,
        )

    over = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "limit": 5000}
    )
    under = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "limit": 0}
    )

    assert over.status_code == 200
    assert len(over.json()["items"]) == 4
    assert under.status_code == 200
    assert len(under.json()["items"]) == 1


async def test_a_garbage_cursor_is_a_readable_422(client):
    response = await client.get(
        "/issues/nearby", params={"lat": LAT, "lng": LNG, "cursor": "!!!not-a-cursor"}
    )

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_confirming_raises_the_count_and_flips_the_flag(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    created = await create_issue(client, reporter, report_id=report_id())
    issue_id = created.json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["confirmation_count"] == 1
    assert body["confirmed_by_me"] is True


async def test_confirming_twice_is_not_an_error(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    first = await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )
    second = await client.post(
        f"/issues/{issue_id}/confirmations",
        headers=auth(neighbour),
        json={"note": "Still open this morning."},
    )

    assert first.status_code == second.status_code == 200
    assert second.json()["confirmation_count"] == 1


async def test_withdrawing_a_confirmation_lowers_the_count(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour), json={}
    )

    response = await client.delete(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour)
    )

    assert response.status_code == 200
    assert response.json()["confirmation_count"] == 0
    assert response.json()["confirmed_by_me"] is False


async def test_withdrawing_a_confirmation_that_was_never_made_is_not_an_error(
    client, sender
):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await client.delete(
        f"/issues/{issue_id}/confirmations", headers=auth(neighbour)
    )

    assert response.status_code == 200
    assert response.json()["confirmation_count"] == 0


async def test_a_reporter_cannot_confirm_their_own_report(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    response = await client.post(
        f"/issues/{issue_id}/confirmations", headers=auth(reporter), json={}
    )

    assert response.status_code == 403
    assert "cannot confirm" in response.json()["detail"]
    read = await client.get(f"/issues/{issue_id}")
    assert read.json()["confirmation_count"] == 0


async def test_confirming_requires_a_token(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    response = await client.post(f"/issues/{issue_id}/confirmations", json={})

    assert response.status_code == 401


async def test_confirming_an_unknown_issue_is_404(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await client.post(
        f"/issues/{uuid.uuid4().hex}/confirmations", headers=auth(token), json={}
    )

    assert response.status_code == 404


async def test_an_overlong_support_body_is_rejected(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "x" * 2001},
    )

    assert response.status_code == 422


async def test_photo_supports_promote_the_issue_to_community_verified(
    client, sender
):
    """Two people other than the reporter, each with a photo. A tap is not
    evidence; standing in the same place with a camera is."""
    threshold = get_settings().photo_supports_to_confirm
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    tokens = [await sign_in(client, sender, phone) for phone in (NEIGHBOUR, THIRD)]
    assert len(tokens) >= threshold

    statuses = []
    for token in tokens:
        response = await client.post(
            f"/issues/{issue_id}/supports",
            headers=auth(token),
            data={"body": "", **HERE},
            files=[("photos", ("p.jpg", jpeg_bytes(320, 240), "image/jpeg"))],
        )
        statuses.append(response.json()["status"])

    assert statuses[0] == "reported"
    assert statuses[-1] == "community_verified"


async def test_bare_confirmations_no_longer_promote(client, sender):
    """They still count as seen. Confirming is a higher bar than being seen."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]

    for phone in (NEIGHBOUR, THIRD):
        token = await sign_in(client, sender, phone)
        response = await client.post(
            f"/issues/{issue_id}/confirmations", headers=auth(token)
        )

    assert response.json()["confirmation_count"] == 2
    assert response.json()["photo_support_count"] == 0
    assert response.json()["status"] == "reported"
    assert response.json()["confirmed_at"] is None

    withdrawn = await client.delete(
        f"/issues/{issue_id}/confirmations", headers=auth(token)
    )
    assert withdrawn.json()["confirmation_count"] == 1
    assert withdrawn.json()["status"] == "reported"


async def test_nearby_rejects_a_latitude_off_the_globe(client):
    response = await client.get("/issues/nearby", params={"lat": 200, "lng": LNG})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_nearby_requires_a_position(client):
    response = await client.get("/issues/nearby")

    assert response.status_code == 422
    assert "required" in response.json()["detail"]
