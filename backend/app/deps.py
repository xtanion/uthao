import ipaddress
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .models import User
from .security import TokenInvalid, read_token

bearer = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]

UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to continue.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def optional_user(
    credentials: CredentialsDep, session: SessionDep
) -> User | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        user_id = read_token(credentials.credentials, "access")
    except TokenInvalid:
        return None
    user = await session.get(User, user_id)
    return None if user is None or user.is_deleted else user


async def current_user(
    credentials: CredentialsDep, session: SessionDep
) -> User:
    if credentials is None or not credentials.credentials:
        raise UNAUTHENTICATED
    try:
        user_id = read_token(credentials.credentials, "access")
    except TokenInvalid as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    user = await session.get(User, user_id)
    if user is None or user.is_deleted:
        # Tokens outlive the account by up to 30 days, so this is the check
        # that actually ends the session.
        raise UNAUTHENTICATED
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(optional_user)]


def client_ip(request: Request) -> str:
    """The address the per-IP OTP limit counts against.

    Only CLIENT_IP_HEADER is believed, because the proxy in front overwrites
    it; any other header is whatever the caller chose to send, and reading one
    let anybody walk past the limit by changing it per request. Of a list, the
    last entry is the one the nearest proxy added.
    """
    name = get_settings().client_ip_header
    if name:
        value = request.headers.get(name, "").split(",")[-1].strip()
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            # Missing or junk: fall back to the peer, which at worst puts
            # everyone behind the proxy in one bucket rather than none.
            pass
    return request.client.host if request.client else "unknown"


ClientIp = Annotated[str, Depends(client_ip)]
