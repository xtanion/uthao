from app.config import get_settings
from tests.conftest import auth, sign_in

PHONE = "+919876543210"


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
    assert body["display_name"] == "Hooman 3210"
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
