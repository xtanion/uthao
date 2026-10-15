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


async def moderate(text: str, images: list[bytes], *, model: str) -> list[str] | None:
    """OpenAI's moderation check on a caption and its photos. Free to call.

    Returns the flagged category names (empty when clean), or None when the
    call failed and the caller should try again later.
    """
    import base64

    inputs: list[dict] = []
    if text.strip():
        inputs.append({"type": "text", "text": text})
    for image in images:
        encoded = base64.b64encode(image).decode()
        inputs.append(
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encoded}"}}
        )
    try:
        response = await _openai().moderations.create(model=model, input=inputs)
    except Exception:
        log.warning("moderation call failed", exc_info=True)
        return None
    flagged: set[str] = set()
    for result in response.results:
        if result.flagged:
            categories = result.categories.model_dump(by_alias=True)
            flagged.update(name for name, hit in categories.items() if hit)
    return sorted(flagged)


async def classify(
    system: str,
    prompt: str,
    images: list[bytes],
    *,
    schema: dict,
    model: str,
    purpose: str,
) -> dict | None:
    """A structured verdict about some photos, or None when the model declined.

    Photos go in as low-detail JPEGs: the check is "is this a pothole", not
    "read the number plate", and low detail is a fraction of the tokens.
    """
    import base64
    import json

    content: list[dict] = [{"type": "input_text", "text": prompt}]
    for image in images:
        encoded = base64.b64encode(image).decode()
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{encoded}",
                "detail": "low",
            }
        )
    response = await _openai().responses.create(
        model=model,
        instructions=system,
        input=[{"role": "user", "content": content}],
        reasoning={"effort": "none"},
        max_output_tokens=200,
        text={"format": {"type": "json_schema", "name": purpose, "schema": schema, "strict": True}},
    )
    if response.status == "incomplete":
        log.warning("%s cut off: %s", purpose, response.incomplete_details)
        return None
    try:
        return json.loads(response.output_text)
    except (ValueError, TypeError):
        log.warning("%s returned something that is not JSON", purpose)
        return None


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
