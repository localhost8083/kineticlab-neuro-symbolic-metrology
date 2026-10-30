"""Bounded M1 fit over synthetic angle data with honest diagnostics (KL-5.2).

Fits the closed-form small-angle M1 curve ``theta(t) = A*cos(omega*t
+ phi)`` to observed pixel points from ``kineticlab.fit.synthetic``
trajectories. This module FITS; it never generates. M2 stays out
(KL-5.3); uncertainty machinery stays out (KL-5.4); tolerance
verdicts stay out (KL-5.4 owns the recovery matrix).

TEST convention (read before interpreting any number): the input
points are synthetic fixture data, the pivot is caller-supplied
known TEST geometry (the calibrated-camera analogue), time is in
seconds, and ``g_over_l`` is reported as ``omega^2`` — a TEST
recovery of the identifiable ``g/L_eff`` quantity, never a physical
gravity claim. ``length_px`` never enters the fit (it cancels in
the angle conversion); no ``g`` in m/s^2 is produced from synthetic
data. The ``TEST_CONVENTION_NOTE`` string is embedded in every
result and every JSON export.

Angle recovery: each observed point ``(t, x, y)`` becomes an angle
via ``theta = atan2(x - pivot_x, y - pivot_y)`` (the exact inverse
of the synthetic projection; scale-free), then the series is
unwrapped (successive differences folded into ``(-pi, pi]``) so
swings beyond ``+-pi`` stay continuous. Points are stably sorted by
time first; duplicate timestamps are allowed (both fitted). The
generative ``theta_rad`` values a trajectory may carry are NEVER
read — the fitter sees only ``(t_seconds, x_px, y_px)``, exactly
what a pixel-space estimator would see. Observation weights are
uniform (unweighted least squares), stated explicitly.

Optimizer: separable least squares over a deterministic omega grid
plus golden-section refinement. For fixed omega the model is linear
in ``C = A*cos(phi)``, ``S = -A*sin(phi)`` and solved in closed
form through the 2x2 normal equations, so the only search dimension
is omega:

1. Evaluate the sum-of-squared-residuals (SSR) at ``grid_n_omega``
   uniformly spaced omega values covering the caller's omega box
   (endpoints included, ascending order, first-minimum wins ties).
2. Bracket the grid best with its grid neighbors (clamped to the
   box) and run golden-section refinement for at most
   ``max_refine_iterations`` evaluations, stopping early when the
   bracket width drops below ``OMEGA_REFINE_TOL``.
3. Solve the linear pair at the final omega, wrap phase to
   ``(-pi, pi]``, project amplitude onto the caller's amplitude box
   (radial rescale preserving phase; hits recorded, never hidden),
   and evaluate all downstream values (residuals, rmse, initial
   conditions) at the REPORTED ``(A, omega, phi)``.

Determinism contract: fixed grid, fixed evaluation order, no wall
clock, no randomness — same request = identical result bytes on a
given platform/CPython+libm build. Cross-platform float
bit-identity is NOT promised (libm ``sin``/``cos``/``atan2`` may
differ in the last ulp); determinism tests pin exact bytes on the
verified platform and note the caveat.

Known limitations (documented, not hidden):

- Frequency recovery needs the omega grid to sample the true SSR
  valley: sparse/short data narrows the valley and admits aliases,
  so grid density is the caller's responsibility. (The
  singularity guard incidentally keeps the 4-point micro test on
  the true valley by rejecting near-collinear spurious designs;
  that robustness is welcome but not relied upon.)
- Unwrap anchors the absolute 2π branch to the first sample, which
  is correct only when ``|theta(t0)| <= pi``; planted amplitudes
  beyond ``+-pi`` are out of scope for KL-5.2.
- Amplitude box enforcement is radial projection of the
  unconstrained separable solution (exact only for isotropic
  designs); bound hits are flagged so projected values are never
  mistaken for interior optima.

Bounds (caller-supplied; no defaults anywhere in the request):

- ``amplitude_rad`` box ``[lo, hi]`` with ``0 <= lo <= hi``;
  violations of the fitted amplitude are projected radially and
  recorded in ``bound_hits`` with the unclamped value. Radial
  projection is exact only for isotropic designs; the hit flag
  exists so no consumer mistakes a projected value for an
  interior optimum.
- ``omega_per_s`` box ``[lo, hi]`` with ``0 < lo <= hi``; a grid
  best at an endpoint raises the corresponding
  ``omega_grid_best_at_*_edge`` flag (a grid method detects edge
  optima; it does not land on bounds).
- Phase is circular and unbounded by design (reported wrapped to
  ``(-pi, pi]``); it carries no bound diagnostics.

``converged`` is true if and only if the final omega bracket width
fell below ``OMEGA_REFINE_TOL`` — a stationarity certificate, not
an accuracy claim. Anything else is an HONEST NON-CONVERGED STATE
(``converged: false`` + ``termination_reason``, never a crash,
never silent garbage):

- ``flat_objective_unidentifiable``: every observed angle is
  exactly 0.0 (null SSR is exactly zero), so no frequency is
  identifiable; reported parameters are the degenerate iterate
  (A = 0, first grid omega), residuals unclaimed (null).
- ``degenerate_design``: the 2x2 normal equations are singular at
  every grid omega (e.g. all timestamps identical); reported
  omega is the lower grid bound, residuals unclaimed.
- ``refine_budget_exhausted``: the bracket was still wider than
  tolerance when the caller's iteration budget ran out; reported
  parameters are the best omega evaluated so far, residuals
  unclaimed.

Non-converged results still validate as ``fit.v1`` (the contract
allows ``converged: false`` with null residuals and null initial
conditions); the ``fit`` record always carries the optimizer's
actual state, never invented values.

Output: ``fit_m1(request)`` returns ``{"fitter", "model",
"test_convention_note", "fit", "diagnostics"}``. ``fit`` is a valid
``fit.v1`` dict (M1 parameters exactly ``{"g_over_l": omega^2}`` in
``1/s^2`` with the identical echo in ``g_over_l_per_s2``; converged
fits derive ``initial_conditions`` as ``theta0 = A*cos(phi)``,
``omega0 = -A*omega*sin(phi)`` because the contract requires stated
initial conditions for converged fits; gravity stays null without
an independent length — never produced here). ``diagnostics`` is
plain JSON-native data (no new schema version): fitted
``amplitude_rad``/``omega_per_s``/``phase_rad``/``period_s``,
``bound_hits``, omega edge flags, ``termination_reason``,
``grid_evaluations``/``refine_iterations``/objective trace
(null/baseline, grid-best, refine-best, final), per-sample radian
residuals or null, ``weights: "uniform"``, a midpoint-singularity
fallback flag (normally false), and parameter errors vs the
caller's ``truth`` (null when truth is null — unknown stays
null).

Named constants carry KL-4.2-style written rationale:

- ``OMEGA_REFINE_TOL = 1e-9`` rad/s: at estimator test scales
  (omega ~ 1-10 rad/s) this is <= 1e-9 relative, 1000x below the
  tightest recovery tolerance, so termination never limits
  reported recovery; it certifies stationarity only.
- ``MIN_POINTS = 3``: three curve parameters are fitted, so three
  points are the algebraic floor (dof = n - 3 >= 0).
- ``GRID_N_MIN = 2``: two grid values (the box endpoints) are the
  coarsest meaningful grid; refinement still brackets the box.
- ``RECOVERY_TOL_*``: clean-case recovery tolerances used by the
  KL-5.2 tests (1e-6 on amplitude/omega/phase), set 1000x or more
  above the measured clean-fit errors (~1e-10) and 1000x or more
  below broken-fit errors (~0.1+), with measured headroom recorded
  in the test module — a pass means genuine recovery, neither
  optimizer noise nor a vacuous bound. KL-5.4 owns all verdict
  tolerances beyond these.

Failure map (registered codes only, full error collection with
nested paths such as ``bounds.omega_per_s`` or ``points[2].x_px``):

- non-dict request / non-dict ``bounds``/``truth`` / non-list
  ``points`` / malformed point or bound entries -> ``E_WRONG_TYPE``.
- unknown request keys -> ``E_UNEXPECTED_FIELD``; absent keys ->
  ``E_MISSING_FIELD``; null where a value is required ->
  ``E_NULL_NOT_ALLOWED``.
- NaN/inf numerics -> ``E_NON_FINITE``; fewer than ``MIN_POINTS``
  points, ``grid_n_omega`` below ``GRID_N_MIN``, negative
  ``max_refine_iterations``, negative amplitude bound or truth
  amplitude, non-positive omega bound or truth omega ->
  ``E_OUT_OF_RANGE``.
- bound pair inverted (``lo > hi``) -> ``E_INCOHERENT_VALUE``.

Exports follow the ``result`` style: ``export_fit_json`` emits
canonical bytes (sorted keys, indent 2, ASCII-only, single trailing
LF) and ``parse_fit_json`` inverts them (the ``fit`` part
re-validated through ``FitRecord.from_dict`` codes-preserved with
the ``fit.`` path prefix; diagnostics pass through as data). No CSV
export: the task does not call for one.
"""

