"""The geocoder is swapped for a stub or a mock transport; nothing here calls
Nominatim."""
import uuid

import httpx
import pytest

from app import geocode
from tests.conftest import auth, jpeg_bytes, sign_in

REPORTER = "+919876543210"


async def file_report(client, token: str, *, locality: str | None = None):
    data = {
        "client_report_id": str(uuid.uuid4()),
        "title": "Cover missing on the footpath side",
        "description": "Unlit after dark.",
        "category": "manhole",
        "severity": "high",
        "latitude": "19.0176",
        "longitude": "72.8172",
    }
    if locality is not None:
        data["locality"] = locality
    return await client.post(
        "/issues",
        headers=auth(token),
        data=data,
        files=[("photos", ("photo_0.jpg", jpeg_bytes(400, 300), "image/jpeg"))],
    )


@pytest.fixture
def lookup(monkeypatch):
    calls: list[tuple[float, float]] = []
    answer = {"name": "Worli, Mumbai"}

    async def stub(latitude: float, longitude: float, **_) -> str | None:
        calls.append((latitude, longitude))
        return answer["name"]

    monkeypatch.setattr(geocode, "locality", stub)
    stub.calls = calls
    stub.answer = answer
    return stub


@pytest.fixture
def geocoder_on(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("GEOCODER_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "address, expected",
    [
        ({"suburb": "Worli", "city": "Mumbai"}, "Worli, Mumbai"),
        ({"neighbourhood": "Bandra West", "state_district": "Mumbai Suburban"}, "Bandra West, Mumbai Suburban"),
        ({"village": "Mumbai", "city": "Mumbai"}, "Mumbai"),
        ({"city": "Pune"}, "Pune"),
        ({}, None),
        # Real Nominatim answers at zoom 17 for three reports in Lower Parel,
        # which at zoom 14 all read "G/S Ward, Mumbai City District".
        (
            {"road": "Pandurang Budhkar Marg", "neighbourhood": "Gopal Nagar", "suburb": "Nehru Nagar",
             "city_district": "Mumbai Zone 2", "state_district": "Mumbai City District"},
            "Pandurang Budhkar Marg, Nehru Nagar",
        ),
        (
            {"road": "Shankar Rao Naram Path (Gowalia Chawl Lane)", "neighbourhood": "Gopal Nagar",
             "suburb": "Lower Parel", "city_district": "Mumbai Zone 2"},
            "Shankar Rao Naram Path, Lower Parel",
        ),
        (
            {"residential": "Lodha Place", "suburb": "Lower Parel", "city_district": "Mumbai Zone 2"},
            "Lodha Place, Lower Parel",
        ),
        ({"suburb": "G/S Ward", "city_district": "Mumbai Zone 2", "city": "Mumbai"}, "Mumbai"),
    ],
)
def test_an_address_is_named_street_then_area(address, expected):
    assert geocode._name(address) == expected


async def test_the_lookup_reads_nominatims_address(geocoder_on):
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"address": {"suburb": "Worli", "city": "Mumbai"}})

    name = await geocode.locality(19.0176, 72.8172, transport=httpx.MockTransport(answer))

    assert name == "Worli, Mumbai"
    assert seen[0].url.params["lat"] == "19.0176"
    assert seen[0].url.params["zoom"] == "17"
    assert seen[0].headers["user-agent"].startswith("uthao/")


async def test_a_failed_lookup_is_none_not_an_error(geocoder_on):
    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert await geocode.locality(19.0, 72.8, transport=httpx.MockTransport(down)) is None


async def test_the_server_names_the_report_after_responding(client, sender, lookup):
    token = await sign_in(client, sender, REPORTER)

    created = await file_report(client, token, locality="Phone's guess")

    assert created.status_code == 201, created.text
    assert created.json()["locality"] == "Phone's guess", "the response does not wait for it"
    assert lookup.calls == [(19.0176, 72.8172)]
    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["locality"] == "Worli, Mumbai"


async def test_the_phones_name_stays_when_the_lookup_fails(client, sender, lookup):
    lookup.answer["name"] = None
    token = await sign_in(client, sender, REPORTER)

    created = await file_report(client, token, locality="Lower Parel, Mumbai")

    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["locality"] == "Lower Parel, Mumbai"


async def test_a_retried_upload_is_not_looked_up_again(client, sender, lookup):
    token = await sign_in(client, sender, REPORTER)
    data = {
        "client_report_id": str(uuid.uuid4()),
        "title": "Cover missing on the footpath side",
        "category": "manhole",
        "severity": "high",
        "latitude": "19.0176",
        "longitude": "72.8172",
    }

    for _ in range(2):
        response = await client.post(
            "/issues",
            headers=auth(token),
            data=data,
            files=[("photos", ("photo_0.jpg", jpeg_bytes(400, 300), "image/jpeg"))],
        )
        assert response.status_code in (200, 201), response.text

    assert len(lookup.calls) == 1
