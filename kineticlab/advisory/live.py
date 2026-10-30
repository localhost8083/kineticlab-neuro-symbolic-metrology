"""Live-request shapes for the Spark cache helper (no network here).

Request-body builder + response-content extractor for the
USER-VERIFIED Spark contract (2026-10-28): base ``https://api.meta.ai/v1``,
resource ``/chat/completions``, OpenAI-compatible, model
``muse-spark-1.3-contributor`` (fallback ``muse-spark-1.3``), bearer key
from ``MODEL_API_KEY`` env only.

Endpoint and model id are ALWAYS caller-supplied arguments — this
module hardcodes neither. The only fixed shapes are the
OpenAI-compatible ``messages`` request body and the
``choices[0].message.content`` response location, both covered by the
user's "OpenAI-compatible" verification. Network I/O lives solely in
``scripts/spark_live_cache.py``, which is never imported by tests or
by this subpackage. Malformed responses fail with registered codes.
"""

from __future__ import annotations

from typing import Any

from kineticlab.contracts import ContractError, FieldError

SETUP_REVIEW_INSTRUCTION = (
    "You are a setup reviewer for a fixed-camera planar pendulum "
    "experiment. Inspect the supplied frame-derived features and reply "
    "with EXACTLY one JSON object, no other text, matching this schema: "
    '{"schema_version": "advisory.setup-review.v1", '
    '"card_fully_visible": boolean, '
    '"camera_appears_static": boolean, '
    '"motion_blur_severity": "none"|"mild"|"severe", '
    '"pendulum_appears_planar": boolean, '
    '"unexpected_note": string-or-null, '
    '"model": string}. '
    "Every key is required. Report only what the features show."
)

NARRATIVE_INSTRUCTION = (
    "You are explaining a computed pendulum result to a lab partner. "
    "Reply with EXACTLY one JSON object, no other text, matching this "
    'schema: {"schema_version": "advisory.narrative.v1", '
    '"explanation": string, "suggested_experiment": string, '
    '"model": string}. '
    "Every key is required. CRITICAL: every number you write must "
    "appear with its unit exactly as in the supplied result JSON. "
    "Never invent, round, or convert a number."
)

_KIND_INSTRUCTIONS = {
    "setup-review": SETUP_REVIEW_INSTRUCTION,
    "narrative": NARRATIVE_INSTRUCTION,
}


def build_chat_request(model: str, kind: str, input_json: str) -> dict[str, Any]:
    """Build a minimal chat-completions body (model/messages only).

    ``model`` and the endpoint URL (used by the caller) are never
    defaulted here. No sampling parameters are set: the verified
    contract covers the resource shape, not tuning knobs.
    """
    if not isinstance(model, str) or not model:
        raise ContractError([FieldError(
            "E_EMPTY_STRING", "model",
            "serving model id must be a non-empty string")])
    if kind not in _KIND_INSTRUCTIONS:
        raise ContractError([FieldError(
            "E_BAD_ENUM", "kind",
            f"{kind!r} is outside {sorted(_KIND_INSTRUCTIONS)}")])
    if not isinstance(input_json, str) or not input_json:
        raise ContractError([FieldError(
            "E_EMPTY_STRING", "input_json",
            "request input must be a non-empty JSON string")])
    return {
        "model": model,
        "messages": [
            {"role": "user",
             "content": _KIND_INSTRUCTIONS[kind] + "\n\nINPUT:\n" + input_json},
        ],
    }


def extract_content(response_json: Any) -> str:
    """Extract the assistant text from a chat-completions response.

    Strict OpenAI-compatible shape: object with non-empty ``choices``
    list whose first item holds ``message.content`` as a non-empty
    string. Anything else fails with registered codes.
    """
    import json as _json

    if isinstance(response_json, (str, bytes)):
        try:
            text = response_json.decode("utf-8") \
                if isinstance(response_json, bytes) else response_json
            response_json = _json.loads(text)
        except (UnicodeDecodeError, _json.JSONDecodeError) as error:
            raise ContractError([FieldError(
                "E_MALFORMED_JSON", None,
                f"API response is not JSON: {error}")]) from error
    if not isinstance(response_json, dict):
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", None,
            "API response must be a JSON object, got "
            f"{type(response_json).__name__}")])
    choices = response_json.get("choices")
    if choices is None:
        raise ContractError([FieldError(
            "E_MISSING_FIELD", "choices",
            "API response lacks 'choices'")])
    if not isinstance(choices, list) or not choices:
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "choices",
            "API response 'choices' must be a non-empty list")])
    first = choices[0]
    if not isinstance(first, dict) or not isinstance(first.get("message"), dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "choices[0].message",
            "first choice must hold a message object")])
    content = first["message"].get("content")
    if not isinstance(content, str) or not content:
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "choices[0].message.content",
            "assistant content must be a non-empty string")])
    return content
