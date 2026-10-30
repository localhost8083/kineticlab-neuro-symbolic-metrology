"""Observation quality reporting: coverage, gaps, jumps, shape (KL-4.1).

REPORT ONLY — this module derives plain-data facts from a chain
(ingest frame table + observation records) and judges nothing: no
thresholds, no good/bad labels, no rejection decisions, no smoothing.
Those are KL-4.2 with rationale-backed thresholds.

Placement follows the master plan: no ``quality`` stage exists in
section 5, and section 5.5 assigns reporting/writing duties to
``result``, next to the KL-3.3 observation exports. Output is plain
JSON-native data (no new contract schema version): ``dict``/``list``
of str/int/float/bool/None only, serializable via
``export_quality_json`` in the KL-3.3 canonical style (sorted keys,
indent 2, ASCII-only, trailing LF) for byte-stable reports.

Formulas (every number below is derivable from the inputs as stated):

- frame universe: sorted unique ``frame_index`` over the frame table.
- observed: sorted unique ``frame_index`` over the records.
- span: [min, max] of observed; nulls when no records.
- gaps: sorted observed-span indices absent from observed.
- jumps: over records sorted by frame index (stable; duplicates kept,
  never dropped), consecutive pairs report ``frame_delta`` (later
  minus earlier index) and ``centroid_distance_px`` =
  hypot(dx, dy); null when either centroid is incomplete.
- bbox fill ratio: ``mask_area_px / ((x2-x1+1) * (y2-y1+1))``; null
  when bbox or area is null or spans are non-positive. The +1 terms
  encode the established vendor convention of inclusive integer box
  spans (KL-3.1); for true float boxes this reads as inclusive-span
  product by documented assumption.
- summaries (area, fill ratio, confidence): count/min/max/mean over
  non-null values; nulls with count 0 when empty; mean = sum/n.
- confidence: per-record ``c`` verbatim; ``missing_count`` tallies
  explicit nulls.
- identity: frame-index lists grouped by observed ``object_id`` plus
  sorted roles. No switch verdict is derivable: ids are
  caller-declared per file, so the report states
  ``id_switch_detectable: false`` with that limitation instead of
  inventing detection.
- invalid rows appear under ``coverage.invalid_retained`` with frame
  index, PTS, warning codes, and a geometry flag — never dropped.

Malformed builder inputs reuse registered codes (a quality REPORT
raises no codes): non-list input -> ``E_NOT_AN_OBJECT``; non-record
or non-frame items -> ``E_WRONG_TYPE``.
"""

from __future__ import annotations

import json
import math
from typing import Any

from kineticlab.contracts import (
    ContractError,
    FieldError,
    FrameRecord,
    ObservationRecord,
)


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _check_chain(frame_table: Any, records: Any) -> None:
    if not isinstance(frame_table, list):
        _fail("E_NOT_AN_OBJECT", None,
              "quality report needs a frame-table list, got "
              f"{type(frame_table).__name__}")
    if not isinstance(records, list):
        _fail("E_NOT_AN_OBJECT", None,
              "quality report needs an observation list, got "
              f"{type(records).__name__}")
    for index, row in enumerate(frame_table):
        if not isinstance(row, FrameRecord):
            _fail("E_WRONG_TYPE", f"frame_table[{index}]",
                  f"expected FrameRecord, got {type(row).__name__}")
    for index, record in enumerate(records):
        if not isinstance(record, ObservationRecord):
            _fail("E_WRONG_TYPE", f"records[{index}]",
                  f"expected ObservationRecord, got {type(record).__name__}")


def _summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {"count": len(values), "min": min(values), "max": max(values),
            "mean": sum(values) / len(values)}


def record_fill_ratio(record: ObservationRecord) -> float | None:
    """Mask fill ratio for one record (shared with trajectory export)."""
    if record.bbox is None or record.mask_area_px is None:
        return None
    width = record.bbox[2] - record.bbox[0] + 1.0
    height = record.bbox[3] - record.bbox[1] + 1.0
    if width <= 0.0 or height <= 0.0:
        return None
    return record.mask_area_px / (width * height)


