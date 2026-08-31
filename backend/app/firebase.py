"""Signing in with a phone number Firebase already verified.

Google sends the SMS and holds the DLT registration India requires, so nothing
here registers a sender, a header, or a template. What arrives is an ID token;
what comes out is the phone number inside it, and from there the flow is the
same as the OTP one - find or create the account, hand back our own tokens.

Verification is `google.oauth2.id_token`, which is Google's own code, rather
than a hand-rolled JWT check. It validates the signature, the audience, and
expiry, but *not* the issuer, so that one is checked here.
"""
import logging
from dataclasses import dataclass

import anyio

from .config import Settings, get_settings

log = logging.getLogger(__name__)

ISSUER = "https://securetoken.google.com/"


class TokenRejected(Exception):
    pass


@dataclass(frozen=True)
class VerifiedPhone:
    phone: str
    uid: str


class TokenVerifier:
    async def verify(self, id_token: str) -> VerifiedPhone:
        raise NotImplementedError


class GoogleTokenVerifier(TokenVerifier):
    def __init__(self, settings: Settings) -> None:
        self._project = settings.firebase_project_id
        self._http = None

    def _transport(self):
        """urllib3 rather than the requests transport: botocore already brings
        urllib3, and requests would be a dependency for one HTTP call.

        The pool is kept because verification fetches Google's signing
        certificates on every call, so the connection is worth reusing.
        """
        if self._http is None:
            import urllib3
            from google.auth.transport import urllib3 as google_urllib3

            self._http = google_urllib3.Request(urllib3.PoolManager())
        return self._http

    def _check(self, id_token: str) -> VerifiedPhone:
        from google.oauth2 import id_token as google_id_token

        try:
            claims = google_id_token.verify_firebase_token(
                id_token, self._transport(), audience=self._project
            )
        except Exception as exc:
            # Wrong signature, wrong project, or expired. All the same to a
            # caller, and saying which would help someone guessing.
            raise TokenRejected("That sign-in could not be verified.") from exc

        if claims.get("iss") != f"{ISSUER}{self._project}":
            # google-auth checks the audience but not the issuer.
            raise TokenRejected("That sign-in could not be verified.")

        provider = (claims.get("firebase") or {}).get("sign_in_provider")
        if provider != "phone":
            # A project with other providers enabled can mint tokens with no
            # phone number at all; this is what keeps them off this door.
            raise TokenRejected("Sign in with your phone number.")

        phone = claims.get("phone_number")
        uid = claims.get("sub")
        if not phone or not uid:
            raise TokenRejected("That sign-in carried no phone number.")
        return VerifiedPhone(phone=phone, uid=uid)

    async def verify(self, id_token: str) -> VerifiedPhone:
        # Sync, and it fetches Google's signing certificates, so it goes to a
        # worker thread rather than blocking the loop.
        return await anyio.to_thread.run_sync(self._check, id_token)


_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier | None:
    """None when no project is configured, which is what makes the endpoint
    answer 503 rather than pretending to check something."""
    global _verifier
    if _verifier is None:
        settings = get_settings()
        if not settings.firebase_project_id:
            return None
        _verifier = GoogleTokenVerifier(settings)
    return _verifier


def set_verifier(verifier: TokenVerifier | None) -> None:
    global _verifier
    _verifier = verifier
