"""Deciding what a report is about, and whose desk it belongs on.

Two decisions, one model call, because they are the same reasoning: knowing a
photograph of standing water is a drainage problem is most of knowing it
belongs with the storm water drains engineer.

The safety property that matters here: the model never produces an email
address. It picks a key out of a list of desks this authority actually has, and
anything it returns that is not in that list is discarded. A model that
hallucinates a plausible `che.roads@mcgm.gov.in` cannot cause a letter to be
sent there, because the address is read from the row, not from the response.

Everything degrades to what came before it. No API key and the reporter's own
category stands and the static category-to-department mapping routes it, which
is what shipped before this file existed.
"""
import json
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .authority import AuthorityContact, contact_from, desks_for, authority_row_for
from .config import Settings, get_settings
from .enums import Category, ContactPointKind

log = logging.getLogger(__name__)

SYSTEM = """You route civic complaints in Indian cities to the right municipal \
desk.

You are given a resident's report and the desks this corporation actually has. \
Reply with a single JSON object and nothing else:

  {"category": "<category>", "desk": "<desk key or null>"}

`category` must be exactly one of the category keys listed. Use the reporter's \
own category unless the description plainly contradicts it - they were \
standing there and you were not. Change it when the text describes something \
else: a report filed as "other" that describes an overflowing bin is garbage.

`desk` must be exactly one of the desk keys listed, or null. Choose the desk \
that does the physical work. If no desk plainly owns it, use null - the \
complaint then goes to the corporation's own address, which is a worse but \
honest outcome. Do not guess to avoid a null.

No explanation. Only the object."""


@dataclass(frozen=True)
class Routing:
    """Where a report is going, and how that was decided."""

    category: Category
    contact: AuthorityContact
    # The desk's name, for the record kept on the escalation. None means the
    # letter is going to the body's own address.
    desk: str | None = None
    # The model disagreed with the reporter about what this is.
    reclassified: bool = False


class Router:
    async def route(
        self, title: str, description: str, reported: Category, desks: list[tuple[str, str]]
    ) -> tuple[Category | None, str | None]:
        raise NotImplementedError


class NullRouter(Router):
    """The default. Keeps the reporter's category and picks no desk, which
    leaves the static category-to-department mapping to do the routing."""

    async def route(
        self, title: str, description: str, reported: Category, desks: list[tuple[str, str]]
    ) -> tuple[Category | None, str | None]:
        return None, None


class ClaudeRouter(Router):
    def __init__(self, settings: Settings) -> None:
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.ai_summary_model

    async def route(
        self, title: str, description: str, reported: Category, desks: list[tuple[str, str]]
    ) -> tuple[Category | None, str | None]:
        catalogue = "\n".join(f"- {key}: {name}" for key, name in desks) or "- (none)"
        prompt = (
            f"Categories: {', '.join(c.value for c in Category)}\n"
            f"Desks:\n{catalogue}\n\n"
            f"Reporter's category: {reported.value}\n"
            f"Title: {title}\n"
            f"Description: {description[:2000]}"
        )
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=200,
            system=SYSTEM,
            # Low: this is a classification against a closed list, not writing.
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            return None, None
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        return _parse(text, {key for key, _ in desks})


def _parse(text: str, keys: set[str]) -> tuple[Category | None, str | None]:
    """Anything unrecognised becomes None, which falls back rather than fails.

    A desk key that is not on the list is the case this exists for: it is what
    a hallucinated address looks like by the time it reaches here, and it must
    not survive.
    """
    text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        log.warning("router did not answer with JSON: %r", text[:200])
        return None, None
    if not isinstance(payload, dict):
        return None, None

    category = None
    try:
        category = Category(payload.get("category"))
    except ValueError:
        log.warning("router chose an unknown category: %r", payload.get("category"))

    desk = payload.get("desk")
    if desk is not None and desk not in keys:
        log.warning("router chose a desk that does not exist: %r", desk)
        desk = None
    return category, desk


_router: Router | None = None


def get_router() -> Router:
    global _router
    if _router is None:
        settings = get_settings()
        if settings.ai_routing_configured:
            _router = ClaudeRouter(settings)
        else:
            log.info("routing is not configured; reported categories stand")
            _router = NullRouter()
    return _router


def set_router(router: Router | None) -> None:
    global _router
    _router = router


async def route_report(
    session: AsyncSession,
    *,
    title: str,
    description: str,
    category: Category,
    latitude: float,
    longitude: float,
) -> Routing:
    """The whole pipeline: which body, what is this, whose desk, what address.

    Ordered so that every step can fail into the one before it. No authority
    for these coordinates and it is the configured fallback; no model and it is
    the reporter's category through the static mapping; no desk and it is the
    body's own front door.
    """
    row = await authority_row_for(session, latitude, longitude)
    if row is None:
        from .authority import settings_contact

        return Routing(category=category, contact=settings_contact())

    desks = await desks_for(session, row.id, ContactPointKind.DEPARTMENT)
    catalogue = [(desk.key, desk.name) for desk in desks]

    chosen_category, chosen_key = category, None
    reclassified = False
    try:
        proposed, chosen_key = await get_router().route(
            title, description, category, catalogue
        )
    except Exception:
        # A complaint that is a day late beats one sent to the wrong desk, but
        # both beat a cron run that dies. Fall through to the static mapping.
        log.exception("routing failed; falling back to the reported category")
        chosen_key = None
        proposed = None

    if proposed is not None and proposed is not category:
        chosen_category, reclassified = proposed, True

    desk = next((d for d in desks if d.key == chosen_key), None)
    if desk is None:
        # Either the model picked nothing or it is switched off. The static
        # mapping is keyed on the category, which the model may have corrected.
        desk = next((d for d in desks if d.key == chosen_category.value), None)

    return Routing(
        category=chosen_category,
        contact=contact_from(row, desk),
        desk=desk.name if desk else None,
        reclassified=reclassified,
    )
