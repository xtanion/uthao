import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)

from .. import service
from ..config import get_settings
from ..cursor import InvalidCursor, NearbyCursor, TimeCursor
from ..deps import CurrentUser, OptionalUser, SessionDep
from ..enums import Category, Severity, Status
from ..geo import within_geofence
from ..images import ImageRejected, ProcessedImage, process_jpeg
from ..schemas import (
    EscalationOut,
    DuplicatesOut,
    FixDateIn,
    FixDatesOut,
    IssueOut,
    Page,
    PhotoOut,
    SupportPage,
)
from ..storage import get_store

router = APIRouter(prefix="/issues", tags=["issues"])

NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="That report is no longer available.",
)


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


@router.get("/nearby", response_model=Page)
async def nearby(
    session: SessionDep,
    viewer: OptionalUser,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    radius_m: Annotated[float | None, Query(gt=0)] = None,
    category: Category | None = None,
    severity: Severity | None = None,
    status_filter: Annotated[Status | None, Query(alias="status")] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    cursor: str | None = None,
    limit: int | None = None,
) -> Page:
    settings = get_settings()
    requested_radius = settings.default_radius_m if radius_m is None else radius_m
    radius = min(requested_radius, settings.max_radius_m)
    requested_limit = settings.default_limit if limit is None else limit
    page_size = max(1, min(requested_limit, settings.max_limit))

    parsed: NearbyCursor | None = None
    if cursor:
        try:
            parsed = NearbyCursor.decode(cursor)
        except InvalidCursor as exc:
            raise _unprocessable(str(exc)) from exc

    return await service.nearby(
        session,
        viewer=viewer,
        store=get_store(),
        latitude=lat,
        longitude=lng,
        radius_m=radius,
        category=category,
        severity=severity,
        status=status_filter,
        query=q,
        cursor=parsed,
        limit=page_size,
    )


@router.get("/duplicates", response_model=DuplicatesOut)
async def duplicates(
    session: SessionDep,
    viewer: OptionalUser,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    category: Category | None = None,
    radius_m: Annotated[float | None, Query(gt=0)] = None,
) -> DuplicatesOut:
    """Reports near enough that a new one is probably the same thing.

    The report screen calls this before publishing so it can offer to add the
    photo to what is already there rather than filing a second report on the
    same pothole.
    """
    settings = get_settings()
    radius = min(
        settings.duplicate_radius_m if radius_m is None else radius_m,
        settings.max_radius_m,
    )
    return await service.duplicates(
        session,
        viewer=viewer,
        store=get_store(),
        latitude=lat,
        longitude=lng,
        category=category,
        radius_m=radius,
    )


@router.get("/{issue_id}", response_model=IssueOut)
async def read(
    issue_id: str, session: SessionDep, viewer: OptionalUser
) -> IssueOut:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    return await service.serialize(
        session, issue, viewer, get_store(), with_photos=True
    )


def _normalized_report_id(raw: str) -> str:
    try:
        return str(uuid.UUID(raw.strip()))
    except ValueError as exc:
        raise _unprocessable("client_report_id must be a UUID.") from exc


async def _processed_photos(
    photos: list[UploadFile], *, required: bool = True
) -> list[ProcessedImage]:
    settings = get_settings()
    usable = [photo for photo in photos if photo.filename or photo.size]
    if not usable:
        if not required:
            return []
        raise _unprocessable("Attach at least one photo.")
    if len(usable) > settings.max_photos_per_report:
        raise _unprocessable(
            f"Attach at most {settings.max_photos_per_report} photos."
        )
    processed = []
    for photo in usable:
        try:
            processed.append(await process_jpeg(await photo.read()))
        except ImageRejected as exc:
            raise _unprocessable(str(exc)) from exc
        finally:
            await photo.close()
    return processed


