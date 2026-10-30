"""Setup-review advisory: schema-validated Spark flags, applied conservatively.

A setup-review response carries five flags about the experiment setup:
card visibility, camera stability, motion-blur severity, pendulum
planarity, and an unexpected-content note. Every flag maps onto the
EXISTING warning code ``W_ASSUMPTION_UNVERIFIED`` with a fact-only
detail naming the flag: each fired flag disconfirms one stated setup
assumption, which is exactly what that code means. Alternatives were
considered and rejected: ``W_PARTIAL_OBSERVATION`` is about record
geometry, ``W_LOW_CONFIDENCE`` about retained confidences, and
``W_SHORT_TRACK`` about span length — none of them is setup-assumption
semantics. No new code was needed, so none was added.

Hard rules (PLAN.md Phase M, M-2 bullet a):

- Flags may ADD warnings or DOWNGRADE ``success`` to
  ``success_with_warnings``. They can never upgrade a state, change a
  number, or remove/suppress an existing warning: application output is
  always a superset of its input.
- Malformed, schema-violating, hostile, or missing responses are
  rejected with registered codes; the caller then proceeds as if no
  advisory existed, which is never less conservative than applying it.
- The free-text ``unexpected_note`` is untrusted telemetry: its
  CONTENT is never quoted into warnings, exports, or claims. Details
  carry presence + length + the cache source ref so a human can
  inspect the cached raw bytes.

Stdlib only. No network. Deterministic: same bytes in, same objects
out, always.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from kineticlab.contracts import (
    ERROR_CODES,
    WARNING_CODES,
    ContractError,
    FieldError,
    ResultState,
    Warning,
)

SETUP_REVIEW_VERSION = "advisory.setup-review.v1"
"""Exact schema version for setup-review advisory responses."""

BLUR_SEVERITIES = frozenset({"none", "mild", "severe"})
"""Locked motion-blur severity vocabulary."""

SETUP_FIELDS = frozenset({
    "schema_version",
    "card_fully_visible",
    "camera_appears_static",
    "motion_blur_severity",
    "pendulum_appears_planar",
    "unexpected_note",
    "model",
})
"""All required keys; unknown keys fail loudly."""

SURFACED_CODE = "W_ASSUMPTION_UNVERIFIED"
"""The single registered code every fired flag surfaces through."""

assert SURFACED_CODE in WARNING_CODES
assert all(code in ERROR_CODES for code in (
    "E_MALFORMED_JSON", "E_NOT_AN_OBJECT", "E_BAD_VERSION",
    "E_MISSING_FIELD", "E_UNEXPECTED_FIELD", "E_WRONG_TYPE",
    "E_BAD_ENUM", "E_EMPTY_STRING",
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


def _strict_bool(value: Any, collector: _Collector, field: str) -> bool | None:
    # bool is a subclass of int: accept True/False only, never 0/1.
    if isinstance(value, bool):
        return value
    collector.add("E_WRONG_TYPE", field,
                  f"expected JSON boolean, got {type(value).__name__}")
    return None


@dataclass(frozen=True)
class SetupReview:
    """Validated setup-review advisory flags (``advisory.setup-review.v1``)."""

    card_fully_visible: bool
    camera_appears_static: bool
    motion_blur_severity: str
    pendulum_appears_planar: bool
    unexpected_note: str | None
    model: str

    @classmethod
    def from_dict(cls, record: Any) -> "SetupReview":
        collector = _Collector()
        if not isinstance(record, dict):
            collector.add("E_NOT_AN_OBJECT", None,
                          f"expected JSON object, got {type(record).__name__}")
            collector.raise_if_any()
        assert isinstance(record, dict)
        for key in sorted(record):
            if key not in SETUP_FIELDS:
                collector.add("E_UNEXPECTED_FIELD", key,
                              f"unknown setup-review key {key!r}")
        for key in sorted(SETUP_FIELDS):
            if key not in record:
                collector.add("E_MISSING_FIELD", key,
                              f"required setup-review key {key!r} is absent")
        version = record.get("schema_version")
        if "schema_version" in record and version != SETUP_REVIEW_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {SETUP_REVIEW_VERSION!r}, "
                          f"got {version!r}")
        card = _strict_bool(record.get("card_fully_visible"), collector,
                            "card_fully_visible") \
            if "card_fully_visible" in record else None
        camera = _strict_bool(record.get("camera_appears_static"), collector,
                              "camera_appears_static") \
            if "camera_appears_static" in record else None
        planar = _strict_bool(record.get("pendulum_appears_planar"), collector,
                              "pendulum_appears_planar") \
            if "pendulum_appears_planar" in record else None
        severity: str | None = None
        if "motion_blur_severity" in record:
            raw_severity = record["motion_blur_severity"]
            if not isinstance(raw_severity, str):
                collector.add("E_WRONG_TYPE", "motion_blur_severity",
                              "expected string, got "
                              f"{type(raw_severity).__name__}")
            elif raw_severity not in BLUR_SEVERITIES:
                collector.add("E_BAD_ENUM", "motion_blur_severity",
                              f"{raw_severity!r} is outside "
                              f"{sorted(BLUR_SEVERITIES)}")
            else:
                severity = raw_severity
        note: str | None = None
        if "unexpected_note" in record:
            raw_note = record["unexpected_note"]
            if raw_note is not None and not isinstance(raw_note, str):
                collector.add("E_WRONG_TYPE", "unexpected_note",
                              "expected string or null, got "
                              f"{type(raw_note).__name__}")
            else:
                note = raw_note
        model: str | None = None
        if "model" in record:
            raw_model = record["model"]
            if not isinstance(raw_model, str):
                collector.add("E_WRONG_TYPE", "model",
                              f"expected string, got {type(raw_model).__name__}")
            elif not raw_model:
                collector.add("E_EMPTY_STRING", "model",
                              "serving model id must be non-empty")
            else:
                model = raw_model
        collector.raise_if_any()
        assert card is not None and camera is not None
        assert planar is not None and severity is not None
        assert model is not None
        return cls(card_fully_visible=card, camera_appears_static=camera,
                   motion_blur_severity=severity,
                   pendulum_appears_planar=planar, unexpected_note=note,
                   model=model)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SETUP_REVIEW_VERSION,
            "card_fully_visible": self.card_fully_visible,
            "camera_appears_static": self.camera_appears_static,
            "motion_blur_severity": self.motion_blur_severity,
            "pendulum_appears_planar": self.pendulum_appears_planar,
            "unexpected_note": self.unexpected_note,
            "model": self.model,
        }


def parse_setup_review(payload: str | bytes | dict) -> SetupReview:
    """Parse untrusted bytes/text/object into a validated ``SetupReview``.

    Raises ``ContractError`` with registered codes only; never returns
    a partial object.
    """
    import json

    if isinstance(payload, dict):
        return SetupReview.from_dict(payload)
    if isinstance(payload, bytes):
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContractError([FieldError(
                "E_MALFORMED_JSON", None,
                f"advisory bytes are not UTF-8: {error}")]) from error
    elif isinstance(payload, str):
        text = payload
    else:
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", None,
            f"expected JSON text or object, got {type(payload).__name__}")])
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError([FieldError(
            "E_MALFORMED_JSON", None,
            f"advisory text is not JSON: {error}")]) from error
    return SetupReview.from_dict(record)


def _detail(flag: str, fact: str, source_ref: str) -> str:
    return (f"advisory flag {flag}: {fact} "
            f"(source: {source_ref}; model output is untrusted telemetry)")


def map_flags_to_warnings(review: SetupReview, source_ref: str) -> list[Warning]:
    """Map fired flags onto existing-code warnings (pure data, no I/O).

    Nominal flags (visible/static/none/planar/absent note) map to zero
    warnings. Every returned warning carries ``W_ASSUMPTION_UNVERIFIED``
    with a fact-only detail naming the flag, its observed value, and
    the cache source ref. The note's CONTENT is never quoted.
    """
    warnings: list[Warning] = []
    if not review.card_fully_visible:
        warnings.append(Warning(
            SURFACED_CODE,
            _detail("card_fully_visible=false",
                    "full-card-visibility assumption disconfirmed",
                    source_ref)))
    if not review.camera_appears_static:
        warnings.append(Warning(
            SURFACED_CODE,
            _detail("camera_appears_static=false",
                    "fixed-camera assumption disconfirmed", source_ref)))
    if review.motion_blur_severity != "none":
        warnings.append(Warning(
            SURFACED_CODE,
            _detail(f"motion_blur_severity={review.motion_blur_severity}",
                    "negligible-blur assumption disconfirmed", source_ref)))
    if not review.pendulum_appears_planar:
        warnings.append(Warning(
            SURFACED_CODE,
            _detail("pendulum_appears_planar=false",
                    "planar-motion assumption disconfirmed", source_ref)))
    if review.unexpected_note is not None and review.unexpected_note.strip():
        warnings.append(Warning(
            SURFACED_CODE,
            _detail("unexpected_note=present",
                    f"nominal-scene assumption disconfirmed "
                    f"(note length {len(review.unexpected_note)} chars; "
                    f"content not quoted)",
                    source_ref)))
    for warning in warnings:
        assert warning.code in WARNING_CODES
    return warnings


def apply_setup_advisory(warnings: list[Warning], status: str,
                         review: SetupReview,
                         source_ref: str) -> tuple[list[Warning], str]:
    """Apply validated flags to a warning list + result state.

    Output warnings always contain the input warnings in order, plus
    the mapped flag warnings appended (exact code+detail duplicates
    suppressed so re-application is idempotent). ``success`` with at
    least one mapped warning becomes ``success_with_warnings``; every
    other state passes through untouched. There is no upgrade path:
    warnings only grow, states only stay or downgrade.
    """
    if not isinstance(warnings, list):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "warnings",
            f"expected a warning list, got {type(warnings).__name__}")])
    for index, warning in enumerate(warnings):
        if not isinstance(warning, Warning):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", f"warnings[{index}]",
                f"expected Warning, got {type(warning).__name__}")])
        if warning.code not in WARNING_CODES:
            raise ContractError([FieldError(
                "E_UNKNOWN_WARNING_CODE", f"warnings[{index}].code",
                f"{warning.code!r} is outside the locked taxonomy")])
    states = {state.value for state in ResultState}
    if status not in states:
        raise ContractError([FieldError(
            "E_BAD_ENUM", "status",
            f"{status!r} is outside {sorted(states)}")])
    mapped = map_flags_to_warnings(review, source_ref)
    seen = {(warning.code, warning.detail) for warning in warnings}
    merged = list(warnings)
    for warning in mapped:
        if (warning.code, warning.detail) not in seen:
            seen.add((warning.code, warning.detail))
            merged.append(warning)
    if mapped and status == ResultState.SUCCESS.value:
        status = ResultState.SUCCESS_WITH_WARNINGS.value
    return merged, status
