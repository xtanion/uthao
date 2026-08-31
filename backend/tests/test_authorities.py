"""Which body a report is raised with, and whether it can be raised at all."""
from datetime import datetime, timezone

import pytest

from app import mail as mail_module
from app.authority import (
    AuthorityContact,
    ConcernRequest,
    EmailAuthorityChannel,
    authority_for,
)
from app.config import get_settings
from app.db import sessionmaker
from app.enums import ContactChannel, ContactPointKind
from app.mail import MailTransport, OutboundEmail
from app.models import Authority, AuthorityContactPoint

# Somewhere in Bandra East, which is what the rest of the suite reports on.
MUMBAI = (19.0655, 72.8480)
PUNE = (18.5204, 73.8567)
# The Bay of Bengal. Inside the India geofence, inside no corporation.
OPEN_WATER = (15.0, 88.0)


class Post(MailTransport):
    def __init__(self) -> None:
        self.sent: list[OutboundEmail] = []

    async def send(self, message: OutboundEmail) -> str | None:
        self.sent.append(message)
        return message.message_id


def a_request() -> ConcernRequest:
    return ConcernRequest(
        issue_id="0123456789abcdef",
        reporter_name="A resident",
        title="The manhole on the corner is open",
        description="It has been open for a week.",
        category="manhole",
        severity="high",
        locality="Bandra East",
        latitude=MUMBAI[0],
        longitude=MUMBAI[1],
        confirmed_on="2026-08-30",
        photo_support_count=2,
        seen_count=5,
        voices=["A branch is stuck in it."],
    )


def an_authority(slug: str, box, **kwargs) -> Authority:
    low_lat, high_lat, low_lng, high_lng = box
    return Authority(
        slug=slug,
        name=kwargs.pop("name", slug),
        city=kwargs.pop("city", "Somewhere"),
        state=kwargs.pop("state", "Somestate"),
        min_latitude=low_lat,
        max_latitude=high_lat,
        min_longitude=low_lng,
        max_longitude=high_lng,
        verified_at=datetime(2026, 8, 31, tzinfo=timezone.utc),
        **kwargs,
    )


async def save(*rows: Authority) -> None:
    async with sessionmaker()() as session:
        for row in rows:
            session.add(row)
        await session.commit()


async def resolve(point) -> AuthorityContact:
    async with sessionmaker()() as session:
        return await authority_for(session, *point)


async def test_a_report_is_matched_to_the_body_that_covers_it(client):
    await save(
        an_authority(
            "bmc", (18.89, 19.28, 72.77, 72.99),
            name="Brihanmumbai Municipal Corporation",
            channel=ContactChannel.PORTAL,
        ),
        an_authority(
            "pmc", (18.41, 18.64, 73.72, 73.99),
            name="Pune Municipal Corporation",
            channel=ContactChannel.EMAIL,
            email="feedback@punecorporation.org",
        ),
    )

    assert (await resolve(MUMBAI)).name == "Brihanmumbai Municipal Corporation"
    assert (await resolve(PUNE)).email == "feedback@punecorporation.org"


async def test_the_smallest_box_wins(client):
    """A city sitting inside a state-wide row is the one that gets the letter,
    not the state."""
    await save(
        an_authority(
            "maharashtra", (15.6, 22.1, 72.6, 80.9),
            name="the Urban Development Department",
            channel=ContactChannel.EMAIL,
            email="state@example.gov.in",
        ),
        an_authority(
            "bmc", (18.89, 19.28, 72.77, 72.99),
            name="Brihanmumbai Municipal Corporation",
            channel=ContactChannel.PORTAL,
        ),
    )

    assert (await resolve(MUMBAI)).name == "Brihanmumbai Municipal Corporation"


async def test_an_inactive_body_is_not_matched(client):
    await save(
        an_authority(
            "bmc", (18.89, 19.28, 72.77, 72.99),
            name="Brihanmumbai Municipal Corporation",
            channel=ContactChannel.EMAIL,
            email="old@example.gov.in",
            active=False,
        ),
    )

    # Falls through to the setting rather than writing to a retired address.
    assert (await resolve(MUMBAI)).name == get_settings().default_authority


async def test_nowhere_covered_falls_back_to_the_setting(client, monkeypatch):
    monkeypatch.setenv("AUTHORITY_EMAIL", "fallback@example.gov.in")
    get_settings.cache_clear()
    try:
        contact = await resolve(OPEN_WATER)

        assert contact.email == "fallback@example.gov.in"
        assert contact.channel is ContactChannel.EMAIL
    finally:
        monkeypatch.delenv("AUTHORITY_EMAIL", raising=False)
        get_settings.cache_clear()


