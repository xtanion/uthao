import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .models import OtpChallenge, OtpRequestLog, User, new_id
from .security import generate_otp, hash_otp, otp_matches

log = logging.getLogger(__name__)


# What the app calls people until they pick a name. Letters to an authority
# say "Resident" instead; see jobs.formal_name.
DEFAULT_NAME = "Hooman"
DEFAULT_NAME_PATTERN = re.compile(rf"^{DEFAULT_NAME} (\d{{4}})$")


class RateLimited(Exception):
    pass


class OtpRejected(Exception):
    pass


class OtpSender:
    async def send(self, phone: str, code: str) -> None:
        raise NotImplementedError


class ConsoleOtpSender(OtpSender):
    """Development sender. Swap in an SMS provider before shipping."""

    async def send(self, phone: str, code: str) -> None:
        log.warning("OTP for %s is %s (no SMS provider configured)", phone, code)


_sender: OtpSender = ConsoleOtpSender()


def set_sender(sender: OtpSender) -> None:
    global _sender
    _sender = sender


async def _count_since(
    session: AsyncSession, column, value: str, since: datetime
) -> int:
    total = await session.scalar(
        select(func.count())
        .select_from(OtpRequestLog)
        .where(column == value, OtpRequestLog.created_at >= since)
    )
    return int(total or 0)


async def request_otp(session: AsyncSession, phone: str, ip: str) -> None:
    settings = get_settings()
    since = datetime.now(timezone.utc) - timedelta(hours=1)

    by_phone = await _count_since(session, OtpRequestLog.phone, phone, since)
    by_ip = await _count_since(session, OtpRequestLog.ip, ip, since)
    if (
        by_phone >= settings.otp_requests_per_phone_per_hour
        or by_ip >= settings.otp_requests_per_ip_per_hour
    ):
        raise RateLimited("Too many codes requested. Try again in an hour.")

    code = generate_otp()
    session.add(OtpRequestLog(phone=phone, ip=ip))
    session.add(
        OtpChallenge(
            phone=phone,
            code_hash=hash_otp(phone, code),
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=settings.otp_ttl_seconds),
        )
    )
    await session.commit()
    await _sender.send(phone, code)


async def upsert_user(session: AsyncSession, phone: str) -> User:
    """Find or create the account for a verified number.

    Shared with the Firebase path: however the number was verified, it is the
    same person and the same account.
    """
    user = await session.scalar(select(User).where(User.phone == phone))
    if user is not None:
        return user
    user = User(
        id=new_id(), phone=phone, display_name=f"{DEFAULT_NAME} {phone[-4:]}"
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        existing = await session.scalar(select(User).where(User.phone == phone))
        if existing is None:
            raise
        return existing
    return user


async def verify_otp(session: AsyncSession, phone: str, code: str) -> User:
    settings = get_settings()
    if settings.otp_debug_code and code == settings.otp_debug_code:
        user = await upsert_user(session, phone)
        await session.commit()
        return user

    now = datetime.now(timezone.utc)
    challenge = await session.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    )
    rejected = OtpRejected("That code is wrong or has expired. Request a new one.")
    if challenge is None:
        raise rejected

    expires_at = challenge.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now or challenge.attempts >= settings.otp_max_attempts:
        raise rejected

    if not otp_matches(phone, code, challenge.code_hash):
        challenge.attempts += 1
        await session.commit()
        raise rejected

    challenge.consumed_at = now
    user = await upsert_user(session, phone)
    await session.commit()
    return user