from __future__ import annotations

import json
import math
from typing import Any

from kineticlab.contracts import (
    ContractError,
    FieldError,
    FitRecord,
)
from kineticlab.fit.synthetic import JSON_INDENT

FITTER_NAME = "kineticlab.fit.m1"
MODEL_ID = "M1"

TEST_CONVENTION_NOTE = (
    "TEST RECOVERY — input points are synthetic fixture data; g_over_l "
    "is omega^2 under the synthetic test convention (t in seconds, "
    "planted omega); not a physical measurement, no gravity claim."
)

SOLVER_NAME = "closed_form_small_angle"
OPTIMIZER_NAME = "separable_omega_grid_linear_lsq_golden_refine_v1"

OMEGA_REFINE_TOL = 1e-9
"""Golden-section stop width in rad/s (stationarity certificate)."""

DESIGN_SINGULAR_REL_TOL = 1e-12
"""Singularity floor for the 2x2 normal-equation determinant.

A determinant at/below 1e-12 of the diagonal product means the
cos/sin design is collinear to ~12 digits (condition number >=
~1e12), so fewer than ~4 digits would survive the 2x2 inverse —
inversion noise, not a solution. Such omegas report an infinite
objective instead of garbage coefficients. Healthy designs sit at
~0.1-1.0 on this relative scale; exactly-collinear sampling
(e.g. identical timestamps at every omega) scores ~0 and takes
the ``degenerate_design`` path honestly.
"""

