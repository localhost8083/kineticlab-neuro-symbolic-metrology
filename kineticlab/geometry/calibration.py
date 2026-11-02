"""KL-6.1 card calibration: explicit dimensions, assumptions, bounds.

Builds a validated ``calibration.v1`` record from oriented card
rectangles plus caller-supplied user inputs — this module hardcodes
no card size (the contract forbids it): U-1 dimensions, U-1
assumption flags, U-3 depths, and video dimensions all arrive as
arguments and are validated, never defaulted.

Scale design (KL-6.2): isotropic ``scale_mm_per_px`` = mean of the
width/long-side and height/short-side ratios over CLEAN frames
(non-occluded; occlusion distorts masks with bob-shaped holes, so
clean-frame selection is method, not cherry-picking — the split is
reported). The near-frontal view makes both ratios estimate one
scale; their spread is reported as ``anisotropy`` data.
``plane_transform`` stays null with a stated reason: PCA corners are
unlabeled, so no corner correspondence to physical card corners
exists to constrain a homography — isotropic scale is the honest
fallback, and the exactly-one-scale rule is satisfied.

Assumptions (KL-6.3): same-plane and camera-fixed ride the record
(valid records state both); tilt, truncation, blur, and length ride
the report with value-or-null-plus-reason — truncation is MEASURED
(corners inside frame?), the rest stay null with reasons except
length (null: U-2 not provided, g/L_eff only). The U-3 bound
(offset/distance, ~1.7%) is stated in the report, in a record
warning detail, and anywhere scale is used — as an ASSUMPTION, never
as an uncertainty (``scale_uncertainty_mm_per_px`` stays null with a
``W_UNCERTAINTY_UNAVAILABLE`` warning stating exactly that).

M-3e limitation (documented, never corrected): the hollow ball
distributes mass away from its center and the string adds
distributed mass and flexure, while M1/M2 assume a point mass on a
massless rigid rod — fitted g/L_eff absorbs these into an effective
length. Carried in the report's ``model_limitations`` field and this
docstring; any future gravity claim must state it alongside the U-3
bound (master-plan rule). No new warning code: the record carries
only existing codes.

Stdlib only. No network. Deterministic.
"""

from __future__ import annotations

import math
from typing import Any

from kineticlab.contracts import (
    CalibrationRecord,
    ContractError,
    FieldError,
)

