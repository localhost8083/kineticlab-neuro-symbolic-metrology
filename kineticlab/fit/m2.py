"""Bounded M2 fit over synthetic angle data with warnings (KL-5.3).

Fits the closed-form damped curve ``theta(t) = A*exp(-gamma*t) *
cos(omega*t + phi)`` to observed pixel points from
``kineticlab.fit.synthetic`` trajectories. This task exists BECAUSE
M1 recovery stands (KL-5.2 verified): M2 reuses M1's pure
machinery (angle recovery, amplitude/phase conversion, amplitude
projection, tolerances, termination vocabulary) by import, never
calls ``fit_m1``, never re-fits M1, and never mutates M1 outputs
(all functions pure, no shared state). ``m1.py`` is untouched by
this module; KL-5.2's verification stands as-is.

Model note: the plan defines M2 as linear damping
(``theta'' + gamma*theta' + (g/L)*sin(theta) = 0``), whose
small-angle solution has envelope ``exp(-gamma*t/2)`` with omega
coupled to ``(g, L, gamma)``. The fitting model here uses the
envelope-rate parametrization ``exp(-gamma*t)`` with FREE omega —
the phenomenological damped sinusoid, exactly matching the KL-5.1
generator's damped model, so recovery tests are self-consistent
by construction. ``gamma`` is therefore the ENVELOPE decay rate
(1/s), and damping is decay-only: negative gamma (growing
oscillation) is rejected as out of range, a physical gate the
contract explicitly leaves to the fitting stage.

TEST convention (same as KL-5.2): synthetic fixture input, pivot
as caller-supplied known TEST geometry, time in seconds, and
``g_over_l = omega^2`` — a TEST recovery of ``g/L_eff``, never a
physical claim. No ``g`` in m/s^2 from synthetic data. The
``TEST_CONVENTION_NOTE`` (shared with M1) is embedded in every
result; JSON export/parsing reuse M1's ``export_fit_json`` /
``parse_fit_json`` unchanged (identical result envelope; the
``fitter``/``model`` fields distinguish content).

Angle recovery is M1's (imported): atan2 off the pivot, stable
time sort, unwrap. Generative ``theta_rad`` is NEVER read.
Weights are uniform, stated explicitly. The separable structure
is preserved: for fixed ``(omega, gamma)`` the model is linear in
``(C, S)`` over the envelope basis ``u = exp(-gamma*t)*cos(omega
*t)``, ``v = exp(-gamma*t)*sin(omega*t)``, solved in closed form
through the 2x2 normal equations with M1's scale-relative
singularity guard (infinite objective when singular).

Optimizer: deterministic nested grid plus alternating
golden-section refinement, documented exactly:

1. Grid: ``grid_n_omega`` x ``grid_n_gamma`` points covering the
   caller boxes (endpoints included). Evaluation order is omega
   outer ascending, gamma inner ascending; first-minimum-wins on
   SSR ties.
2. Bracket the grid best with its grid neighbors per dimension
   (clamped to the box). Refine by alternating golden-section
   steps: each iteration steps omega first, then gamma (one new
   evaluation per step, other dimension fixed at its current
   bracket midpoint); dimensions already narrower than tolerance
   rest ("converged dimensions rest"). Ties shrink from below,
   as in M1.
3. Budgets: ``max_refine_iterations`` counts alternation rounds
   (each round adds at most 2 evaluations); the 4 initial golden
   probes are bracketing overhead outside the budget, exactly as
   M1's 2 probes are. ``grid_n_*`` minima are 2 (endpoints-only
   grid still brackets).

``converged`` is true if and only if BOTH final bracket widths
fell below tolerance (``OMEGA_REFINE_TOL``, ``GAMMA_REFINE_TOL``)
— a two-dimensional localization certificate, not an accuracy
claim and not a gradient certificate (alternating steps localize
each line-minimum; recovery accuracy is demonstrated by tests).
Anything else is an HONEST NON-CONVERGED STATE with null
residuals/initial-conditions and best-iterate parameters in a
still-valid ``fit.v1``:

- ``flat_objective_unidentifiable``: null SSR exactly zero.
- ``degenerate_design``: singular at every grid point.
- ``refine_budget_exhausted``: a bracket still wide at budget end.

Overflow discipline (KL-7.5 F5): request-time span validation
rejects timestamp spans no in-bounds candidate can evaluate
(``E_OUT_OF_RANGE``); every ``math.exp`` evaluation site maps
overflow to the existing infinite-objective / non-convergence
machinery instead of escaping.

Warnings are the deliverable. Every warning uses a REGISTERED
code only — no invented codes. The mapping (reviewable here so
the gate can act on it): ``W_UNCERTAINTY_UNAVAILABLE`` always
(uncertainty is KL-5.4); every situational warning uses
``W_ASSUMPTION_UNVERIFIED`` ("a required assumption is stated but
not independently verified"), because each situation disconfirms
something the fit assumes: stationarity reached (non-convergence),
the box containing the optimum (bound/edge hits), a damped model
being appropriate (mismatch). Warning details state FACTS and
carry NO floats (numbers live in diagnostics), so details are
exactly pinnable. Fixed order: uncertainty, non-convergence,
amplitude hit, omega edges (lower, upper), gamma edges (lower,
upper), mismatch. Facts compose: several warnings may fire
together; none declares goodness.

- Non-convergence: ``converged: false`` + warning naming the
  termination reason; parameters are the best iterate.
- Bound hits: amplitude projection hits warn naming parameter +
  bound (unclamped value in diagnostics). Omega/gamma optima at
  a grid edge warn naming parameter + edge, with endpoint and
  neighbor SSR as the descent evidence in diagnostics (a grid
  method detects edge optima; it cannot produce an out-of-box
  "unclamped" value).
- Mismatch: fires iff the fitted gamma satisfies ``gamma * span
  < MISMATCH_MAX_DECAY`` (envelope decays <1% across the fitted
  span: data consistent with undamped M1), evaluated only when
  the search localized an (omega, gamma) optimum (converged or
  budget-exhausted paths). With the standard zero-lower-bound
  gamma box this coincides with gamma pinned at the zero bound;
  with an excluding box the edge warning (not mismatch) is the
  honest flag. Degenerate iterates carry no model-form
  information, so flat/degenerate paths never raise mismatch.

Output mirrors M1: ``fit_m2(request)`` returns ``{"fitter",
"model", "test_convention_note", "fit", "diagnostics"}`` with
``model "M2"``. ``fit`` is a valid ``fit.v1`` dict: M2 parameters
exactly ``{"g_over_l": omega^2, "gamma": gamma}`` in ``1/s^2``
and ``1/s`` (contract-forced units); converged fits derive
``initial_conditions`` as ``theta0 = A*cos(phi)``,
``omega0 = -A*gamma*cos(phi) - A*omega*sin(phi)``
(the M2 derivative at t=0; the contract requires stated initial
conditions for converged fits); gravity stays null; method none.
Diagnostics add ``gamma_per_s`` (fitted), ``period_s`` (the
oscillation quasi-period ``2*pi/omega``; envelope separate),
gamma edge flags + edge evidence, ``gamma_span_decay``
(``gamma * span``), and the gamma error in ``errors_vs_truth``.
``dof`` is ``n - 4`` (four curve parameters), hence
``MIN_POINTS = 4``.

Named constants carry written rationale:

- ``GAMMA_REFINE_TOL = 1e-9`` 1/s: same stationarity-cert
  rationale as M1's omega tolerance; at test scales (gamma ~
  0.05-0.3) this is <= 1e-8 relative, 1000x below recovery needs.
- ``MISMATCH_MAX_DECAY = 0.01``: below 1% total envelope decay
  across the fitted span, damping changes the curve by <1% of
  amplitude — beneath estimator relevance — so presenting an
  unflagged damped fit would overstate; the warning states the
  measured decay fraction's position, not a verdict.
- ``RECOVERY_TOL_GAMMA_PER_S``: clean-case gamma recovery
  tolerance (measured headroom recorded in tests/test_fit_m2.py);
  amplitude/omega/phase reuse M1's 1e-6 tolerances.
- ``MIN_POINTS = 4``: four curve parameters need four points
  (dof = n - 4 >= 0).

Failure map (registered codes only, full error collection with
nested paths such as ``bounds.gamma_per_s``):

- non-dict request / non-dict ``bounds``/``truth`` / non-list
  ``points`` / malformed entries -> ``E_WRONG_TYPE``.
- unknown keys -> ``E_UNEXPECTED_FIELD``; absent keys ->
  ``E_MISSING_FIELD``; null where required ->
  ``E_NULL_NOT_ALLOWED``.
- NaN/inf -> ``E_NON_FINITE``; fewer than ``MIN_POINTS`` points,
  grid counts below 2, negative ``max_refine_iterations``,
  negative amplitude/gamma bound or truth, non-positive omega
  bound or truth -> ``E_OUT_OF_RANGE``.
- bound pair inverted (``lo > hi``) -> ``E_INCOHERENT_VALUE``.

Determinism contract: fixed grids, fixed evaluation order, no
wall clock, no randomness — same request = identical result bytes
on a given platform/CPython+libm build (same libm caveat as M1).

Known limitations (documented, not hidden): closed-form
envelope-rate M2 only (not integrated-ODE fitting); the grid must
sample the true SSR valley in BOTH dimensions (density is the
caller's); planted ``|theta| > pi`` out of scope (unwrap branch,
as in M1); amplitude projection approximate for anisotropic
designs (flagged); alternating refinement localizes brackets, it
does not certify a joint stationary point — recovery accuracy is
CONFIG-DEPENDENT (mapped by the KL-5.4 matrix, not just "sparse
data"): short-span/few-cycle configs stall (measured: <=0.77
cycles stalls at 1e-3, >=0.83 cycles recovers to 1e-10), a narrow
gamma ~= 0.05 island stalls amid recovering neighbors, and
grid/box alignment decides stall-vs-recovery non-monotonically
(measured: 512x128 stalls marginally where coarser AND finer
grids recover; a narrowed omega box stalls where the wide box
recovers). Stalls are budget-independent and report
converged:true with full errors_vs_truth — localization, never a
claim of accuracy.
"""