async def test_the_fallback_with_no_address_is_not_reachable(client):
    contact = await resolve(OPEN_WATER)

    assert contact.email is None
    assert not contact.reachable_by_email


# --- what actually gets sent -----------------------------------------------


async def test_a_portal_only_body_is_not_written_to(client):
    """Most corporations publish a portal and no complaint address. That is
    not a misconfiguration and must not become a letter to nobody."""
    contact = AuthorityContact(
        name="Greater Chennai Corporation",
        email=None,
        channel=ContactChannel.PORTAL,
        portal_url="https://gccservices.chennaicorporation.gov.in/pgr",
    )
    transport = Post()
    mail_module.set_transport(transport)
    try:
        channel = EmailAuthorityChannel("reply-token", contact)

        reference = await channel.send("Subject", "Body", a_request())

        # None is "not sent", which keeps the report's status from moving.
        assert reference is None
        assert transport.sent == []
    finally:
        mail_module.set_transport(None)


async def test_an_email_body_is_written_to(client):
    transport = Post()
    mail_module.set_transport(transport)
    try:
        contact = AuthorityContact(
            name="Pune Municipal Corporation",
            email="feedback@punecorporation.org",
            channel=ContactChannel.EMAIL,
        )
        channel = EmailAuthorityChannel("reply-token", contact)

        reference = await channel.send("Subject", "Body", a_request())

        assert reference is not None
        assert transport.sent[0].to == "feedback@punecorporation.org"
        assert "To the Pune Municipal Corporation," in transport.sent[0].body
    finally:
        mail_module.set_transport(None)


# --- departmental routing --------------------------------------------------


async def a_bmc_with_desks() -> str:
    row = an_authority(
        "bmc", (18.89, 19.28, 72.77, 72.99),
        name="Brihanmumbai Municipal Corporation",
        channel=ContactChannel.PORTAL,
        portal_url="https://portal.mcgm.gov.in/",
    )
    await save(row)
    async with sessionmaker()() as session:
        for kind, key, name, email, active in (
            (ContactPointKind.DEPARTMENT, "pothole_road",
             "Chief Engineer (Roads and Traffic)", "che.rt@mcgm.gov.in", True),
            (ContactPointKind.DEPARTMENT, "garbage",
             "Chief Engineer (Solid Waste Management)", "che.swm@mcgm.gov.in", True),
            (ContactPointKind.WARD, "H/East",
             "Assistant Commissioner, H/East Ward", "ac.heast@mcgm.gov.in", False),
        ):
            session.add(
                AuthorityContactPoint(
                    authority_id=row.id, kind=kind, key=key,
                    name=name, email=email, active=active,
                )
            )
        await session.commit()
    return row.id


async def test_the_department_that_owns_the_category_gets_it(client):
    await a_bmc_with_desks()

    async with sessionmaker()() as session:
        pothole = await authority_for(session, *MUMBAI, "pothole_road")
        rubbish = await authority_for(session, *MUMBAI, "garbage")

    assert pothole.email == "che.rt@mcgm.gov.in"
    assert rubbish.email == "che.swm@mcgm.gov.in"


async def test_a_department_makes_a_portal_body_reachable(client):
    """BMC publishes no complaint address at its front door. A department
    address is what turns that from unsendable into sendable."""
    await a_bmc_with_desks()

    async with sessionmaker()() as session:
        front_door = await authority_for(session, *MUMBAI)
        routed = await authority_for(session, *MUMBAI, "pothole_road")

    assert not front_door.reachable_by_email
    assert routed.reachable_by_email


async def test_the_corporation_is_still_who_the_letter_addresses(client):
    """The department opens it; the corporation is answerable for it."""
    await a_bmc_with_desks()

    async with sessionmaker()() as session:
        contact = await authority_for(session, *MUMBAI, "pothole_road")

    assert contact.name == "Brihanmumbai Municipal Corporation"


async def test_an_unmapped_category_falls_back_to_the_front_door(client):
    """Traffic infrastructure is not one department's, and guessing would put
    it on the wrong desk."""
    await a_bmc_with_desks()

    async with sessionmaker()() as session:
        contact = await authority_for(session, *MUMBAI, "traffic_infrastructure")

    assert contact.email is None
    assert contact.channel is ContactChannel.PORTAL


async def test_ward_desks_are_not_routed_to_yet(client):
    """They are the better destination, and they need ward geometry. Until
    then they are carried, not used."""
    await a_bmc_with_desks()

    async with sessionmaker()() as session:
        contact = await authority_for(session, *MUMBAI, "H/East")

    assert contact.email != "ac.heast@mcgm.gov.in"
