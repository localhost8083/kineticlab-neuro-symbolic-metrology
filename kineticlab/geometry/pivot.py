"""Arc-fit pivot localization for an out-of-frame pivot (M-3a).

The pivot never appears in the clip, so its position is estimated by
fitting a circle to the bob-centre arc (algebraic Kasa fit: closed
form via 3x3 normal equations, partial-pivot Gaussian elimination,
fixed operation order — deterministic, stdlib only). This SUPERSEDES
the M-2 narrative demo's labeled placeholder pivot (swing-midpoint x
+ 1D radius-variance search, residual 4.627 px): history is not
rewritten, but all P-006 work uses this fit.

Shallow arcs condition circle fits poorly (Fable's unconstrained
Kasa hit a degenerate pivot and was discarded before any call), so
the fit reports its own conditioning as data: radius, angular span
of the arc around the fitted center, full per-frame radial
residuals, and the top-10 residual frames joined with their mask
areas (blur-proximity data, never a blur attribution). Singular or
non-physical solutions are honest failure states (``fitted:
False`` + reason), never crashes, never fabricated pivots.
Malformed inputs raise ``ContractError`` with registered codes.

The fitted radius is a PIXEL length. It becomes a metric length
only through card scale (KL-6.1) with the U-3 bound and the M-3e
limitation stated alongside — never silently.
"""

from __future__ import annotations

import math
from typing import Any

from kineticlab.contracts import ContractError, FieldError

TOP_RESIDUAL_COUNT = 10
"""Descriptive rank width: top-N residual frames, never a verdict."""


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _read_points(points: Any) -> list[tuple[float, float]]:
    if not isinstance(points, (list, tuple)):
        _fail("E_WRONG_TYPE", "points",
              f"expected a point list, got {type(points).__name__}")
        raise AssertionError("unreachable")
    clean: list[tuple[float, float]] = []
    for index, point in enumerate(points):
        field = f"points[{index}]"
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            _fail("E_WRONG_TYPE", field,
                  f"expected an [x, y] pair, got {point!r}")
        pair: list[float] = []
        for axis, value in enumerate(point):
            if isinstance(value, bool) \
                    or not isinstance(value, (int, float)):
                _fail("E_WRONG_TYPE", f"{field}[{axis}]",
                      f"expected a number, got {type(value).__name__}")
            if not math.isfinite(value):
                _fail("E_NON_FINITE", f"{field}[{axis}]",
                      "point coordinate is not finite")
            pair.append(float(value))
        clean.append((pair[0], pair[1]))
    return clean


SINGULARITY_GUARD = 1e-12
"""Relative singularity guard for the normal equations.

Exact-collinear clouds cancel to ~ulp-level pivots rather than
exact zeros, so singularity is tested relative to the matrix scale.
Well-conditioned arcs pivot far above this; degenerate clouds fall
below it and report fitted:false. A numerical guard, not a verdict.
"""


def _solve_3x3(matrix: list[list[float]],
               vector: list[float]) -> list[float] | None:
    # Partial-pivot Gaussian elimination; None on (near-)singularity.
    scale = max(abs(entry) for row in matrix for entry in row)
    floor = SINGULARITY_GUARD * scale if scale > 0.0 else 0.0
    rows = [row[:] + [value] for row, value in zip(matrix, vector)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda r: abs(rows[r][column]))
        if abs(rows[pivot][column]) <= floor:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for row in range(column + 1, 3):
            factor = rows[row][column] / rows[column][column]
            for tail in range(column, 4):
                rows[row][tail] -= factor * rows[column][tail]
    solution = [0.0, 0.0, 0.0]
    for row in (2, 1, 0):
        if abs(rows[row][row]) <= floor:
            return None
        solution[row] = (rows[row][3] - sum(
            rows[row][tail] * solution[tail] for tail in range(row + 1, 3))
        ) / rows[row][row]
    return solution


def _angular_span(angles: list[float]) -> float:
    # Circular span = full circle minus the largest angular gap.
    ordered = sorted(angles)
    gaps = [ordered[index + 1] - ordered[index]
            for index in range(len(ordered) - 1)]
    gaps.append(ordered[0] + 2.0 * math.pi - ordered[-1])
    return 2.0 * math.pi - max(gaps)