from __future__ import annotations

import math
from typing import Any

from kineticlab.contracts import (
    ContractError,
    FieldError,
    FitRecord,
)
from kineticlab.fit.m1 import (
    DESIGN_SINGULAR_REL_TOL,
    GRID_N_MIN,
    MAX_POINTS,
    OMEGA_REFINE_TOL,
    TERMINATION_BUDGET_EXHAUSTED,
    TERMINATION_DEGENERATE_DESIGN,
    TERMINATION_FLAT_OBJECTIVE,
    TERMINATION_TOLERANCE_MET,
    TEST_CONVENTION_NOTE,
    _circular_error,
    _observed_angles,
    _project_amplitude,
)

FITTER_NAME = "kineticlab.fit.m2"
MODEL_ID = "M2"

SOLVER_NAME = "closed_form_small_angle_damped"
OPTIMIZER_NAME = "separable_omega_gamma_grid_linear_lsq_alternating_golden_refine_v1"

GAMMA_REFINE_TOL = 1e-9
"""Golden-section stop width in 1/s for gamma (localization cert)."""

MISMATCH_MAX_DECAY = 0.01
"""Mismatch line: gamma*span below this is undamped-consistent."""

MIN_POINTS = 4
"""Algebraic floor: four curve parameters need four points."""

