from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .. import stats as impact
from ..cache import public_cache
from ..deps import SessionDep
from ..schemas import StatsAreaOption, StatsContributorsOut, StatsOut
from ..storage import get_store

router = APIRouter(prefix="/stats", tags=["stats"])

Latitude = Annotated[float | None, Query(ge=-90, le=90)]
Longitude = Annotated[float | None, Query(ge=-180, le=180)]


async def _area(
    session: SessionDep, area: str | None, lat: float | None, lng: float | None
) -> impact.Area:
    try:
        return await impact.area_for(session, slug=area, latitude=lat, longitude=lng)
    except impact.UnknownArea as exc:
        raise HTTPException(status_code=404, detail="That area is not available.") from exc


def _slug(area: impact.Area) -> str | None:
    return area.authority.slug if area.authority else None


@router.get("", response_model=StatsOut)
async def read_stats(
    session: SessionDep,
    area: str | None = None,
    lat: Latitude = None,
    lng: Longitude = None,
) -> StatsOut:
    if area:
        return await public_cache().get_or_load(
            ("stats", area),
            lambda: _stats_for(session, area),
        )
    resolved = await _area(session, None, lat, lng)
    return await public_cache().get_or_load(
        ("stats", _slug(resolved)),
        lambda: impact.stats(session, resolved),
    )


async def _stats_for(session: SessionDep, slug: str) -> StatsOut:
    return await impact.stats(session, await _area(session, slug, None, None))


@router.get("/areas", response_model=list[StatsAreaOption])
async def read_areas(session: SessionDep) -> list[StatsAreaOption]:
    async def load() -> list[StatsAreaOption]:
        return [
            StatsAreaOption(slug=row.slug, city=row.city, reports=reports)
            for row, reports in await impact.areas(session)
        ]

    return await public_cache().get_or_load(("areas",), load)


@router.get("/contributors", response_model=StatsContributorsOut)
async def read_top_contributors(
    session: SessionDep,
    period: impact.Period = impact.Period.MONTH,
    area: str | None = None,
    lat: Latitude = None,
    lng: Longitude = None,
) -> StatsContributorsOut:
    resolved = await _area(session, area, lat, lng)
    return await public_cache().get_or_load(
        ("contributors", period.value, _slug(resolved)),
        lambda: impact.top_contributors(
            session, store=get_store(), period=period, area=resolved
        ),
    )