MIN_POINTS = 3
"""Algebraic floor: three curve parameters need three points."""

GRID_N_MIN = 2
"""Coarsest meaningful omega grid (box endpoints, refinement brackets)."""

MAX_POINTS = 100_000
"""Mirrors the synthetic generator bound; keeps fits bounded."""

RECOVERY_TOL_AMPLITUDE_RAD = 1e-6
RECOVERY_TOL_OMEGA_PER_S = 1e-6
RECOVERY_TOL_PHASE_RAD = 1e-6
"""Clean-case recovery tolerances (rationale in module docstring).

All three sit 1000x or more above the measured clean-fit errors
(~1e-10; recorded in tests/test_fit_m1.py) and 1000x or more below
broken-fit errors (~0.1+ for a wrong branch or missed frequency),
so a pass means genuine recovery. Noisy data is NOT tolerance-gated
in KL-5.2 (KL-5.4 owns verdicts); these constants gate clean
recovery only.
"""

REQUEST_KEYS = frozenset({
    "points",
    "pivot_x_px",
    "pivot_y_px",
    "bounds",
    "grid_n_omega",
    "max_refine_iterations",
    "truth",
})

POINT_KEYS = frozenset({"t_seconds", "x_px", "y_px"})

BOUNDS_KEYS = frozenset({"amplitude_rad", "omega_per_s"})

TRUTH_KEYS = frozenset({
    "amplitude_rad",
    "angular_frequency_per_s",
    "phase_rad",
})

TERMINATION_TOLERANCE_MET = "refine_tolerance_met"
TERMINATION_BUDGET_EXHAUSTED = "refine_budget_exhausted"
TERMINATION_FLAT_OBJECTIVE = "flat_objective_unidentifiable"
TERMINATION_DEGENERATE_DESIGN = "degenerate_design"


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_float(value: Any) -> bool:
    return (_is_int(value) or isinstance(value, float))