def fit_arc(points: Any,
            areas: Any = None) -> dict[str, Any]:
    """Fit a circle to arc points (Kasa closed form; see module docstring).

    ``points`` is ``[(x, y), ...]`` in frame pixels; ``areas`` is an
    optional parallel list of mask areas joined onto the residual
    ranking as blur-proximity data (length must match ``points``).
    Returns the fitted circle + residual diagnostics, or
    ``{"fitted": False, "reason", "n"}`` for degenerate clouds.
    """
    clean = _read_points(points)
    joined: list[float] | None = None
    if areas is not None:
        if not isinstance(areas, (list, tuple)) \
                or len(areas) != len(clean):
            _fail("E_WRONG_TYPE", "areas",
                  "areas must parallel points exactly")
        joined = []
        for index, value in enumerate(areas):
            if isinstance(value, bool) \
                    or not isinstance(value, (int, float)) \
                    or not math.isfinite(value):
                _fail("E_WRONG_TYPE", f"areas[{index}]",
                      "area must be a finite number")
            joined.append(float(value))
    if len(set(clean)) < 3:
        return {"fitted": False,
                "reason": "fewer than 3 distinct points",
                "n": len(clean)}
    # Normal equations for x^2 + y^2 + a*x + b*y + c = 0.
    sums = {"x": 0.0, "y": 0.0, "xx": 0.0, "xy": 0.0, "yy": 0.0,
            "xxx": 0.0, "xxy": 0.0, "xyy": 0.0, "yyy": 0.0}
    for x, y in clean:
        sums["x"] += x
        sums["y"] += y
        sums["xx"] += x * x
        sums["xy"] += x * y
        sums["yy"] += y * y
        sums["xxx"] += x * x * x
        sums["xxy"] += x * x * y
        sums["xyy"] += x * y * y
        sums["yyy"] += y * y * y
    matrix = [[sums["xx"], sums["xy"], sums["x"]],
              [sums["xy"], sums["yy"], sums["y"]],
              [sums["x"], sums["y"], float(len(clean))]]
    vector = [-(sums["xxx"] + sums["xyy"]),
              -(sums["xxy"] + sums["yyy"]),
              -(sums["xx"] + sums["yy"])]
    solved = _solve_3x3(matrix, vector)
    if solved is None:
        return {"fitted": False, "reason": "singular normal equations "
                "(collinear or degenerate cloud)", "n": len(clean)}
    a, b, c = solved
    center = (-a / 2.0, -b / 2.0)
    radius_squared = (a * a + b * b) / 4.0 - c
    if not math.isfinite(radius_squared) or radius_squared <= 0.0:
        return {"fitted": False, "reason": "non-physical radius",
                "n": len(clean)}
    radius = math.sqrt(radius_squared)
    if not math.isfinite(center[0]) or not math.isfinite(center[1]) \
            or not math.isfinite(radius):
        return {"fitted": False, "reason": "non-finite circle",
                "n": len(clean)}
    residuals = [abs(math.hypot(x - center[0], y - center[1]) - radius)
                 for x, y in clean]
    angles = [math.atan2(y - center[1], x - center[0]) for x, y in clean]
    ranked = sorted(range(len(clean)), key=lambda i: residuals[i],
                    reverse=True)
    median_area: float | None = None
    top: list[dict[str, Any]] = []
    if joined is not None:
        ordered_areas = sorted(joined)
        middle = len(ordered_areas) // 2
        if len(ordered_areas) % 2:
            median_area = ordered_areas[middle]
        else:
            median_area = (ordered_areas[middle - 1]
                           + ordered_areas[middle]) / 2.0
    for rank in ranked[:TOP_RESIDUAL_COUNT]:
        entry: dict[str, Any] = {"index": rank,
                                 "radial_residual_px": residuals[rank]}
        if joined is not None:
            entry["mask_area_px"] = joined[rank]
            entry["median_area_px"] = median_area
        top.append(entry)
    mean_residual = sum(residuals) / len(residuals)
    return {
        "fitted": True,
        "n": len(clean),
        "center_px": [center[0], center[1]],
        "radius_px": radius,
        "radial_residuals_px": residuals,
        "mean_abs_residual_px": mean_residual,
        "max_abs_residual_px": max(residuals),
        "max_residual_index": max(range(len(clean)),
                                  key=lambda i: residuals[i]),
        "arc_span_rad": _angular_span(angles),
        "top_residual_frames": top,
    }