MODEL_LIMITATIONS = (
    "M-3e hollow-ball/string-mass bias (stated limitation, no correction "
    "applied): the M1/M2 pendulum models assume a point mass on a "
    "massless rigid rod; the real bob is hollow (mass distributed in a "
    "shell about its center) and the string contributes distributed "
    "mass and flexure. Fitted g/L_eff absorbs these into an effective "
    "length. Any future gravity claim must state this limitation "
    "alongside the U-3 depth-offset bound.",
)
"""Model limitations carried wherever calibration output travels."""


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _positive_float(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("E_WRONG_TYPE", field,
              f"expected a number, got {type(value).__name__}")
        raise AssertionError("unreachable")
    if not math.isfinite(value) or value <= 0.0:
        _fail("E_OUT_OF_RANGE", field,
              f"expected a positive finite number, got {value!r}")
        raise AssertionError("unreachable")
    return float(value)


def _strict_bool_or_null(value: Any, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        _fail("E_WRONG_TYPE", field,
              f"expected a boolean or null, got {type(value).__name__}")
        raise AssertionError("unreachable")
    return value


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def build_calibration(*, card_width_mm: Any, card_height_mm: Any,
                      oriented: Any, clean_frames: Any,
                      same_plane: Any, camera_fixed: Any,
                      depth_offset_mm: Any, camera_distance_mm: Any,
                      video_width: Any, video_height: Any,
                      provenance: Any) -> tuple[CalibrationRecord, dict[str, Any]]:
    """Build a validated calibration record + assumptions report.

    ``oriented`` is ``[(frame_index, oriented_rectangle(...)), ...]``;
    ``clean_frames`` the non-occluded frame set used for medians.
    Card size, assumptions, U-3 depths, video size, and provenance
    are caller-supplied (U-1/U-3 inputs) and strictly validated.
    Returns ``(record, report)``; the record always passes
    ``CalibrationRecord.from_dict`` (valid or explicitly invalid). ``valid``
    means structurally usable scale with both assumptions assessed; it does
    not certify true assumptions or physical accuracy. A false U-3
    same-plane assumption can therefore remain valid while g/L measurement
    proceeds with the depth offset explicitly stated.
    """
    width_mm = _positive_float(card_width_mm, "card_width_mm")
    height_mm = _positive_float(card_height_mm, "card_height_mm")
    offset_mm = _positive_float(depth_offset_mm, "depth_offset_mm")
    distance_mm = _positive_float(camera_distance_mm, "camera_distance_mm")
    same_plane_flag = _strict_bool_or_null(same_plane, "same_plane")
    camera_fixed_flag = _strict_bool_or_null(camera_fixed, "camera_fixed")
    for name, size in (("video_width", video_width),
                       ("video_height", video_height)):
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
            _fail("E_WRONG_TYPE" if not isinstance(size, int)
                  or isinstance(size, bool) else "E_OUT_OF_RANGE", name,
                  f"expected a positive int, got {size!r}")
    assert isinstance(video_width, int) and isinstance(video_height, int)
    if not isinstance(clean_frames, (set, frozenset, list, tuple)):
        _fail("E_WRONG_TYPE", "clean_frames",
              f"expected a frame collection, got {type(clean_frames).__name__}")
        raise AssertionError("unreachable")
    clean = set(clean_frames)
    for frame in clean:
        if isinstance(frame, bool) or not isinstance(frame, int):
            _fail("E_WRONG_TYPE", "clean_frames",
                  "frame indices must be ints")
    if not isinstance(oriented, (list, tuple)):
        _fail("E_WRONG_TYPE", "oriented",
              f"expected a list, got {type(oriented).__name__}")
        raise AssertionError("unreachable")
    fitted: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(oriented):
        field = f"oriented[{index}]"
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            _fail("E_WRONG_TYPE", field,
                  "expected a (frame_index, rectangle) pair")
        frame_index, rect = item
        if isinstance(frame_index, bool) \
                or not isinstance(frame_index, int):
            _fail("E_WRONG_TYPE", f"{field}[0]",
                  "frame_index must be an int")
        if not isinstance(rect, dict) or rect.get("fitted") is not True:
            continue
        for key in ("long_side", "short_side", "corners"):
            if key not in rect:
                _fail("E_MISSING_FIELD", f"{field}[1].{key}",
                      "fitted rectangle lacks geometry")
        fitted.append((frame_index, rect))
    usable = [(frame, rect) for frame, rect in fitted if frame in clean]
    if not usable:
        _fail("E_INCOHERENT_VALUE", "clean_frames",
              "no fitted rectangles on clean frames: calibration refused")
        raise AssertionError("unreachable")
    long_med = _median([rect["long_side"] for _, rect in usable])
    short_med = _median([rect["short_side"] for _, rect in usable])
    if long_med <= 0.0 or short_med <= 0.0:
        _fail("E_INCOHERENT_VALUE", "oriented",
              "median sides must be positive")
    corners_med = [
        [_median([rect["corners"][corner][axis] for _, rect in usable])
         for axis in (0, 1)]
        for corner in range(4)]
    ratio_long = width_mm / long_med
    ratio_short = height_mm / short_med
    scale = (ratio_long + ratio_short) / 2.0
    anisotropy = abs(ratio_long - ratio_short) / scale
    aspect_measured = long_med / short_med
    aspect_nominal = width_mm / height_mm
    bound_fraction = offset_mm / distance_mm
    bound_percent = bound_fraction * 100.0
    inside = 0
    total = 0
    for _, rect in usable:
        for corner in rect["corners"]:
            total += 1
            if 0.0 <= corner[0] < video_width \
                    and 0.0 <= corner[1] < video_height:
                inside += 1
    assessed = same_plane_flag is not None and camera_fixed_flag is not None
    bound_text = (f"U-3 depth-offset scale bound {bound_percent:.1f}% "
                  f"({offset_mm} mm offset over {distance_mm} mm camera "
                  f"distance, tape estimate) stated as an assumption "
                  f"wherever this scale is used")
    record_dict: dict[str, Any] = {
        "schema_version": "calibration.v1",
        "reference_type": "iso_id1_confirmed",
        "reference_dimensions_mm": {"width_mm": width_mm,
                                    "height_mm": height_mm},
        "dimension_source": "user_confirmed",
        "observed_corners_px": corners_med,
        "observed_oriented_dimensions_px": {"long_side_px": long_med,
                                            "short_side_px": short_med},
        "scale_mm_per_px": scale,
        "plane_transform": None,
        "scale_uncertainty_mm_per_px": None,
        "same_plane_assumption": same_plane_flag,
        "camera_fixed_assumption": camera_fixed_flag,
        "valid": assessed,
        "warnings": [
            {"code": "W_UNCERTAINTY_UNAVAILABLE",
             "detail": "no scale uncertainty estimated; the U-3 bound "
                       "is a stated assumption, not an uncertainty"},
            {"code": "W_ASSUMPTION_UNVERIFIED",
             "detail": bound_text},
        ],
        "provenance": provenance,
    }
    record = CalibrationRecord.from_dict(record_dict)
    report = {
        "n_usable_frames": len(usable),
        "clean_frame_count": len(clean),
        "median_long_side_px": long_med,
        "median_short_side_px": short_med,
        "scale_sides_mm_per_px": {"width_over_long": ratio_long,
                                  "height_over_short": ratio_short},
        "scale_mm_per_px": scale,
        "anisotropy": anisotropy,
        "aspect_measured": aspect_measured,
        "aspect_nominal": aspect_nominal,
        "plane_transform": None,
        "plane_transform_reason": "corners are unlabeled PCA corners "
                                  "with no correspondence to physical "
                                  "card corners; isotropic scale is the "
                                  "honest fallback",
        "u3_bound": {"depth_offset_mm": offset_mm,
                     "camera_distance_mm": distance_mm,
                     "bound_fraction": bound_fraction,
                     "bound_percent": bound_percent,
                     "statement": bound_text},
        "assumptions": {
            "same_plane": {
                "value": same_plane_flag,
                "basis": "U-1 near-coplanar with ~25 mm depth offset "
                         "(U-3); offset carried in u3_bound",
            },
            "camera_fixed": {
                "value": camera_fixed_flag,
                "basis": "U-1 camera fixed yes; see M-3b corner-jitter "
                         "diagnostic for supporting evidence",
            },
            "tilt": {
                "value": None,
                "reason": "single-view isotropic scale cannot separate "
                          "out-of-plane tilt from scale; apparent "
                          "aspect reported as data only",
            },
            "truncation": {
                "value": inside == total,
                "detail": f"{inside}/{total} clean-frame corners inside "
                          f"{video_width}x{video_height}",
            },
            "blur": {
                "value": None,
                "reason": "no per-frame optical blur metric exists; "
                          "geometric elongation/area proxy reported "
                          "as data only (M-3d)",
            },
            "length": {
                "value": None,
                "reason": "U-2 pivot length not provided; g/L_eff "
                          "only, gravity stays null",
            },
        },
        "model_limitations": list(MODEL_LIMITATIONS),
        "record_valid": record.valid,
    }
    return record, report
