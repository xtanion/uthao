"""Short headlines for reports, written from what the reporter said.

The app has one composer field, so the title it sends is the caption clipped
to fit. That reads badly on a map pin or a letter's subject line, so once the
report is filed a model rewrites it. Same shape as `summarize`: with no key the
titler is a no-op and the clipped caption stays.
"""
import logging
import re
from dataclasses import dataclass

from .config import get_settings
from .llm import complete

log = logging.getLogger(__name__)

MAX_LENGTH = 60

SYSTEM = f"""You write headlines for civic issue reports on a public app used \
in India. The headline appears on map pins, in the feed, and as the subject of \
a letter to the municipal corporation.

Write one headline of at most {MAX_LENGTH} characters that says what the \
problem is and, if the report says, where. Write it in plain English even when \
the report is in Hindi, Marathi or another language. Use sentence case.

Report only what the text says. Do not guess at causes, do not add urgency the \
reporter did not express, and do not invent a location.

Reply with the headline itself. No quotation marks, no trailing full stop, no \
preamble."""


@dataclass(frozen=True)
class TitleRequest:
    description: str
    category: str
    locality: str | None


def render(request: TitleRequest) -> str:
    lines = [f"Category: {request.category}"]
    if request.locality:
        lines.append(f"Locality: {request.locality}")
    lines.append(f"\nReporter wrote: {request.description}")
    return "\n".join(lines)


def clean(text: str) -> str | None:
    """The model's reply, or None when it is not usable as a title."""
    title = re.sub(r"\s+", " ", text).strip().strip("\"'“”‘’").rstrip(".").strip()
    if len(title) < 3:
        return None
    if len(title) > 140:
        return None
    return title


class Titler:
    async def title(self, request: TitleRequest) -> str | None:
        raise NotImplementedError


class NullTitler(Titler):
    """The default. No key, no rewrite, and the clipped caption stays."""

    async def title(self, request: TitleRequest) -> str | None:
        return None


class OpenAITitler(Titler):
    async def title(self, request: TitleRequest) -> str | None:
        text = await complete(SYSTEM, render(request), max_output_tokens=100, purpose="title")
        return clean(text) if text else None


_titler: Titler | None = None


def get_titler() -> Titler:
    global _titler
    if _titler is None:
        settings = get_settings()
        if settings.ai_titles_configured:
            _titler = OpenAITitler()
        else:
            log.info("no OPENAI_API_KEY or AI_TITLES off; titles are not rewritten")
            _titler = NullTitler()
    return _titler


def set_titler(titler: Titler | None) -> None:
    global _titler
    _titler = titler
