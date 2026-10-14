from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status

from .. import push, service
from ..config import get_settings
from ..cursor import InvalidCursor, TimeCursor
from ..deps import CurrentUser, SessionDep
from ..images import ImageRejected, process_jpeg
from ..schemas import MeIn, MeOut, Page, PushTokenIn
from ..storage import get_store

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeOut)
async def read_me(user: CurrentUser) -> MeOut:
    return _me(user)


def _me(user) -> MeOut:
    avatar_url = None
    if user.avatar_key:
        avatar_url = get_store().signed_url(
            user.avatar_key, get_settings().signed_url_ttl_seconds
        )
    return MeOut(id=user.id, display_name=user.display_name, avatar_url=avatar_url)


@router.patch("/me", response_model=MeOut)
async def update_me(body: MeIn, session: SessionDep, user: CurrentUser) -> MeOut:
    if not body.display_name.strip():
        raise HTTPException(status_code=422, detail="Give yourself a name.")
    updated = await service.set_display_name(
        session, user=user, display_name=body.display_name
    )
    return _me(updated)


@router.put("/me/avatar", response_model=MeOut)
async def set_avatar(
    session: SessionDep,
    user: CurrentUser,
    photo: Annotated[UploadFile, File()],
) -> MeOut:
    """Same pipeline as a report photo, so a face is stripped of EXIF too."""
    try:
        image = await process_jpeg(await photo.read())
    except ImageRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await photo.close()
    updated = await service.set_avatar(
        session, user=user, store=get_store(), image=image
    )
    return _me(updated)


@router.delete("/me/avatar", response_model=MeOut)
async def delete_avatar(session: SessionDep, user: CurrentUser) -> MeOut:
    updated = await service.clear_avatar(session, user=user, store=get_store())
    return _me(updated)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_me(session: SessionDep, user: CurrentUser) -> None:
    """Close the account and destroy everything that identifies the person.

    Reports and supports stay, credited to nobody: they are the evidence other
    residents built on, and are not this person's to take back. What goes is
    the phone number, the name, the avatar, the notification feed, and any
    outstanding offer to turn up somewhere.
    """
    await service.delete_account(session, user=user, store=get_store())


@router.put("/me/push-tokens", status_code=status.HTTP_204_NO_CONTENT)
async def register_push_token(body: PushTokenIn, session: SessionDep, user: CurrentUser) -> None:
    await push.register(session, user=user, token=body.token, platform=body.platform)


@router.delete("/me/push-tokens/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_push_token(token: str, session: SessionDep, user: CurrentUser) -> None:
    """Called on sign-out, so the next person on this phone is not told about
    the last one's reports. Unknown tokens are not an error."""
    await push.unregister(session, user=user, token=token)


@router.get("/me/issues", response_model=Page)
async def read_my_issues(
    session: SessionDep,
    reporter: CurrentUser,
    cursor: str | None = None,
    limit: Annotated[int | None, Query()] = None,
) -> Page:
    settings = get_settings()
    requested = settings.default_limit if limit is None else limit
    page_size = max(1, min(requested, settings.max_limit))

    parsed: TimeCursor | None = None
    if cursor:
        try:
            parsed = TimeCursor.decode(cursor)
        except InvalidCursor as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return await service.my_issues(
        session,
        reporter=reporter,
        store=get_store(),
        cursor=parsed,
        limit=page_size,
    )
