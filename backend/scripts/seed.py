"""Fill the database with plausible Mumbai reports for running the app locally.

Goes through the real service layer rather than writing rows directly, so the
photos take the same path a real upload does: EXIF stripped, thumbnail derived,
object stored, signed URL handed back. What the app renders is what it would
render in production.

    uv run python scripts/seed.py --reset
"""
import argparse
import asyncio
import io
import math
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy import delete, select, update

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, service  # noqa: E402
from app.enums import Category, EscalationState, Severity, Status  # noqa: E402
from app.images import process_jpeg  # noqa: E402
from app.models import (
    ActivityEvent, Escalation, Issue, IssuePhoto, Support, User, new_id, utcnow,
)  # noqa: E402
from app.storage import get_store  # noqa: E402

CENTRE = (19.0612, 72.8371)

LOCALITIES = [
    "Bandra East", "Khar Road", "Santacruz West", "Dadar TT", "Sion Circle",
    "Andheri East", "Mahim Junction", "Matunga", "Vile Parle", "Kurla West",
]

# Base colours per category, so the grid reads as varied at a glance.
PALETTE = {
    Category.POTHOLE_ROAD: (74, 78, 84),
    Category.GARBAGE: (96, 84, 52),
    Category.FOOTPATH: (108, 102, 96),
    Category.STREETLIGHT: (44, 52, 76),
    Category.WATER_DRAINAGE: (48, 78, 92),
    Category.MANHOLE: (62, 62, 66),
    Category.TRAFFIC_INFRASTRUCTURE: (104, 72, 54),
    Category.FALLEN_TREE: (60, 84, 58),
    Category.PUBLIC_PROPERTY: (84, 76, 92),
    Category.OTHER: (80, 80, 84),
}