class _Request:
    """Validated fit request (full error collection, then one raise)."""

    def __init__(self, request: Any) -> None:
        self.errors: list[FieldError] = []
        self.request = request
        self.points: list[tuple[float, float, float]] = []
        self.pivot_x = 0.0
        self.pivot_y = 0.0
        self.amp_lo = 0.0
        self.amp_hi = 0.0
        self.omega_lo = 0.0
        self.omega_hi = 0.0
        self.grid_n = 0
        self.max_refine = 0
        self.truth: dict[str, float] | None = None

    def fail(self, code: str, field: str | None, message: str) -> None:
        self.errors.append(FieldError(code, field, message))

    def read_float(self, data: dict, key: str, where: str, *,
                   minimum: float | None = None,
                   strict_min: bool = False) -> float | None:
        field = f"{where}.{key}" if where else key
        if key not in data:
            return None
        value = data[key]
        if value is None:
            self.fail("E_NULL_NOT_ALLOWED", field,
                      "value is null where a value is required")
            return None
        if not _is_float(value):
            self.fail("E_WRONG_TYPE", field,
                      f"expected a number, got {type(value).__name__}")
            return None
        number = float(value)
        if not math.isfinite(number):
            self.fail("E_NON_FINITE", field,
                      "value must be finite (NaN/inf rejected)")
            return None
        if minimum is not None and (number < minimum
                                    or (strict_min and number == minimum)):
            bound = f"> {minimum}" if strict_min else f">= {minimum}"
            self.fail("E_OUT_OF_RANGE", field,
                      f"value {number!r} is outside the locked range ({bound})")
            return None
        return number

    def read_int(self, data: dict, key: str, where: str, *,
                 minimum: int | None = None) -> int | None:
        field = f"{where}.{key}" if where else key
        if key not in data:
            return None
        value = data[key]
        if value is None:
            self.fail("E_NULL_NOT_ALLOWED", field,
                      "value is null where a value is required")
            return None
        if not _is_int(value):
            self.fail("E_WRONG_TYPE", field,
                      f"expected an int, got {type(value).__name__}")
            return None
        if minimum is not None and value < minimum:
            self.fail("E_OUT_OF_RANGE", field,
                      f"value {value!r} is outside the locked range "
                      f"(>= {minimum})")
            return None
        return value

    def check_keys(self, data: Any, expected: frozenset[str],
                   where: str) -> dict | None:
        if not isinstance(data, dict):
            self.fail("E_WRONG_TYPE", where or None,
                      f"expected an object, got {type(data).__name__}")
            return None
        for key in sorted(set(data) - expected):
            self.fail("E_UNEXPECTED_FIELD",
                      f"{where}.{key}" if where else key,
                      f"unknown key {key!r}")
        for key in sorted(expected - set(data)):
            self.fail("E_MISSING_FIELD",
                      f"{where}.{key}" if where else key,
                      f"required key {key!r} is absent")
        return data

    def validate(self) -> None:
        if not isinstance(self.request, dict):
            self.fail("E_WRONG_TYPE", None,
                      "fit request must be an object, got "
                      f"{type(self.request).__name__}")
            raise ContractError(self.errors)
        request = self.request
        for key in sorted(set(request) - REQUEST_KEYS):
            self.fail("E_UNEXPECTED_FIELD", key, f"unknown key {key!r}")
        for key in sorted(REQUEST_KEYS - set(request)):
            self.fail("E_MISSING_FIELD", key,
                      f"required key {key!r} is absent")
        self.validate_points(request.get("points"))
        pivot_x = (self.read_float(request, "pivot_x_px", "")
                   if "pivot_x_px" in request else None)
        if pivot_x is not None:
            self.pivot_x = pivot_x
        pivot_y = (self.read_float(request, "pivot_y_px", "")
                   if "pivot_y_px" in request else None)
        if pivot_y is not None:
            self.pivot_y = pivot_y
        self.validate_bounds(request.get("bounds"))
        grid_n = (self.read_int(request, "grid_n_omega", "",
                                minimum=GRID_N_MIN)
                  if "grid_n_omega" in request else None)
        if grid_n is not None:
            self.grid_n = grid_n
        max_refine = (self.read_int(request, "max_refine_iterations", "",
                                    minimum=0)
                      if "max_refine_iterations" in request else None)
        if max_refine is not None:
            self.max_refine = max_refine
        self.validate_truth(request.get("truth"))
        if self.errors:
            raise ContractError(self.errors)

    def validate_points(self, points: Any) -> None:
        if "points" not in self.request:
            return
        if points is None:
            self.fail("E_NULL_NOT_ALLOWED", "points",
                      "value is null where a value is required")
            return
        if not isinstance(points, list):
            self.fail("E_WRONG_TYPE", "points",
                      f"expected a list, got {type(points).__name__}")
            return
        if not MIN_POINTS <= len(points) <= MAX_POINTS:
            self.fail("E_OUT_OF_RANGE", "points",
                      f"expected {MIN_POINTS}..{MAX_POINTS} points, got "
                      f"{len(points)}")
            return
        clean: list[tuple[float, float, float]] = []
        failed = False
        for index, entry in enumerate(points):
            field = f"points[{index}]"
            if not isinstance(entry, dict):
                self.fail("E_WRONG_TYPE", field,
                          f"expected an object, got {type(entry).__name__}")
                failed = True
                continue
            for key in sorted(set(entry) - POINT_KEYS):
                self.fail("E_UNEXPECTED_FIELD", f"{field}.{key}",
                          f"unknown key {key!r}")
                failed = True
            values: list[float] = []
            entry_failed = False
            for key in ("t_seconds", "x_px", "y_px"):
                if key not in entry:
                    self.fail("E_MISSING_FIELD", f"{field}.{key}",
                              f"required key {key!r} is absent")
                    entry_failed = True
                    continue
                value = entry[key]
                if value is None:
                    self.fail("E_NULL_NOT_ALLOWED", f"{field}.{key}",
                              "value is null where a value is required")
                    entry_failed = True
                elif not _is_float(value):
                    self.fail("E_WRONG_TYPE", f"{field}.{key}",
                              f"expected a number, got {type(value).__name__}")
                    entry_failed = True
                elif not math.isfinite(float(value)):
                    self.fail("E_NON_FINITE", f"{field}.{key}",
                              "value must be finite (NaN/inf rejected)")
                    entry_failed = True
                else:
                    values.append(float(value))
            if entry_failed:
                failed = True
                continue
            moment, x, y = values
            clean.append((moment, x, y))
        if not failed:
            self.points = clean

    def read_bound(self, bounds: dict, key: str) -> tuple[float, float] | None:
        field = f"bounds.{key}"
        if key not in bounds:
            return None
        pair = bounds[key]
        if pair is None:
            self.fail("E_NULL_NOT_ALLOWED", field,
                      "value is null where a value is required")
            return None
        if (not isinstance(pair, list) or len(pair) != 2
                or any(item is None for item in pair)):
            if isinstance(pair, list) and any(item is None for item in pair):
                self.fail("E_NULL_NOT_ALLOWED", field,
                          "bound endpoint is null where a value is required")
            else:
                self.fail("E_WRONG_TYPE", field,
                          "expected a [lo, hi] pair of numbers")
            return None
        if not all(_is_float(item) for item in pair):
            self.fail("E_WRONG_TYPE", field,
                      "expected a [lo, hi] pair of numbers")
            return None
        lo, hi = float(pair[0]), float(pair[1])
        if not math.isfinite(lo) or not math.isfinite(hi):
            self.fail("E_NON_FINITE", field,
                      "bound endpoints must be finite (NaN/inf rejected)")
            return None
        return (lo, hi)

    def validate_bounds(self, bounds: Any) -> None:
        if "bounds" not in self.request:
            return
        if bounds is None:
            self.fail("E_NULL_NOT_ALLOWED", "bounds",
                      "value is null where a value is required")
            return
        checked = self.check_keys(bounds, BOUNDS_KEYS, "bounds")
        if checked is None:
            return
        amp = self.read_bound(bounds, "amplitude_rad")
        if amp is not None:
            lo, hi = amp
            if lo < 0.0:
                self.fail("E_OUT_OF_RANGE", "bounds.amplitude_rad",
                          f"amplitude lower bound {lo!r} must be >= 0")
            elif lo > hi:
                self.fail("E_INCOHERENT_VALUE", "bounds.amplitude_rad",
                          f"amplitude bounds inverted ({lo!r} > {hi!r})")
            else:
                self.amp_lo, self.amp_hi = lo, hi
        omega = self.read_bound(bounds, "omega_per_s")
        if omega is not None:
            lo, hi = omega
            if lo <= 0.0:
                self.fail("E_OUT_OF_RANGE", "bounds.omega_per_s",
                          f"omega lower bound {lo!r} must be > 0")
            elif lo > hi:
                self.fail("E_INCOHERENT_VALUE", "bounds.omega_per_s",
                          f"omega bounds inverted ({lo!r} > {hi!r})")
            else:
                self.omega_lo, self.omega_hi = lo, hi

    def validate_truth(self, truth: Any) -> None:
        if "truth" not in self.request:
            return
        if truth is None:
            self.truth = None
            return
        checked = self.check_keys(truth, TRUTH_KEYS, "truth")
        if checked is None:
            return
        amplitude = self.read_float(truth, "amplitude_rad", "truth",
                                    minimum=0.0)
        omega = self.read_float(truth, "angular_frequency_per_s", "truth",
                                minimum=0.0, strict_min=True)
        phase = self.read_float(truth, "phase_rad", "truth")
        if (amplitude is not None and omega is not None
                and phase is not None):
            self.truth = {"amplitude_rad": amplitude,
                          "angular_frequency_per_s": omega,
                          "phase_rad": phase}


