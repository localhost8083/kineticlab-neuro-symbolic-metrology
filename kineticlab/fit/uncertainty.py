"""Seeded block-bootstrap intervals for the M1 frequency estimate (KL-10.11).

The reported ``g/L_eff`` used to carry ``fit_uncertainty_method=none``.
This module closes that gap the honest way: a SEEDED BLOCK BOOTSTRAP
over measured frames, refitting M1 per replicate, reporting percentile
intervals on omega and on ``g/L_eff = omega^2``.

Honesty framing (binding on every consumer):

- Resampling-based under the M1 model. The interval captures
  measurement NOISE, not M1 model-adequacy bias: M1 residuals are
  structured (lag-1 autocorrelation ~0.88), and that limitation
  stands unchanged wherever this interval is reported.
- Blocks preserve short-range time dependence. A bootstrap over
  IID residuals would be a lie on structured residuals, so the
  resampling unit is the FRAME RECORD ``(t_seconds, x_px, y_px)``
  in time order — never a residual, never a single shuffled point.
- NOT analytic. No standard error, no linearized propagation, no
  error bar on truth. Endpoints are percentiles of refits, and the
  method string says ``block_bootstrap`` everywhere it appears.
- The pivot is HELD FIXED at the run's assembled value, not
  resampled: geometry is not part of this resampling experiment.
  Each replicate flows through the SAME ``fit_m1`` entry point
  (same request template, same bounds/grid/termination), which
  re-derives theta from pixels internally — no theta-to-pixel
  reconstruction machinery exists or is needed.
- Fail-closed. Any replicate that does not converge, raises, or
  returns a non-finite/non-positive omega fails the WHOLE interval
  (``None``): a percentile interval over a convergence-selected
  subset would be selection-biased. Callers render ``None`` as
  null fields plus ``W_UNCERTAINTY_UNAVAILABLE``, unchanged.

Determinism: ``random.Random(seed)`` only; same seed + same
records + same platform = identical floats. Cross-platform libm
may drift the last ulp inside refits, so byte pins of these
intervals join the ``KL_CROSS_PLATFORM`` gate like every other
float pin.
"""

from __future__ import annotations

import math
import random
from typing import Any

from kineticlab.contracts import ContractError
from kineticlab.fit.m1 import fit_m1

METHOD = "block_bootstrap"
"""Locked method label; must stay a member of the contracts vocabulary."""

BOOTSTRAP_SEED = 20261103
"""Fixed seed, recorded in every output that carries an interval."""

N_BOOT = 800
"""Replicate count.

Measured on the pinned demo replay (234 points): one M1 refit
costs ~0.02 s and replicate costs are stable across resamples
(0.021-0.023 s, all converging), so 800 replicates add ~16-20 s —
the largest of {200, 400, 800} fitting the ~90 s budget with wide
margin. Full mode stays ~22 min total.
"""

# Main-fit request template, mirrored from the assembly success
# path (same estimator/termination by construction). MUST match
# kineticlab.assembly.build AMP_BOUNDS/OMEGA_BOUNDS/GRID_N_OMEGA/
# MAX_REFINE exactly — tests/test_uncertainty.py locks that
# equality (a direct import would invert the fit<-assembly layering).
_TEMPLATE_BOUNDS = {
    "amplitude_rad": [0.0, 2.0],
    "omega_per_s": [0.5, 8.0],
}
_TEMPLATE_GRID_N_OMEGA = 200
_TEMPLATE_MAX_REFINE = 200


def _m1_request(points: list[dict[str, float]], pivot_x: float,
                pivot_y: float) -> dict[str, Any]:
    return {
        "points": points,
        "pivot_x_px": pivot_x,
        "pivot_y_px": pivot_y,
        "bounds": {key: list(value)
                   for key, value in _TEMPLATE_BOUNDS.items()},
        "grid_n_omega": _TEMPLATE_GRID_N_OMEGA,
        "max_refine_iterations": _TEMPLATE_MAX_REFINE,
        "truth": None,
    }


def _as_records(frame_records: Any) -> list[tuple[float, float, float]] | None:
    """Finite (t, x, y) triples in input order, else None."""
    if not isinstance(frame_records, (list, tuple)):
        return None
    triples = []
    for record in frame_records:
        if not isinstance(record, dict):
            return None
        try:
            triple = (float(record["t_seconds"]),
                      float(record["x_px"]), float(record["y_px"]))
        except (KeyError, TypeError, ValueError):
            return None
        if any(isinstance(v, bool) or not math.isfinite(v)
               for v in triple):
            return None
        triples.append(triple)
    return triples