REPORTS = [
    ("Cover missing on the footpath side", "Manhole cover has been gone about a week. Unlit after dark and the gap is wide enough to take a leg.", Category.MANHOLE, Severity.HIGH),
    ("Water collects across both lanes", "Standing water across the full width after any rain. Two-wheelers are going onto the footpath to get past.", Category.POTHOLE_ROAD, Severity.MEDIUM),
    ("Whole stretch dark between market and bridge", "None of the lights on this stretch have worked since the storm. People are walking in the road.", Category.STREETLIGHT, Severity.HIGH),
    ("Rubbish piled beside the school gate", "Uncollected for days and children walk past it twice a day. Dogs have been pulling it into the road.", Category.GARBAGE, Severity.MEDIUM),
    ("Footpath slabs lifted outside the clinic", "Several slabs have lifted and rock underfoot. Someone using a walking stick would go over.", Category.FOOTPATH, Severity.MEDIUM),
    ("Drain backing up at the junction", "Comes up through the grate every high tide and floods the corner shop.", Category.WATER_DRAINAGE, Severity.HIGH),
    ("Signal out at the crossing", "Traffic signal has been dead since Tuesday. Nobody is giving way and there are near misses all morning.", Category.TRAFFIC_INFRASTRUCTURE, Severity.HIGH),
    ("Branch down across the service road", "Came down in the wind and is blocking one side completely.", Category.FALLEN_TREE, Severity.MEDIUM),
    ("Bus shelter bench broken", "Bench has collapsed at one end, so people are standing in the sun.", Category.PUBLIC_PROPERTY, Severity.LOW),
    ("Potholes right along the approach", "A run of deep potholes on the approach to the flyover. Autos are swerving into the next lane.", Category.POTHOLE_ROAD, Severity.HIGH),
    ("Streetlight flickering all night", "Comes on and off every few seconds. More disorienting than having it off.", Category.STREETLIGHT, Severity.LOW),
    ("Skip has not been emptied", "Overflowing and starting to smell in this heat.", Category.GARBAGE, Severity.MEDIUM),
    ("Open drain beside the footpath", "No cover for about ten feet. Fine in daylight, dangerous at night.", Category.WATER_DRAINAGE, Severity.HIGH),
    ("Railing missing on the overbridge", "A section of railing has gone from the middle of the span.", Category.PUBLIC_PROPERTY, Severity.HIGH),
    ("Footpath blocked by parked bikes", "Parked two deep every evening, so the footpath is unusable and people walk in traffic.", Category.FOOTPATH, Severity.LOW),
    ("Speed breaker worn flat", "Worn down to nothing and nobody slows for the crossing any more.", Category.TRAFFIC_INFRASTRUCTURE, Severity.MEDIUM),
    ("Water leaking from the main", "Been running for three days down the side of the road.", Category.WATER_DRAINAGE, Severity.MEDIUM),
    ("Tree leaning over the wires", "Leaning badly after the rain and the upper branches are into the power line.", Category.FALLEN_TREE, Severity.HIGH),
    ("Rubbish dumped on the empty plot", "People are dumping construction waste here overnight.", Category.GARBAGE, Severity.LOW),
    ("Pothole at the bus stop", "Right where the buses pull in, so it fills with water and sprays everyone waiting.", Category.POTHOLE_ROAD, Severity.MEDIUM),
    ("Manhole cover sits proud of the road", "Raised a good three inches. Heard a scooter bottom out on it last night.", Category.MANHOLE, Severity.MEDIUM),
    ("No light at the corner shop turn", "Pitch dark at the turning and it is a blind corner.", Category.STREETLIGHT, Severity.MEDIUM),
    ("Broken glass along the footpath", "Someone smashed bottles along the whole stretch.", Category.OTHER, Severity.LOW),
    ("Drain cover cracked through", "Cracked across the middle and sagging. Will not hold much longer.", Category.MANHOLE, Severity.HIGH),
    ("Footpath ends without a ramp", "Just a drop at the end, so wheelchairs and prams have to go into the road.", Category.FOOTPATH, Severity.MEDIUM),
    ("Zebra crossing worn away", "Nothing left of the markings outside the school.", Category.TRAFFIC_INFRASTRUCTURE, Severity.MEDIUM),
    ("Bin missing from the park gate", "Bin was removed and not replaced, so litter is going straight on the ground.", Category.GARBAGE, Severity.LOW),
    ("Puddle never drains outside the station", "Sits there for days after rain and everyone has to step into traffic.", Category.WATER_DRAINAGE, Severity.MEDIUM),
    ("Bench and lamp both vandalised", "Lamp post bent and the bench slats pulled off.", Category.PUBLIC_PROPERTY, Severity.MEDIUM),
    ("Loose slab throws water on passers-by", "Rocks when stepped on and throws dirty water up at whoever is next to you.", Category.FOOTPATH, Severity.LOW),
    ("Road edge collapsing into the drain", "The edge is giving way where the drain runs underneath.", Category.POTHOLE_ROAD, Severity.HIGH),
    ("Dead streetlight outside the temple", "Out for a fortnight now. Busy every evening.", Category.STREETLIGHT, Severity.MEDIUM),
    ("Overflowing drain at the market end", "Backs up every morning when the market washes down.", Category.WATER_DRAINAGE, Severity.MEDIUM),
    ("Barricade left in the middle of the road", "Left behind after the roadworks finished and nobody has taken it away.", Category.OTHER, Severity.MEDIUM),
    ("Kerb broken at the crossing point", "Broken away exactly where people cross.", Category.FOOTPATH, Severity.LOW),
    ("Rubbish burning beside the road", "Someone sets it alight most evenings and the smoke goes into the flats.", Category.GARBAGE, Severity.HIGH),
    ("Signal timing far too short", "Green for about four seconds. Nobody older gets across in one go.", Category.TRAFFIC_INFRASTRUCTURE, Severity.MEDIUM),
    ("Uprooted tree still lying there", "Came down in last month's storm and is still across the verge.", Category.FALLEN_TREE, Severity.LOW),
    ("Cover rattles under every vehicle", "Loud enough to wake the whole street at night.", Category.MANHOLE, Severity.LOW),
    ("Pavement flooded by a burst pipe", "Burst pipe has flooded the whole pavement and it is turning to mud.", Category.WATER_DRAINAGE, Severity.HIGH),
    ("Bus shelter roof leaking through", "Roof leaks right where people stand to keep dry.", Category.PUBLIC_PROPERTY, Severity.LOW),
    ("Deep pothole at the turning", "Deep enough to swallow a wheel and it is on the racing line into the turn.", Category.POTHOLE_ROAD, Severity.HIGH),
]

