"""Seed the authorities table.

Idempotent: matched on `slug`, so re-running updates a contact that has
changed rather than duplicating the body.

    uv run python scripts/seed_authorities.py

On what is in here. Six corporations were checked against their own sites in
August 2026, and only one of them - Pune - publishes an address a resident is
invited to send a complaint to. The rest run a portal and a helpline. Several
do publish a Municipal Commissioner's address, and those are deliberately not
recorded: a commissioner's office is an executive desk, and a stream of
automated pothole letters arriving there is how a domain earns a spam
reputation, which then costs us the one address that does work.

So the portal rows carry no email and send nothing. They are here because they
are still the truth about where a complaint goes, because the app can show a
resident the portal and the helpline, and because a portal integration needs
somewhere to hang. Fill in `email` and flip `channel` for any body you can
confirm accepts complaints by mail.

The boxes are approximate city extents, not corporation boundaries. They are
good enough to pick the right corporation in a metro and should be replaced
with real ward geometry before that claim gets load-bearing.
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import dispose, sessionmaker
from app.enums import Category, ContactChannel, ContactPointKind
from app.models import Authority, AuthorityContactPoint

CHECKED = datetime(2026, 8, 31, tzinfo=timezone.utc)

AUTHORITIES = [
    {
        "slug": "pmc-pune",
        "name": "Pune Municipal Corporation",
        "city": "Pune",
        "state": "Maharashtra",
        "channel": ContactChannel.EMAIL,
        "email": "feedback@punecorporation.org",
        "portal_url": "https://complaint.pmc.gov.in/",
        "helpline": "020-25501000",
        "box": (18.41, 18.64, 73.72, 73.99),
        "source_url": "https://www.pmc.gov.in/en/grievance-redressal",
    },
    {
        "slug": "bmc-mumbai",
        "name": "Brihanmumbai Municipal Corporation",
        "city": "Mumbai",
        "state": "Maharashtra",
        "channel": ContactChannel.PORTAL,
        "email": None,
        "portal_url": "https://portal.mcgm.gov.in/irj/portal/anonymous/qlcomplaintreg",
        "helpline": "1916",
        "box": (18.89, 19.28, 72.77, 72.99),
        "source_url": "https://portal.mcgm.gov.in/irj/portal/anonymous/contactus",
    },
    {
        "slug": "bbmp-bengaluru",
        "name": "Bruhat Bengaluru Mahanagara Palike",
        "city": "Bengaluru",
        "state": "Karnataka",
        "channel": ContactChannel.PORTAL,
        "email": None,
        "portal_url": "https://site.bbmp.gov.in/MP3.html",
        "helpline": "1533",
        "box": (12.83, 13.14, 77.46, 77.78),
        "source_url": "https://site.bbmp.gov.in/contact.html",
    },
    {
        "slug": "mcd-delhi",
        "name": "Municipal Corporation of Delhi",
        "city": "Delhi",
        "state": "Delhi",
        "channel": ContactChannel.PORTAL,
        # The only address MCD publishes is an IT helpdesk for portal logins.
        "email": None,
        "portal_url": "https://mcdonline.nic.in/portal/contactUs",
        "helpline": "155305",
        "box": (28.40, 28.88, 76.84, 77.35),
        "source_url": "https://mcdonline.nic.in/portal/contactUs",
    },
    {
        "slug": "gcc-chennai",
        "name": "Greater Chennai Corporation",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "channel": ContactChannel.PORTAL,
        "email": None,
        "portal_url": "https://gccservices.chennaicorporation.gov.in/pgr",
        "helpline": "1913",
        "box": (12.83, 13.24, 80.12, 80.33),
        "source_url": "https://chennaicorporation.gov.in/gcc/complaints/",
    },
    {
        "slug": "ghmc-hyderabad",
        "name": "Greater Hyderabad Municipal Corporation",
        "city": "Hyderabad",
        "state": "Telangana",
        "channel": ContactChannel.PORTAL,
        "email": None,
        "portal_url": "https://igs.ghmc.gov.in/",
        "helpline": "21111111",
        "box": (17.25, 17.60, 78.24, 78.63),
        "source_url": "https://www.ghmc.gov.in/KeyContacts.aspx",
    },
]


# MCGM publishes a department directory, which is where these come from. It is
# dated July 2019, so treat it as a lead rather than a fact: these are role
# addresses (`che.rt@`, `ac.heast@`) rather than named individuals, which is
# the kind that survives a reshuffle, but each one still wants a test message
# before a resident's complaint is sent to it.
MCGM_DIRECTORY = (
    "https://portal.mcgm.gov.in/irj/go/km/docs/documents/MCGM%20Department%20List"
    "/IT%20Department/Email%20IDs%20for%20MCGM%20employees"
    "/Executive%20feature%20mcgm%20email%20users.pdf"
)

# What is broken decides the desk. Categories left out - traffic
# infrastructure, public property, other - are deliberate: they are not one
# department's, and guessing would put a complaint on the wrong desk, which is
# worse than the corporation's own front door.
BMC_DEPARTMENTS = [
    (Category.POTHOLE_ROAD, "Chief Engineer (Roads and Traffic)", "che.rt@mcgm.gov.in"),
    (Category.FOOTPATH, "Chief Engineer (Roads and Traffic)", "che.rt@mcgm.gov.in"),
    (Category.GARBAGE, "Chief Engineer (Solid Waste Management)", "che.swm@mcgm.gov.in"),
    (Category.WATER_DRAINAGE, "Chief Engineer (Storm Water Drains)", "che.swd@mcgm.gov.in"),
    (Category.MANHOLE, "Chief Engineer (Storm Water Drains)", "che.swd@mcgm.gov.in"),
    (Category.STREETLIGHT, "Chief Engineer (Mechanical and Electrical)", "che.me@mcgm.gov.in"),
    (Category.FALLEN_TREE, "Superintendent of Gardens", "sg.gardens@mcgm.gov.in"),
]

# All 24 of them. Inactive: an assistant commissioner's ward office is the
# right destination for a civic complaint - better than a citywide chief
# engineer - but choosing between them needs ward boundaries, and the box on
# the BMC row is the whole city. They are here so that the day geometry lands,
# routing is a join rather than another trip through a 2019 PDF.
BMC_WARDS = [
    ("A", "ac.a@mcgm.gov.in"), ("B", "ac.b@mcgm.gov.in"),
    ("C", "ac.c@mcgm.gov.in"), ("D", "ac.d@mcgm.gov.in"),
    ("E", "ac.e@mcgm.gov.in"), ("F/North", "ac.fn@mcgm.gov.in"),
    ("F/South", "ac.fs@mcgm.gov.in"), ("G/North", "ac.gn@mcgm.gov.in"),
    ("G/South", "ac.gs@mcgm.gov.in"), ("H/East", "ac.heast@mcgm.gov.in"),
    ("H/West", "ac.hw@mcgm.gov.in"), ("K/East", "ac.ke@mcgm.gov.in"),
    ("K/West", "ac.kw@mcgm.gov.in"), ("L", "ac.l@mcgm.gov.in"),
    ("M/East", "ac.meast@mcgm.gov.in"), ("M/West", "ac.mw@mcgm.gov.in"),
    ("N", "ac.n@mcgm.gov.in"), ("P/North", "ac.pn@mcgm.gov.in"),
    ("P/South", "ac.ps@mcgm.gov.in"), ("R/Central", "ac.rc@mcgm.gov.in"),
    ("R/North", "ac.rn@mcgm.gov.in"), ("R/South", "ac.rs@mcgm.gov.in"),
    ("S", "ac.s@mcgm.gov.in"), ("T", "ac.t@mcgm.gov.in"),
]


async def main() -> None:
    async with sessionmaker()() as session:
        for entry in AUTHORITIES:
            row = await session.scalar(
                select(Authority).where(Authority.slug == entry["slug"])
            )
            if row is None:
                row = Authority(slug=entry["slug"])
                session.add(row)
            low_lat, high_lat, low_lng, high_lng = entry["box"]
            row.name = entry["name"]
            row.city = entry["city"]
            row.state = entry["state"]
            row.channel = entry["channel"]
            row.email = entry["email"]
            row.portal_url = entry["portal_url"]
            row.helpline = entry["helpline"]
            row.min_latitude, row.max_latitude = low_lat, high_lat
            row.min_longitude, row.max_longitude = low_lng, high_lng
            row.source_url = entry["source_url"]
            row.verified_at = CHECKED
            row.active = True
        await session.flush()

        bmc = await session.scalar(
            select(Authority).where(Authority.slug == "bmc-mumbai")
        )
        desks = [
            (ContactPointKind.DEPARTMENT, category.value, name, email, True)
            for category, name, email in BMC_DEPARTMENTS
        ] + [
            (ContactPointKind.WARD, code, f"Assistant Commissioner, {code} Ward", email, False)
            for code, email in BMC_WARDS
        ]
        for kind, key, name, email, active in desks:
            point = await session.scalar(
                select(AuthorityContactPoint).where(
                    AuthorityContactPoint.authority_id == bmc.id,
                    AuthorityContactPoint.kind == kind,
                    AuthorityContactPoint.key == key,
                )
            )
            if point is None:
                point = AuthorityContactPoint(
                    authority_id=bmc.id, kind=kind, key=key
                )
                session.add(point)
            point.name = name
            point.email = email
            point.active = active
            point.source_url = MCGM_DIRECTORY
            point.verified_at = CHECKED

        await session.commit()

    postable = sum(1 for e in AUTHORITIES if e["channel"] is ContactChannel.EMAIL)
    print(
        f"{len(AUTHORITIES)} authorities, {postable} reachable by email at the "
        f"front door; {len(BMC_DEPARTMENTS)} BMC departments routable by "
        f"category, {len(BMC_WARDS)} wards held for geometry"
    )
    await dispose()


if __name__ == "__main__":
    asyncio.run(main())
