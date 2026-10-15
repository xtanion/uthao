"""The moderation and vision calls are swapped for stubs, so nothing here calls
a model."""
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from PIL import Image

from app import review
from tests.conftest import auth, create_issue, jpeg_bytes, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
STRANGER = "+919876500002"
HEADLINE = "Missing manhole cover on the footpath"
SUMMARY = "A manhole cover is missing on the footpath."

# create_issue files at this point.
SPOT = (19.0612, 72.8371)


def report_id() -> str:
    return str(uuid.uuid4())


def other_jpeg() -> bytes:
    """A photo nothing like the report's own, so the copy check lets it by."""
    image = Image.new("RGB", (400, 300))
    for y in range(300):
        for x in range(400):
            image.putpixel((x, y), (255 - (y * 255) // 300, (x * 255) // 400, 30))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class Model:
    """Stands in for both calls. Each verdict is used in order."""

    def __init__(self) -> None:
        self.flagged: list[str] | None = []
        self.verdicts: list[dict | None] = []
        self.moderated = 0
        self.classified: list[str] = []

    async def moderate(self, text, images, *, model):
        self.moderated += 1
        return self.flagged

    async def classify(self, system, prompt, images, *, schema, model, purpose):
        self.classified.append(purpose)
        return self.verdicts.pop(0) if self.verdicts else {"approve": True, "reason": ""}


@pytest.fixture
def model(monkeypatch):
    from app import summarize, titles
    from app.config import get_settings

    class Titler(titles.Titler):
        async def title(self, request):
            return HEADLINE

    class Summarizer(summarize.Summarizer):
        async def summarize(self, request):
            return SUMMARY

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.setenv("AI_REVIEW", "true")
    get_settings.cache_clear()
    stub = Model()
    monkeypatch.setattr(review, "moderate", stub.moderate)
    monkeypatch.setattr(review, "classify", stub.classify)
    titles.set_titler(Titler())
    summarize.set_summarizer(Summarizer())
    yield stub
    titles.set_titler(None)
    summarize.set_summarizer(None)
    get_settings.cache_clear()


@pytest.fixture
def checks_on(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("SUPPORT_LOCATION_REQUIRED", "true")
    monkeypatch.setenv("DUPLICATE_PHOTO_MAX_BITS", "12")
    monkeypatch.setenv("CONTRIBUTIONS_AFTER_DAYS", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def file_held_report(client, sender, model) -> tuple[str, str]:
    """A report held in review: the verdict is not yet given."""
    model.flagged = None
    token = await sign_in(client, sender, REPORTER)
    created = await create_issue(client, token, report_id=report_id())
    assert created.status_code == 201, created.text
    model.flagged = []
    return token, created.json()["id"]


async def file_public_report(client, sender, model) -> tuple[str, str]:
    token = await sign_in(client, sender, REPORTER)
    created = await create_issue(client, token, report_id=report_id())
    assert created.status_code == 201, created.text
    return token, created.json()["id"]


async def support(client, token, issue_id, *, photo: bytes | None = None, body="Still there", **fields):
    files = [("photos", ("photo_0.jpg", photo, "image/jpeg"))] if photo else None
    return await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(token),
        data={"body": body, **{k: str(v) for k, v in fields.items()}},
        files=files,
    )


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def test_a_report_waits_in_review_seen_only_by_its_reporter(client, sender, model):
    token, issue_id = await file_held_report(client, sender, model)

    own = await client.get(f"/issues/{issue_id}", headers=auth(token))
    assert own.status_code == 200
    assert own.json()["status"] == "in_review"
    stranger = await sign_in(client, sender, STRANGER)
    assert (await client.get(f"/issues/{issue_id}", headers=auth(stranger))).status_code == 404
    assert (await client.get(f"/issues/{issue_id}")).status_code == 404


async def test_an_approved_report_is_published_titled_and_summarized(client, sender, model):
    _, issue_id = await file_public_report(client, sender, model)

    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["status"] == "reported"
    assert detail["title"] == HEADLINE
    assert detail["ai_summary"] == SUMMARY
    assert model.classified == ["photo_review"]


async def test_a_rejected_report_keeps_a_reason_for_its_reporter(client, sender, model):
    model.verdicts = [{"approve": False, "reason": "That looks like a selfie."}]
    token = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, token, report_id=report_id())).json()["id"]

    own = (await client.get(f"/issues/{issue_id}", headers=auth(token))).json()
    assert own["status"] == "rejected"
    assert own["review_note"] == "That looks like a selfie."
    assert own["ai_summary"] is None
    assert (await client.get(f"/issues/{issue_id}")).status_code == 404


async def test_moderation_rejects_without_the_paid_check(client, sender, model):
    model.flagged = ["violence/graphic"]
    token = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, token, report_id=report_id())).json()["id"]

    own = (await client.get(f"/issues/{issue_id}", headers=auth(token))).json()
    assert own["status"] == "rejected"
    assert own["review_note"] == review.MODERATION_REASONS["violence"]
    assert model.classified == []


