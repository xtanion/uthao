import uuid
from datetime import timedelta

from tests.conftest import auth, create_issue, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"


def report_id() -> str:
    return str(uuid.uuid4())


async def file(client, token, title: str, **over) -> str:
    response = await create_issue(client, token, report_id=report_id(), title=title, **over)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def set_status(issue_id: str, status: str, resolved_days_ago: float | None = None) -> None:
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.enums import ActivityType
    from app.models import ActivityEvent, Issue, utcnow

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.status = status
        if resolved_days_ago is not None:
            session.add(
                ActivityEvent(
                    user_id=issue.reporter_id,
                    issue_id=issue.id,
                    type=ActivityType.STATUS_CHANGED,
                    to_status=status,
                    created_at=utcnow() - timedelta(days=resolved_days_ago),
                )
            )
        await session.commit()


async def backdate(issue_id: str, days: float) -> None:
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.models import Issue, utcnow

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.created_at = utcnow() - timedelta(days=days)
        await session.commit()


async def test_an_empty_city_is_all_zeroes(client):
    response = await client.get("/stats")

    body = response.json()
    assert response.status_code == 200
    assert body["totals"] == {
        "reported": 0,
        "confirmed": 0,
        "raised": 0,
        "resolved": 0,
        "photos": 0,
        "contributors": 0,
        "emails_sent": 0,
    }
    assert body["area"] is None
    assert len(body["weeks"]) == 12
    assert all(w["reported"] == 0 and w["resolved"] == 0 for w in body["weeks"])
    assert body["categories"] == []
    assert body["points"] == []


async def test_stages_count_everything_that_reached_them(client, sender):
    token = await sign_in(client, sender, REPORTER)
    ids = [await file(client, token, f"Report number {n} on this road") for n in range(6)]
    await set_status(ids[1], "community_verified")
    await set_status(ids[2], "in_progress")
    await set_status(ids[3], "resolved")
    await set_status(ids[4], "duplicate")
    await set_status(ids[5], "removed")

    totals = (await client.get("/stats")).json()["totals"]

    assert totals["reported"] == 4
    assert totals["confirmed"] == 3
    assert totals["raised"] == 2
    assert totals["resolved"] == 1
    assert totals["photos"] == 4
    assert totals["contributors"] == 1