@router.post("", response_model=IssueOut, status_code=status.HTTP_201_CREATED)
async def create(
    session: SessionDep,
    reporter: CurrentUser,
    background: BackgroundTasks,
    client_report_id: Annotated[str, Form(max_length=64)],
    title: Annotated[str, Form(min_length=3, max_length=140)],
    category: Annotated[Category, Form()],
    severity: Annotated[Severity, Form()],
    latitude: Annotated[float, Form(ge=-90, le=90)],
    longitude: Annotated[float, Form(ge=-180, le=180)],
    photos: Annotated[list[UploadFile], File()],
    description: Annotated[str, Form(max_length=2000)] = "",
) -> IssueOut:
    report_id = _normalized_report_id(client_report_id)
    if not title.strip():
        raise _unprocessable("Give the report a short title.")
    if not within_geofence(latitude, longitude):
        raise _unprocessable("Reports are only accepted inside India for now.")

    try:
        await service.check_write_budget(session, reporter, kind="report")
    except service.TooManyWrites as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    processed = await _processed_photos(photos)
    try:
        issue, _ = await service.create_issue(
            session,
            reporter=reporter,
            store=get_store(),
            client_report_id=report_id,
            title=title.strip(),
            description=description.strip(),
            category=category,
            severity=severity,
            latitude=latitude,
            longitude=longitude,
            photos=processed,
        )
    except service.ConflictError as exc:
        raise _unprocessable(str(exc)) from exc

    if service.summary_is_due(issue):
        background.add_task(service.refresh_summary, issue.id)
    return await service.serialize(session, issue, reporter, get_store())


@router.get("/{issue_id}/supports", response_model=SupportPage)
async def read_supports(
    issue_id: str,
    session: SessionDep,
    viewer: OptionalUser,
    cursor: str | None = None,
    limit: Annotated[int | None, Query()] = None,
) -> SupportPage:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND

    settings = get_settings()
    requested = settings.default_limit if limit is None else limit
    page_size = max(1, min(requested, settings.max_limit))

    parsed: TimeCursor | None = None
    if cursor:
        try:
            parsed = TimeCursor.decode(cursor)
        except InvalidCursor as exc:
            raise _unprocessable(str(exc)) from exc

    return await service.supports(
        session,
        issue=issue,
        viewer=viewer,
        store=get_store(),
        cursor=parsed,
        limit=page_size,
    )


@router.get("/{issue_id}/escalation", response_model=EscalationOut)
async def read_escalation(issue_id: str, session: SessionDep) -> EscalationOut:
    """The letter raised with the authority, readable by the people it was sent
    for. Never carries the recipient address or the reply token."""
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    record = await service.escalation_for(session, issue)
    if record is None:
        raise HTTPException(
            status_code=404, detail="This report has not been raised yet."
        )
    return EscalationOut(
        authority=record.authority,
        state=record.state,
        subject=record.subject,
        body=record.body,
        reference=record.reference,
        detail=record.detail,
        sent_at=record.sent_at,
    )


@router.get("/{issue_id}/photos", response_model=list[PhotoOut])
async def read_photos(issue_id: str, session: SessionDep) -> list[PhotoOut]:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    return await service.gallery(session, issue, get_store())