def _observed_angles(points: list[tuple[float, float, float]],
                     pivot_x: float, pivot_y: float,
                     ) -> list[tuple[int, float, float]]:
    """Recover per-point angles: stable time sort, atan2, unwrap.

    Returns ``(point_index, t_seconds, theta_rad)`` in fitted (time
    sorted) order; ``point_index`` is the input-list position for
    auditability. Unwrap folds each successive difference into
    ``(-pi, pi]`` so multi-revolution swings stay continuous.
    """
    ordered = sorted(enumerate(points), key=lambda item: item[1][0])
    angles: list[tuple[int, float, float]] = []
    previous: float | None = None
    for point_index, (moment, x, y) in ordered:
        theta = math.atan2(x - pivot_x, y - pivot_y)
        if previous is not None:
            while theta - previous > math.pi:
                theta -= 2.0 * math.pi
            while theta - previous <= -math.pi:
                theta += 2.0 * math.pi
        angles.append((point_index, moment, theta))
        previous = theta
    return angles


def _linear_pair(times: list[float], values: list[float], omega: float,
                 ) -> tuple[float, float] | None:
    """Closed-form least-squares ``(C, S)`` at fixed omega.

    Solves the 2x2 normal equations for ``y = C*cos(wt) +
    S*sin(wt)``; returns None when the design is singular or
    numerically collinear (determinant at/below
    ``DESIGN_SINGULAR_REL_TOL`` of the diagonal product), which
    the caller treats as an infinite objective rather than a crash
    or garbage coefficients.
    """
    sum_cc = sum_ss = sum_cs = sum_cy = sum_sy = 0.0
    for moment, value in zip(times, values):
        cosine = math.cos(omega * moment)
        sine = math.sin(omega * moment)
        sum_cc += cosine * cosine
        sum_ss += sine * sine
        sum_cs += cosine * sine
        sum_cy += cosine * value
        sum_sy += sine * value
    determinant = sum_cc * sum_ss - sum_cs * sum_cs
    if not determinant > DESIGN_SINGULAR_REL_TOL * sum_cc * sum_ss:
        return None
    inv_det = 1.0 / determinant
    coef_c = (sum_ss * sum_cy - sum_cs * sum_sy) * inv_det
    coef_s = (sum_cc * sum_sy - sum_cs * sum_cy) * inv_det
    return (coef_c, coef_s)


def _ssr(times: list[float], values: list[float], omega: float,
         ) -> tuple[float, tuple[float, float] | None]:
    """SSR at omega via the linear pair (inf when singular)."""
    pair = _linear_pair(times, values, omega)
    if pair is None:
        return (math.inf, None)
    coef_c, coef_s = pair
    total = 0.0
    for moment, value in zip(times, values):
        residual = (value - coef_c * math.cos(omega * moment)
                    - coef_s * math.sin(omega * moment))
        total += residual * residual
    return (total, pair)


def _to_amplitude_phase(coef_c: float, coef_s: float,
                        ) -> tuple[float, float]:
    """``(C, S)`` -> ``(A, phi)`` with phi wrapped to ``(-pi, pi]``.

    Zero amplitude has undefined phase; it reports exactly 0.0
    (deterministic; only reachable on degenerate input).
    """
    amplitude = math.hypot(coef_c, coef_s)
    if amplitude == 0.0:
        return (0.0, 0.0)
    return (amplitude, math.atan2(-coef_s, coef_c))


def _circular_error(fitted: float, truth: float) -> float:
    """Absolute circular distance between two phases in radians."""
    delta = (fitted - truth) % (2.0 * math.pi)
    if delta > math.pi:
        delta = 2.0 * math.pi - delta
    return delta


