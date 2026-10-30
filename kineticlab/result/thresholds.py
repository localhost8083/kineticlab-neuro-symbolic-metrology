"""Rationale-backed quality thresholds over KL-4.1 reports (KL-4.2).

First judgment layer: classifies the REPORT-ONLY facts from
``quality.build_quality_report`` into per-item flags plus a chain
verdict. Classification lives in report data (booleans + reasons) —
never as taxonomy codes, which stay reserved for contract failures.

Threshold table (every constant named here with its rationale; no
magic numbers, no physics claims — gravity is P-005):

- ``JUMP_MAX_DIAGONALS_PER_STEP = 1.0`` — own-footprint rule. A
  rigid tracked object cannot move more than its own full extent in
  one frame step without leaving its predicted gate, so a centroid
  displacement above one bbox diagonal per frame-delta step reads as
  mistrack/teleport. The limit scales linearly with frame_delta
  (``limit = 1.0 * diagonal * frame_delta``) and uses the larger of
  the two endpoint diagonals (inclusive spans, same convention as
  the fill ratio). Needs record bboxes as context; without them the
  jump dimension is honestly not assessable.
- ``FILL_MIN = 0.5`` — box-as-bounds coherence. The protocol says
  the mask carries its box as bounds; a mask covering under half
  its box contradicts that (wrong object, mistrack, decode fault).
  For reference a tight circle fills ~0.785, so 0.5 sits well below
  any coherent shape.
- ``FILL_MAX = 1.0`` — exact geometric bound, not a tuning choice:
  mask area cannot exceed its own box; above 1.0 is contradiction.
- ``AREA_MIN_PX = 100.0`` — coarse near-zero guard (10x10
  equivalent). Below this a mask rests on fewer samples than a
  coarse patch; flagged for review, not rejected. Documented as
  coarse: the sensitive collapse detector is the step ratio below.
- ``AREA_MAX_STEP_RATIO = 4.0`` — area continuity. Consecutive
  mask areas differing by more than 4x mean the linear extent
  doubled (or halved) in one step — implausible for a rigid
  tracked object without an event (occlusion, mistrack). Ratio is
  max/min over the pair; a non-positive step endpoint flags
  immediately. Single-record chains assess the floor only (no step
  exists for continuity, so that half is vacuously unflagged).
- Confidence: NO value threshold (judging confidence values needs
  calibration, out of scope — documented absence). Only exact
  absence is flagged: records with null confidence are counted
  and named.

Missing dimension in the input report -> ``assessable: false``
with a reason, never a default pass. Malformed inputs (non-dict
report, wrong-typed items) reuse registered codes: the report
itself never raises for being empty or ugly.
"""

from __future__ import annotations

import math
from typing import Any

from kineticlab.contracts import (
    ContractError,
    FieldError,
    ObservationRecord,
)

JUMP_MAX_DIAGONALS_PER_STEP = 1.0
FILL_MIN = 0.5
FILL_MAX = 1.0
AREA_MIN_PX = 100.0
AREA_MAX_STEP_RATIO = 4.0


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _require_section(report: dict[str, Any], name: str) -> Any | None:
    section = report.get(name)
    if section is None:
        return None
    if not isinstance(section, dict):
        _fail("E_WRONG_TYPE", name,
              f"report section {name!r} must be a dict, got "
              f"{type(section).__name__}")
    return section


def _require_items(section: dict[str, Any], section_name: str,
                   key: str) -> list[Any]:
    items = section.get(key)
    if items is None:
        return []
    if not isinstance(items, list):
        _fail("E_WRONG_TYPE", f"{section_name}.{key}",
              f"expected a list, got {type(items).__name__}")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            _fail("E_WRONG_TYPE", f"{section_name}.{key}[{index}]",
                  f"expected a dict, got {type(item).__name__}")
    return items