RECOVERY_TOL_GAMMA_PER_S = 1e-6
"""Clean-case gamma recovery tolerance (headroom in tests)."""

WARNING_UNCERTAINTY_DETAIL = (
    "KL-5.3 estimates no uncertainty; "
    "method is none (KL-5.4 owns uncertainty)."
)

MISMATCH_DETAIL = (
    "fitted gamma envelope decays less than 1% across the fitted "
    "span; data are consistent with undamped M1; see diagnostics "
    "gamma_span_decay and fitted gamma."
)

REQUEST_KEYS = frozenset({
    "points",
    "pivot_x_px",
    "pivot_y_px",
    "bounds",
    "grid_n_omega",
    "grid_n_gamma",
    "max_refine_iterations",
    "truth",
})

POINT_KEYS = frozenset({"t_seconds", "x_px", "y_px"})

BOUNDS_KEYS = frozenset({"amplitude_rad", "omega_per_s", "gamma_per_s"})

TRUTH_KEYS = frozenset({
    "amplitude_rad",
    "angular_frequency_per_s",
    "phase_rad",
    "damping_per_s",
})


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_float(value: Any) -> bool:
    return (_is_int(value) or isinstance(value, float))


class _M2Request:
    """Validated M2 fit request (full error collection, one raise)."""

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
        self.gamma_lo = 0.0
        self.gamma_hi = 0.0
        self.grid_n_omega = 0
        self.grid_n_gamma = 0
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
        grid_omega = (self.read_int(request, "grid_n_omega", "",
                                    minimum=GRID_N_MIN)
                      if "grid_n_omega" in request else None)
        if grid_omega is not None:
            self.grid_n_omega = grid_omega
        grid_gamma = (self.read_int(request, "grid_n_gamma", "",
                                    minimum=GRID_N_MIN)
                      if "grid_n_gamma" in request else None)
        if grid_gamma is not None:
            self.grid_n_gamma = grid_gamma
        max_refine = (self.read_int(request, "max_refine_iterations", "",
                                    minimum=0)
                      if "max_refine_iterations" in request else None)
        if max_refine is not None:
            self.max_refine = max_refine
        self.validate_truth(request.get("truth"))
        self._validate_span()
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
        gamma = self.read_bound(bounds, "gamma_per_s")
        if gamma is not None:
            lo, hi = gamma
            if lo < 0.0:
                self.fail("E_OUT_OF_RANGE", "bounds.gamma_per_s",
                          f"gamma lower bound {lo!r} must be >= 0 "
                          f"(damping is decay-only)")
            elif lo > hi:
                self.fail("E_INCOHERENT_VALUE", "bounds.gamma_per_s",
                          f"gamma bounds inverted ({lo!r} > {hi!r})")
            else:
                self.gamma_lo, self.gamma_hi = lo, hi

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
        damping = self.read_float(truth, "damping_per_s", "truth",
                                  minimum=0.0)
        if (amplitude is not None and omega is not None
                and phase is not None and damping is not None):
            self.truth = {"amplitude_rad": amplitude,
                          "angular_frequency_per_s": omega,
                          "phase_rad": phase,
                          "damping_per_s": damping}

    def _validate_span(self) -> None:
        # F5: reject timestamp spans no in-bounds candidate can
        # evaluate. self.points is set only when point validation
        # passed; bounds may still carry errors, in which case
        # their defaults keep this probe silent and the bounds
        # errors carry the failure.
        points = getattr(self, "points", None)
        if not points:
            return
        moments = [moment for moment, _, _ in points]
        span = max(moments) - min(moments)
        if not math.isfinite(span):
            self.fail("E_OUT_OF_RANGE", "points",
                      "timestamp span is not finite; the M2 envelope "
                      "cannot be evaluated")
            return
        peak_lo = min(moments)
        peak_hi = max(moments)
        try:
            for corner in (-self.gamma_lo * peak_lo,
                           -self.gamma_lo * peak_hi,
                           -self.gamma_hi * peak_lo,
                           -self.gamma_hi * peak_hi):
                math.exp(corner)
        except OverflowError:
            self.fail("E_OUT_OF_RANGE", "points",
                      "timestamp span is too large for finite M2 "
                      "envelope evaluation at the gamma bounds")
            return
        trig = (self.omega_lo * peak_lo, self.omega_lo * peak_hi,
                self.omega_hi * peak_lo, self.omega_hi * peak_hi)
        if not all(math.isfinite(value) for value in trig):
            self.fail("E_OUT_OF_RANGE", "points",
                      "timestamp span is too large for finite M2 "
                      "trigonometric evaluation at the omega bounds")