def _project_amplitude(amplitude: float, coef_c: float, coef_s: float,
                       lo: float, hi: float,
                       ) -> tuple[float, float, list[dict[str, Any]]]:
    """Project fitted amplitude onto ``[lo, hi]`` (radial rescale).

    Returns ``(amplitude, phase, hits)``; ``hits`` holds at most one
    entry with the unclamped value. Zero amplitude projecting onto a
    positive lower bound reports phase 0.0 (documented convention:
    phase is undefined at zero amplitude).
    """
    hits: list[dict[str, Any]] = []
    if amplitude > hi:
        scale = hi / amplitude
        hits.append({"parameter": "amplitude_rad", "bound": "upper",
                     "bound_value": hi, "unclamped_value": amplitude})
        amplitude, (coef_c, coef_s) = hi, (coef_c * scale, coef_s * scale)
    elif amplitude < lo:
        hits.append({"parameter": "amplitude_rad", "bound": "lower",
                     "bound_value": lo, "unclamped_value": amplitude})
        if amplitude == 0.0:
            return (lo, 0.0, hits)
        scale = lo / amplitude
        amplitude, (coef_c, coef_s) = lo, (coef_c * scale, coef_s * scale)
    _, phase = _to_amplitude_phase(coef_c, coef_s)
    if amplitude == 0.0:
        phase = 0.0
    return (amplitude, phase, hits)


def _fit_record_dict(*, converged: bool, g_over_l: float,
                     count: int, theta0: float | None,
                     omega0: float | None,
                     residual: dict[str, Any] | None) -> dict[str, Any]:
    """Assemble the ``fit.v1`` dict (validated by the caller)."""
    return {
        "schema_version": "fit.v1",
        "model_id": MODEL_ID,
        "parameter_names": ["g_over_l"],
        "parameters": {"g_over_l": g_over_l},
        "parameter_units": {"g_over_l": "1/s^2"},
        "initial_conditions": {"theta0_rad": theta0,
                               "omega0_rad_s": omega0},
        "solver": SOLVER_NAME,
        "optimizer": OPTIMIZER_NAME,
        "converged": converged,
        "residual_summary": residual,
        "observation_count": count,
        "rejected_count": 0,
        "fit_uncertainty_method": "none",
        "pivot_length_mm": None,
        "pivot_length_source": "not_provided",
        "g_over_l_per_s2": g_over_l,
        "gravity_m_s2": None,
        "warnings": [{"code": "W_UNCERTAINTY_UNAVAILABLE",
                      "detail": "KL-5.2 estimates no uncertainty; "
                                "method is none (KL-5.4 owns uncertainty)."}],
        "provenance": None,
    }


def _errors_vs_truth(amplitude: float | None, omega: float,
                     phase: float | None,
                     truth: dict[str, float] | None,
                     ) -> dict[str, float | None] | None:
    """Absolute parameter errors vs caller truth (null-aware)."""
    if truth is None:
        return None
    return {
        "amplitude_rad": (abs(amplitude - truth["amplitude_rad"])
                          if amplitude is not None else None),
        "omega_per_s": abs(omega - truth["angular_frequency_per_s"]),
        "phase_rad": (_circular_error(phase, truth["phase_rad"])
                      if phase is not None else None),
    }


