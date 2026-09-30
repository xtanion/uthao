"""The titler is swapped for a recorder, so nothing here calls a model."""
import uuid

import pytest

from app.service import title_is_derived
from app.titles import TitleRequest, Titler, clean, render
from tests.conftest import create_issue, sign_in

REPORTER = "+919876543210"
CAPTION = "The manhole cover near the bus stop has been missing for a week and it is unlit at night"
CLIPPED = CAPTION[:40].strip()


def report_id() -> str:
    return str(uuid.uuid4())


class RecordingTitler(Titler):
    def __init__(self, text: str | None = "Missing manhole cover near the bus stop") -> None:
        self.calls: list[TitleRequest] = []
        self.text = text

    async def title(self, request: TitleRequest) -> str | None:
        self.calls.append(request)
        return self.text


@pytest.fixture
def titler(monkeypatch):
    from app import summarize, titles
    from app.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    get_settings.cache_clear()
    recorder = RecordingTitler()
    titles.set_titler(recorder)
    summarize.set_summarizer(summarize.NullSummarizer())
    yield recorder
    summarize.set_summarizer(None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()


async def test_a_clipped_caption_is_rewritten(client, sender, titler):
    token = await sign_in(client, sender, REPORTER)

    created = await create_issue(
        client, token, report_id=report_id(), title=CLIPPED, description=CAPTION
    )

    assert created.json()["title"] == CLIPPED, "the response does not wait for it"
    assert titler.calls[0].description == CAPTION
    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["title"] == "Missing manhole cover near the bus stop"


async def test_a_title_the_reporter_wrote_is_kept(client, sender, titler):
    token = await sign_in(client, sender, REPORTER)

    created = await create_issue(
        client, token, report_id=report_id(), title="Open manhole", description=CAPTION
    )

    assert titler.calls == []
    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["title"] == "Open manhole"


async def test_a_retried_upload_is_not_titled_twice(client, sender, titler):
    token = await sign_in(client, sender, REPORTER)
    same = report_id()

    await create_issue(client, token, report_id=same, title=CLIPPED, description=CAPTION)
    await create_issue(client, token, report_id=same, title=CLIPPED, description=CAPTION)

    assert len(titler.calls) == 1


async def test_no_answer_leaves_the_caption(client, sender, titler):
    titler.text = None
    token = await sign_in(client, sender, REPORTER)

    created = await create_issue(
        client, token, report_id=report_id(), title=CLIPPED, description=CAPTION
    )

    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["title"] == CLIPPED


async def test_a_failing_titler_does_not_fail_the_report(client, sender, titler):
    from app import titles

    class Broken(Titler):
        async def title(self, request: TitleRequest) -> str | None:
            raise RuntimeError("model unavailable")

    titles.set_titler(Broken())
    token = await sign_in(client, sender, REPORTER)

    created = await create_issue(
        client, token, report_id=report_id(), title=CLIPPED, description=CAPTION
    )

    assert created.status_code == 201
    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["title"] == CLIPPED


async def test_without_a_key_nothing_is_asked(client, sender):
    from app import titles

    recorder = RecordingTitler()
    titles.set_titler(recorder)
    token = await sign_in(client, sender, REPORTER)

    await create_issue(client, token, report_id=report_id(), title=CLIPPED, description=CAPTION)

    assert recorder.calls == []


def test_the_app_clipping_counts_as_derived():
    assert title_is_derived("The manhole cover near the bus…", CAPTION[:30] + " stop")
    assert title_is_derived(CAPTION, CAPTION)
    assert not title_is_derived("Open manhole", CAPTION)
    assert not title_is_derived("Anything", "")


def test_replies_are_tidied_or_refused():
    assert clean('"Missing manhole cover near the bus stop."\n') == "Missing manhole cover near the bus stop"
    assert clean("  Broken   streetlight ") == "Broken streetlight"
    assert clean("") is None
    assert clean("x" * 141) is None


def test_the_prompt_carries_what_the_reporter_said():
    text = render(TitleRequest(description=CAPTION, category="manhole", locality="Dadar"))
    assert "Category: manhole" in text
    assert "Locality: Dadar" in text
    assert CAPTION in text