REPLIES = [
    "Still like this as of this morning.",
    "Same here. Nearly went over on it last week.",
    "Confirmed, walked past on the way to the station.",
    "It has been like this at least a fortnight.",
    "Photographed it again today, no change.",
    "Worse after last night's rain.",
    "My neighbour reported this too and heard nothing back.",
    "Please can someone look at this before the monsoon.",
]


def photo(seed: int, category: Category, width=1280, height=960) -> bytes:
    """A synthetic 'evidence' photo: distinct per issue, obviously not real."""
    rng = random.Random(seed)
    base = PALETTE[category]
    image = Image.new("RGB", (width, height), base)
    draw = ImageDraw.Draw(image, "RGBA")

    for i in range(height // 6):
        y = i * 6
        shade = 12 - int(24 * (y / height))
        draw.rectangle([0, y, width, y + 6], fill=(255, 255, 255, max(0, shade)))

    for _ in range(rng.randint(5, 9)):
        x, y = rng.randint(-80, width), rng.randint(int(height * 0.3), height)
        w, h = rng.randint(120, 460), rng.randint(60, 240)
        tint = rng.randint(0, 60)
        draw.ellipse([x, y, x + w, y + h], fill=(tint, tint, tint + 8, 150))

    for _ in range(rng.randint(2, 4)):
        x = rng.randint(0, width)
        draw.line([(x, 0), (x + rng.randint(-160, 160), height)],
                  fill=(255, 255, 255, 26), width=rng.randint(6, 22))

    horizon = int(height * 0.34)
    draw.rectangle([0, 0, width, horizon], fill=(168, 176, 188))
    for _ in range(rng.randint(4, 7)):
        x = rng.randint(0, width)
        w = rng.randint(60, 190)
        top = rng.randint(int(horizon * 0.2), horizon - 10)
        draw.rectangle([x, top, x + w, horizon], fill=(126, 133, 146))

    for corner in ((0, 0), (width, 0), (0, height), (width, height)):
        draw.ellipse(
            [corner[0] - 420, corner[1] - 420, corner[0] + 420, corner[1] + 420],
            fill=(0, 0, 0, 22),
        )

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def scatter(rng: random.Random, metres: float) -> tuple[float, float]:
    angle = rng.uniform(0, 2 * math.pi)
    distance = metres * math.sqrt(rng.uniform(0, 1))
    d_lat = (distance * math.cos(angle)) / 111_320
    d_lng = (distance * math.sin(angle)) / (
        111_320 * math.cos(math.radians(CENTRE[0]))
    )
    return CENTRE[0] + d_lat, CENTRE[1] + d_lng


async def wipe(session) -> None:
    for model in (ActivityEvent, Escalation, IssuePhoto, Support, Issue, User):
        await session.execute(delete(model))
    await session.commit()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="wipe first")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    store = get_store()

    async with db.sessionmaker()() as session:
        if args.reset:
            await wipe(session)
            print("wiped existing rows")

        residents = []
        for index in range(7):
            phone = f"+9198765{index:05d}"
            user = await session.scalar(select(User).where(User.phone == phone))
            if user is None:
                user = User(
                    id=new_id(), phone=phone,
                    display_name=f"Resident {phone[-4:]}",
                    created_at=datetime.now(timezone.utc)
                    - timedelta(days=rng.randint(40, 400)),
                )
                session.add(user)
            residents.append(user)
        await session.commit()
        print(f"{len(residents)} residents")

        created: list[Issue] = []
        for index, (title, body, category, severity) in enumerate(REPORTS):
            reporter = residents[index % len(residents)]
            # Most sit inside the 500 m feed radius; the rest give search and
            # the map something to reach for.
            radius = 420.0 if index < 30 else 3_800.0
            lat, lng = scatter(rng, radius)
            processed = [await process_jpeg(photo(args.seed * 1000 + index, category))]
            issue, _ = await service.create_issue(
                session,
                reporter=reporter,
                store=store,
                client_report_id=str(uuid.uuid4()),
                title=title,
                description=body,
                category=category,
                severity=severity,
                latitude=lat,
                longitude=lng,
                photos=processed,
            )
            issue.locality = LOCALITIES[index % len(LOCALITIES)]
            created.append(issue)
        await session.commit()
        print(f"{len(created)} issues with photos")

        backings = 0
        for index, issue in enumerate(created):
            supporters = [r for r in residents if r.id != issue.reporter_id]
            rng.shuffle(supporters)
            for supporter in supporters[: rng.randint(0, 4)]:
                with_photo = rng.random() < 0.25
                await service.add_support(
                    session,
                    issue=issue,
                    user=supporter,
                    store=store,
                    body=rng.choice(REPLIES) if rng.random() < 0.55 else None,
                    # Seeded supporters stand right at the report.
                    latitude=issue.latitude,
                    longitude=issue.longitude,
                    captured_at=utcnow(),
                    photos=(
                        [await process_jpeg(photo(90_000 + backings, issue.category))]
                        if with_photo
                        else []
                    ),
                )
                backings += 1
        print(f"{backings} supports")

        # Only reports that genuinely reached the photo bar are moved along.
        # Advancing an unconfirmed one would show a ticked "Confirmed" step
        # above "0 of 2 photo confirmations", which is a state the real
        # workflow cannot produce.
        eligible = [i for i in created if i.confirmed_at is not None]
        advanced = 0
        for issue, status in zip(
            eligible,
            [Status.SUBMITTED_TO_AUTHORITY, Status.IN_PROGRESS, Status.RESOLVED,
             Status.AUTHORITY_ACKNOWLEDGED, Status.RESOLVED, Status.IN_PROGRESS],
        ):
            issue.status = status
            advanced += 1
        await session.commit()
        print(f"{advanced} issues moved along the workflow")

        # Anything past "submitted" has been raised with somebody, so give it
        # the letter that would have gone out.
        raised = 0
        wards = [
            "H/East Ward, MCGM", "H/West Ward, MCGM", "G/North Ward, MCGM",
            "K/East Ward, MCGM", "F/North Ward, MCGM",
        ]
        for issue in created:
            if issue.status not in (
                Status.SUBMITTED_TO_AUTHORITY, Status.AUTHORITY_ACKNOWLEDGED,
                Status.IN_PROGRESS, Status.RESOLVED,
            ):
                continue
            authority = wards[raised % len(wards)]
            session.add(
                Escalation(
                    issue_id=issue.id,
                    authority=authority,
                    recipient=f"ward{raised}@example.gov.in",
                    reply_token=new_id(),
                    subject=f"{issue.title} - {issue.locality}",
                    body=(
                        f"Dear {authority},\n\n"
                        f"Residents of {issue.locality} have reported the following, "
                        f"and more than one of them has photographed it:\n\n"
                        f"{issue.description}\n\n"
                        f"Location: {issue.latitude:.5f}, {issue.longitude:.5f}\n"
                        f"Independently confirmed by {issue.photo_support_count} "
                        f"resident(s) with photographs.\n\n"
                        "We would be grateful for an indication of when this will be "
                        "attended to. Replies to this address reach the residents who "
                        "reported it.\n\nfihy, on behalf of the residents above."
                    ),
                    state=EscalationState.SENT,
                    reference=f"MCGM/2026/{4000 + raised}",
                    sent_at=datetime.now(timezone.utc)
                    - timedelta(days=rng.randint(2, 20)),
                )
            )
            raised += 1
        await session.commit()
        print(f"{raised} escalations")

        # create_issue stamps "now"; spread them so the feed shows real ages.
        now = datetime.now(timezone.utc)
        for index, issue in enumerate(created):
            await session.execute(
                update(Issue)
                .where(Issue.id == issue.id)
                .values(created_at=now - timedelta(hours=rng.randint(2, 22 * 24)))
            )
        await session.commit()
        print("backdated")

    await db.dispose()
    print("\nsign in with any phone number and the code from OTP_DEBUG_CODE")


if __name__ == "__main__":
    asyncio.run(main())
