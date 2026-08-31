from fastapi import APIRouter, HTTPException, Response, status

from .. import firebase, otp
from ..deps import ClientIp, SessionDep
from ..models import User
from ..schemas import FirebaseSignInIn, OtpRequestIn, OtpVerifyIn, RefreshIn, TokenOut
from ..security import TokenInvalid, create_access_token, create_refresh_token, read_token

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user: User) -> TokenOut:
    access_token, expires_in = create_access_token(user.id)
    return TokenOut(
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=create_refresh_token(user.id),
    )


@router.post("/otp/request", status_code=status.HTTP_204_NO_CONTENT)
async def request_code(
    body: OtpRequestIn, session: SessionDep, ip: ClientIp
) -> Response:
    # 204 whether or not the number has an account: the response must not tell
    # a caller which numbers are registered.
    try:
        await otp.request_otp(session, body.phone, ip)
    except otp.RateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/otp/verify", response_model=TokenOut)
async def verify_code(body: OtpVerifyIn, session: SessionDep) -> TokenOut:
    try:
        user = await otp.verify_otp(session, body.phone, body.code)
    except otp.OtpRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    return _tokens(user)


@router.post("/firebase", response_model=TokenOut)
async def sign_in_with_firebase(
    body: FirebaseSignInIn, session: SessionDep
) -> TokenOut:
    """Exchange a Firebase ID token for ours.

    Firebase has already verified the phone number by SMS, which is the part
    that would otherwise need a DLT registration. Everything past this point is
    identical to the OTP path: the same account, keyed on the same phone
    number, and the same pair of tokens back.
    """
    verifier = firebase.get_verifier()
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Signing in with Firebase is not available.",
        )
    try:
        verified = await verifier.verify(body.id_token)
    except firebase.TokenRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc

    user = await otp.upsert_user(session, verified.phone)
    await session.commit()
    return _tokens(user)


@router.post("/token/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, session: SessionDep) -> TokenOut:
    """Not in the contract yet. Access tokens are long-lived by default, so the
    client does not need this until it opts into short ones."""
    try:
        user_id = read_token(body.refresh_token, "refresh")
    except TokenInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)
        ) from exc
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again.",
        )
    return _tokens(user)
