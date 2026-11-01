"""Narrative advisory: number-echo audit plus deterministic template.

A narrative response carries a plain-language ``explanation`` and one
``suggested_experiment`` for an already-computed result JSON. Model
text is untrusted telemetry: it is displayed, never executed, and
NEVER parsed for numbers. The only gate between model text and the
reader is the number-echo audit:

- Every number token in the narrative must match a VALUE present in
  the input JSON (exact float equality — rounded or altered values
  fail) AND carry a unit/counter word that is both in the locked
  vocabulary below and present in the JSON (keys or string values).
- Any unjustified number discards the WHOLE narrative and emits the
  deterministic template instead. The audit errs strict: discarding
  a good narrative costs a template; passing a hallucination would
  cost trust.
- Prompt-injection text without numbers passes the audit by design
  (there is nothing numeric to falsify), but it cannot act: emitted
  narratives are display-only strings with no parser behind them,
  and this module exposes no narrative-to-numbers function.

The template is a total function of the result JSON: static skeleton
plus JSON values only, byte-stable for identical input. Its suggested
experiment is fixed project text (an independent length is the known
missing input for any gravity claim), never model words.

Stdlib only. No network. Deterministic.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from kineticlab.contracts import (
    ERROR_CODES,
    ContractError,
    FieldError,
)

NARRATIVE_VERSION = "advisory.narrative.v1"
"""Exact schema version for narrative advisory responses."""

NARRATIVE_FIELDS = frozenset({
    "schema_version",
    "explanation",
    "suggested_experiment",
    "model",
})
"""All required keys; unknown keys fail loudly."""

SLASH_UNITS = ("1/s^2", "m/s^2", "rad/s")
"""Multi-char units tried first when reading a governing word."""

UNIT_VOCABULARY = frozenset({
    "1/s^2", "m/s^2", "rad/s", "rad", "px", "mm", "m", "s", "ms",
    "frames", "frame", "records", "record", "observations",
    "observation", "confidence",
})
"""Locked words a narrative number may carry.