async def test_contributors_include_people_who_only_backed_a_report(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    issue = await file(client, reporter, "Cover missing on the footpath side")
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(f"/issues/{issue}/confirmations", headers=auth(neighbour), json={})

    totals = (await client.get("/stats")).json()["totals"]

    assert totals["contributors"] == 2


async def test_weeks_count_a_fix_when_it_was_fixed(client, sender):
    token = await sign_in(client, sender, REPORTER)
    quick = await file(client, token, "Fixed within the week here")
    slow = await file(client, token, "Took most of a month to fix")
    await backdate(quick, 10)
    await backdate(slow, 30)
    await set_status(quick, "resolved", resolved_days_ago=6)
    await set_status(slow, "resolved", resolved_days_ago=2)

    body = (await client.get("/stats")).json()

    assert sum(w["resolved"] for w in body["weeks"]) == 2
    assert sum(w["reported"] for w in body["weeks"]) == 2


async def test_weeks_ignore_reports_older_than_the_window(client, sender):
    token = await sign_in(client, sender, REPORTER)
    old = await file(client, token, "Filed a long time ago now")
    await file(client, token, "Filed just this morning here")
    await backdate(old, 200)

    weeks = (await client.get("/stats")).json()["weeks"]

    assert sum(w["reported"] for w in weeks) == 1
    assert weeks[-1]["reported"] == 1
    assert weeks[0]["week_start"] < weeks[-1]["week_start"]


async def test_categories_split_what_was_fixed(client, sender):
    token = await sign_in(client, sender, REPORTER)
    first = await file(client, token, "Pothole on the main road", category="pothole_road")
    await file(client, token, "Another pothole by the signal", category="pothole_road")
    await file(client, token, "Garbage left by the market", category="garbage")
    await set_status(first, "resolved")

    categories = (await client.get("/stats")).json()["categories"]

    assert categories == [
        {"category": "pothole_road", "total": 2, "resolved": 1},
        {"category": "garbage", "total": 1, "resolved": 0},
    ]


async def test_points_mark_the_fixed_ones(client, sender):
    token = await sign_in(client, sender, REPORTER)
    fixed = await file(client, token, "Fixed near the station", latitude=19.07, longitude=72.84)
    await file(client, token, "Still open by the bridge", latitude=19.05, longitude=72.83)
    hidden = await file(client, token, "Taken down for spam here")
    duplicate = await file(client, token, "Same pothole reported twice")
    await set_status(fixed, "resolved")
    await set_status(hidden, "removed")
    await set_status(duplicate, "duplicate")

    points = (await client.get("/stats")).json()["points"]

    assert sorted((p["latitude"], p["resolved"]) for p in points) == [
        (19.05, False),
        (19.07, True),
    ]


async def board(client, period: str | None = None) -> list[dict]:
    response = await client.get("/stats/contributors", params={"period": period} if period else None)
    assert response.status_code == 200, response.text
    return response.json()["items"]


async def backdate_support(issue_id: str, when) -> None:
    from sqlalchemy import update

    from app.db import sessionmaker
    from app.models import Support

    async with sessionmaker()() as session:
        await session.execute(update(Support).where(Support.issue_id == issue_id).values(created_at=when))
        await session.commit()


async def set_created(issue_id: str, when) -> None:
    from sqlalchemy import select

    from app.db import sessionmaker
    from app.models import Issue

    async with sessionmaker()() as session:
        issue = await session.scalar(select(Issue).where(Issue.id == issue_id))
        issue.created_at = when
        await session.commit()


def test_periods_start_at_midnight_in_india():
    from datetime import date, datetime, timezone

    from app.stats import Period, period_start

    today = date(2026, 10, 14)
    assert period_start(Period.DAY, today) == datetime(2026, 10, 13, 18, 30, tzinfo=timezone.utc)
    assert period_start(Period.MONTH, today) == datetime(2026, 9, 30, 18, 30, tzinfo=timezone.utc)
    assert period_start(Period.YEAR, today) == datetime(2025, 12, 31, 18, 30, tzinfo=timezone.utc)


async def test_the_board_defaults_to_this_month(client):
    response = await client.get("/stats/contributors")

    body = response.json()
    assert body["period"] == "month"
    assert body["since"].endswith("Z")
    assert body["items"] == []


async def test_an_unknown_period_is_a_422(client):
    response = await client.get("/stats/contributors", params={"period": "week"})

    assert response.status_code == 422


async def test_top_contributors_rank_on_profile_reputation(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await sign_in(client, sender, THIRD)

    mine = await file(client, reporter, "Cover missing on the footpath side")
    await file(client, reporter, "Streetlight out past the bridge")
    await set_status(mine, "resolved", resolved_days_ago=0)
    await file(client, neighbour, "Garbage left by the market")

    rows = await board(client, "year")
    me = (await client.get("/me", headers=auth(reporter))).json()["id"]
    profile = (await client.get(f"/users/{me}")).json()

    assert [row["reputation"] for row in rows] == [9, 2]
    assert rows[0]["id"] == me
    assert rows[0]["reputation"] == profile["reputation"]
    assert rows[0]["reports"] == 2
    assert rows[0]["resolutions"] == 1


async def test_reports_filed_before_the_period_do_not_count(client, sender):
    from datetime import timedelta

    from app.stats import Period, period_start

    reporter = await sign_in(client, sender, REPORTER)
    old = await file(client, reporter, "Filed before this month began")
    await set_created(old, period_start(Period.MONTH) - timedelta(hours=1))
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await file(client, neighbour, "Filed just now by a neighbour")

    rows = await board(client, "month")

    assert len(rows) == 1
    assert rows[0]["reports"] == 1
    assert rows[0]["id"] != (await client.get("/me", headers=auth(reporter))).json()["id"]


async def test_a_fix_counts_in_the_period_it_was_fixed(client, sender):
    from datetime import timedelta

    from app.stats import Period, period_start

    reporter = await sign_in(client, sender, REPORTER)
    issue = await file(client, reporter, "Fixed a long while after filing")
    await set_created(issue, period_start(Period.YEAR) - timedelta(days=30))
    await set_status(issue, "resolved", resolved_days_ago=0)

    rows = await board(client, "day")

    assert rows[0]["reports"] == 0
    assert rows[0]["resolutions"] == 1
    assert rows[0]["reputation"] == 5


async def test_backing_counts_when_it_was_given(client, sender):
    from datetime import timedelta

    from app.stats import Period, period_start

    reporter = await sign_in(client, sender, REPORTER)
    issue = await file(client, reporter, "Cover missing on the footpath side")
    await set_created(issue, period_start(Period.DAY) - timedelta(days=400))
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(f"/issues/{issue}/confirmations", headers=auth(neighbour), json={})

    assert [row["reputation"] for row in await board(client, "day")] == [1]

    await backdate_support(issue, period_start(Period.DAY) - timedelta(hours=1))

    assert await board(client, "day") == []


async def test_deleted_accounts_leave_the_board(client, sender):
    reporter = await sign_in(client, sender, REPORTER)
    await file(client, reporter, "Cover missing on the footpath side")
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await file(client, neighbour, "Garbage left by the market")

    deleted = await client.delete("/me", headers=auth(reporter))
    assert deleted.status_code in (200, 204)

    assert len(await board(client)) == 1


MUMBAI = (18.89, 19.27, 72.77, 72.99)
INSIDE = {"lat": 19.06, "lng": 72.84}


async def add_authority(city: str, box: tuple[float, float, float, float]) -> None:
    from app.db import sessionmaker
    from app.models import Authority

    min_lat, max_lat, min_lng, max_lng = box
    async with sessionmaker()() as session:
        session.add(
            Authority(
                slug=city.lower(),
                name=f"{city} Municipal Corporation",
                city=city,
                state="Maharashtra",
                min_latitude=min_lat,
                max_latitude=max_lat,
                min_longitude=min_lng,
                max_longitude=max_lng,
            )
        )
        await session.commit()


async def test_the_page_is_scoped_to_the_viewers_city(client, sender):
    await add_authority("Mumbai", MUMBAI)
    token = await sign_in(client, sender, REPORTER)
    await file(client, token, "Pothole near the station", latitude=19.06, longitude=72.84)
    pune = await file(client, token, "Pothole on the Pune road", latitude=18.52, longitude=73.85)
    await set_status(pune, "resolved")

    scoped = (await client.get("/stats", params=INSIDE)).json()
    everywhere = (await client.get("/stats")).json()

    assert scoped["area"]["city"] == "Mumbai"
    assert scoped["area"]["slug"] == "mumbai"
    assert scoped["totals"]["reported"] == 1
    assert scoped["totals"]["resolved"] == 0
    assert [p["resolved"] for p in scoped["points"]] == [False]
    assert everywhere["area"]["city"] == "Mumbai"


PUNE = (18.40, 18.65, 73.70, 74.00)


async def test_somewhere_no_authority_covers_falls_back_to_the_busiest_city(client, sender):
    await add_authority("Mumbai", MUMBAI)
    await add_authority("Pune", PUNE)
    token = await sign_in(client, sender, REPORTER)
    await file(client, token, "Pothole near the station", latitude=19.06, longitude=72.84)
    await file(client, token, "Garbage by the market", latitude=19.07, longitude=72.85)
    await file(client, token, "Pothole on the Pune road", latitude=18.52, longitude=73.85)

    body = (await client.get("/stats", params={"lat": 26.9, "lng": 75.8})).json()

    assert body["area"]["city"] == "Mumbai"
    assert body["totals"]["reported"] == 2


async def test_a_chosen_area_wins_over_location(client, sender):
    await add_authority("Mumbai", MUMBAI)
    await add_authority("Pune", PUNE)
    token = await sign_in(client, sender, REPORTER)
    await file(client, token, "Pothole on the Pune road", latitude=18.52, longitude=73.85)

    body = (await client.get("/stats", params={**INSIDE, "area": "pune"})).json()

    assert body["area"]["city"] == "Pune"
    assert body["totals"]["reported"] == 1


async def test_an_unknown_area_is_a_404(client):
    response = await client.get("/stats", params={"area": "atlantis"})

    assert response.status_code == 404


async def test_areas_list_cities_with_reports_busiest_first(client, sender):
    await add_authority("Mumbai", MUMBAI)
    await add_authority("Pune", PUNE)
    await add_authority("Chennai", (12.8, 13.3, 80.0, 80.4))
    token = await sign_in(client, sender, REPORTER)
    await file(client, token, "Pothole near the station", latitude=19.06, longitude=72.84)
    await file(client, token, "Garbage by the market", latitude=19.07, longitude=72.85)
    await file(client, token, "Pothole on the Pune road", latitude=18.52, longitude=73.85)

    areas = (await client.get("/stats/areas")).json()

    assert areas == [
        {"slug": "mumbai", "city": "Mumbai", "reports": 2},
        {"slug": "pune", "city": "Pune", "reports": 1},
    ]


async def test_the_board_is_scoped_to_the_city_too(client, sender):
    await add_authority("Mumbai", MUMBAI)
    reporter = await sign_in(client, sender, REPORTER)
    await file(client, reporter, "Pothole near the station", latitude=19.06, longitude=72.84)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await file(client, neighbour, "Pothole on the Pune road", latitude=18.52, longitude=73.85)

    response = await client.get("/stats/contributors", params={**INSIDE, "period": "year"})

    body = response.json()
    assert body["area"]["city"] == "Mumbai"
    assert len(body["items"]) == 1
    assert body["items"][0]["reports"] == 1


async def test_emails_sent_counts_every_outbound_letter(client, sender):
    from app.db import sessionmaker
    from app.enums import EscalationState, MessageDirection
    from app.models import Escalation, EscalationMessage

    token = await sign_in(client, sender, REPORTER)
    issue = await file(client, token, "Cover missing on the footpath side")
    async with sessionmaker()() as session:
        escalation = Escalation(
            issue_id=issue,
            authority="H/East Ward, MCGM",
            subject="Manhole cover missing",
            body="A missing cover on the footpath side.",
            state=EscalationState.SENT,
        )
        session.add(escalation)
        await session.flush()
        for direction in (MessageDirection.OUTBOUND, MessageDirection.OUTBOUND, MessageDirection.INBOUND):
            session.add(
                EscalationMessage(
                    escalation_id=escalation.id,
                    direction=direction,
                    sender="ward@example.gov.in",
                    subject="Manhole cover missing",
                    body="Text of the message.",
                )
            )
        await session.commit()

    totals = (await client.get("/stats")).json()["totals"]

    assert totals["emails_sent"] == 2


async def test_coordinates_out_of_range_are_a_422(client):
    response = await client.get("/stats", params={"lat": 120, "lng": 72.8})

    assert response.status_code == 422
