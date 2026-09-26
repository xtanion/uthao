import hashlib
import hmac
import time
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from .. import inbound
from ..config import get_settings
from ..deps import SessionDep

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class InboundMailIn(BaseModel):
    # The address the provider delivered to. This is what says which report the
    # reply belongs to.
    to: str = Field(max_length=320)
    sender: str = Field(max_length=320)
    subject: str = Field(default="", max_length=998)
    body: str = Field(default="", max_length=200_000)
    message_id: str | None = Field(default=None, max_length=300)


class DeliveryIn(BaseModel):
    to: str = Field(max_length=320)
    delivered: bool
    detail: str | None = Field(default=None, max_length=2000)


async def _verified(
    request: Request, signature: str | None, timestamp: str | None
) -> bytes:
    """The reply address is unguessable, but this endpoint is not: without a
    signature anyone who learned an address could post a fake resolution and
    close a real problem.

    The signature covers when the request was sent as well as what it says,
    and anything older than the tolerance is refused. Signing the body alone
    left a captured request valid forever: a bounce replayed next month would
    still send a report backwards.
    """
    settings = get_settings()
    secret = settings.inbound_mail_secret
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Inbound mail is not configured.",
        )
    raw = await request.body()
    if not signature or not timestamp or not timestamp.isdigit():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That signature does not match.",
        )
    signed = timestamp.encode() + b"." + raw
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That signature does not match.",
        )
    if abs(time.time() - int(timestamp)) > settings.webhook_tolerance_seconds:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That request is too old to accept.",
        )
    return raw


@router.post("/inbound-mail", status_code=status.HTTP_204_NO_CONTENT)
async def inbound_mail(
    request: Request,
    session: SessionDep,
    body: InboundMailIn,
    x_fihy_signature: Annotated[str | None, Header()] = None,
    x_fihy_timestamp: Annotated[str | None, Header()] = None,
) -> None:
    await _verified(request, x_fihy_signature, x_fihy_timestamp)
    await inbound.record_reply(
        session,
        inbound.InboundMail(
            to=body.to,
            sender=body.sender,
            subject=body.subject,
            body=body.body,
            message_id=body.message_id,
        ),
    )


@router.post("/mail-events", status_code=status.HTTP_204_NO_CONTENT)
async def mail_events(
    request: Request,
    session: SessionDep,
    body: DeliveryIn,
    x_fihy_signature: Annotated[str | None, Header()] = None,
    x_fihy_timestamp: Annotated[str | None, Header()] = None,
) -> None:
    await _verified(request, x_fihy_signature, x_fihy_timestamp)
    await inbound.record_delivery(
        session,
        inbound.Delivery(to=body.to, delivered=body.delivered, detail=body.detail),
    )
