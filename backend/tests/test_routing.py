"""Classifying a report and choosing the desk its letter goes to."""
import pytest

from app import routing as routing_module
from app.authority import AuthorityContact
from app.db import sessionmaker
from app.enums import Category, ContactChannel, ContactPointKind
from app.models import Authority, AuthorityContactPoint
from app.routing import NullRouter, Router, Routing, route_report, _parse
from tests.test_authorities import MUMBAI, OPEN_WATER, an_authority, save

DESKS = [
    ("pothole_road", "Chief Engineer (Roads and Traffic)", "che.rt@mcgm.gov.in"),
    ("garbage", "Chief Engineer (Solid Waste Management)", "che.swm@mcgm.gov.in"),
    ("water_drainage", "Chief Engineer (Storm Water Drains)", "che.swd@mcgm.gov.in"),
]


class Fixed(Router):
    """Answers with whatever the test told it to, and records the catalogue it
    was offered so a test can assert the model never sees an address."""

    def __init__(self, category=None, desk=None) -> None:
        self.category, self.desk = category, desk
        self.offered: list[tuple[str, str]] = []

    async def route(self, title, description, reported, desks):
        self.offered = desks
        return self.category, self.desk


class Explodes(Router):
    async def route(self, title, description, reported, desks):
        raise RuntimeError("the model is having a day")


@pytest.fixture(autouse=True)
def _reset():
    yield
    routing_module.set_router(None)


async def a_bmc() -> Authority:
    row = an_authority(
        "bmc", (18.89, 19.28, 72.77, 72.99),
        name="Brihanmumbai Municipal Corporation",
        channel=ContactChannel.PORTAL,
    )
    await save(row)
    async with sessionmaker()() as session:
        for key, name, email in DESKS:
            session.add(
                AuthorityContactPoint(
                    authority_id=row.id, kind=ContactPointKind.DEPARTMENT,
                    key=key, name=name, email=email, active=True,
                )
            )
        await session.commit()
    return row


async def run(title="A pothole", description="", category=Category.OTHER, point=MUMBAI) -> Routing:
    async with sessionmaker()() as session:
        return await route_report(
            session,
            title=title,
            description=description,
            category=category,
            latitude=point[0],
            longitude=point[1],
        )


# --- the model never produces an address -----------------------------------


def test_a_desk_that_does_not_exist_is_discarded():
    """This is what a hallucinated address looks like by the time it gets
    here, and it must not survive."""
    category, desk = _parse(
        '{"category": "garbage", "desk": "che.invented@mcgm.gov.in"}',
        {"pothole_road", "garbage"},
    )

    assert category is Category.GARBAGE
    assert desk is None


def test_an_unknown_category_is_discarded():
    category, desk = _parse('{"category": "sinkhole", "desk": "garbage"}', {"garbage"})

    assert category is None
    assert desk == "garbage"


def test_prose_instead_of_json_is_discarded():
    assert _parse("I think this is a pothole!", {"garbage"}) == (None, None)


def test_a_fenced_object_is_still_read():
    category, _ = _parse('```json\n{"category": "garbage", "desk": null}\n```', set())

    assert category is Category.GARBAGE


async def test_the_model_is_only_ever_offered_keys_and_names(client):
    """It picks from a catalogue. It is not shown an address, so it cannot
    return one."""
    await a_bmc()
    router = Fixed(category=Category.GARBAGE, desk="garbage")
    routing_module.set_router(router)

    await run(category=Category.OTHER)

    assert router.offered == sorted((key, name) for key, name, _ in DESKS)
    flat = str(router.offered)
    assert "@" not in flat


# --- the pipeline ----------------------------------------------------------


async def test_a_miscategorised_report_reaches_the_right_desk(client):
    """Filed as "other", described as an overflowing bin."""
    await a_bmc()
    routing_module.set_router(Fixed(category=Category.GARBAGE, desk="garbage"))

    result = await run(
        title="The bins on the corner have not been emptied",
        description="Rubbish is across the footpath now.",
        category=Category.OTHER,
    )

    assert result.category is Category.GARBAGE
    assert result.contact.email == "che.swm@mcgm.gov.in"
    assert result.desk == "Chief Engineer (Solid Waste Management)"
    assert result.reclassified is True


async def test_agreeing_with_the_reporter_is_not_a_reclassification(client):
    await a_bmc()
    routing_module.set_router(Fixed(category=Category.POTHOLE_ROAD, desk="pothole_road"))

    result = await run(category=Category.POTHOLE_ROAD)

    assert result.reclassified is False
    assert result.contact.email == "che.rt@mcgm.gov.in"


async def test_a_corrected_category_routes_even_with_no_desk_chosen(client):
    """The model reclassified but would not pick a desk. The static mapping
    still gets it to the right place on the corrected category."""
    await a_bmc()
    routing_module.set_router(Fixed(category=Category.WATER_DRAINAGE, desk=None))

    result = await run(category=Category.OTHER)

    assert result.contact.email == "che.swd@mcgm.gov.in"


async def test_no_desk_and_no_mapping_is_the_front_door(client):
    await a_bmc()
    routing_module.set_router(Fixed(category=Category.PUBLIC_PROPERTY, desk=None))

    result = await run(category=Category.OTHER)

    assert result.contact.email is None
    assert result.contact.channel is ContactChannel.PORTAL
    assert result.desk is None


async def test_with_routing_off_the_reported_category_stands(client):
    await a_bmc()
    routing_module.set_router(NullRouter())

    result = await run(category=Category.GARBAGE)

    assert result.category is Category.GARBAGE
    assert result.contact.email == "che.swm@mcgm.gov.in"
    assert result.reclassified is False


async def test_a_model_that_fails_does_not_stop_the_letter(client):
    """A complaint routed by the reporter's own category beats a cron run that
    dies halfway through the batch."""
    await a_bmc()
    routing_module.set_router(Explodes())

    result = await run(category=Category.GARBAGE)

    assert result.category is Category.GARBAGE
    assert result.contact.email == "che.swm@mcgm.gov.in"


async def test_nowhere_covered_still_falls_back_to_the_setting(client):
    routing_module.set_router(Fixed(category=Category.GARBAGE, desk="garbage"))

    result = await run(category=Category.OTHER, point=OPEN_WATER)

    assert result.desk is None
    assert result.category is Category.OTHER
