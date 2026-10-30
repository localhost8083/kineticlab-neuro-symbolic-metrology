"""Advisory cache: file-backed Spark responses with offline replay.

Every cache entry binds a raw model response to its request metadata,
a SHA-256 over the response bytes, and an explicit provenance label:

- ``live``: bytes captured from a real API call (written only by the
  live-cache helper after a genuine call).
- ``replay``: bytes copied from a ``live`` entry into the offline
  replay set; must name the live entry's response hash in
  ``replayed_from_sha256`` (chain documented, resolved by humans).
- ``synthetic-fixture``: hand-authored test data, never a live claim.

Replay is fully offline by construction: this module has no network
code. ``load_entry`` re-verifies the hash before anything else, so
tampered bytes fail with ``E_INCOHERENT_VALUE`` instead of parsing.
``replay_entry`` goes one step further and returns the validated
advisory object (setup-review or narrative) the rest of the pipeline
consumes — the exact path a live response will travel once cached.

Canonical bytes: UTF-8, LF, sorted keys, indent 2, ASCII-escaped.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from kineticlab.advisory.narrative import Narrative, parse_narrative
from kineticlab.advisory.setup_review import SetupReview, parse_setup_review
from kineticlab.contracts import ERROR_CODES, ContractError, FieldError

CACHE_VERSION = "advisory.cache.v1"
"""Exact schema version for cache entries."""

CACHE_LABELS = frozenset({"live", "replay", "synthetic-fixture"})
"""Locked provenance labels; nothing else is storable."""

CACHE_KINDS = frozenset({"setup-review", "narrative"})
"""Locked advisory kinds served from cache."""

CACHE_FIELDS = frozenset({
    "schema_version",
    "label",
    "kind",
    "request",
    "response_text",
    "response_sha256",
    "replayed_from_sha256",
})
"""All required keys; unknown keys fail loudly."""

REQUEST_FIELDS = frozenset({
    "endpoint",
    "model",
    "input_sha256",
    "input_desc",
    "recorded_utc",
})
"""All required request-metadata keys."""

_SHA256_RE = re.compile(r"[0-9a-f]{64}")

assert all(code in ERROR_CODES for code in (
    "E_MALFORMED_JSON", "E_NOT_AN_OBJECT", "E_BAD_VERSION",
    "E_MISSING_FIELD", "E_UNEXPECTED_FIELD", "E_WRONG_TYPE",
    "E_BAD_ENUM", "E_EMPTY_STRING", "E_BAD_SHA256", "E_INCOHERENT_VALUE",
))


class _Collector:
    """Gathers every field error so one parse reports all failures."""

    def __init__(self) -> None:
        self.errors: list[FieldError] = []

    def add(self, code: str, field: str | None, message: str) -> None:
        self.errors.append(FieldError(code, field, message))

    def raise_if_any(self) -> None:
        if self.errors:
            raise ContractError(self.errors)


def response_digest(response_text: str) -> str:
    """SHA-256 over the UTF-8 bytes of a raw model response."""
    return hashlib.sha256(response_text.encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def validate_entry(record: Any) -> dict[str, Any]:
    """Strict-validate a cache entry dict; return it unchanged.

    Raises ``ContractError`` with registered codes only. Hash shape
    AND hash agreement are both checked: a well-formed hash that does
    not match the response bytes is ``E_INCOHERENT_VALUE``.
    """
    collector = _Collector()
    if not isinstance(record, dict):
        collector.add("E_NOT_AN_OBJECT", None,
                      f"expected JSON object, got {type(record).__name__}")
        collector.raise_if_any()
    assert isinstance(record, dict)
    for key in sorted(record):
        if key not in CACHE_FIELDS:
            collector.add("E_UNEXPECTED_FIELD", key,
                          f"unknown cache key {key!r}")
    for key in sorted(CACHE_FIELDS):
        if key not in record:
            collector.add("E_MISSING_FIELD", key,
                          f"required cache key {key!r} is absent")
    version = record.get("schema_version")
    if "schema_version" in record and version != CACHE_VERSION:
        collector.add("E_BAD_VERSION", "schema_version",
                      f"expected {CACHE_VERSION!r}, got {version!r}")
    label = record.get("label")
    if "label" in record:
        if not isinstance(label, str):
            collector.add("E_WRONG_TYPE", "label",
                          f"expected string, got {type(label).__name__}")
        elif label not in CACHE_LABELS:
            collector.add("E_BAD_ENUM", "label",
                          f"{label!r} is outside {sorted(CACHE_LABELS)}")
    kind = record.get("kind")
    if "kind" in record:
        if not isinstance(kind, str):
            collector.add("E_WRONG_TYPE", "kind",
                          f"expected string, got {type(kind).__name__}")
        elif kind not in CACHE_KINDS:
            collector.add("E_BAD_ENUM", "kind",
                          f"{kind!r} is outside {sorted(CACHE_KINDS)}")
    request = record.get("request")
    if "request" in record:
        if not isinstance(request, dict):
            collector.add("E_WRONG_TYPE", "request",
                          "expected JSON object, got "
                          f"{type(request).__name__}")
        else:
            for key in sorted(request):
                if key not in REQUEST_FIELDS:
                    collector.add("E_UNEXPECTED_FIELD", f"request.{key}",
                                  f"unknown request key {key!r}")
            for key in sorted(REQUEST_FIELDS):
                if key not in request:
                    collector.add("E_MISSING_FIELD", f"request.{key}",
                                  f"required request key {key!r} is absent")
            endpoint = request.get("endpoint")
            if "endpoint" in request and endpoint is not None \
                    and not isinstance(endpoint, str):
                collector.add("E_WRONG_TYPE", "request.endpoint",
                              "expected string or null, got "
                              f"{type(endpoint).__name__}")
            for key in ("model", "input_desc", "recorded_utc"):
                if key in request:
                    raw = request[key]
                    if not isinstance(raw, str):
                        collector.add("E_WRONG_TYPE", f"request.{key}",
                                      "expected string, got "
                                      f"{type(raw).__name__}")
                    elif not raw:
                        collector.add("E_EMPTY_STRING", f"request.{key}",
                                      f"request.{key} must be non-empty")
            if "input_sha256" in request \
                    and not _is_sha256(request["input_sha256"]):
                collector.add("E_BAD_SHA256", "request.input_sha256",
                              "input hash is not 64 lowercase hex")
    text = record.get("response_text")
    if "response_text" in record:
        if not isinstance(text, str):
            collector.add("E_WRONG_TYPE", "response_text",
                          f"expected string, got {type(text).__name__}")
        elif not text:
            collector.add("E_EMPTY_STRING", "response_text",
                          "cached response must be non-empty")
    digest = record.get("response_sha256")
    if "response_sha256" in record and not _is_sha256(digest):
        collector.add("E_BAD_SHA256", "response_sha256",
                      "response hash is not 64 lowercase hex")
    replayed = record.get("replayed_from_sha256")
    if "replayed_from_sha256" in record:
        if label == "replay":
            if not _is_sha256(replayed):
                collector.add("E_BAD_SHA256", "replayed_from_sha256",
                              "replay entries must name a live response hash")
        elif replayed is not None:
            collector.add("E_INCOHERENT_VALUE", "replayed_from_sha256",
                          f"label {label!r} forbids a replay source hash")
    if (isinstance(text, str) and text and _is_sha256(digest)
            and response_digest(text) != digest):
        collector.add("E_INCOHERENT_VALUE", "response_sha256",
                      "response hash does not match the response bytes")
    collector.raise_if_any()
    return record


def build_entry(*, label: str, kind: str, request: dict[str, Any],
                response_text: str,
                replayed_from_sha256: str | None = None) -> dict[str, Any]:
    """Build a validated cache entry (computes the response hash).

    Raises ``ContractError`` for bad inputs before returning anything.
    """
    entry = {
        "schema_version": CACHE_VERSION,
        "label": label,
        "kind": kind,
        "request": dict(request),
        "response_text": response_text,
        "response_sha256": response_digest(response_text)
        if isinstance(response_text, str) else response_text,
        "replayed_from_sha256": replayed_from_sha256,
    }
    return validate_entry(entry)


def entry_bytes(entry: dict[str, Any]) -> bytes:
    """Canonical bytes for a validated entry (UTF-8, LF, sorted, indented)."""
    validate_entry(entry)
    return (json.dumps(entry, sort_keys=True, indent=2,
                       ensure_ascii=True) + "\n").encode("utf-8")


def save_entry(path: str | Path, entry: dict[str, Any]) -> Path:
    """Validate and write one cache entry; returns the path written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(entry_bytes(entry))
    return target


def load_entry(path: str | Path) -> dict[str, Any]:
    """Read and strict-validate one cache entry (hash re-verified).

    Raises ``ContractError`` with registered codes for missing files
    (surfaced as ``E_MALFORMED_JSON`` with a fact-only detail — the
    file is unreadable as JSON), bad JSON, schema violations, and
    hash mismatches.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise ContractError([FieldError(
            "E_MALFORMED_JSON", None,
            f"cache entry is unreadable: {error}")]) from error
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ContractError([FieldError(
            "E_MALFORMED_JSON", None,
            f"cache entry is not JSON: {error}")]) from error
    return validate_entry(record)


def replay_entry(entry: dict[str, Any]) -> SetupReview | Narrative:
    """Replay a cache entry into its validated advisory object.

    Hash-verifies first (via ``validate_entry``), then parses the raw
    response text with the kind's strict parser. This is the exact
    path live responses travel once cached — fully offline.
    """
    validate_entry(entry)
    if entry["kind"] == "setup-review":
        return parse_setup_review(entry["response_text"])
    return parse_narrative(entry["response_text"])