def fit_m1(request: dict[str, Any]) -> dict[str, Any]:
    """Fit bounded M1 to observed pixel points (deterministic).

    Pure function of its input: no I/O, no wall clock, no
    randomness. Returns ``{"fitter", "model",
    "test_convention_note", "fit", "diagnostics"}`` where ``fit`` is
    a validated ``fit.v1`` dict. Raises ``ContractError``
    (registered codes, full collection) for malformed requests —
    never partial output. Fit failures are honest non-converged
    states inside the result, never exceptions.
    """
    parsed = _Request(request)
    parsed.validate()

    angles = _observed_angles(parsed.points, parsed.pivot_x, parsed.pivot_y)
    times = [moment for (_, moment, _) in angles]
    values = [value for (_, _, value) in angles]
    count = len(angles)
    null_ssr = sum(value * value for value in values)

    grid = [parsed.omega_lo + index * (parsed.omega_hi - parsed.omega_lo)
            / (parsed.grid_n - 1)
            for index in range(parsed.grid_n)]

    # --- Flat objective: every observed angle is exactly 0.0. ---
    if null_ssr == 0.0:
        amplitude, phase, hits = _project_amplitude(
            0.0, 0.0, 0.0, parsed.amp_lo, parsed.amp_hi)
        g_over_l = parsed.omega_lo * parsed.omega_lo
        fit = FitRecord.from_dict(_fit_record_dict(
            converged=False, g_over_l=g_over_l, count=count,
            theta0=None, omega0=None, residual=None)).to_dict()
        return {
            "fitter": FITTER_NAME,
            "model": MODEL_ID,
            "test_convention_note": TEST_CONVENTION_NOTE,
            "fit": fit,
            "diagnostics": {
                "fitted": {"amplitude_rad": amplitude,
                           "omega_per_s": parsed.omega_lo,
                           "phase_rad": phase,
                           "period_s": 2.0 * math.pi / parsed.omega_lo},
                "bound_hits": hits,
                "omega_grid_best_at_lower_edge": False,
                "omega_grid_best_at_upper_edge": False,
                "termination_reason": TERMINATION_FLAT_OBJECTIVE,
                "converged": False,
                "grid_evaluations": 0,
                "refine_iterations": 0,
                "objective_evaluations": 0,
                "objectives": {"null_amplitude_ssr": null_ssr,
                               "grid_best_ssr": None,
                               "refine_best_ssr": None,
                               "final_ssr": None},
                "weights": "uniform",
                "n_points": count,
                "residuals_available": False,
                "residuals": None,
                "errors_vs_truth": _errors_vs_truth(
                    amplitude, parsed.omega_lo, phase, parsed.truth),
            },
        }

    # --- Grid search (ascending omega, first-minimum wins ties). ---
    grid_best_ssr = math.inf
    grid_best_pair: tuple[float, float] | None = None
    grid_best_index = 0
    for index, omega in enumerate(grid):
        ssr, pair = _ssr(times, values, omega)
        if ssr < grid_best_ssr:
            grid_best_ssr = ssr
            grid_best_pair = pair
            grid_best_index = index
    # Best-seen state travels with its linear pair so no omega is
    # ever re-solved to recover one (re-solving could only agree,
    # but carrying the pair removes even the theoretical crack).
    best_omega = grid[grid_best_index]
    best_pair = grid_best_pair
    edge_lower = grid_best_index == 0
    edge_upper = grid_best_index == parsed.grid_n - 1

    # --- Degenerate design: singular normal equations everywhere. ---
    if grid_best_pair is None:
        g_over_l = parsed.omega_lo * parsed.omega_lo
        fit = FitRecord.from_dict(_fit_record_dict(
            converged=False, g_over_l=g_over_l, count=count,
            theta0=None, omega0=None, residual=None)).to_dict()
        return {
            "fitter": FITTER_NAME,
            "model": MODEL_ID,
            "test_convention_note": TEST_CONVENTION_NOTE,
            "fit": fit,
            "diagnostics": {
                "fitted": {"amplitude_rad": None,
                           "omega_per_s": parsed.omega_lo,
                           "phase_rad": None,
                           "period_s": 2.0 * math.pi / parsed.omega_lo},
                "bound_hits": [],
                "omega_grid_best_at_lower_edge": edge_lower,
                "omega_grid_best_at_upper_edge": edge_upper,
                "termination_reason": TERMINATION_DEGENERATE_DESIGN,
                "converged": False,
                "grid_evaluations": parsed.grid_n,
                "refine_iterations": 0,
                "objective_evaluations": parsed.grid_n,
                "objectives": {"null_amplitude_ssr": null_ssr,
                               "grid_best_ssr": None,
                               "refine_best_ssr": None,
                               "final_ssr": None},
                "weights": "uniform",
                "n_points": count,
                "residuals_available": False,
                "residuals": None,
                "errors_vs_truth": _errors_vs_truth(
                    None, parsed.omega_lo, None, parsed.truth),
            },
        }

    # --- Golden-section refinement of the grid bracket. ---
    bracket_lo = grid[max(0, grid_best_index - 1)]
    bracket_hi = grid[min(parsed.grid_n - 1, grid_best_index + 1)]
    best_ssr = grid_best_ssr
    assert best_pair is not None  # degenerate path returned otherwise
    refine_best_ssr: float | None = None
    evaluations = parsed.grid_n
    iterations = 0
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    invphi2 = (3.0 - math.sqrt(5.0)) / 2.0
    span = bracket_hi - bracket_lo
    probe_c = bracket_lo + invphi2 * span
    probe_d = bracket_lo + invphi * span
    ssr_c, pair_c = _ssr(times, values, probe_c)
    ssr_d, pair_d = _ssr(times, values, probe_d)
    evaluations += 2
    for probe_omega, probe_ssr, probe_pair in ((probe_c, ssr_c, pair_c),
                                               (probe_d, ssr_d, pair_d)):
        if probe_ssr < best_ssr:
            best_ssr = probe_ssr
            best_omega = probe_omega
            best_pair = probe_pair
    refine_best_ssr = min(ssr_c, ssr_d)
    while (bracket_hi - bracket_lo) >= OMEGA_REFINE_TOL \
            and iterations < parsed.max_refine:
        iterations += 1
        if ssr_c < ssr_d:
            # Ties shrink from below (deterministic branch).
            bracket_hi = probe_d
            probe_d, ssr_d, pair_d = probe_c, ssr_c, pair_c
            probe_c = bracket_lo + invphi2 * (bracket_hi - bracket_lo)
            ssr_c, pair_c = _ssr(times, values, probe_c)
            evaluations += 1
            if ssr_c < best_ssr:
                best_ssr = ssr_c
                best_omega = probe_c
                best_pair = pair_c
            if refine_best_ssr is None or ssr_c < refine_best_ssr:
                refine_best_ssr = ssr_c
        else:
            bracket_lo = probe_c
            probe_c, ssr_c, pair_c = probe_d, ssr_d, pair_d
            probe_d = bracket_lo + invphi * (bracket_hi - bracket_lo)
            ssr_d, pair_d = _ssr(times, values, probe_d)
            evaluations += 1
            if ssr_d < best_ssr:
                best_ssr = ssr_d
                best_omega = probe_d
                best_pair = pair_d
            if refine_best_ssr is None or ssr_d < refine_best_ssr:
                refine_best_ssr = ssr_d
    width = bracket_hi - bracket_lo
    if refine_best_ssr is not None and not math.isfinite(refine_best_ssr):
        # No finite refine value exists (all probes singular);
        # null keeps the export strict-JSON-safe (inf is not JSON).
        refine_best_ssr = None

    midpoint_fallback = False
    if width < OMEGA_REFINE_TOL:
        omega_star = (bracket_lo + bracket_hi) / 2.0
        pair = _linear_pair(times, values, omega_star)
        if pair is None:
            # Pathological midpoint singularity (measure-zero): fall
            # back to the best evaluated omega, which provably has a
            # finite pair, and say so in diagnostics.
            midpoint_fallback = True
            omega_star = best_omega
            assert best_pair is not None  # finite best_ssr by selection
            pair = best_pair
        coef_c, coef_s = pair
        raw_amplitude = math.hypot(coef_c, coef_s)
        amplitude, phase, hits = _project_amplitude(
            raw_amplitude, coef_c, coef_s, parsed.amp_lo, parsed.amp_hi)
        residuals: list[dict[str, Any]] = []
        total = 0.0
        worst = 0.0
        for point_index, moment, value in angles:
            residual = value - amplitude * math.cos(omega_star * moment
                                                    + phase)
            total += residual * residual
            worst = max(worst, abs(residual))
            residuals.append({"point_index": point_index,
                              "t_seconds": moment,
                              "residual_rad": residual})
        rmse = math.sqrt(total / count)
        g_over_l = omega_star * omega_star
        fit = FitRecord.from_dict(_fit_record_dict(
            converged=True, g_over_l=g_over_l, count=count,
            theta0=amplitude * math.cos(phase),
            omega0=-amplitude * omega_star * math.sin(phase),
            residual={"rmse": rmse, "max_abs": worst,
                      "dof": count - MIN_POINTS})).to_dict()
        termination = TERMINATION_TOLERANCE_MET
        converged = True
        final_ssr: float | None = total
        fitted = {"amplitude_rad": amplitude, "omega_per_s": omega_star,
                  "phase_rad": phase,
                  "period_s": 2.0 * math.pi / omega_star}
    else:
        assert best_pair is not None  # finite best_ssr by selection
        coef_c, coef_s = best_pair
        raw_amplitude = math.hypot(coef_c, coef_s)
        amplitude, phase, hits = _project_amplitude(
            raw_amplitude, coef_c, coef_s, parsed.amp_lo, parsed.amp_hi)
        g_over_l = best_omega * best_omega
        fit = FitRecord.from_dict(_fit_record_dict(
            converged=False, g_over_l=g_over_l, count=count,
            theta0=None, omega0=None, residual=None)).to_dict()
        termination = TERMINATION_BUDGET_EXHAUSTED
        converged = False
        final_ssr = None
        residuals = None  # type: ignore[assignment]
        fitted = {"amplitude_rad": amplitude, "omega_per_s": best_omega,
                  "phase_rad": phase,
                  "period_s": 2.0 * math.pi / best_omega}

    return {
        "fitter": FITTER_NAME,
        "model": MODEL_ID,
        "test_convention_note": TEST_CONVENTION_NOTE,
        "fit": fit,
        "diagnostics": {
            "fitted": fitted,
            "bound_hits": hits,
            "omega_grid_best_at_lower_edge": edge_lower,
            "omega_grid_best_at_upper_edge": edge_upper,
            "termination_reason": termination,
            "converged": converged,
            "omega_midpoint_singular_fallback": midpoint_fallback,
            "grid_evaluations": parsed.grid_n,
            "refine_iterations": iterations,
            "objective_evaluations": evaluations,
            "objectives": {"null_amplitude_ssr": null_ssr,
                           "grid_best_ssr": grid_best_ssr,
                           "refine_best_ssr": refine_best_ssr,
                           "final_ssr": final_ssr},
            "weights": "uniform",
            "n_points": count,
            "residuals_available": converged,
            "residuals": residuals,
            "errors_vs_truth": _errors_vs_truth(
                fitted["amplitude_rad"], fitted["omega_per_s"],
                fitted["phase_rad"], parsed.truth),
        },
    }


