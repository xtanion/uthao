"""The gate between filing a report and other people seeing it.

A new report starts IN_REVIEW, visible only to its reporter. Two things happen
after the response is sent:

0. OpenAI's free moderation endpoint screens the caption and photos for
   nudity, gore, self-harm and abuse. Flagged reports are rejected here and
   never cost a paid call.
1. A small vision model looks at the photos and says whether they show the
   problem the report describes. Not a photo of a problem (a selfie, a
   screenshot, a meme, something unrelated) and the report is REJECTED, with
   a one-line reason the reporter can read.
2. The title is rewritten into a headline, whatever the reporter typed.

Only when both have run does the report become REPORTED and reach the feed.

Any failure (timeout, outage, a restart mid-way) leaves it IN_REVIEW, and
`python -m app.jobs review` picks it up again. Nothing is approved by
accident: the model has to say yes.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select

from .config import get_settings
from .enums import ActivityType, Status
from .llm import classify, moderate
from .models import ActivityEvent, Issue, utcnow
from .storage import ObjectStore, get_store
from .titles import TitleRequest, get_titler

log = logging.getLogger(__name__)

SYSTEM = """You check photos attached to civic issue reports on a public app \
in India, before the report is shown to other residents.

Approve when the photos plausibly show the reported problem: a damaged road, \
garbage, a broken streetlight, a blocked drain, an open manhole, a fallen tree, \
damaged public property and the like. Photos can be dark, blurry, taken at an \
angle or from a distance; that is normal for people standing on a street.

Reject when none of the photos shows a public civic problem: a selfie or \
portrait, a screenshot, a meme, text or a document, an indoor private space, \
a blank or fully black frame, or a scene with nothing wrong in it. Also reject \
nudity, gore, or anything that identifies a private person as the subject.

If the photos show a real civic problem but a different one from the stated \
category, approve: the category can be corrected later.

The reason is shown to the reporter. Keep it to one short, plain, polite \
sentence, and leave it empty when you approve."""

SCHEMA = {
    "type": "object",
    "properties": {
        "approve": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["approve", "reason"],
    "additionalProperties": False,
}

# Thumbnails are plenty to tell a pothole from a selfie.
MAX_IMAGES = 3

# What the reporter is told when moderation flags their report. Matched on the
# category's prefix ("sexual/minors" is "sexual"). Kept general on purpose:
# the exact category is logged, not shown.
MODERATION_REASONS = {
    "sexual": "The photos can't include nudity or sexual content.",
    "violence": "The photos can't include graphic or violent content.",
    "self-harm": "This report can't be published. If you're going through something, please reach out to someone you trust.",
    "hate": "The description breaks our community guidelines.",
    "harassment": "The description breaks our community guidelines.",
    "illicit": "This report can't be published as it stands.",
}
FALLBACK_MODERATION_REASON = "This report can't be published as it stands."


def _moderation_reason(flagged: list[str]) -> str:
    for name in flagged:
        reason = MODERATION_REASONS.get(name.split("/")[0])
        if reason:
            return reason
    return FALLBACK_MODERATION_REASON


@dataclass(frozen=True)
class Verdict:
    approve: bool
    reason: str | None


async def check_photos(issue: Issue, store: ObjectStore) -> Verdict | None:
    """The model's verdict, or None when it could not give one."""
    images = []
    for photo in sorted(issue.photos, key=lambda p: p.position)[:MAX_IMAGES]:
        data = await store.get(photo.thumbnail_key)
        if data:
            images.append(data)
    if not images:
        # A report is always filed with photos. None readable means storage
        # trouble, which is worth retrying rather than rejecting.
        return None

    settings = get_settings()
    caption = issue.description or issue.title

    # Free moderation pass first. Flagged means rejected without paying for
    # the photo check; a failed call means retry later, never approve.
    if settings.ai_moderation:
        flagged = await moderate(caption, images, model=settings.moderation_model)
        if flagged is None:
            return None
        if flagged:
            log.info("issue %s flagged by moderation: %s", issue.id, ", ".join(flagged))
            return Verdict(approve=False, reason=_moderation_reason(flagged))

    prompt = f"Category: {issue.category.value}\nReporter wrote: {caption}"
    result = await classify(
        SYSTEM,
        prompt,
        images,
        schema=SCHEMA,
        model=settings.ai_review_model or settings.ai_model,
        purpose="photo_review",
    )
    if result is None:
        return None
    reason = (result.get("reason") or "").strip()[:300] or None
    return Verdict(approve=bool(result.get("approve")), reason=reason)


def _move(issue: Issue, to: Status) -> ActivityEvent:
    """Changes the status and returns the event that tells the reporter."""
    event = ActivityEvent(
        user_id=issue.reporter_id,
        issue_id=issue.id,
        type=ActivityType.STATUS_CHANGED,
        from_status=issue.status,
        to_status=to,
    )
    issue.status = to
    return event


async def review_report(issue_id: str) -> None:
    """Check one report and publish or reject it. Safe to run twice: it only
    acts on a report that is still IN_REVIEW."""
    from .db import sessionmaker

    store = get_store()
    try:
        async with sessionmaker()() as session:
            issue = await session.get(Issue, issue_id)
            if issue is None or issue.status != Status.IN_REVIEW:
                return

            verdict = await check_photos(issue, store)
            if verdict is None:
                return  # stays in review; the job retries

            if not verdict.approve:
                issue.review_note = verdict.reason or "The photos don't seem to show the problem described."
                session.add(_move(issue, Status.REJECTED))
                await session.commit()
                return

            # Every title is rewritten, not only clipped captions. An
            # unusable reply keeps the reporter's own; an exception leaves the
            # report in review for another go.
            title = await get_titler().title(
                TitleRequest(
                    description=issue.description or issue.title,
                    category=issue.category.value,
                    locality=issue.locality,
                )
            )
            # The model calls took a while; make sure nothing else (a removal,
            # an overlapping retry) got to it first.
            await session.refresh(issue)
            if issue.status != Status.IN_REVIEW:
                return
            if title:
                issue.title = title[:140]
            issue.review_note = None
            session.add(_move(issue, Status.REPORTED))
            await session.commit()
    except Exception:
        log.exception("could not review issue %s; it stays in review", issue_id)


async def retry_stuck(limit: int | None = None) -> int:
    """Reviews reports that have sat in review past the retry window. Returns
    how many were attempted."""
    from .db import sessionmaker

    settings = get_settings()
    if not settings.ai_review_configured:
        return 0
    cutoff = utcnow() - timedelta(minutes=settings.review_retry_after_minutes)
    async with sessionmaker()() as session:
        query = (
            select(Issue.id)
            .where(Issue.status == Status.IN_REVIEW, Issue.created_at < cutoff)
            .order_by(Issue.created_at.asc())
        )
        if limit:
            query = query.limit(limit)
        ids = list((await session.scalars(query)).all())
    for issue_id in ids:
        await review_report(issue_id)
    return len(ids)
