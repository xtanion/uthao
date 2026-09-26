from fastapi import APIRouter, HTTPException, Response, status

from .. import otp
from ..deps import ClientIp, SessionDep
from ..models import User
from ..schemas import OtpRequestIn, OtpVerifyIn, RefreshIn, TokenOut
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
    # A closed account keeps its row, so existing is not enough: without the
    # deleted check its refresh token would mint access tokens indefinitely.
    if user is None or user.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired. Sign in again.",
        )
    return _tokens(user)