def period_block_frames(n_points: int, period_s: float,
                        span_s: float) -> int | None:
    """Block length: ceil(one measured period's worth of frames).

    The n frames span span_s seconds, so a period_s window holds
    n * period_s / span_s frames, rounded up. Unusable inputs
    (non-positive span, non-finite period) yield None.
    """
    if not isinstance(n_points, int) or isinstance(n_points, bool):
        return None
    if n_points < 2 or not math.isfinite(period_s) \
            or not math.isfinite(span_s):
        return None
    if period_s <= 0.0 or span_s <= 0.0:
        return None
    return max(1, math.ceil(n_points * period_s / span_s))


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile (numpy 'linear' method).

    Rank r = (pct/100)*(m-1) over the m sorted values; the result
    interpolates between ranks floor(r) and ceil(r).
    """
    rank = (pct / 100.0) * (len(sorted_vals) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_vals[low]
    frac = rank - low
    return sorted_vals[low] * (1.0 - frac) + sorted_vals[high] * frac


def _fit_omega(points: list[dict[str, float]], pivot_x: float,
               pivot_y: float) -> tuple[float, float, float] | None:
    """One M1 refit: (omega, period, g_over_l) or None unless converged."""
    try:
        result = fit_m1(_m1_request(points, pivot_x, pivot_y))
    except ContractError:
        # A replicate the estimator itself rejects fails the
        # interval closed. Anything else propagates: only
        # ContractError is an honest data verdict.
        return None
    diagnostics = result.get("diagnostics") \
        if isinstance(result, dict) else None
    if not isinstance(diagnostics, dict) \
            or diagnostics.get("converged") is not True:
        return None
    fitted = diagnostics.get("fitted") or {}
    omega = fitted.get("omega_per_s")
    period = fitted.get("period_s")
    fit = result.get("fit") or {}
    g_over_l = fit.get("g_over_l_per_s2")
    if any(isinstance(v, bool) or not isinstance(v, (int, float))
           or not math.isfinite(float(v))
           for v in (omega, period, g_over_l)):
        return None
    omega_f, period_f = float(omega), float(period)
    if omega_f <= 0.0 or period_f <= 0.0:
        return None
    return omega_f, period_f, float(g_over_l)


def omega_interval(frame_records: Any, *, pivot_x_px: float,
                   pivot_y_px: float, seed: int,
                   n_boot: int) -> dict[str, Any] | None:
    """Seeded circular block bootstrap interval on omega (KL-10.11).

    ``frame_records`` are the run's (t_seconds, x_px, y_px) frames;
    the pivot is held fixed. Returns the interval dict, or None
    when the bootstrap cannot run honestly (too few frames for two
    blocks, degenerate span, any replicate failing closed). ``None``
    means null fields plus ``W_UNCERTAINTY_UNAVAILABLE`` upstream.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"seed must be an int, got {seed!r}")
    if isinstance(n_boot, bool) or not isinstance(n_boot, int) \
            or n_boot < 1:
        raise ValueError(f"n_boot must be a positive int, got {n_boot!r}")
    triples = _as_records(frame_records)
    if triples is None or len(triples) < 2:
        return None
    if not isinstance(pivot_x_px, (int, float)) \
            or not isinstance(pivot_y_px, (int, float)):
        return None
    if isinstance(pivot_x_px, bool) or isinstance(pivot_y_px, bool):
        return None
    if not math.isfinite(pivot_x_px) or not math.isfinite(pivot_y_px):
        return None
    points = [{"t_seconds": t, "x_px": x, "y_px": y}
              for t, x, y in triples]
    # The point estimate is the SAME estimator on the full records
    # (bit-identical to the assembly main fit on the same input);
    # its period sets the block length.
    point = _fit_omega(points, float(pivot_x_px), float(pivot_y_px))
    if point is None:
        return None
    omega_point, period_s, g_point = point
    times = sorted(t for t, _, _ in triples)
    span = times[-1] - times[0]
    block = period_block_frames(len(triples), period_s, span)
    if block is None or len(triples) <= block:
        # Fewer than two blocks: resampling cannot vary honestly.
        return None
    n_blocks = math.ceil(len(triples) / block)
    rng = random.Random(seed)
    omegas = []
    for _ in range(n_boot):
        sample = []
        for _ in range(n_blocks):
            start = rng.randrange(len(triples))
            for offset in range(block):
                t, x, y = triples[(start + offset) % len(triples)]
                sample.append({"t_seconds": t, "x_px": x, "y_px": y})
                if len(sample) == len(triples):
                    break
            if len(sample) == len(triples):
                break
        replicate = _fit_omega(sample, float(pivot_x_px),
                               float(pivot_y_px))
        if replicate is None:
            return None
        omegas.append(replicate[0])
    ordered = sorted(omegas)
    low = _percentile(ordered, 2.5)
    high = _percentile(ordered, 97.5)
    # The contracts require the reported value to lie inside its
    # interval; a percentile pair that would exclude the point
    # estimate is extended to contain it, and the output says so
    # (extended_to_contain_point). Dormant on the pinned replay.
    extended = False
    if low > omega_point:
        low = omega_point
        extended = True
    if high < omega_point:
        high = omega_point
        extended = True
    # x -> x^2 is monotone on omega > 0 (gated above), so the g/L
    # interval is the mapped omega pair; the point is the
    # estimator's own g_over_l, not a recomputation.
    return {
        "method": METHOD,
        "seed": seed,
        "n_boot": n_boot,
        "block_frames": block,
        "extended_to_contain_point": extended,
        "omega_per_s": {"low": low, "point": omega_point,
                        "high": high},
        "g_over_l_eff_per_s2": {"low": low * low, "point": g_point,
                                "high": high * high},
    }
