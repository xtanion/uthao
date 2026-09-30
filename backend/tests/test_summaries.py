"""The summarizer is swapped for a recorder, so nothing here calls a model."""
import uuid

import pytest

from app.summarize import SummaryRequest, Summarizer, render
from tests.conftest import auth, create_issue, sign_in

REPORTER = "+919876543210"
NEIGHBOUR = "+919876500001"
THIRD = "+919876500002"


def report_id() -> str:
    return str(uuid.uuid4())


class RecordingSummarizer(Summarizer):
    def __init__(self, text: str = "A manhole cover is missing on the footpath.") -> None:
        self.calls: list[SummaryRequest] = []
        self.text = text

    async def summarize(self, request: SummaryRequest) -> str | None:
        self.calls.append(request)
        return self.text


@pytest.fixture
def summarizer(monkeypatch):
    from app import summarize
    from app.config import get_settings

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    get_settings.cache_clear()
    recorder = RecordingSummarizer()
    summarize.set_summarizer(recorder)
    yield recorder
    summarize.set_summarizer(None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()


async def test_a_new_report_is_summarized(client, sender, summarizer):
    token = await sign_in(client, sender, REPORTER)

    created = await create_issue(client, token, report_id=report_id())

    assert created.json()["ai_summary"] is None, "the response does not wait for it"
    assert len(summarizer.calls) == 1
    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["ai_summary"] == "A manhole cover is missing on the footpath."


async def test_the_summary_sees_what_people_wrote(client, sender, summarizer):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "Someone put a branch in it as a warning."},
    )

    latest = summarizer.calls[-1]
    assert latest.title == "Cover missing on the footpath side"
    assert latest.voices == ["Someone put a branch in it as a warning."]
    assert latest.category == "manhole"
    assert latest.severity == "high"


async def test_a_bare_support_does_not_rewrite_the_summary(client, sender, summarizer):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    before = len(summarizer.calls)

    await client.post(f"/issues/{issue_id}/confirmations", headers=auth(neighbour))

    assert len(summarizer.calls) == before, "a +1 changes no words"


async def test_the_first_reply_always_lands(client, sender, summarizer):
    """A plain time debounce would swallow it, because writing the summary at
    report time starts the clock. The first words are the ones worth having."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    before = len(summarizer.calls)
    neighbour = await sign_in(client, sender, NEIGHBOUR)

    await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "A branch is stuck in it now."},
    )

    assert len(summarizer.calls) == before + 1
    assert summarizer.calls[-1].voices == ["A branch is stuck in it now."]


async def test_later_replies_in_quick_succession_are_held(client, sender, summarizer):
    """Ten people replying in a minute should not mean ten model calls."""
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "First words."},
    )
    before = len(summarizer.calls)

    third = await sign_in(client, sender, THIRD)
    await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(third),
        data={"body": "Second words, moments later."},
    )

    assert len(summarizer.calls) == before, "the interval holds from here on"


async def test_the_interval_lets_it_catch_up_later(client, sender, summarizer, monkeypatch):
    reporter = await sign_in(client, sender, REPORTER)
    issue_id = (await create_issue(client, reporter, report_id=report_id())).json()["id"]
    neighbour = await sign_in(client, sender, NEIGHBOUR)
    await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(neighbour),
        data={"body": "First words."},
    )
    before = len(summarizer.calls)

    from app.config import get_settings

    monkeypatch.setenv("AI_SUMMARY_MIN_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    third = await sign_in(client, sender, THIRD)
    await client.post(
        f"/issues/{issue_id}/supports",
        headers=auth(third),
        data={"body": "Second words, much later."},
    )

    assert len(summarizer.calls) == before + 1
    assert len(summarizer.calls[-1].voices) == 2


async def test_with_no_key_there_is_no_summary_and_no_call(client, sender):
    """The default path: a checkout with no key runs and the field is null."""
    from app import summarize

    summarize.set_summarizer(None)
    token = await sign_in(client, sender, REPORTER)

    created = await create_issue(client, token, report_id=report_id())

    detail = await client.get(f"/issues/{created.json()['id']}")
    assert detail.json()["ai_summary"] is None


async def test_a_summarizer_that_fails_does_not_break_the_report(client, sender, monkeypatch):
    from app import summarize
    from app.config import get_settings

    class Broken(Summarizer):
        async def summarize(self, request):
            raise RuntimeError("the model is down")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    get_settings.cache_clear()
    summarize.set_summarizer(Broken())
    try:
        token = await sign_in(client, sender, REPORTER)
        created = await create_issue(client, token, report_id=report_id())
        assert created.status_code == 201, "the report is filed regardless"
        detail = await client.get(f"/issues/{created.json()['id']}")
        assert detail.json()["ai_summary"] is None
    finally:
        summarize.set_summarizer(None)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        get_settings.cache_clear()


def test_the_prompt_carries_the_report_and_the_replies():
    body = render(
        SummaryRequest(
            title="Cover missing",
            description="Unlit after dark.",
            category="manhole",
            severity="high",
            status="community_verified",
            locality="Bandra East",
            voices=["Still open.", "A branch is stuck in it."],
        )
    )

    assert "Cover missing" in body
    assert "Unlit after dark." in body
    assert "Bandra East" in body
    assert "- Still open." in body
    assert "- A branch is stuck in it." in body


def test_the_prompt_says_so_when_nobody_has_replied():
    body = render(
        SummaryRequest(
            title="Cover missing",
            description="",
            category="manhole",
            severity="high",
            status="reported",
            locality=None,
            voices=[],
        )
    )

    assert "Nobody else has written anything yet." in body
    assert "Locality" not in body