def export_fit_json(result: dict[str, Any]) -> bytes:
    """Serialize a fit result to canonical JSON bytes (lossless)."""
    if not isinstance(result, dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None,
            "fit result export requires a dict, got "
            f"{type(result).__name__}")])
    for key in ("fitter", "model", "test_convention_note", "fit",
                "diagnostics"):
        if key not in result:
            raise ContractError([FieldError(
                "E_MISSING_FIELD", key,
                f"required key {key!r} is absent")])
    text = json.dumps(result, sort_keys=True, indent=JSON_INDENT,
                      ensure_ascii=True)
    return (text + "\n").encode("utf-8")


def parse_fit_json(data: bytes | str) -> dict[str, Any]:
    """Parse canonical JSON bytes back to a fit result (inverse)."""
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
    if not isinstance(raw, dict):
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", None,
            "fit result export must be a JSON object")])
    for key in ("fitter", "model", "test_convention_note", "fit",
                "diagnostics"):
        if key not in raw:
            raise ContractError([FieldError(
                "E_MISSING_FIELD", key,
                f"required key {key!r} is absent")])
    if not isinstance(raw["fit"], dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "fit",
            f"expected an object, got {type(raw['fit']).__name__}")])
    try:
        fit = FitRecord.from_dict(raw["fit"])
    except ContractError as error:
        raise ContractError([
            FieldError(item.code,
                       "fit" + (f".{item.field}" if item.field else ""),
                       item.message)
            for item in error.errors
        ]) from error
    if not isinstance(raw["diagnostics"], dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "diagnostics",
            "expected an object, got "
            f"{type(raw['diagnostics']).__name__}")])
    return {"fitter": raw["fitter"], "model": raw["model"],
            "test_convention_note": raw["test_convention_note"],
            "fit": fit.to_dict(), "diagnostics": raw["diagnostics"]}