def _envelope_pair(times: list[float], values: list[float],
                   omega: float, gamma: float,
                   ) -> tuple[float, float] | None:
    """Closed-form least-squares ``(C, S)`` at fixed ``(omega, gamma)``.

    The envelope twin of M1's linear pair: solves the 2x2 normal
    equations for ``y = C*u + S*v`` with ``u = exp(-gamma*t) *
    cos(omega*t)``, ``v = exp(-gamma*t) * sin(omega*t)``. Returns
    None under M1's scale-relative singularity guard (shared
    constant), which the caller treats as an infinite objective.
    """
    sum_uu = sum_vv = sum_uv = sum_uy = sum_vy = 0.0
    try:
        for moment, value in zip(times, values):
            envelope = math.exp(-gamma * moment)
            basis_u = envelope * math.cos(omega * moment)
            basis_v = envelope * math.sin(omega * moment)
            sum_uu += basis_u * basis_u
            sum_vv += basis_v * basis_v
            sum_uv += basis_u * basis_v
            sum_uy += basis_u * value
            sum_vy += basis_v * value
    except OverflowError:
        # F5: unrepresentable envelope maps to the infinite
        # objective (caller treats None exactly like singular).
        return None
    determinant = sum_uu * sum_vv - sum_uv * sum_uv
    if not determinant > DESIGN_SINGULAR_REL_TOL * sum_uu * sum_vv:
        return None
    inv_det = 1.0 / determinant
    coef_c = (sum_vv * sum_uy - sum_uv * sum_vy) * inv_det
    coef_s = (sum_uu * sum_vy - sum_uv * sum_uy) * inv_det
    return (coef_c, coef_s)


def _ssr(times: list[float], values: list[float],
         omega: float, gamma: float,
         ) -> tuple[float, tuple[float, float] | None]:
    """SSR at ``(omega, gamma)`` via the envelope pair (inf if singular)."""
    pair = _envelope_pair(times, values, omega, gamma)
    if pair is None:
        return (math.inf, None)
    coef_c, coef_s = pair
    total = 0.0
    try:
        for moment, value in zip(times, values):
            envelope = math.exp(-gamma * moment)
            residual = (value - envelope * (coef_c * math.cos(omega * moment)
                                            + coef_s * math.sin(omega * moment)))
            total += residual * residual
    except OverflowError:
        # F5: unrepresentable envelope maps to the infinite
        # objective (pair discarded like the singular path, so
        # degenerate-grid detection keeps working).
        return (math.inf, None)
    return (total, pair)


class _Golden1D:
    """One golden-section bracket (probes always evaluated fresh).

    No probe inheritance across steps: each step re-evaluates both
    interior probes at the other dimension's current midpoint, so
    comparisons never mix values from different line functions.
    """

    def __init__(self, lo: float, hi: float) -> None:
        self.lo = lo
        self.hi = hi

    @property
    def width(self) -> float:
        return self.hi - self.lo

    @property
    def midpoint(self) -> float:
        return (self.lo + self.hi) / 2.0