def build_quality_report(frame_table: list[FrameRecord],
                         records: list[ObservationRecord]) -> dict[str, Any]:
    """Derive the report-only quality facts for one object chain."""
    _check_chain(frame_table, records)
    universe = sorted({row.frame_index for row in frame_table})
    ordered = sorted(records, key=lambda record: record.frame_index)
    observed = sorted({record.frame_index for record in ordered})
    observed_set = set(observed)
    if observed:
        span_first, span_last = observed[0], observed[-1]
        gaps = [index for index in range(span_first, span_last + 1)
                if index not in observed_set]
    else:
        span_first, span_last, gaps = None, None, []
    jumps: list[dict[str, Any]] = []
    for earlier, later in zip(ordered, ordered[1:]):
        first_x, first_y = earlier.centroid_x_px, earlier.centroid_y_px
        second_x, second_y = later.centroid_x_px, later.centroid_y_px
        if None in (first_x, first_y, second_x, second_y):
            distance = None
        else:
            distance = math.hypot(second_x - first_x, second_y - first_y)
        jumps.append({
            "from_frame_index": earlier.frame_index,
            "to_frame_index": later.frame_index,
            "frame_delta": later.frame_index - earlier.frame_index,
            "centroid_distance_px": distance,
        })
    per_area: list[dict[str, Any]] = []
    areas: list[float] = []
    fills: list[float] = []
    per_confidence: list[dict[str, Any]] = []
    confidences: list[float] = []
    missing_confidence = 0
    by_id: dict[str, list[int]] = {}
    roles: set[str] = set()
    invalid_retained: list[dict[str, Any]] = []
    valid_count = 0
    for record in ordered:
        per_area.append({"frame_index": record.frame_index,
                         "mask_area_px": record.mask_area_px,
                         "bbox_fill_ratio": record_fill_ratio(record)})
        if record.mask_area_px is not None:
            areas.append(record.mask_area_px)
        fill = record_fill_ratio(record)
        if fill is not None:
            fills.append(fill)
        per_confidence.append({"frame_index": record.frame_index,
                               "confidence": record.confidence})
        if record.confidence is None:
            missing_confidence += 1
        else:
            confidences.append(record.confidence)
        by_id.setdefault(record.object_id, []).append(record.frame_index)
        roles.add(record.object_role.value)
        if record.valid:
            valid_count += 1
        else:
            invalid_retained.append({
                "frame_index": record.frame_index,
                "pts_seconds": record.pts_seconds,
                "warning_codes": [warning.code for warning in record.warnings],
                "has_geometry": (record.centroid_x_px is not None
                                 and record.centroid_y_px is not None
                                 and record.mask_area_px is not None),
            })
    return {
        "frame_table": {
            "size": len(frame_table),
            "valid_count": sum(1 for row in frame_table if row.valid),
            "invalid_count": sum(1 for row in frame_table if not row.valid),
            "null_pts_count": sum(1 for row in frame_table
                                  if row.pts_seconds is None),
            "frame_indices": universe,
        },
        "coverage": {
            "observed_frame_indices": observed,
            "observed_count": len(observed),
            "record_count": len(ordered),
            "valid_count": valid_count,
            "invalid_count": len(invalid_retained),
            "invalid_retained": invalid_retained,
        },
        "span": {"first_frame_index": span_first,
                 "last_frame_index": span_last},
        "gaps": {"missing_within_span": gaps, "count": len(gaps)},
        "jumps": jumps,
        "area_shape": {
            "per_frame": per_area,
            "mask_area_px": _summary(areas),
            "bbox_fill_ratio": _summary(fills),
        },
        "confidence": {
            "per_frame": per_confidence,
            "present_count": len(confidences),
            "missing_count": missing_confidence,
            **_summary(confidences),
        },
        "identity": {
            "object_ids": [{"object_id": object_id, "frame_indices": indices}
                           for object_id, indices in sorted(by_id.items())],
            "object_roles": sorted(roles),
            "id_switch_detectable": False,
            "note": ("object_id is caller-declared per file, so no ID-switch "
                     "verdict is derivable from one chain; per-id frame "
                     "lists above are the continuity facts"),
        },
    }


def export_quality_json(report: dict[str, Any]) -> bytes:
    """Serialize a quality report to canonical JSON bytes (byte-stable)."""
    if not isinstance(report, dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None,
            f"quality report must be a dict, got {type(report).__name__}")])
    return (json.dumps(report, sort_keys=True, indent=2,
                       ensure_ascii=True) + "\n").encode("utf-8")
