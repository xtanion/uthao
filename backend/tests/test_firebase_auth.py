"""Signing in with a phone Firebase already verified.

The verifier is swapped for a double, so nothing here reaches Google.
"""
import uuid

import pytest

from app import firebase
from app.firebase import TokenRejected, TokenVerifier, VerifiedPhone
from tests.conftest import auth

PHONE = "+919876543210"


class Accepts(TokenVerifier):
    def __init__(self, phone: str = PHONE, uid: str = "firebase-uid-1") -> None:
        self.result = VerifiedPhone(phone=phone, uid=uid)
        self.seen: list[str] = []

    async def verify(self, id_token: str) -> VerifiedPhone:
        self.seen.append(id_token)
        return self.result


class Refuses(TokenVerifier):
    def __init__(self, why: str = "That sign-in could not be verified.") -> None:
        self.why = why

    async def verify(self, id_token: str) -> VerifiedPhone:
        raise TokenRejected(self.why)


@pytest.fixture
def verifier(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("FIREBASE_PROJECT_ID", "fihy-test")
    get_settings.cache_clear()
    double = Accepts()
    firebase.set_verifier(double)
    yield double
    firebase.set_verifier(None)
    monkeypatch.delenv("FIREBASE_PROJECT_ID", raising=False)
    get_settings.cache_clear()


async def sign_in(client, token="a-firebase-id-token-long-enough"):
    return await client.post("/auth/firebase", json={"id_token": token})


async def test_a_verified_token_returns_our_tokens(client, verifier):
    response = await sign_in(client)

    body = response.json()
    assert response.status_code == 200, body
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert verifier.seen == ["a-firebase-id-token-long-enough"]


async def test_it_makes_the_same_account_the_otp_path_would(client, verifier):
    response = await sign_in(client)
    me = await client.get("/me", headers=auth(response.json()["access_token"]))

    assert me.json()["display_name"] == "Resident 3210", "named from the number"


async def test_signing_in_twice_is_the_same_person(client, verifier):
    first = (await sign_in(client)).json()["access_token"]
    second = (await sign_in(client)).json()["access_token"]

    one = (await client.get("/me", headers=auth(first))).json()["id"]
    two = (await client.get("/me", headers=auth(second))).json()["id"]
    assert one == two


async def test_the_same_number_reaches_the_same_account_either_way(client, verifier, sender):
    """A person who signed in by OTP before and by Firebase after is not two
    people. The phone number is the identity on both paths."""
    from tests.conftest import sign_in as otp_sign_in

    by_otp = await otp_sign_in(client, sender, PHONE)
    original = (await client.get("/me", headers=auth(by_otp))).json()["id"]

    by_firebase = (await sign_in(client)).json()["access_token"]

    assert (await client.get("/me", headers=auth(by_firebase))).json()["id"] == original


async def test_a_rejected_token_is_401(client, verifier):
    firebase.set_verifier(Refuses())

    response = await sign_in(client)

    assert response.status_code == 401
    assert response.json()["detail"] == "That sign-in could not be verified."


async def test_a_token_without_a_phone_is_refused(client, verifier):
    firebase.set_verifier(Refuses("That sign-in carried no phone number."))

    response = await sign_in(client)

    assert response.status_code == 401
    assert "no phone number" in response.json()["detail"]


async def test_with_no_project_configured_it_is_503(client):
    """Not 401: nothing was wrong with the caller, the door is simply shut."""
    firebase.set_verifier(None)

    response = await sign_in(client)

    assert response.status_code == 503
    assert "not available" in response.json()["detail"]


async def test_a_stub_token_is_refused_before_it_reaches_google(client, verifier):
    response = await client.post("/auth/firebase", json={"id_token": "short"})

    assert response.status_code == 422
    assert verifier.seen == []


async def test_the_otp_path_still_works_alongside_it(client, verifier, sender):
    from tests.conftest import sign_in as otp_sign_in

    token = await otp_sign_in(client, sender, "+919876500001")

    assert (await client.get("/me", headers=auth(token))).status_code == 200


# --- what the real verifier checks -----------------------------------------


def claims(**over):
    base = {
        "iss": "https://securetoken.google.com/fihy-test",
        "sub": "uid-1",
        "phone_number": PHONE,
        "firebase": {"sign_in_provider": "phone"},
    }
    base.update(over)
    return base


def verify_claims(monkeypatch, payload):
    """Drive GoogleTokenVerifier's checks with the signature step stubbed, so
    the claim rules are tested without a network call or a real token."""
    from app.config import get_settings
    from app.firebase import GoogleTokenVerifier

    monkeypatch.setenv("FIREBASE_PROJECT_ID", "fihy-test")
    get_settings.cache_clear()
    verifier = GoogleTokenVerifier(get_settings())

    import google.oauth2.id_token as google_id_token

    monkeypatch.setattr(
        google_id_token, "verify_firebase_token", lambda *a, **k: payload
    )
    try:
        return verifier._check("token")
    finally:
        get_settings.cache_clear()


def test_a_good_token_yields_the_phone(monkeypatch):
    assert verify_claims(monkeypatch, claims()).phone == PHONE


def test_another_projects_token_is_refused(monkeypatch):
    """google-auth checks the audience but not the issuer, so this is the
    check that has to exist here."""
    with pytest.raises(TokenRejected):
        verify_claims(
            monkeypatch,
            claims(iss="https://securetoken.google.com/somebody-elses-project"),
        )


def test_a_non_phone_provider_is_refused(monkeypatch):
    """A project with anonymous or email sign-in enabled can mint tokens with
    no phone number; this keeps them off this door."""
    with pytest.raises(TokenRejected):
        verify_claims(monkeypatch, claims(firebase={"sign_in_provider": "anonymous"}))


def test_a_token_missing_the_phone_is_refused(monkeypatch):
    with pytest.raises(TokenRejected):
        verify_claims(monkeypatch, claims(phone_number=None))


def test_a_token_missing_the_uid_is_refused(monkeypatch):
    with pytest.raises(TokenRejected):
        verify_claims(monkeypatch, claims(sub=None))


def test_a_bad_signature_is_refused(monkeypatch):
    from app.config import get_settings
    from app.firebase import GoogleTokenVerifier

    monkeypatch.setenv("FIREBASE_PROJECT_ID", "fihy-test")
    get_settings.cache_clear()
    verifier = GoogleTokenVerifier(get_settings())

    import google.oauth2.id_token as google_id_token

    def boom(*a, **k):
        raise ValueError("Token signature is invalid")

    monkeypatch.setattr(google_id_token, "verify_firebase_token", boom)
    try:
        with pytest.raises(TokenRejected):
            verifier._check("token")
    finally:
        get_settings.cache_clear()