def _nonconv_detail(reason: str) -> str:
    return (
        f"optimizer did not reach stationarity ({reason}); reported "
        f"parameters are the best iterate, not a stationary point; "
        f"residuals unclaimed; see diagnostics termination_reason"
    )


def _projection_detail(parameter: str, bound: str) -> str:
    return (
        f"{parameter} projected onto the {bound} box bound; optimum "
        f"may lie outside the box; see diagnostics bound_hits"
    )


def _edge_detail(parameter: str, edge: str) -> str:
    return (
        f"{parameter} grid best at the {edge} box edge; optimum may "
        f"lie outside the box; see diagnostics edge_evidence"
    )


def _fit_record_dict(*, converged: bool, g_over_l: float, gamma: float,
                     count: int, theta0: float | None,
                     omega0: float | None,
                     residual: dict[str, Any] | None,
                     warnings: list[dict[str, str]]) -> dict[str, Any]:
    """Assemble the M2 ``fit.v1`` dict (validated by the caller)."""
    return {
        "schema_version": "fit.v1",
        "model_id": MODEL_ID,
        "parameter_names": ["g_over_l", "gamma"],
        "parameters": {"g_over_l": g_over_l, "gamma": gamma},
        "parameter_units": {"g_over_l": "1/s^2", "gamma": "1/s"},
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
        "warnings": warnings,
        "provenance": None,
    }


def _errors_vs_truth(amplitude: float | None, omega: float,
                     phase: float | None, gamma: float,
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
        "gamma_per_s": abs(gamma - truth["damping_per_s"]),
    }


def _finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def _base_warnings() -> list[dict[str, str]]:
    return [{"code": "W_UNCERTAINTY_UNAVAILABLE",
             "detail": WARNING_UNCERTAINTY_DETAIL}]


