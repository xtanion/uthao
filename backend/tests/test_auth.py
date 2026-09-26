import pytest

from app.config import get_settings
from tests.conftest import auth, sign_in

PHONE = "+919876543210"


@pytest.fixture
def env(monkeypatch):
    """Settings are cached, so an override has to clear the cache both ways."""

    def override(**values: str) -> None:
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()

    yield override
    monkeypatch.undo()
    get_settings.cache_clear()


async def test_requesting_a_code_returns_204_and_sends_it(client, sender):
    response = await client.post("/auth/otp/request", json={"phone": PHONE})

    assert response.status_code == 204
    assert response.content == b""
    assert sender.codes[PHONE].isdigit()
    assert len(sender.codes[PHONE]) == 6


async def test_an_unknown_number_is_indistinguishable_from_a_known_one(
    client, sender
):
    known = await client.post("/auth/otp/request", json={"phone": PHONE})
    await sign_in(client, sender, PHONE)
    unknown = await client.post("/auth/otp/request", json={"phone": "+919000000001"})

    assert known.status_code == unknown.status_code == 204
    assert known.content == unknown.content


async def test_verifying_returns_a_bearer_token(client, sender):
    await client.post("/auth/otp/request", json={"phone": PHONE})
    response = await client.post(
        "/auth/otp/verify", json={"phone": PHONE, "code": sender.codes[PHONE]}
    )

    body = response.json()
    assert response.status_code == 200
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().access_token_ttl_seconds
    assert body["access_token"] and body["refresh_token"]


async def test_a_wrong_code_is_401_with_a_readable_detail(client, sender):
    await client.post("/auth/otp/request", json={"phone": PHONE})

    response = await client.post(
        "/auth/otp/verify", json={"phone": PHONE, "code": "000000"}
    )

    assert response.status_code == 401
    assert response.json()["detail"] == (
        "That code is wrong or has expired. Request a new one."
    )


async def test_a_code_cannot_be_replayed(client, sender):
    await client.post("/auth/otp/request", json={"phone": PHONE})
    code = sender.codes[PHONE]
    first = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})
    second = await client.post("/auth/otp/verify", json={"phone": PHONE, "code": code})

    assert first.status_code == 200
    assert second.status_code == 401


async def test_guessing_is_capped_by_the_attempt_limit(client, sender):
    settings = get_settings()
    await client.post("/auth/otp/request", json={"phone": PHONE})
    code = sender.codes[PHONE]

    for _ in range(settings.otp_max_attempts):
        await client.post("/auth/otp/verify", json={"phone": PHONE, "code": "000000"})

    response = await client.post(
        "/auth/otp/verify", json={"phone": PHONE, "code": code}
    )
    assert response.status_code == 401


async def test_requests_are_rate_limited_per_phone(client, sender):
    settings = get_settings()

    for _ in range(settings.otp_requests_per_phone_per_hour):
        assert (
            await client.post("/auth/otp/request", json={"phone": PHONE})
        ).status_code == 204

    response = await client.post("/auth/otp/request", json={"phone": PHONE})
    assert response.status_code == 429
    assert "hour" in response.json()["detail"]


async def test_a_forwarded_header_does_not_dodge_the_ip_limit(client, sender, env):
    """Changing X-Forwarded-For or CF-Connecting-IP per request used to reset
    the count, and every request that got through was an SMS."""
    env(OTP_REQUESTS_PER_IP_PER_HOUR="3")

    statuses = []
    for n in range(4):
        response = await client.post(
            "/auth/otp/request",
            json={"phone": f"+9198765000{n:02d}"},
            headers={
                "X-Forwarded-For": f"203.0.113.{n}",
                "CF-Connecting-IP": f"198.51.100.{n}",
            },
        )
        statuses.append(response.status_code)

    assert statuses == [204, 204, 204, 429]


async def test_the_configured_proxy_header_is_believed(client, sender, env):
    env(OTP_REQUESTS_PER_IP_PER_HOUR="1", CLIENT_IP_HEADER="fly-client-ip")

    async def ask(phone: str, ip: str) -> int:
        response = await client.post(
            "/auth/otp/request", json={"phone": phone}, headers={"Fly-Client-IP": ip}
        )
        return response.status_code

    assert await ask("+919876500010", "203.0.113.7") == 204
    assert await ask("+919876500011", "203.0.113.8") == 204, "another caller, another count"
    assert await ask("+919876500012", "203.0.113.7") == 429


async def test_a_malformed_phone_is_rejected_with_one_sentence(client):
    response = await client.post("/auth/otp/request", json={"phone": "9876543210"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


async def test_me_returns_the_signed_in_user(client, sender):
    token = await sign_in(client, sender, PHONE)

    response = await client.get("/me", headers=auth(token))

    body = response.json()
    assert response.status_code == 200
    assert body["id"]
    assert body["display_name"] == "Resident 3210"
    assert body["avatar_url"] is None


async def test_me_without_a_token_is_401(client):
    response = await client.get("/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Sign in to continue."


async def test_a_junk_token_is_401_not_500(client):
    response = await client.get("/me", headers=auth("not.a.jwt"))

    assert response.status_code == 401


async def test_a_refresh_token_exchanges_for_a_new_access_token(client, sender):
    await client.post("/auth/otp/request", json={"phone": PHONE})
    verified = await client.post(
        "/auth/otp/verify", json={"phone": PHONE, "code": sender.codes[PHONE]}
    )
    refresh_token = verified.json()["refresh_token"]

    response = await client.post(
        "/auth/token/refresh", json={"refresh_token": refresh_token}
    )

    assert response.status_code == 200
    assert (await client.get("/me", headers=auth(response.json()["access_token"]))).status_code == 200


async def test_an_access_token_is_not_accepted_as_a_refresh_token(client, sender):
    token = await sign_in(client, sender, PHONE)

    response = await client.post("/auth/token/refresh", json={"refresh_token": token})

    assert response.status_code == 401
