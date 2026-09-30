"""The one place the backend talks to a language model.

Titles, summaries, routing, letters and reply-reading all send one system
prompt and one message and want text back, so they share this. Each keeps its
own no-op default; this is only reached when a key is configured.
"""
import logging

from .config import get_settings

log = logging.getLogger(__name__)

_client = None


def _openai():
    global _client
    if _client is None:
        from openai import AsyncOpenAI

        _client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _client


async def complete(system: str, prompt: str, *, max_output_tokens: int, purpose: str) -> str | None:
    """The model's reply as plain text, or None when it declined or said nothing.

    Reasoning is off: every caller rewrites, classifies or drafts from text
    already in hand, and none of them is worth the latency of thinking first.
    """
    response = await _openai().responses.create(
        model=get_settings().ai_model,
        instructions=system,
        input=prompt,
        reasoning={"effort": "none"},
        max_output_tokens=max_output_tokens,
    )
    for item in response.output:
        if item.type == "message":
            for part in item.content:
                if part.type == "refusal":
                    log.warning("%s refused: %s", purpose, part.refusal)
                    return None
    if response.status == "incomplete":
        log.warning("%s cut off: %s", purpose, response.incomplete_details)
        return None
    return response.output_text.strip() or None
