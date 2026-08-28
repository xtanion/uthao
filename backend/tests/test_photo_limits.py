import uuid

from tests.conftest import auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"


def report_id() -> str:
    return str(uuid.uuid4())


def shots(count: int):
    return [
        ("photos", (f"p{i}.jpg", jpeg_bytes(320, 240), "image/jpeg"))
        for i in range(count)
    ]


async def file_report(client, token, count: int):
    return await client.post(
        "/issues",
        headers=auth(token),
        data={
            "client_report_id": report_id(),
            "title": "Cover missing on the footpath side",
            "description": "",
            "category": "manhole",
            "severity": "high",
            "latitude": "19.0612",
            "longitude": "72.8371",
        },
        files=shots(count),
    )


async def test_the_cap_is_three(client, sender):
    from app.config import get_settings

    assert get_settings().max_photos_per_upload == 3


async def test_three_photos_on_a_report_is_fine(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await file_report(client, token, 3)

    assert response.status_code == 201, response.text
    assert response.json()["photo_count"] == 3


async def test_a_fourth_photo_is_refused_readably(client, sender):
    token = await sign_in(client, sender, REPORTER)

    response = await file_report(client, token, 4)

    assert response.status_code == 422
    assert response.json()["detail"] == "Attach at most 3 photos."


async def test_the_same_cap_applies_to_a_support(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    ok = await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "Saw it."},
        files=shots(3),
    )
    too_many = await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "Saw it."},
        files=shots(4),
    )

    assert ok.status_code in (200, 201), ok.text
    assert too_many.status_code == 422
    assert too_many.json()["detail"] == "Attach at most 3 photos."


async def test_a_report_with_no_photo_field_is_refused(client, sender):
    """Omitting the field entirely is caught by request validation, before the
    handler runs, so the wording comes from there."""
    token = await sign_in(client, sender, REPORTER)

    response = await file_report(client, token, 0)

    assert response.status_code == 422
    assert response.json()["detail"] == "photos is required."


async def test_a_photo_with_no_bytes_is_refused(client, sender):
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
            "latitude": "19.0612",
            "longitude": "72.8371",
        },
        files=[("photos", ("empty.jpg", b"", "image/jpeg"))],
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "That photo was empty."
