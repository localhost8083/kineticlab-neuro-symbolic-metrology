"""Camera-stability, blur-proxy, and occlusion diagnostics (M-3b/d).

- Corner jitter (M-3b): per-frame displacement of the oriented card
  corners as a camera-stability diagnostic. CONNECTION TO THE
  ADVISORY MODULE (stated, not wired): large sustained jitter would
  disconfirm the fixed-camera assumption the setup-review
  ``camera_appears_static`` flag speaks to — but this module neither
  reads nor writes advisory state; the advisory layer stays untouched
  per the P-006 lock. A human (or a later stage) compares the two.
- Blur proxy (M-3d): GEOMETRIC ONLY — bbox elongation and mask area
  relative to the chain median. The pipeline has NO per-frame
  optical-blur metric (no PSF estimate, no edge-spread fit); this
  diagnostic measures shape variation across the swing and LABELS
  exactly that. It must never be cited as a blur measurement.
- Overlap frames: bob/card bbox intersection per frame, recomputed
  from records (M-1's 117-frame finding is a cross-check, never an
  input).

All outputs are pure descriptive data (KL-5.4 pattern): counts,
min/max/mean, ranked frame lists. No thresholds, no verdicts, no
good/bad labels. Malformed inputs raise registered codes.
"""

from __future__ import annotations

import math
from typing import Any

from kineticlab.contracts import ContractError, FieldError

STATIONARY_BANDS_PX = (1.0, 2.0)
"""Descriptive stillness bins for jitter (reported, never judged)."""

TOP_RANK_COUNT = 10
"""Descriptive rank width for elongation lists, never a verdict."""


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _corners_list(value: Any) -> list[tuple[int, list[list[float]]]]:
    if not isinstance(value, (list, tuple)):
        _fail("E_WRONG_TYPE", "corners_by_frame",
              f"expected a list, got {type(value).__name__}")
        raise AssertionError("unreachable")
    clean: list[tuple[int, list[list[float]]]] = []
    for index, item in enumerate(value):
        field = f"corners_by_frame[{index}]"
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            _fail("E_WRONG_TYPE", field,
                  "expected a (frame_index, corners) pair")
        frame_index, corners = item
        if isinstance(frame_index, bool) \
                or not isinstance(frame_index, int):
            _fail("E_WRONG_TYPE", f"{field}[0]",
                  "frame_index must be an int")
        if not isinstance(corners, (list, tuple)) or len(corners) != 4:
            _fail("E_WRONG_TYPE", f"{field}[1]",
                  "corners must be 4 [x, y] pairs")
        parsed: list[list[float]] = []
        for corner_no, corner in enumerate(corners):
            if not isinstance(corner, (list, tuple)) or len(corner) != 2:
                _fail("E_WRONG_TYPE", f"{field}[1][{corner_no}]",
                      "expected an [x, y] pair")
            pair = []
            for axis, number in enumerate(corner):
                if isinstance(number, bool) \
                        or not isinstance(number, (int, float)) \
                        or not math.isfinite(number):
                    _fail("E_WRONG_TYPE", f"{field}[1][{corner_no}][{axis}]",
                          "corner coordinate must be a finite number")
                pair.append(float(number))
            parsed.append(pair)
        clean.append((frame_index, parsed))
    return clean


def corner_jitter(corners_by_frame: Any) -> dict[str, Any]:
    """Per-frame corner displacement stats (see module docstring).

    Input is ``[(frame_index, [4 [x, y] corners]), ...]`` in any
    order; only consecutive (delta == 1) pairs form displacements,
    measured as the max corner move. Returns pair counts, min/max/
    mean, stillness-bin counts, and the max pair identity.
    """
    clean = sorted(_corners_list(corners_by_frame),
                   key=lambda item: item[0])
    pairs: list[dict[str, Any]] = []
    for earlier, later in zip(clean, clean[1:]):
        if later[0] - earlier[0] != 1:
            continue
        move = max(math.hypot(b[0] - a[0], b[1] - a[1])
                   for a, b in zip(earlier[1], later[1]))
        pairs.append({"from_frame_index": earlier[0],
                      "to_frame_index": later[0],
                      "max_corner_move_px": move})
    moves = [pair["max_corner_move_px"] for pair in pairs]
    if not moves:
        return {"n_pairs": 0, "pairs": [],
                "min_px": None, "max_px": None, "mean_px": None,
                "stationary_counts": {str(band): 0
                                      for band in STATIONARY_BANDS_PX},
                "max_pair": None}
    worst = max(pairs, key=lambda pair: pair["max_corner_move_px"])
    return {
        "n_pairs": len(pairs),
        "pairs": pairs,
        "min_px": min(moves),
        "max_px": max(moves),
        "mean_px": sum(moves) / len(moves),
        "stationary_counts": {
            str(band): sum(1 for move in moves if move <= band)
            for band in STATIONARY_BANDS_PX},
        "max_pair": {"from_frame_index": worst["from_frame_index"],
                     "to_frame_index": worst["to_frame_index"],
                     "max_corner_move_px": worst["max_corner_move_px"]},
    }