def fit_m2(request: dict[str, Any]) -> dict[str, Any]:
    """Fit bounded M2 to observed pixel points (deterministic).

    Pure function of its input: no I/O, no wall clock, no
    randomness. Returns ``{"fitter", "model",
    "test_convention_note", "fit", "diagnostics"}`` where ``fit`` is
    a validated M2 ``fit.v1`` dict. Raises ``ContractError``
    (registered codes, full collection) for malformed requests —
    never partial output. Fit failures are honest non-converged
    states with warnings inside the result, never exceptions.
    Reuses M1's pure helpers by import; never calls ``fit_m1``.
    """
    parsed = _M2Request(request)
    parsed.validate()

    angles = _observed_angles(parsed.points, parsed.pivot_x, parsed.pivot_y)
    times = [moment for (_, moment, _) in angles]
    values = [value for (_, _, value) in angles]
    count = len(angles)
    null_ssr = sum(value * value for value in values)
    span = times[-1] - times[0]

    omega_grid = [parsed.omega_lo + index
                  * (parsed.omega_hi - parsed.omega_lo)
                  / (parsed.grid_n_omega - 1)
                  for index in range(parsed.grid_n_omega)]
    gamma_grid = [parsed.gamma_lo + index
                  * (parsed.gamma_hi - parsed.gamma_lo)
                  / (parsed.grid_n_gamma - 1)
                  for index in range(parsed.grid_n_gamma)]

    # --- Flat objective: every observed angle is exactly 0.0. ---
    if null_ssr == 0.0:
        amplitude, phase, hits = _project_amplitude(
            0.0, 0.0, 0.0, parsed.amp_lo, parsed.amp_hi)
        warnings = _base_warnings()
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _nonconv_detail(TERMINATION_FLAT_OBJECTIVE)})
        for hit in hits:
            warnings.append({
                "code": "W_ASSUMPTION_UNVERIFIED",
                "detail": _projection_detail(hit["parameter"],
                                             hit["bound"])})
        g_over_l = parsed.omega_lo * parsed.omega_lo
        fit = FitRecord.from_dict(_fit_record_dict(
            converged=False, g_over_l=g_over_l, gamma=parsed.gamma_lo,
            count=count, theta0=None, omega0=None, residual=None,
            warnings=warnings)).to_dict()
        return {
            "fitter": FITTER_NAME,
            "model": MODEL_ID,
            "test_convention_note": TEST_CONVENTION_NOTE,
            "fit": fit,
            "diagnostics": {
                "fitted": {"amplitude_rad": amplitude,
                           "omega_per_s": parsed.omega_lo,
                           "phase_rad": phase,
                           "gamma_per_s": parsed.gamma_lo,
                           "period_s": 2.0 * math.pi / parsed.omega_lo},
                "bound_hits": hits,
                "omega_grid_best_at_lower_edge": False,
                "omega_grid_best_at_upper_edge": False,
                "gamma_grid_best_at_lower_edge": False,
                "gamma_grid_best_at_upper_edge": False,
                "edge_evidence": {"omega_lower": None, "omega_upper": None,
                                  "gamma_lower": None, "gamma_upper": None},
                "gamma_span_decay": parsed.gamma_lo * span,
                "t_span_s": span,
                "termination_reason": TERMINATION_FLAT_OBJECTIVE,
                "converged": False,
                "omega_midpoint_singular_fallback": False,
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
                    amplitude, parsed.omega_lo, phase, parsed.gamma_lo,
                    parsed.truth),
            },
        }

    # --- Nested grid: omega outer ascending, gamma inner ascending,
    # --- first-minimum-wins ties. Full SSR matrix kept for edge evidence.
    matrix: list[list[float]] = []
    grid_best_ssr = math.inf
    grid_best_pair: tuple[float, float] | None = None
    best_i = 0
    best_j = 0
    for omega in omega_grid:
        row: list[float] = []
        for gamma in gamma_grid:
            ssr, pair = _ssr(times, values, omega, gamma)
            row.append(ssr)
            if ssr < grid_best_ssr:
                grid_best_ssr = ssr
                grid_best_pair = pair
                best_i = len(matrix)
                best_j = len(row) - 1
        matrix.append(row)
    grid_evaluations = parsed.grid_n_omega * parsed.grid_n_gamma
    edge_omega_lo = best_i == 0
    edge_omega_hi = best_i == parsed.grid_n_omega - 1
    edge_gamma_lo = best_j == 0
    edge_gamma_hi = best_j == parsed.grid_n_gamma - 1

    def edge_entry(cells: list[list[float]], fixed: int, edge: int,
                   neighbor: int, *, along_gamma: bool,
                   ) -> dict[str, float | None]:
        if along_gamma:
            edge_ssr = cells[fixed][edge]
            neighbor_ssr = cells[fixed][neighbor]
        else:
            edge_ssr = cells[edge][fixed]
            neighbor_ssr = cells[neighbor][fixed]
        return {"edge_ssr": _finite_or_none(edge_ssr),
                "neighbor_ssr": _finite_or_none(neighbor_ssr)}

    edge_evidence: dict[str, dict[str, float | None] | None] = {
        "omega_lower": (edge_entry(matrix, best_j, 0, 1,
                                   along_gamma=False)
                        if edge_omega_lo else None),
        "omega_upper": (edge_entry(matrix, best_j,
                                   parsed.grid_n_omega - 1,
                                   parsed.grid_n_omega - 2,
                                   along_gamma=False)
                        if edge_omega_hi else None),
        "gamma_lower": (edge_entry(matrix, best_i, 0, 1,
                                   along_gamma=True)
                        if edge_gamma_lo else None),
        "gamma_upper": (edge_entry(matrix, best_i,
                                   parsed.grid_n_gamma - 1,
                                   parsed.grid_n_gamma - 2,
                                   along_gamma=True)
                        if edge_gamma_hi else None),
    }

    # --- Degenerate design: singular normal equations everywhere. ---
    # --- No finite grid best exists, so edge detection is vacuous:
    # --- flags read False (edge ⟺ FINITE best at an endpoint). ---
    if grid_best_pair is None:
        warnings = _base_warnings()
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _nonconv_detail(TERMINATION_DEGENERATE_DESIGN)})
        edge_evidence = {"omega_lower": None, "omega_upper": None,
                         "gamma_lower": None, "gamma_upper": None}
        g_over_l = parsed.omega_lo * parsed.omega_lo
        fit = FitRecord.from_dict(_fit_record_dict(
            converged=False, g_over_l=g_over_l, gamma=parsed.gamma_lo,
            count=count, theta0=None, omega0=None, residual=None,
            warnings=warnings)).to_dict()
        return {
            "fitter": FITTER_NAME,
            "model": MODEL_ID,
            "test_convention_note": TEST_CONVENTION_NOTE,
            "fit": fit,
            "diagnostics": {
                "fitted": {"amplitude_rad": None,
                           "omega_per_s": parsed.omega_lo,
                           "phase_rad": None,
                           "gamma_per_s": parsed.gamma_lo,
                           "period_s": 2.0 * math.pi / parsed.omega_lo},
                "bound_hits": [],
                "omega_grid_best_at_lower_edge": False,
                "omega_grid_best_at_upper_edge": False,
                "gamma_grid_best_at_lower_edge": False,
                "gamma_grid_best_at_upper_edge": False,
                "edge_evidence": edge_evidence,
                "gamma_span_decay": parsed.gamma_lo * span,
                "t_span_s": span,
                "termination_reason": TERMINATION_DEGENERATE_DESIGN,
                "converged": False,
                "omega_midpoint_singular_fallback": False,
                "grid_evaluations": grid_evaluations,
                "refine_iterations": 0,
                "objective_evaluations": grid_evaluations,
                "objectives": {"null_amplitude_ssr": null_ssr,
                               "grid_best_ssr": None,
                               "refine_best_ssr": None,
                               "final_ssr": None},
                "weights": "uniform",
                "n_points": count,
                "residuals_available": False,
                "residuals": None,
                "errors_vs_truth": _errors_vs_truth(
                    None, parsed.omega_lo, None, parsed.gamma_lo,
                    parsed.truth),
            },
        }

    # --- Alternating golden-section refinement. Each round steps
    # --- omega first, then gamma (gamma sees the post-step omega
    # --- bracket); converged dimensions rest. Both probes per step
    # --- are evaluated fresh: 2 evaluations per dimension-step.
    omega_state = _Golden1D(
        omega_grid[max(0, best_i - 1)],
        omega_grid[min(parsed.grid_n_omega - 1, best_i + 1)])
    gamma_state = _Golden1D(
        gamma_grid[max(0, best_j - 1)],
        gamma_grid[min(parsed.grid_n_gamma - 1, best_j + 1)])
    best_omega = omega_grid[best_i]
    best_gamma = gamma_grid[best_j]
    best_pair = grid_best_pair
    assert best_pair is not None  # degenerate path returned otherwise
    best_ssr = grid_best_ssr
    evaluations = grid_evaluations
    iterations = 0
    invphi = (math.sqrt(5.0) - 1.0) / 2.0
    invphi2 = (3.0 - math.sqrt(5.0)) / 2.0
    refine_probes: list[float] = []

    def consider(omega: float, gamma: float, ssr: float,
                 pair: tuple[float, float] | None) -> None:
        nonlocal best_omega, best_gamma, best_pair, best_ssr
        refine_probes.append(ssr)
        if ssr < best_ssr:
            best_ssr = ssr
            best_omega = omega
            best_gamma = gamma
            best_pair = pair

    def omega_probes() -> None:
        nonlocal evaluations
        fixed = gamma_state.midpoint
        span_w = omega_state.width
        probe_c = omega_state.lo + invphi2 * span_w
        probe_d = omega_state.lo + invphi * span_w
        ssr_c, pair_c = _ssr(times, values, probe_c, fixed)
        ssr_d, pair_d = _ssr(times, values, probe_d, fixed)
        evaluations += 2
        consider(probe_c, fixed, ssr_c, pair_c)
        consider(probe_d, fixed, ssr_d, pair_d)
        # Ties shrink from below (deterministic branch, as in M1).
        if ssr_c < ssr_d:
            omega_state.hi = probe_d
        else:
            omega_state.lo = probe_c

    def gamma_probes() -> None:
        nonlocal evaluations
        fixed = omega_state.midpoint
        span_g = gamma_state.width
        probe_c = gamma_state.lo + invphi2 * span_g
        probe_d = gamma_state.lo + invphi * span_g
        ssr_c, pair_c = _ssr(times, values, fixed, probe_c)
        ssr_d, pair_d = _ssr(times, values, fixed, probe_d)
        evaluations += 2
        consider(fixed, probe_c, ssr_c, pair_c)
        consider(fixed, probe_d, ssr_d, pair_d)
        if ssr_c < ssr_d:
            gamma_state.hi = probe_d
        else:
            gamma_state.lo = probe_c

    # Initial probes double as the first shrink of each bracket.
    omega_probes()
    gamma_probes()
    while ((omega_state.width >= OMEGA_REFINE_TOL
            or gamma_state.width >= GAMMA_REFINE_TOL)
           and iterations < parsed.max_refine):
        iterations += 1
        if omega_state.width >= OMEGA_REFINE_TOL:
            omega_probes()
        if gamma_state.width >= GAMMA_REFINE_TOL:
            gamma_probes()
    refine_best_ssr = _finite_or_none(min(refine_probes))

    midpoint_fallback = False
    envelope_overflow = False
    if (omega_state.width < OMEGA_REFINE_TOL
            and gamma_state.width < GAMMA_REFINE_TOL):
        omega_star = omega_state.midpoint
        gamma_star = gamma_state.midpoint
        pair = _envelope_pair(times, values, omega_star, gamma_star)
        if pair is None:
            # Pathological midpoint singularity (measure-zero): fall
            # back to the best evaluated point, which provably has
            # a finite pair, and say so in diagnostics.
            midpoint_fallback = True
            omega_star = best_omega
            gamma_star = best_gamma
            assert best_pair is not None  # finite best_ssr by selection
            pair = best_pair
        coef_c, coef_s = pair
        raw_amplitude = math.hypot(coef_c, coef_s)
        amplitude, phase, hits = _project_amplitude(
            raw_amplitude, coef_c, coef_s, parsed.amp_lo, parsed.amp_hi)
        residuals: list[dict[str, Any]] | None = []
        total = 0.0
        worst = 0.0
        try:
            for point_index, moment, value in angles:
                residual = (value - amplitude
                            * math.exp(-gamma_star * moment)
                            * math.cos(omega_star * moment + phase))
                total += residual * residual
                worst = max(worst, abs(residual))
                residuals.append({"point_index": point_index,
                                  "t_seconds": moment,
                                  "residual_rad": residual})
        except OverflowError:
            # F5: unreachable after request-time span validation
            # (every in-bounds envelope evaluates finitely); if it
            # ever triggers, map to the controlled non-convergence
            # branch below rather than escaping.
            envelope_overflow = True
        if not envelope_overflow:
            rmse = math.sqrt(total / count)
            g_over_l = omega_star * omega_star
            theta0 = amplitude * math.cos(phase)
            omega0 = (-amplitude * gamma_star * math.cos(phase)
                      - amplitude * omega_star * math.sin(phase))
            residual_summary: dict[str, Any] | None = {
                "rmse": rmse, "max_abs": worst, "dof": count - MIN_POINTS}
            termination = TERMINATION_TOLERANCE_MET
            converged = True
            final_ssr: float | None = total
            fitted = {"amplitude_rad": amplitude, "omega_per_s": omega_star,
                      "phase_rad": phase, "gamma_per_s": gamma_star,
                      "period_s": 2.0 * math.pi / omega_star}
    if (omega_state.width >= OMEGA_REFINE_TOL
            or gamma_state.width >= GAMMA_REFINE_TOL
            or envelope_overflow):
        assert best_pair is not None  # finite best_ssr by selection
        coef_c, coef_s = best_pair
        raw_amplitude = math.hypot(coef_c, coef_s)
        amplitude, phase, hits = _project_amplitude(
            raw_amplitude, coef_c, coef_s, parsed.amp_lo, parsed.amp_hi)
        g_over_l = best_omega * best_omega
        theta0 = None
        omega0 = None
        residual_summary = None
        residuals = None
        termination = TERMINATION_BUDGET_EXHAUSTED
        converged = False
        final_ssr = None
        fitted = {"amplitude_rad": amplitude, "omega_per_s": best_omega,
                  "phase_rad": phase, "gamma_per_s": best_gamma,
                  "period_s": 2.0 * math.pi / best_omega}

    warnings = _base_warnings()
    if not converged:
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _nonconv_detail(termination)})
    for hit in hits:
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _projection_detail(hit["parameter"], hit["bound"])})
    if edge_omega_lo:
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _edge_detail("omega", "lower")})
    if edge_omega_hi:
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _edge_detail("omega", "upper")})
    if edge_gamma_lo:
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _edge_detail("gamma", "lower")})
    if edge_gamma_hi:
        warnings.append({
            "code": "W_ASSUMPTION_UNVERIFIED",
            "detail": _edge_detail("gamma", "upper")})
    gamma_star_value: float = fitted["gamma_per_s"]
    gamma_span_decay = gamma_star_value * span
    if gamma_span_decay < MISMATCH_MAX_DECAY:
        warnings.append({"code": "W_ASSUMPTION_UNVERIFIED",
                         "detail": MISMATCH_DETAIL})
    fit = FitRecord.from_dict(_fit_record_dict(
        converged=converged, g_over_l=g_over_l, gamma=gamma_star_value,
        count=count, theta0=theta0, omega0=omega0,
        residual=residual_summary, warnings=warnings)).to_dict()

    return {
        "fitter": FITTER_NAME,
        "model": MODEL_ID,
        "test_convention_note": TEST_CONVENTION_NOTE,
        "fit": fit,
        "diagnostics": {
            "fitted": fitted,
            "bound_hits": hits,
            "omega_grid_best_at_lower_edge": edge_omega_lo,
            "omega_grid_best_at_upper_edge": edge_omega_hi,
            "gamma_grid_best_at_lower_edge": edge_gamma_lo,
            "gamma_grid_best_at_upper_edge": edge_gamma_hi,
            "edge_evidence": edge_evidence,
            "gamma_span_decay": gamma_span_decay,
            "t_span_s": span,
            "termination_reason": termination,
            "converged": converged,
            "omega_midpoint_singular_fallback": midpoint_fallback,
            "grid_evaluations": grid_evaluations,
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
                fitted["phase_rad"], fitted["gamma_per_s"],
                parsed.truth),
        },
    }
