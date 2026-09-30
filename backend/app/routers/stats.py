from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .. import stats as impact
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


@router.get("", response_model=StatsOut)
async def read_stats(
    session: SessionDep,
    area: str | None = None,
    lat: Latitude = None,
    lng: Longitude = None,
) -> StatsOut:
    return await impact.stats(session, await _area(session, area, lat, lng))


@router.get("/areas", response_model=list[StatsAreaOption])
async def read_areas(session: SessionDep) -> list[StatsAreaOption]:
    return [
        StatsAreaOption(slug=row.slug, city=row.city, reports=reports)
        for row, reports in await impact.areas(session)
    ]


@router.get("/contributors", response_model=StatsContributorsOut)
async def read_top_contributors(
    session: SessionDep,
    period: impact.Period = impact.Period.MONTH,
    area: str | None = None,
    lat: Latitude = None,
    lng: Longitude = None,
) -> StatsContributorsOut:
    return await impact.top_contributors(
        session,
        store=get_store(),
        period=period,
        area=await _area(session, area, lat, lng),
    )