@router.post("/{issue_id}/supports", response_model=IssueOut)
async def write_support(
    issue_id: str,
    session: SessionDep,
    user: CurrentUser,
    background: BackgroundTasks,
    body: Annotated[str | None, Form(max_length=2000)] = None,
    photos: Annotated[list[UploadFile] | None, File()] = None,
    latitude: Annotated[float | None, Form(ge=-90, le=90)] = None,
    longitude: Annotated[float | None, Form(ge=-180, le=180)] = None,
) -> IssueOut:
    """Back a report, optionally with words and photos.

    Multipart rather than JSON because photos travel with it. Supporting twice
    updates the row instead of failing, which is what someone adding a photo to
    something they already backed expects. Photos need the phone's location,
    and it has to be near the report.
    """
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    if (latitude is None) != (longitude is None):
        raise _unprocessable("Send latitude and longitude together.")
    location = None if latitude is None else (latitude, longitude)

    try:
        await service.check_write_budget(session, user, kind="support")
    except service.TooManyWrites as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    text = (body or "").strip() or None
    processed = await _processed_photos(photos or [], required=False)
    try:
        issue = await service.add_support(
            session,
            issue=issue,
            user=user,
            store=get_store(),
            body=text,
            photos=processed,
            location=location,
        )
    except service.SelfConfirmation as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    except (service.ConflictError, service.NotStandingThere) as exc:
        raise _unprocessable(str(exc)) from exc

    # Only words change what a summary would say; a bare +1 does not.
    if text and service.summary_is_due(issue):
        background.add_task(service.refresh_summary, issue.id)
    return await service.serialize(session, issue, user, get_store())


@router.delete("/{issue_id}/supports", response_model=IssueOut)
async def withdraw_support(
    issue_id: str, session: SessionDep, user: CurrentUser
) -> IssueOut:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    issue = await service.remove_support(session, issue, user, get_store())
    return await service.serialize(session, issue, user, get_store())


def _poll_refused(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/{issue_id}/fix-dates", response_model=FixDatesOut)
async def read_fix_dates(
    issue_id: str, session: SessionDep, viewer: OptionalUser
) -> FixDatesOut:
    """Readable before the window opens, so people can see what is coming."""
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    return await service.fix_dates(session, issue=issue, viewer=viewer)


@router.post("/{issue_id}/fix-dates", response_model=FixDatesOut)
async def propose_fix_date(
    issue_id: str, session: SessionDep, user: CurrentUser, body: FixDateIn
) -> FixDatesOut:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    try:
        return await service.propose_fix_date(
            session,
            issue=issue,
            user=user,
            fix_on=body.fix_on,
            fix_time=body.fix_time,
        )
    except (service.PollClosed, service.PollFull, service.AlreadyProposed) as exc:
        raise _poll_refused(exc) from exc


@router.post("/{issue_id}/fix-dates/{fix_date_id}/votes", response_model=FixDatesOut)
async def back_fix_date(
    issue_id: str, fix_date_id: str, session: SessionDep, user: CurrentUser
) -> FixDatesOut:
    return await _vote(session, issue_id, fix_date_id, user, on=True)


@router.delete("/{issue_id}/fix-dates/{fix_date_id}/votes", response_model=FixDatesOut)
async def drop_fix_date_vote(
    issue_id: str, fix_date_id: str, session: SessionDep, user: CurrentUser
) -> FixDatesOut:
    return await _vote(session, issue_id, fix_date_id, user, on=False)


async def _vote(
    session, issue_id: str, fix_date_id: str, user, *, on: bool
) -> FixDatesOut:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    try:
        result = await service.vote_fix_date(
            session, issue=issue, user=user, fix_date_id=fix_date_id, on=on
        )
    except service.PollClosed as exc:
        raise _poll_refused(exc) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="That day is no longer on this report.",
        )
    return result


@router.post("/{issue_id}/confirmations", response_model=IssueOut)
async def confirm(
    issue_id: str, session: SessionDep, user: CurrentUser
) -> IssueOut:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    try:
        issue = await service.add_support(
            session,
            issue=issue,
            user=user,
            store=get_store(),
            body=None,
            photos=[],
        )
    except service.SelfConfirmation as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
    return await service.serialize(session, issue, user, get_store())


@router.delete("/{issue_id}/confirmations", response_model=IssueOut)
async def unconfirm(
    issue_id: str, session: SessionDep, user: CurrentUser
) -> IssueOut:
    issue = await service.get_visible_issue(session, issue_id)
    if issue is None:
        raise NOT_FOUND
    issue = await service.remove_support(session, issue, user, get_store())
    return await service.serialize(session, issue, user, get_store())
