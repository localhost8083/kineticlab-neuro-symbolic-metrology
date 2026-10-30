"""Oriented rectangles from mask pixels via PCA (P-006, KL-6.2).

A PCA rectangle summarizes a set-bit cloud by its principal axes:
the major axis direction is the orientation angle, and the
min/max projections onto both axes give the side lengths and the
four corners. Eigendecomposition is closed-form for symmetric 2x2
(no iteration, no randomness, fixed operation order), so identical
pixels always yield identical bytes on a platform. The major-axis
sign is canonicalized (positive x, else positive y) so the angle is
stable across runs.

Why PCA and not minimum-area rotating calipers: the card masks are
dense near-rectangles with ragged model edges; PCA summarizes the
whole cloud instead of hinging on extreme pixels, and it is twenty
lines of exact arithmetic instead of a hull + caliper state machine.
The tradeoff is documented: on ragged edges the PCA box need not be
minimum-area, and corner positions inherit edge noise — which is
exactly what the jitter diagnostic (M-3b) measures.

Degenerate clouds (fewer than 3 distinct pixels) are honest failure
states (``fitted: False`` + reason), never crashes, never fabricated
corners. Malformed inputs (non-lists, non-numbers, non-finite)
raise ``ContractError`` with registered codes.

Output corners follow the calibration contract: clockwise as seen
in the image (y down), starting at the corner nearest the image
origin.
"""

from __future__ import annotations

import math
from typing import Any

from kineticlab.contracts import ContractError, FieldError


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


def _major_axis(cxx: float, cxy: float, cyy: float) -> tuple[float, float]:
    # Closed-form principal eigenvector of [[cxx, cxy], [cxy, cyy]]:
    # (lam - cyy, cxy) is an eigenvector for the major eigenvalue lam
    # unless cxy == 0, in which case the axes are already principal.
    # Sign canonicalized to (+x, else +y) for run-to-run stability.
    trace = cxx + cyy
    disc = math.sqrt(max((cxx - cyy) ** 2 + 4.0 * cxy * cxy, 0.0))
    major = trace / 2.0 + disc / 2.0
    if cxy != 0.0:
        vec = (major - cyy, cxy)
    elif cxx >= cyy:
        vec = (1.0, 0.0)
    else:
        vec = (0.0, 1.0)
    norm = math.hypot(vec[0], vec[1])
    assert norm > 0.0
    dx, dy = vec[0] / norm, vec[1] / norm
    if dx < 0.0 or (dx == 0.0 and dy < 0.0):
        dx, dy = -dx, -dy
    return dx, dy


def _order_corners(corners: list[list[float]]) -> list[list[float]]:
    # Contract order: clockwise as seen (y down) from the corner
    # nearest the image origin. Circular order comes from angles
    # around the rectangle CENTER (origin angles misorder off-origin
    # rectangles); in y-down coordinates visual clockwise is
    # increasing atan2(dy, dx). Then rotate so the origin-nearest
    # corner leads. Ties broken by x, then y (deterministic;
    # unreachable on real rectangles).
    cx = sum(c[0] for c in corners) / 4.0
    cy = sum(c[1] for c in corners) / 4.0
    scored = sorted(
        ((math.atan2(c[1] - cy, c[0] - cx), c[0], c[1], c)
         for c in corners))
    ordered = [entry[3] for entry in scored]
    first = min(range(4),
                key=lambda i: (ordered[i][0] ** 2 + ordered[i][1] ** 2,
                               ordered[i][0], ordered[i][1]))
    return ordered[first:] + ordered[:first]


def oriented_rectangle(points: Any) -> dict[str, Any]:
    """Fit a PCA rectangle to pixel coordinates (see module docstring).

    Returns ``{"fitted": True, "n", "center", "angle_rad",
    "long_side", "short_side", "corners"}`` with JSON-native floats,
    or ``{"fitted": False, "reason", "n"}`` for degenerate clouds.
    ``angle_rad`` is the major-axis direction in (-pi, pi] with the
    canonicalized sign above. ``long_side >= short_side`` always.
    """
    clean = _read_points(points)
    distinct = set(clean)
    if len(distinct) < 3:
        return {"fitted": False,
                "reason": "fewer than 3 distinct pixels",
                "n": len(clean)}
    n = float(len(clean))
    mean_x = sum(p[0] for p in clean) / n
    mean_y = sum(p[1] for p in clean) / n
    cxx = sum((p[0] - mean_x) ** 2 for p in clean) / n
    cxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in clean) / n
    cyy = sum((p[1] - mean_y) ** 2 for p in clean) / n
    if cxx == 0.0 and cxy == 0.0 and cyy == 0.0:
        return {"fitted": False, "reason": "zero variance cloud",
                "n": len(clean)}
    dx, dy = _major_axis(cxx, cxy, cyy)
    # Minor axis: major rotated -90 degrees in y-down orientation.
    ex, ey = -dy, dx
    projections = [((p[0] - mean_x) * dx + (p[1] - mean_y) * dy,
                    (p[0] - mean_x) * ex + (p[1] - mean_y) * ey)
                   for p in clean]
    u_min = min(p[0] for p in projections)
    u_max = max(p[0] for p in projections)
    v_min = min(p[1] for p in projections)
    v_max = max(p[1] for p in projections)
    long_side = u_max - u_min
    short_side = v_max - v_min
    corners = [[mean_x + u * dx + v * ex, mean_y + u * dy + v * ey]
               for u, v in ((u_min, v_min), (u_max, v_min),
                            (u_max, v_max), (u_min, v_max))]
    return {
        "fitted": True,
        "n": len(clean),
        "center": [mean_x, mean_y],
        "angle_rad": math.atan2(dy, dx),
        "long_side": long_side,
        "short_side": short_side,
        "corners": _order_corners(corners),
    }