def _bbox_list(records: Any, field: str) -> list[tuple[int, list[float]]]:
    if not isinstance(records, (list, tuple)):
        _fail("E_WRONG_TYPE", field,
              f"expected a record list, got {type(records).__name__}")
        raise AssertionError("unreachable")
    clean: list[tuple[int, list[float]]] = []
    for index, record in enumerate(records):
        frame_index = getattr(record, "frame_index", None)
        bbox = getattr(record, "bbox", None)
        if isinstance(frame_index, bool) \
                or not isinstance(frame_index, int):
            _fail("E_WRONG_TYPE", f"{field}[{index}].frame_index",
                  "frame_index must be an int")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            _fail("E_WRONG_TYPE", f"{field}[{index}].bbox",
                  "bbox must be 4 numbers")
        numbers = []
        for axis, value in enumerate(bbox):
            if isinstance(value, bool) \
                    or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                _fail("E_WRONG_TYPE", f"{field}[{index}].bbox[{axis}]",
                      "bbox corner must be a finite number")
            numbers.append(float(value))
        clean.append((frame_index, numbers))
    return clean


def overlap_frames(bob_records: Any, card_records: Any) -> list[int]:
    """Frame indices where the bob and card bboxes intersect (area > 0).

    Recomputed from records every call; M-1's measured 117-frame list
    is an independent cross-check, never an input.
    """
    bob = dict(_bbox_list(bob_records, "bob_records"))
    card = dict(_bbox_list(card_records, "card_records"))
    frames: list[int] = []
    for frame in sorted(set(bob) & set(card)):
        a, b = bob[frame], card[frame]
        width = min(a[2], b[2]) - max(a[0], b[0])
        height = min(a[3], b[3]) - max(a[1], b[1])
        if width > 0.0 and height > 0.0:
            frames.append(frame)
    return frames


def blur_proxy(records: Any) -> dict[str, Any]:
    """Geometric elongation/area proxy (NOT an optical blur measurement).

    Per record: bbox elongation (long side / short side) and mask
    area relative to the chain median area. Returns per-frame rows,
    min/max/mean of both series, and the top-10 elongation frames.
    Records need ``frame_index``, ``bbox``, and ``mask_area_px``.
    """
    boxes = _bbox_list(records, "records")
    areas: list[float | None] = []
    for index, record in enumerate(records):
        area = getattr(record, "mask_area_px", None)
        if area is not None and (isinstance(area, bool)
                                 or not isinstance(area, (int, float))
                                 or not math.isfinite(area)):
            _fail("E_WRONG_TYPE", f"records[{index}].mask_area_px",
                  "mask area must be a finite number or null")
        areas.append(None if area is None else float(area))
    known = sorted(area for area in areas if area is not None)
    median: float | None = None
    if known:
        middle = len(known) // 2
        median = known[middle] if len(known) % 2 else \
            (known[middle - 1] + known[middle]) / 2.0
    rows: list[dict[str, Any]] = []
    for (frame_index, bbox), area in zip(boxes, areas):
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        if width <= 0.0 or height <= 0.0:
            elongation: float | None = None
        else:
            elongation = max(width, height) / min(width, height)
        rows.append({
            "frame_index": frame_index,
            "bbox_elongation": elongation,
            "area_over_median": (area / median
                                 if area is not None and median else None),
        })
    elongations = [row["bbox_elongation"] for row in rows
                   if row["bbox_elongation"] is not None]
    ranked = sorted(
        (row for row in rows if row["bbox_elongation"] is not None),
        key=lambda row: row["bbox_elongation"], reverse=True)
    return {
        "n": len(rows),
        "median_area_px": median,
        "per_frame": rows,
        "elongation": {
            "min": min(elongations) if elongations else None,
            "max": max(elongations) if elongations else None,
            "mean": (sum(elongations) / len(elongations)
                     if elongations else None),
        },
        "top_elongation_frames": [
            {"frame_index": row["frame_index"],
             "bbox_elongation": row["bbox_elongation"],
             "area_over_median": row["area_over_median"]}
            for row in ranked[:TOP_RANK_COUNT]],
    }
