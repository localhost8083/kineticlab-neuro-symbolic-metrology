"""Fit points and angle series from live bob records (KL-7.1).

Builds the fitter input ``[{t_seconds, x_px, y_px}]`` from
``ObservationRecord``s: time is the record's SOURCE PTS (never
re-zeroed, never synthesized), position the mask-derived centroid.
Records unusable for fitting (invalid, null PTS, null centroid) are
EXCLUDED with their frame indices reported — never silently
dropped, never interpolated.

``angle_series`` renders the same thetas the fitter sees
(``atan2(x - pivot_x, y - pivot_y)`` about the arc-fit pivot,
unwrapped into continuity) for export and human inspection. The
formula duplicates the fitter's ten lines deliberately (the fitter
owns fitting; the assembly owns display), and a test cross-checks
both against the fit residuals plus the fitted curve, so any drift
fails loudly. The angle ZERO is arbitrary image +y: the M1 phase
parameter absorbs any fixed offset, so no upright-camera assumption
is needed — this reasoning is load-bearing and stated in the result
assumptions.

Valid-record PTS must be strictly increasing in source order
(``E_NON_MONOTONIC_PTS``); the gate never sorts, so a reordered
input rejects explicitly instead of fitting scrambled time.
"""

from __future__ import annotations

import math
from typing import Any

from kineticlab.contracts import ContractError, FieldError


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def build_fit_points(records: Any) -> dict[str, Any]:
    """Partition records into fitter points + explicit exclusions.

    Returns ``{"points": [{t_seconds, x_px, y_px, frame_index}],
    "excluded_frames": [int], "n_total": int}``. ``frame_index``
    rides along for auditability (stripped before the fitter call).
    Malformed record lists raise registered codes. Valid-record
    PTS must strictly increase in source order
    (``E_NON_MONOTONIC_PTS``) — never sorted, never silently
    accepted.
    """
    if not isinstance(records, (list, tuple)):
        _fail("E_WRONG_TYPE", "records",
              f"expected a record list, got {type(records).__name__}")
        raise AssertionError("unreachable")
    points: list[dict[str, Any]] = []
    excluded: list[int] = []
    previous_pts: float | None = None
    previous_frame: int | None = None
    for index, record in enumerate(records):
        field = f"records[{index}]"
        frame_index = getattr(record, "frame_index", None)
        valid = getattr(record, "valid", None)
        pts = getattr(record, "pts_seconds", None)
        cx = getattr(record, "centroid_x_px", None)
        cy = getattr(record, "centroid_y_px", None)
        if isinstance(frame_index, bool) \
                or not isinstance(frame_index, int):
            _fail("E_WRONG_TYPE", f"{field}.frame_index",
                  "frame_index must be an int")
        if not isinstance(valid, bool):
            _fail("E_WRONG_TYPE", f"{field}.valid",
                  "valid must be a boolean")
        usable = valid and pts is not None and cx is not None \
            and cy is not None
        if usable:
            for key, number in (("pts_seconds", pts),
                                ("centroid_x_px", cx),
                                ("centroid_y_px", cy)):
                if isinstance(number, bool) \
                        or not isinstance(number, (int, float)) \
                        or not math.isfinite(number):
                    usable = False
                    break
        if not usable:
            excluded.append(frame_index)
            continue
        assert pts is not None and cx is not None and cy is not None
        moment = float(pts)
        if previous_pts is not None and moment <= previous_pts:
            _fail("E_NON_MONOTONIC_PTS", f"{field}.pts_seconds",
                  f"valid-record PTS {moment} at frame {frame_index} "
                  f"does not exceed previous valid PTS {previous_pts} "
                  f"at frame {previous_frame}; source order kept, "
                  "never sorted")
        previous_pts = moment
        previous_frame = frame_index
        points.append({"t_seconds": moment,
                       "x_px": float(cx), "y_px": float(cy),
                       "frame_index": frame_index})
    return {"points": points, "excluded_frames": sorted(excluded),
            "n_total": len(records)}


def angle_series(points: Any, pivot_x: Any,
                 pivot_y: Any) -> list[dict[str, Any]]:
    """Render unwrapped thetas for fit points (display, not fitting).

    ``points`` are ``build_fit_points`` rows (``frame_index`` kept in
    the output). Output rows carry ``frame_index, pts_seconds,
    theta_rad, centroid_x_px, centroid_y_px`` in input order — the
    time key is ``pts_seconds`` (not the fitter's ``t_seconds``)
    because these rows feed the CSV contract, and the name must
    state the provenance: source PTS, never synthesized.
    """
    for name, pivot in (("pivot_x", pivot_x), ("pivot_y", pivot_y)):
        if isinstance(pivot, bool) or not isinstance(pivot, (int, float)) \
                or not math.isfinite(pivot):
            _fail("E_WRONG_TYPE", name,
                  "pivot coordinate must be a finite number")
    assert isinstance(pivot_x, (int, float))
    assert isinstance(pivot_y, (int, float))
    if not isinstance(points, (list, tuple)):
        _fail("E_WRONG_TYPE", "points",
              f"expected a point list, got {type(points).__name__}")
        raise AssertionError("unreachable")
    rows: list[dict[str, Any]] = []
    previous: float | None = None
    for index, point in enumerate(points):
        field = f"points[{index}]"
        if not isinstance(point, dict):
            _fail("E_WRONG_TYPE", field, "expected a point object")
        try:
            moment = float(point["t_seconds"])
            x = float(point["x_px"])
            y = float(point["y_px"])
            frame = point.get("frame_index")
        except (KeyError, TypeError, ValueError) as error:
            _fail("E_WRONG_TYPE", field,
                  f"point lacks numeric t/x/y: {error}")
            raise AssertionError("unreachable")
        if not all(math.isfinite(number) for number in (moment, x, y)):
            _fail("E_NON_FINITE", field, "point must be finite")
        theta = math.atan2(x - pivot_x, y - pivot_y)
        if previous is not None:
            while theta - previous > math.pi:
                theta -= 2.0 * math.pi
            while theta - previous <= -math.pi:
                theta += 2.0 * math.pi
        rows.append({"frame_index": frame, "pts_seconds": moment,
                     "theta_rad": theta, "centroid_x_px": x,
                     "centroid_y_px": y})
        previous = theta
    return rows