async def test_a_failed_call_leaves_it_in_review_and_the_retry_publishes(
    client, sender, model, monkeypatch
):
    from app.config import get_settings

    _, issue_id = await file_held_report(client, sender, model)

    assert await review.retry_stuck() == 0, "too fresh to retry yet"
    monkeypatch.setenv("REVIEW_RETRY_AFTER_MINUTES", "0")
    get_settings.cache_clear()
    assert await review.retry_stuck() == 1
    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["status"] == "reported"
    assert detail["ai_summary"] == SUMMARY, "the retry writes the summary too"


async def test_nobody_can_support_a_report_in_review(client, sender, model):
    _, issue_id = await file_held_report(client, sender, model)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(client, neighbour, issue_id)

    assert response.status_code == 404


async def test_a_support_photo_from_too_far_away_is_refused(client, sender, model, checks_on):
    _, issue_id = await file_public_report(client, sender, model)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(
        client, neighbour, issue_id, photo=other_jpeg(),
        latitude=SPOT[0] + 0.01, longitude=SPOT[1], captured_at=now(),
    )

    assert response.status_code == 422
    assert "m from this report" in response.json()["detail"]


async def test_a_stale_support_photo_is_refused(client, sender, model, checks_on):
    _, issue_id = await file_public_report(client, sender, model)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    hour_ago = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    response = await support(
        client, neighbour, issue_id, photo=other_jpeg(),
        latitude=SPOT[0], longitude=SPOT[1], captured_at=hour_ago,
    )

    assert response.status_code == 422
    assert "Take a fresh one" in response.json()["detail"]


async def test_a_copy_of_the_reports_own_photo_is_refused(client, sender, model, checks_on):
    _, issue_id = await file_public_report(client, sender, model)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(
        client, neighbour, issue_id, photo=jpeg_bytes(400, 300),
        latitude=SPOT[0], longitude=SPOT[1], captured_at=now(),
    )

    assert response.status_code == 422
    assert "already on this report" in response.json()["detail"]


async def test_a_passed_support_photo_counts_and_the_reporter_hears(client, sender, model, checks_on):
    reporter, issue_id = await file_public_report(client, sender, model)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    response = await support(
        client, neighbour, issue_id, photo=other_jpeg(),
        latitude=SPOT[0], longitude=SPOT[1], captured_at=now(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["photo_support_count"] == 0, "pending photos do not count"
    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["photo_support_count"] == 1
    assert model.classified == ["photo_review", "support_review"]
    feed = (await client.get("/notifications", headers=auth(reporter))).json()["items"]
    assert [n["type"] for n in feed].count("support_received") == 1


async def test_a_failed_support_is_taken_down_and_its_author_told(client, sender, model, checks_on):
    reporter, issue_id = await file_public_report(client, sender, model)
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    model.verdicts = [{"approve": False, "reason": "These photos show a different street."}]

    await support(
        client, neighbour, issue_id, photo=other_jpeg(),
        latitude=SPOT[0], longitude=SPOT[1], captured_at=now(),
    )

    detail = (await client.get(f"/issues/{issue_id}")).json()
    assert detail["photo_support_count"] == 0
    assert detail["comment_count"] == 0
    told = (await client.get("/notifications", headers=auth(neighbour))).json()["items"]
    assert told[0]["type"] == "support_rejected"
    assert told[0]["note"] == "These photos show a different street."
    heard = (await client.get("/notifications", headers=auth(reporter))).json()["items"]
    assert "support_received" not in [n["type"] for n in heard]