SI/contract units first; ``frames``/``records``/``observations``
name pipeline counts; ``confidence`` names the unitless observation
quantity by its JSON key. A word must ALSO occur in the input JSON
(as a key, key part, or string value) to justify a number —
vocabulary membership alone is not enough.
"""

assert all(code in ERROR_CODES for code in (
    "E_MALFORMED_JSON", "E_NOT_AN_OBJECT", "E_BAD_VERSION",
    "E_MISSING_FIELD", "E_UNEXPECTED_FIELD", "E_WRONG_TYPE",
    "E_EMPTY_STRING",
))

_NUMBER_TOKEN = re.compile(
    r"(?<![\w.])([+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?)")
# KL-10.21: the audit also fails closed on spelled-out numbers. A
# model can bypass the digit scan with words ("fifteen", "double",
# "percent"); any of these forces the template. Strict by design —
# harmless prose like "one of the frames" is discarded too.
# KL-10.22: inflected forms ("doubled", "tripled", "dozens") slipped
# the \b boundary and ordinals/adverbs ("twice", "second") were
# absent; inflected and open-ended forms are enumerated explicitly.
_NUMBER_WORDS = re.compile(
    r"(?<![\w-])(zero|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|"
    r"nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|hundreds|thousand|thousands|million|millions|billion|"
    r"billions|half|quarter|double|doubles|doubled|triple|triples|"
    r"tripled|dozen|dozens|percent|twice|first|second|third|fourth|"
    r"fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|"
    r"infinite)\b", re.IGNORECASE)
_WORD_AFTER = re.compile(r"[A-Za-z%][A-Za-z0-9_.%]*")
_WORD_BEFORE = re.compile(r"[A-Za-z%][A-Za-z0-9_.%]*$")
_MASK_CHAR = "#"

TEMPLATE_EXPERIMENT = (
    "Collect an independent pivot-length measurement so a gravity "
    "claim becomes decidable; until then report g/L_eff only."
)
"""Fixed template experiment text. Contains no numbers by design."""

TEMPLATE_WITHHELD_LINE = (
    "KineticLab advisory narrative withheld: the model text failed "
    "the number-echo audit, or no advisory was supplied; this "
    "deterministic template replaces it."
)


class _Collector:
    """Gathers every field error so one parse reports all failures."""

    def __init__(self) -> None:
        self.errors: list[FieldError] = []

    def add(self, code: str, field: str | None, message: str) -> None:
        self.errors.append(FieldError(code, field, message))

    def raise_if_any(self) -> None:
        if self.errors:
            raise ContractError(self.errors)


@dataclass(frozen=True)
class Narrative:
    """Validated narrative advisory (``advisory.narrative.v1``)."""

    explanation: str
    suggested_experiment: str
    model: str

    @classmethod
    def from_dict(cls, record: Any) -> "Narrative":
        collector = _Collector()
        if not isinstance(record, dict):
            collector.add("E_NOT_AN_OBJECT", None,
                          f"expected JSON object, got {type(record).__name__}")
            collector.raise_if_any()
        assert isinstance(record, dict)
        for key in sorted(record):
            if key not in NARRATIVE_FIELDS:
                collector.add("E_UNEXPECTED_FIELD", key,
                              f"unknown narrative key {key!r}")
        for key in sorted(NARRATIVE_FIELDS):
            if key not in record:
                collector.add("E_MISSING_FIELD", key,
                              f"required narrative key {key!r} is absent")
        version = record.get("schema_version")
        if "schema_version" in record and version != NARRATIVE_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {NARRATIVE_VERSION!r}, got {version!r}")
        fields: dict[str, str | None] = {}
        for key in ("explanation", "suggested_experiment", "model"):
            if key not in record:
                fields[key] = None
                continue
            raw = record[key]
            if not isinstance(raw, str):
                collector.add("E_WRONG_TYPE", key,
                              f"expected string, got {type(raw).__name__}")
                fields[key] = None
            elif not raw:
                collector.add("E_EMPTY_STRING", key,
                              f"{key} must be non-empty")
                fields[key] = None
            else:
                fields[key] = raw
        collector.raise_if_any()
        assert fields["explanation"] is not None
        assert fields["suggested_experiment"] is not None
        assert fields["model"] is not None
        return cls(explanation=fields["explanation"],
                   suggested_experiment=fields["suggested_experiment"],
                   model=fields["model"])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": NARRATIVE_VERSION,
            "explanation": self.explanation,
            "suggested_experiment": self.suggested_experiment,
            "model": self.model,
        }

    def text(self) -> str:
        """The displayable model text (display-only, never parsed)."""
        return (f"{self.explanation}\n"
                f"Suggested next experiment: {self.suggested_experiment}")


def parse_narrative(payload: str | bytes | dict) -> Narrative:
    """Parse untrusted bytes/text/object into a validated ``Narrative``.

    Raises ``ContractError`` with registered codes only; never returns
    a partial object.
    """
    if isinstance(payload, dict):
        return Narrative.from_dict(payload)
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
            "expected JSON text or object, got "
            f"{type(payload).__name__}")])
    try:
        record = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError([FieldError(
            "E_MALFORMED_JSON", None,
            f"advisory text is not JSON: {error}")]) from error
    return Narrative.from_dict(record)


def _walk_json_numbers_words(node: Any, numbers: list[float],
                             words: set[str]) -> None:
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        value = float(node)
        if math.isfinite(value):
            numbers.append(value)
        return
    if isinstance(node, str):
        words.add(node)
        return
    if isinstance(node, list):
        for item in node:
            _walk_json_numbers_words(item, numbers, words)
        return
    if isinstance(node, dict):
        for key, item in node.items():
            if isinstance(key, str):
                words.add(key)
                # Snake-case key parts ("frames_total" -> "frames")
                # name quantities the narrative may count with.
                words.update(part for part in key.split("_") if part)
            _walk_json_numbers_words(item, numbers, words)


def _masked_text(text: str) -> str:
    # Digits inside slash-units ("1/s^2") are spelling, not numbers:
    # mask them with same-length runs so offsets still line up.
    masked = text
    for unit in ("1/s^2", "m/s^2"):
        masked = masked.replace(unit, _MASK_CHAR * len(unit))
    return masked


def _strip_edge_punct(word: str) -> str:
    # Sentence punctuation is not part of the word ("234 frames.").
    return word.strip(".,;:!?")


def _governing_word(text: str, start: int, end: int) -> str | None:
    # Prefer the word after the number ("6.25 1/s^2"); fall back to
    # the word before it ("confidence 0.89").
    rest = text[end:].lstrip(" \t")
    for unit in SLASH_UNITS:
        if rest.startswith(unit):
            return unit
    match = _WORD_AFTER.match(rest)
    if match:
        stripped = _strip_edge_punct(match.group(0))
        if stripped:
            return stripped
    head = text[:start].rstrip(" \t").rstrip(".,;:!?")
    for unit in SLASH_UNITS:
        if head.endswith(unit):
            return unit
    match = _WORD_BEFORE.search(head)
    if match:
        return match.group(0)
    return None


def audit_narrative(result_json: dict, narrative: Narrative) -> tuple[bool, list[str]]:
    """Run the number-echo audit; ``(True, [])`` keeps the narrative.

    Every number token in the model text must exactly equal a number
    in ``result_json`` and carry a vocabulary word that also occurs in
    ``result_json`` (key, key part, or string value). Problems are
    short fact strings for the discard
    path only — never claims, never parsed.
    """
    if not isinstance(result_json, dict):
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", "result_json",
            f"audit needs a result dict, got {type(result_json).__name__}")])
    numbers: list[float] = []
    words: set[str] = set()
    _walk_json_numbers_words(result_json, numbers, words)
    problems: list[str] = []
    text = narrative.text()
    masked = _masked_text(text)
    for match in _NUMBER_TOKEN.finditer(masked):
        token = match.group(1)
        try:
            value = float(token)
        except ValueError:  # pragma: no cover — regex only emits floats
            problems.append(f"unparsable-number:{token}")
            continue
        if not math.isfinite(value) or not any(value == known for known in numbers):
            problems.append(f"unjustified-value:{token}")
            continue
        word = _governing_word(text, match.start(1), match.end(1))
        if word is None or word not in UNIT_VOCABULARY or word not in words:
            problems.append(f"unjustified-unit:{token}:{word}")
    # KL-10.21: digit tokens are not the only way to state a number —
    # spelled-out words and non-ASCII digits bypassed the scan above.
    word_hit = _NUMBER_WORDS.search(text)
    if word_hit is not None:
        problems.append(
            f"unjustified-number-word:{word_hit.group(1).lower()}")
    for character in text:
        if character.isdigit() and not character.isascii():
            problems.append("non-ascii-digit")
            break
    return (not problems, problems)


def render_template(result_json: dict) -> str:
    """Render the deterministic fallback from the result JSON only.

    Total: any dict in, one string out, byte-stable per input. Values
    come from the JSON; missing keys render as ``unknown``, never as
    guesses. The experiment line is fixed project text.
    """
    if not isinstance(result_json, dict):
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", "result_json",
            f"template needs a result dict, got {type(result_json).__name__}")])
    status = result_json.get("status", "unknown")
    quantity = result_json.get("identifiable_quantity", "unknown")
    value = result_json.get("value", "unknown")
    unit = result_json.get("unit", "unknown")
    warnings = result_json.get("warnings", [])
    reasons = result_json.get("reasons", [])
    warning_count = len(warnings) if isinstance(warnings, list) else "unknown"
    reason_count = len(reasons) if isinstance(reasons, list) else "unknown"
    return (
        f"{TEMPLATE_WITHHELD_LINE}\n"
        f"Result state: {status}. "
        f"Identifiable quantity: {quantity} = {value} {unit}. "
        f"Warnings: {warning_count}. Reasons: {reason_count}.\n"
        f"Suggested next experiment: {TEMPLATE_EXPERIMENT}"
    )


def resolve_narrative(result_json: dict,
                      narrative: Narrative | None) -> tuple[str, str]:
    """Return ``(display_text, source)`` with source ``model``/``template``.

    Missing narratives and audit failures resolve to the template;
    audit passes resolve to the verbatim model text. Callers must show
    the source label next to the text.
    """
    if narrative is None:
        return render_template(result_json), "template"
    passed, _ = audit_narrative(result_json, narrative)
    if passed:
        return narrative.text(), "model"
    return render_template(result_json), "template"
