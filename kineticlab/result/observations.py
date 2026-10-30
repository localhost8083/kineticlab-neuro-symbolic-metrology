"""Deterministic observation-record exports: canonical JSON + CSV (KL-3.3).

Master plan section 5.5 assigns JSON/CSV writing to ``result``;
section 6 rules JSON canonical and CSV export-only. This module
covers observation lists only — result-contract assembly stays a
KL-7.x (P-007) concern.

JSON is the lossless form: ``export_observations_json`` emits
canonical UTF-8 bytes (sorted keys, indent 2, ASCII-only, single
trailing LF) for a top-level array of complete ``observation.v1``
dicts — valid AND invalid rows, warnings and provenance verbatim,
null stays null. ``parse_observations_json`` inverts it exactly:
parse(export(records)) == records, field-for-field.

CSV is presentation-grade: ``export_observations_csv`` flattens one
row per record (invalid rows included) under the fixed
``CSV_COLUMNS`` contract below. Empty cell = null; floats render
via repr (exact round-trip text); ``valid`` renders ``true``/``false``;
bbox splits into four min/max columns; warnings collapse to a
``;``-joined code list (``warning_codes``); provenance inlines as
compact sorted-key JSON (``provenance_json``). There is no CSV
parser by design: consumers needing lossless data take the JSON.

Both writers are pure functions of their input (no timestamps, no
file I/O, no caller-visible nondeterminism) and byte-stable across
runs. Failures use registered codes only: non-record input ->
``E_WRONG_TYPE``; unparseable JSON bytes -> ``E_MALFORMED_JSON``;
non-array JSON -> ``E_NOT_AN_OBJECT``; per-item violations propagate
from ``ObservationRecord.from_dict`` codes-preserved with the item
index prefixed to the field path.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from kineticlab.contracts import (
    ContractError,
    FieldError,
    ObservationRecord,
)
from kineticlab.result.quality import record_fill_ratio

JSON_INDENT = 2

CSV_COLUMNS = (
    "schema_version",
    "frame_index",
    "pts_seconds",
    "object_role",
    "object_id",
    "confidence",
    "bbox_x_min",
    "bbox_y_min",
    "bbox_x_max",
    "bbox_y_max",
    "centroid_x_px",
    "centroid_y_px",
    "mask_area_px",
    "mask_reference",
    "valid",
    "source",
    "warning_codes",
    "provenance_json",
)
"""Fixed CSV column contract (order significant, header always written)."""

TRAJECTORY_COLUMNS = (
    "frame_index",
    "pts_seconds",
    "centroid_x_px",
    "centroid_y_px",
    "mask_area_px",
    "bbox_fill_ratio",
    "confidence",
    "jump_flagged",
    "area_flagged",
    "fill_flagged",
)
"""Fixed trajectory column contract (row order follows input order)."""


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    return repr(value) if isinstance(value, float) else str(value)


def export_observations_json(records: list[ObservationRecord]) -> bytes:
    """Serialize records to canonical JSON bytes (lossless, byte-stable)."""
    for index, record in enumerate(records):
        if not isinstance(record, ObservationRecord):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", None,
                f"export item [{index}] is not an ObservationRecord: "
                f"{type(record).__name__}")])
    text = json.dumps([record.to_dict() for record in records],
                      sort_keys=True, indent=JSON_INDENT, ensure_ascii=True)
    return (text + "\n").encode("utf-8")


def parse_observations_json(data: bytes | str) -> list[ObservationRecord]:
    """Parse canonical JSON bytes back to records (exact inverse)."""
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ContractError([FieldError(
                "E_MALFORMED_JSON", None,
                f"export bytes are not UTF-8 JSON: {error}")]) from error
    else:
        text = data
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError([FieldError(
            "E_MALFORMED_JSON", None,
            f"export text is not parseable JSON: {error}")]) from error
    if not isinstance(raw, list):
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", None,
            "observation export must be a JSON array of records")])
    records: list[ObservationRecord] = []
    for index, item in enumerate(raw):
        try:
            records.append(ObservationRecord.from_dict(item))
        except ContractError as error:
            raise ContractError([
                FieldError(item_error.code,
                           f"[{index}]" + (f".{item_error.field}"
                                           if item_error.field else ""),
                           item_error.message)
                for item_error in error.errors
            ]) from error
    return records


def _flag_cell(value: Any, where: str) -> str:
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    raise ContractError([FieldError(
        "E_WRONG_TYPE", where,
        f"expected a flag bool or null, got {type(value).__name__}")])


def export_trajectory_csv(records: list[ObservationRecord],
                          assessment: dict[str, Any]) -> str:
    """Flatten one chain to presentation-grade trajectory CSV (LF, header).

    Flag columns come from the assessment's per-frame entries by frame
    index (first wins); frames the assessment does not cover render
    empty flag cells (unassessed, never a default pass). Row order
    follows input order. No parser by design: JSON stays lossless.
    """
    for index, record in enumerate(records):
        if not isinstance(record, ObservationRecord):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", None,
                f"export item [{index}] is not an ObservationRecord: "
                f"{type(record).__name__}")])
    if not isinstance(assessment, dict):
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", None,
            f"trajectory assessment must be a dict, got "
            f"{type(assessment).__name__}")])
    entries = assessment.get("frames", [])
    if not isinstance(entries, list):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "frames",
            f"expected a list, got {type(entries).__name__}")])
    flags: dict[int, dict[str, Any]] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", f"frames[{index}]",
                f"expected a dict, got {type(entry).__name__}")])
        frame = entry.get("frame_index")
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", f"frames[{index}].frame_index",
                f"expected a frame index int, got {type(frame).__name__}")])
        flags.setdefault(frame, entry)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(TRAJECTORY_COLUMNS)
    for record in records:
        entry = flags.get(record.frame_index, {})
        writer.writerow([
            _cell(record.frame_index),
            _cell(record.pts_seconds),
            _cell(record.centroid_x_px),
            _cell(record.centroid_y_px),
            _cell(record.mask_area_px),
            _cell(record_fill_ratio(record)),
            _cell(record.confidence),
            _flag_cell(entry.get("jump_flagged"),
                       f"frames[{record.frame_index}].jump_flagged"),
            _flag_cell(entry.get("area_flagged"),
                       f"frames[{record.frame_index}].area_flagged"),
            _flag_cell(entry.get("fill_flagged"),
                       f"frames[{record.frame_index}].fill_flagged"),
        ])
    return buffer.getvalue()


def export_observations_csv(records: list[ObservationRecord]) -> str:
    """Flatten records to presentation-grade CSV text (LF, header always)."""
    for index, record in enumerate(records):
        if not isinstance(record, ObservationRecord):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", None,
                f"export item [{index}] is not an ObservationRecord: "
                f"{type(record).__name__}")])
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for record in records:
        data = record.to_dict()
        bbox = data["bbox"] or [None, None, None, None]
        provenance = data["provenance"]
        writer.writerow([
            _cell(data["schema_version"]),
            _cell(data["frame_index"]),
            _cell(data["pts_seconds"]),
            _cell(data["object_role"]),
            _cell(data["object_id"]),
            _cell(data["confidence"]),
            _cell(bbox[0]),
            _cell(bbox[1]),
            _cell(bbox[2]),
            _cell(bbox[3]),
            _cell(data["centroid_x_px"]),
            _cell(data["centroid_y_px"]),
            _cell(data["mask_area_px"]),
            _cell(data["mask_reference"]),
            _cell(data["valid"]),
            _cell(data["source"]),
            ";".join(warning["code"] for warning in data["warnings"]),
            "" if provenance is None else json.dumps(
                provenance, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True),
        ])
    return buffer.getvalue()