def _number(value: Any, where: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("E_WRONG_TYPE", where,
              f"expected a number or null, got {type(value).__name__}")
    return float(value)


def _frame_id(value: Any, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail("E_WRONG_TYPE", where,
              f"expected a frame index int, got {type(value).__name__}")
    return value


def _bbox_diagonal(record: ObservationRecord) -> float | None:
    if record.bbox is None:
        return None
    width = record.bbox[2] - record.bbox[0] + 1.0
    height = record.bbox[3] - record.bbox[1] + 1.0
    if width <= 0.0 or height <= 0.0:
        return None
    return math.hypot(width, height)


def _assess_jumps(report: dict[str, Any],
                  diagonals: dict[int, float | None],
                  have_records: bool) -> dict[str, Any]:
    jumps = report.get("jumps")
    if jumps is None:
        return {"assessable": False, "reason": "report lacks jumps dimension",
                "flags": [], "flagged_count": 0}
    if not isinstance(jumps, list):
        _fail("E_WRONG_TYPE", "jumps",
              f"expected a list, got {type(jumps).__name__}")
    if not have_records:
        return {"assessable": False,
                "reason": "jump plausibility needs record bboxes as context",
                "flags": [], "flagged_count": 0}
    flags: list[dict[str, Any]] = []
    for index, item in enumerate(jumps):
        where = f"jumps[{index}]"
        if not isinstance(item, dict):
            _fail("E_WRONG_TYPE", where,
                  f"expected a dict, got {type(item).__name__}")
        dist = _number(item.get("centroid_distance_px"),
                       f"{where}.centroid_distance_px")
        delta = item.get("frame_delta")
        if not isinstance(delta, int) or isinstance(delta, bool):
            _fail("E_WRONG_TYPE", f"{where}.frame_delta",
                  f"expected an int, got {type(delta).__name__}")
        ends = tuple(
            diagonals.get(_frame_id(item.get(end), f"{where}.{end}"), None)
            for end in ("from_frame_index", "to_frame_index"))
        flagged: bool | None
        reason: str | None
        if dist is None:
            flagged, reason = None, "centroid distance null; cannot assess"
        elif ends[0] is None or ends[1] is None:
            flagged, reason = None, "endpoint bbox unavailable; cannot assess"
        else:
            limit = (JUMP_MAX_DIAGONALS_PER_STEP * max(ends[0], ends[1])
                     * max(delta, 0))
            if dist > limit:
                flagged = True
                reason = (f"distance {dist} exceeds plausibility limit "
                          f"{limit} ({JUMP_MAX_DIAGONALS_PER_STEP} diagonals "
                          f"x {delta} step(s))")
            else:
                flagged, reason = False, None
        flags.append({"from_frame_index": item.get("from_frame_index"),
                      "to_frame_index": item.get("to_frame_index"),
                      "flagged": flagged, "reason": reason})
    return {"assessable": True, "reason": None, "flags": flags,
            "flagged_count": sum(1 for flag in flags if flag["flagged"])}


def _assess_area_fill(per_frame: list[Any]) -> tuple[dict[str, Any],
                                                    dict[str, Any]]:
    area_flags: list[dict[str, Any]] = []
    fill_flags: list[dict[str, Any]] = []
    previous: tuple[int, float] | None = None
    for index, item in enumerate(per_frame):
        where = f"area_shape.per_frame[{index}]"
        area = _number(item.get("mask_area_px"), f"{where}.mask_area_px")
        fill = _number(item.get("bbox_fill_ratio"),
                       f"{where}.bbox_fill_ratio")
        frame = _frame_id(item.get("frame_index"), f"{where}.frame_index")
        if area is None:
            area_flag: dict[str, Any] = {
                "frame_index": frame, "flagged": None,
                "reason": "mask area null; cannot assess"}
        elif area < AREA_MIN_PX:
            area_flag = {"frame_index": frame, "flagged": True,
                         "reason": f"area {area} below near-zero floor "
                                   f"{AREA_MIN_PX}"}
        elif previous is not None and previous[1] > 0.0 and area > 0.0:
            ratio = max(area, previous[1]) / min(area, previous[1])
            if ratio > AREA_MAX_STEP_RATIO:
                area_flag = {
                    "frame_index": frame, "flagged": True,
                    "reason": (f"area step ratio {ratio} from frame "
                               f"{previous[0]} exceeds {AREA_MAX_STEP_RATIO}")}
            else:
                area_flag = {"frame_index": frame, "flagged": False,
                             "reason": None}
        elif previous is not None and (previous[1] <= 0.0 or area <= 0.0):
            area_flag = {"frame_index": frame, "flagged": True,
                         "reason": "non-positive area step endpoint"}
        else:
            area_flag = {"frame_index": frame, "flagged": False,
                         "reason": None}
        if area is not None:
            previous = (frame, area)
        if fill is None:
            fill_flag: dict[str, Any] = {
                "frame_index": frame, "flagged": None,
                "reason": "fill ratio null; cannot assess"}
        elif fill < FILL_MIN:
            fill_flag = {"frame_index": frame, "flagged": True,
                         "reason": f"fill ratio {fill} below minimum "
                                   f"{FILL_MIN}"}
        elif fill > FILL_MAX:
            fill_flag = {"frame_index": frame, "flagged": True,
                         "reason": f"fill ratio {fill} exceeds box area"}
        else:
            fill_flag = {"frame_index": frame, "flagged": False,
                         "reason": None}
        area_flags.append(area_flag)
        fill_flags.append(fill_flag)
    pack = lambda flags: {"assessable": True, "reason": None, "flags": flags,
                          "flagged_count": sum(1 for flag in flags
                                               if flag["flagged"])}
    return pack(area_flags), pack(fill_flags)


def _assess_confidence(section: dict[str, Any] | None) -> dict[str, Any]:
    if section is None:
        return {"assessable": False,
                "reason": "report lacks confidence dimension",
                "flags": [], "flagged_count": 0}
    items = _require_items(section, "confidence", "per_frame")
    flags: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        where = f"confidence.per_frame[{index}]"
        value = item.get("confidence")
        if value is not None:
            _number(value, f"{where}.confidence")
        flags.append({
            "frame_index": _frame_id(item.get("frame_index"),
                                     f"{where}.frame_index"),
            "flagged": value is None,
            "reason": ("confidence null; absence flagged, values unjudged"
                       if value is None else None),
        })
    return {"assessable": True, "reason": None, "flags": flags,
            "flagged_count": sum(1 for flag in flags if flag["flagged"])}


def assess_chain(report: dict[str, Any],
                 records: list[ObservationRecord] = ()) -> dict[str, Any]:
    """Apply rationale-backed thresholds to a KL-4.1 report.

    ``records`` supplies bbox context for jump plausibility (same
    chain the report was built from); omit it and the jump dimension
    reports honestly unassessable. Returns plain JSON-native data:
    per-dimension flags plus a chain verdict (assessable / flagged /
    fit_worthy) with reasons. Never raises for ugly data — only for
    malformed inputs, with registered codes.
    """
    if not isinstance(report, dict):
        _fail("E_NOT_AN_OBJECT", None,
              f"assessment needs a report dict, got {type(report).__name__}")
    if not isinstance(records, (list, tuple)):
        _fail("E_NOT_AN_OBJECT", None,
              "assessment needs a record list for context, got "
              f"{type(records).__name__}")
    for index, record in enumerate(records):
        if not isinstance(record, ObservationRecord):
            _fail("E_WRONG_TYPE", f"records[{index}]",
                  f"expected ObservationRecord, got {type(record).__name__}")
    diagonals: dict[int, float | None] = {}
    for record in records:
        diagonals.setdefault(record.frame_index, _bbox_diagonal(record))
    jumps = _assess_jumps(report, diagonals, bool(records))
    area_section = _require_section(report, "area_shape")
    if area_section is None:
        missing = {"assessable": False,
                   "reason": "report lacks area_shape dimension",
                   "flags": [], "flagged_count": 0}
        area, fill = missing, dict(missing)
    else:
        area, fill = _assess_area_fill(
            _require_items(area_section, "area_shape", "per_frame"))
    confidence = _assess_confidence(_require_section(report, "confidence"))
    coverage = _require_section(report, "coverage")
    retained: list[Any] = []
    coverage_ok = True
    coverage_reason: str | None = None
    if coverage is None:
        coverage_ok = False
        coverage_reason = "report lacks coverage dimension"
    else:
        retained = coverage.get("invalid_retained", [])
        if not isinstance(retained, list):
            _fail("E_WRONG_TYPE", "coverage.invalid_retained",
                  f"expected a list, got {type(retained).__name__}")
    assessable = (coverage_ok and jumps["assessable"] and area["assessable"]
                  and fill["assessable"] and confidence["assessable"])
    reasons: list[str] = []
    if not coverage_ok:
        reasons.append(f"not assessable: {coverage_reason}")
    for name, dimension in (("jumps", jumps), ("area", area),
                            ("fill ratio", fill),
                            ("confidence", confidence)):
        if not dimension["assessable"]:
            reasons.append(f"{name} not assessable: {dimension['reason']}")
        elif dimension["flagged_count"]:
            reasons.append(f"{dimension['flagged_count']} {name} flag(s)")
    if retained:
        reasons.append(f"{len(retained)} retained invalid row(s)")
    frames: dict[int, dict[str, Any]] = {}
    for entry in area["flags"]:
        frames[entry["frame_index"]] = {
            "frame_index": entry["frame_index"],
            "jump_flagged": None, "area_flagged": entry["flagged"],
            "fill_flagged": None}
    for entry in fill["flags"]:
        frames.setdefault(entry["frame_index"], {
            "frame_index": entry["frame_index"], "jump_flagged": None,
            "area_flagged": None, "fill_flagged": None})
        frames[entry["frame_index"]]["fill_flagged"] = entry["flagged"]
    for entry in jumps["flags"]:
        frames.setdefault(entry["to_frame_index"], {
            "frame_index": entry["to_frame_index"], "jump_flagged": None,
            "area_flagged": None, "fill_flagged": None})
        frames[entry["to_frame_index"]]["jump_flagged"] = entry["flagged"]
    rows = [frames[key] for key in sorted(frames)]
    for row in rows:
        row["flagged_any"] = any(row[column] is True for column in
                                 ("jump_flagged", "area_flagged",
                                  "fill_flagged"))
    flagged = (any(row["flagged_any"] for row in rows) or bool(retained)
               or not rows)
    if not rows:
        reasons.append("chain holds no records")
    return {
        "assessable": assessable,
        "flagged": flagged,
        "fit_worthy": assessable and not flagged,
        "reasons": reasons,
        "dimensions": {"jumps": jumps, "area": area, "fill": fill,
                       "confidence": confidence},
        "frames": rows,
    }