def oriented_rectangle_from_raster(raster: Any, width: int,
                                   height: int, x1: float,
                                   y1: float) -> dict[str, Any]:
    """Fused PCA rectangle straight from a decoded raster (KL-9.2 item 4).

    Bit-identical outputs to ``oriented_rectangle`` over the same
    mask's ``set_pixels()``: same row-major pixel order, same float
    operations in the same sequence (proven by
    ``test_fused_pca_matches_classic_on_live_masks``). Skips only
    redundant work: no per-pixel validation (bytes indexing yields
    ints by construction), no materialized pixel list, no full-set
    distinct tracking (early-exits at 3), fused accumulation
    passes. Internal fast path for verified decodes — malformed
    inputs are the caller's bug.

    Summation subtlety: builtin ``sum()`` over floats uses
    Neumaier-compensated arithmetic (verified empirically against
    this interpreter), so the classic path's means and covariances
    are compensated sums — a naive ``+=`` loop diverges in the
    last ulp. Each accumulator below replicates Neumaier exactly
    (``>=`` branch, single end fold), term for term in the same
    order, which is why the outputs stay bit-identical.
    """
    # Pass 1: count + compensated float sums in set_pixels()
    # order, distinct tracking with early exit (the verdict matches
    # len(set()) < 3).
    count = 0
    sum_x = 0.0
    comp_x = 0.0
    sum_y = 0.0
    comp_y = 0.0
    seen: set | None = set()
    for row in range(height):
        base = row * width
        for col in range(width):
            if not raster[base + col]:
                continue
            pixel_x = x1 + col
            pixel_y = y1 + row
            count += 1
            trial = sum_x + pixel_x
            if abs(sum_x) >= abs(pixel_x):
                comp_x += (sum_x - trial) + pixel_x
            else:
                comp_x += (pixel_x - trial) + sum_x
            sum_x = trial
            trial = sum_y + pixel_y
            if abs(sum_y) >= abs(pixel_y):
                comp_y += (sum_y - trial) + pixel_y
            else:
                comp_y += (pixel_y - trial) + sum_y
            sum_y = trial
            if seen is not None:
                seen.add((pixel_x, pixel_y))
                if len(seen) >= 3:
                    seen = None
    if seen is not None:
        return {"fitted": False,
                "reason": "fewer than 3 distinct pixels",
                "n": count}
    total = float(count)
    mean_x = (sum_x + comp_x) / total
    mean_y = (sum_y + comp_y) / total
    # Pass 2: covariance sums, same terms/order/compensation.
    sum_xx = 0.0
    comp_xx = 0.0
    sum_xy = 0.0
    comp_xy = 0.0
    sum_yy = 0.0
    comp_yy = 0.0
    for row in range(height):
        base = row * width
        for col in range(width):
            if not raster[base + col]:
                continue
            rel_x = x1 + col - mean_x
            rel_y = y1 + row - mean_y
            term_xx = rel_x ** 2
            term_xy = rel_x * rel_y
            term_yy = rel_y ** 2
            trial = sum_xx + term_xx
            if abs(sum_xx) >= abs(term_xx):
                comp_xx += (sum_xx - trial) + term_xx
            else:
                comp_xx += (term_xx - trial) + sum_xx
            sum_xx = trial
            trial = sum_xy + term_xy
            if abs(sum_xy) >= abs(term_xy):
                comp_xy += (sum_xy - trial) + term_xy
            else:
                comp_xy += (term_xy - trial) + sum_xy
            sum_xy = trial
            trial = sum_yy + term_yy
            if abs(sum_yy) >= abs(term_yy):
                comp_yy += (sum_yy - trial) + term_yy
            else:
                comp_yy += (term_yy - trial) + sum_yy
            sum_yy = trial
    cxx = (sum_xx + comp_xx) / total
    cxy = (sum_xy + comp_xy) / total
    cyy = (sum_yy + comp_yy) / total
    if cxx == 0.0 and cxy == 0.0 and cyy == 0.0:
        return {"fitted": False, "reason": "zero variance cloud",
                "n": count}
    dx, dy = _major_axis(cxx, cxy, cyy)
    # Minor axis: major rotated -90 degrees in y-down orientation.
    ex, ey = -dy, dx
    # Pass 3: projection extremes. Same per-pixel values as the
    # classic list; min/max over an identical set is identical.
    u_min = u_max = v_min = v_max = None
    for row in range(height):
        base = row * width
        for col in range(width):
            if not raster[base + col]:
                continue
            rel_x = x1 + col - mean_x
            rel_y = y1 + row - mean_y
            proj_u = rel_x * dx + rel_y * dy
            proj_v = rel_x * ex + rel_y * ey
            if u_min is None or proj_u < u_min:
                u_min = proj_u
            if u_max is None or proj_u > u_max:
                u_max = proj_u
            if v_min is None or proj_v < v_min:
                v_min = proj_v
            if v_max is None or proj_v > v_max:
                v_max = proj_v
    assert u_min is not None and u_max is not None
    assert v_min is not None and v_max is not None
    long_side = u_max - u_min
    short_side = v_max - v_min
    corners = [[mean_x + u * dx + v * ex, mean_y + u * dy + v * ey]
               for u, v in ((u_min, v_min), (u_max, v_min),
                            (u_max, v_max), (u_min, v_max))]
    return {
        "fitted": True,
        "n": count,
        "center": [mean_x, mean_y],
        "angle_rad": math.atan2(dy, dx),
        "long_side": long_side,
        "short_side": short_side,
        "corners": _order_corners(corners),
    }
