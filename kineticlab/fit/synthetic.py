"""Deterministic synthetic pendulum trajectories for estimator testing (KL-5.1).

SYNTHETIC TEST DATA — NOT MEASUREMENTS. Every value this module
produces is fixture data for testing the P-005 physics estimator
(master plan Stage 5, ``PLAN.md`` Phase P-005). Generated angles,
pixels, timestamps, and noise are invented by a seeded generator;
they support no physical claim about any pendulum, carry no
calibration, and must never be presented as measured data. The
``DISCLAIMER`` string below is embedded in every JSON export and
heads every CSV export.

Models (closed-form small-angle pendulums; GENERATE only, no fit):

- ``ideal``: ``theta(t) = A * cos(omega * t + phi)`` — the
  small-angle closed form of the plan's M1
  (``theta'' + (g/L) sin(theta) = 0`` with ``sin(theta) ~= theta``).
- ``damped``: ``theta(t) = A * exp(-gamma * t) * cos(omega * t + phi)``
  — the small-angle closed form of the plan's M2 (M1 plus linear
  damping ``gamma * theta'``).

These are exact closed-form curves, NOT integrated ODE
trajectories: no solver, no tolerance, no convergence state. Fitting
M1/M2 against this output is KL-5.2/KL-5.3 work; this module never
fits, estimates gravity, or reports uncertainty.

Generation runs in ANGLE space, then projects to observation-like
pixel positions through a documented synthetic projection with an
explicit TEST scale (never a calibration claim)::

    x = pivot_x_px + length_px * sin(theta)
    y = pivot_y_px + length_px * cos(theta)

``theta`` is measured from the downward vertical; the pixel frame
is top-left origin, +x right, +y down (contracts coordinate rule).
``length_px`` is a caller-supplied TEST CONSTANT in pixels, not a
physical length.

Seeding discipline: ``seed`` (any JSON int) feeds exactly one
``random.Random`` stream per trajectory. The draw order is fixed —
(1) jitter uniforms in ascending sample order (jittered time mode
only), then (2) noise pairs ``(x, y)`` in ascending grid order for
EVERY grid index (gap indices draw and discard, so noise is
independent of the gap list). Same seed + same spec = identical
bytes on a given platform/CPython+libm build. Cross-platform float
bit-identity is NOT promised (libm ``sin``/``cos``/``exp`` may
differ in the last ulp); determinism tests pin exact bytes on the
verified platform and note the caveat.

Spec schema (plain dict; every key required, unknown keys rejected):

- ``model``: ``"ideal"`` | ``"damped"``.
- ``seed``: int (bool rejected).
- ``amplitude_rad``: finite float >= 0.
- ``angular_frequency_per_s`` / ``period_s``: exactly one non-null;
  whichever is set must be finite and > 0 (``omega = 2*pi/period``).
- ``phase_rad``: finite float.
- ``damping_per_s``: null iff ``model == "ideal"``; finite float
  >= 0 iff ``model == "damped"``.
- ``pivot_x_px``, ``pivot_y_px``: finite floats.
- ``length_px``: finite float > 0 (TEST CONSTANT).
- ``time``: ``{"mode": "uniform", "t0_s", "dt_s", "n"}`` (``dt_s`` > 0,
  ``1 <= n <= MAX_SAMPLES``); ``{"mode": "jittered", ...,
  "jitter_s"}`` (``0 <= 2*jitter_s < dt_s``, so jitter can never
  break strict monotonicity structurally); or ``{"mode":
  "explicit", "times_s": [...]}`` (``1 <= len <= MAX_SAMPLES``,
  finite, strictly increasing).
- ``noise``: ``{"mode": "none"}`` or ``{"mode": "gaussian",
  "sigma_px"}`` (finite, >= 0; independent ``Random.gauss(0, sigma)``
  draws added to x and y).
- ``gaps``: list of ``[start, end]`` inclusive sample-index ranges
  on the full grid; sorted, non-overlapping, within ``[0, n)``.
  Gapped indices emit no sample but keep their indices (gaps are
  visible as missing ``sample_index`` values).
- ``outliers``: list of ``{"sample_index", "dx_px", "dy_px"}``;
  indices unique, within ``[0, n)``, never inside a gap; the
  offset is added to the observed position AFTER noise.

Ground truth ships with the trajectory: ``ground_truth`` echoes
the effective angle parameters (including which frequency source
was given), the projection constants, the time/noise specs, the
gap list with time bounds, and the outlier list WITH true
positions. Each sample carries ``theta_rad`` plus the clean
(``true_x_px``/``true_y_px``) and observed (``x_px``/``y_px``)
positions, so a consumer can verify recovery without re-running
the generator.

Failure map (registered codes only, full error collection with
nested paths such as ``time.dt_s`` or ``outliers[2].dx_px``):

- non-dict spec / non-dict ``time``/``noise`` / non-list ``gaps`` /
  ``outliers`` / ``times_s`` -> ``E_WRONG_TYPE``.
- unknown spec keys -> ``E_UNEXPECTED_FIELD``; absent keys ->
  ``E_MISSING_FIELD``; null where a value is required ->
  ``E_NULL_NOT_ALLOWED``.
- unknown ``model``/``time.mode``/``noise.mode`` -> ``E_BAD_ENUM``;
  bool where int/float is required -> ``E_WRONG_TYPE``.
- NaN/inf numerics -> ``E_NON_FINITE``; range violations
  (negative amplitude, non-positive frequency/period/length/dt,
  negative damping/jitter/sigma, ``n``/list length outside
  ``1..MAX_SAMPLES``, ``2*jitter_s >= dt_s``) -> ``E_OUT_OF_RANGE``.
- both/neither frequency source set; damping present for
  ``ideal`` or missing for ``damped``; gap bounds inverted,
  out of range, unsorted, or overlapping; outlier index out of
  range, duplicated, or inside a gap -> ``E_INCOHERENT_VALUE``.
- explicit ``times_s`` not strictly increasing ->
  ``E_NON_MONOTONIC_PTS`` (mirrors the frame-table contract).

Exports follow the ``result`` style: ``export_trajectory_json``
emits canonical bytes (sorted keys, indent 2, ASCII-only, single
trailing LF) and ``parse_trajectory_json`` inverts them;
``export_synthetic_csv`` flattens samples under the fixed
``CSV_COLUMNS`` contract (disclaimer ``#`` line, then header
always, then one row per sample; floats via repr; ``is_outlier``
renders ``true``/``false``). CSV is presentation-grade: no parser
by design, JSON stays the lossless form.
"""

from __future__ import annotations

import csv
import io
import json
import math
import random
from typing import Any

from kineticlab.contracts import ContractError, FieldError

GENERATOR_NAME = "kineticlab.fit.synthetic"

DISCLAIMER = (
    "SYNTHETIC TEST DATA — generated fixture values, not measurements; "
    "no physical claim, no calibration."
)

JSON_INDENT = 2

MAX_SAMPLES = 100_000
"""Documented upper bound on grid samples (keeps generation bounded)."""

CSV_COLUMNS = (
    "sample_index",
    "t_seconds",
    "theta_rad",
    "true_x_px",
    "true_y_px",
    "x_px",
    "y_px",
    "is_outlier",
)
"""Fixed synthetic-trajectory CSV column contract (order significant)."""

TOP_LEVEL_KEYS = frozenset({
    "model",
    "seed",
    "amplitude_rad",
    "angular_frequency_per_s",
    "period_s",
    "phase_rad",
    "damping_per_s",
    "pivot_x_px",
    "pivot_y_px",
    "length_px",
    "time",
    "noise",
    "gaps",
    "outliers",
})

TIME_KEYS = {
    "uniform": frozenset({"mode", "t0_s", "dt_s", "n"}),
    "jittered": frozenset({"mode", "t0_s", "dt_s", "n", "jitter_s"}),
    "explicit": frozenset({"mode", "times_s"}),
}

NOISE_KEYS = {
    "none": frozenset({"mode"}),
    "gaussian": frozenset({"mode", "sigma_px"}),
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_float(value: Any) -> bool:
    return ((_is_int(value) or isinstance(value, float))
            and not isinstance(value, bool))


class _Spec:
    """Validated spec: field pass collects type/shape errors, then the
    cross-field pass collects coherence errors. Generation only runs
    when both passes are clean."""

    def __init__(self, spec: Any) -> None:
        self.errors: list[FieldError] = []
        self.spec = spec
        self.model = ""
        self.seed = 0
        self.amplitude = 0.0
        self.omega = 0.0
        self.omega_source = ""
        self.phase = 0.0
        self.damping = 0.0
        self.pivot_x = 0.0
        self.pivot_y = 0.0
        self.length = 0.0
        self.times: list[float] = []
        self.time_spec: dict[str, Any] = {}
        self.noise_spec: dict[str, Any] = {}
        self.sigma: float | None = None
        self.jitter: float | None = None
        self.gaps: list[tuple[int, int]] = []
        self.outliers: list[dict[str, Any]] = []

    def fail(self, code: str, field: str | None, message: str) -> None:
        self.errors.append(FieldError(code, field, message))

    def check_keys(self, data: Any, expected: frozenset[str], where: str) -> bool:
        if not isinstance(data, dict):
            self.fail("E_WRONG_TYPE", where or None,
                      f"expected an object, got {type(data).__name__}")
            return False
        for key in sorted(set(data) - expected):
            self.fail("E_UNEXPECTED_FIELD",
                      f"{where}.{key}" if where else key,
                      f"unknown key {key!r}")
        for key in sorted(expected - set(data)):
            self.fail("E_MISSING_FIELD",
                      f"{where}.{key}" if where else key,
                      f"required key {key!r} is absent")
        return True

    def read_float(self, data: dict, key: str, where: str, *,
                   allow_null: bool, minimum: float | None = None,
                   maximum: float | None = None,
                   strict_min: bool = False) -> float | None:
        field = f"{where}.{key}" if where else key
        if key not in data:
            return None
        value = data[key]
        if value is None:
            if not allow_null:
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
        if maximum is not None and number > maximum:
            self.fail("E_OUT_OF_RANGE", field,
                      f"value {number!r} is outside the locked range "
                      f"(<= {maximum})")
            return None
        return number

    def read_int(self, data: dict, key: str, where: str, *,
                 minimum: int | None = None,
                 maximum: int | None = None) -> int | None:
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
        if maximum is not None and value > maximum:
            self.fail("E_OUT_OF_RANGE", field,
                      f"value {value!r} is outside the locked range "
                      f"(<= {maximum})")
            return None
        return value

    def validate(self) -> None:
        if not self.check_keys(self.spec, TOP_LEVEL_KEYS, ""):
            raise ContractError(self.errors)
        spec = self.spec

        model = spec.get("model")
        if "model" in spec:
            if model is None:
                self.fail("E_NULL_NOT_ALLOWED", "model",
                          "value is null where a value is required")
            elif not isinstance(model, str) or model not in ("ideal", "damped"):
                self.fail("E_BAD_ENUM", "model",
                          f"expected 'ideal' or 'damped', got {model!r}")
            else:
                self.model = model

        seed = self.read_int_raw(spec, "seed", "")
        if seed is not None:
            self.seed = seed

        amplitude = self.read_float(spec, "amplitude_rad", "",
                                    allow_null=False, minimum=0.0)
        if amplitude is not None:
            self.amplitude = amplitude

        omega = self.read_float(spec, "angular_frequency_per_s", "",
                                allow_null=True, minimum=0.0, strict_min=True)
        period = self.read_float(spec, "period_s", "",
                                 allow_null=True, minimum=0.0, strict_min=True)
        if omega is not None and period is not None:
            self.fail("E_INCOHERENT_VALUE", "angular_frequency_per_s",
                      "set exactly one of angular_frequency_per_s/period_s, "
                      "not both")
        elif omega is None and period is None and not any(
                error.field in ("angular_frequency_per_s", "period_s")
                for error in self.errors):
            self.fail("E_INCOHERENT_VALUE", "angular_frequency_per_s",
                      "one of angular_frequency_per_s/period_s is required")
        elif omega is not None:
            self.omega = omega
            self.omega_source = "angular_frequency_per_s"
        elif period is not None:
            self.omega = 2.0 * math.pi / period
            self.omega_source = "period_s"

        phase = self.read_float(spec, "phase_rad", "", allow_null=False)
        if phase is not None:
            self.phase = phase

        damping = self.read_float(spec, "damping_per_s", "",
                                  allow_null=True, minimum=0.0)
        if "damping_per_s" in spec:
            if self.model == "ideal" and damping is not None:
                self.fail("E_INCOHERENT_VALUE", "damping_per_s",
                          "damping_per_s must be null for model 'ideal'")
            elif self.model == "damped":
                if damping is None and not any(
                        error.field == "damping_per_s"
                        for error in self.errors):
                    self.fail("E_INCOHERENT_VALUE", "damping_per_s",
                            "damping_per_s is required for model 'damped'")
                elif damping is not None:
                    self.damping = damping

        pivot_x = self.read_float(spec, "pivot_x_px", "", allow_null=False)
        if pivot_x is not None:
            self.pivot_x = pivot_x
        pivot_y = self.read_float(spec, "pivot_y_px", "", allow_null=False)
        if pivot_y is not None:
            self.pivot_y = pivot_y
        length = self.read_float(spec, "length_px", "",
                                 allow_null=False, minimum=0.0,
                                 strict_min=True)
        if length is not None:
            self.length = length

        self.validate_time(spec.get("time"))
        self.validate_noise(spec.get("noise"))
        self.validate_gaps(spec.get("gaps"))
        self.validate_outliers(spec.get("outliers"))

        if self.errors:
            raise ContractError(self.errors)
        self.validate_cross_fields()
        if self.errors:
            raise ContractError(self.errors)

    def read_int_raw(self, data: dict, key: str, where: str) -> int | None:
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
        return value

    def validate_time(self, time: Any) -> None:
        if "time" not in self.spec:
            return
        if not isinstance(time, dict):
            self.fail("E_WRONG_TYPE", "time",
                      f"expected an object, got {type(time).__name__}")
            return
        mode = time.get("mode")
        if "mode" not in time:
            self.fail("E_MISSING_FIELD", "time.mode",
                      "required key 'mode' is absent")
            return
        if mode is None:
            self.fail("E_NULL_NOT_ALLOWED", "time.mode",
                      "value is null where a value is required")
            return
        if not isinstance(mode, str) or mode not in TIME_KEYS:
            self.fail("E_BAD_ENUM", "time.mode",
                      f"expected one of {sorted(TIME_KEYS)}, got {mode!r}")
            return
        self.check_keys(time, TIME_KEYS[mode], "time")
        self.time_spec = {"mode": mode}
        if mode in ("uniform", "jittered"):
            t0 = self.read_float(time, "t0_s", "time", allow_null=False)
            dt = self.read_float(time, "dt_s", "time", allow_null=False,
                                 minimum=0.0, strict_min=True)
            count = self.read_int(time, "n", "time", minimum=1,
                                  maximum=MAX_SAMPLES)
            jitter = None
            if mode == "jittered":
                jitter = self.read_float(time, "jitter_s", "time",
                                         allow_null=False, minimum=0.0)
            if t0 is None or dt is None or count is None:
                return
            if mode == "jittered" and jitter is None:
                return
            if (mode == "jittered" and jitter is not None
                    and 2.0 * jitter >= dt):
                self.fail("E_OUT_OF_RANGE", "time.jitter_s",
                          f"2*jitter_s ({2.0 * jitter!r}) must be < dt_s "
                          f"({dt!r}) so jitter cannot break monotonicity")
                return
            self.time_spec.update({"t0_s": t0, "dt_s": dt, "n": count})
            if mode == "jittered":
                self.time_spec["jitter_s"] = jitter
                self.jitter = jitter
            self.times = [t0 + index * dt for index in range(count)]
        else:
            if "times_s" not in time:
                return
            raw = time["times_s"]
            if raw is None:
                self.fail("E_NULL_NOT_ALLOWED", "time.times_s",
                          "value is null where a value is required")
                return
            if not isinstance(raw, list):
                self.fail("E_WRONG_TYPE", "time.times_s",
                          f"expected a list, got {type(raw).__name__}")
                return
            if not 1 <= len(raw) <= MAX_SAMPLES:
                self.fail("E_OUT_OF_RANGE", "time.times_s",
                          f"expected 1..{MAX_SAMPLES} entries, got {len(raw)}")
                return
            values: list[float] = []
            clean = True
            for index, item in enumerate(raw):
                field = f"time.times_s[{index}]"
                if item is None:
                    self.fail("E_NULL_NOT_ALLOWED", field,
                              "value is null where a value is required")
                    clean = False
                elif not _is_float(item):
                    self.fail("E_WRONG_TYPE", field,
                              f"expected a number, got {type(item).__name__}")
                    clean = False
                elif not math.isfinite(float(item)):
                    self.fail("E_NON_FINITE", field,
                              "value must be finite (NaN/inf rejected)")
                    clean = False
                else:
                    values.append(float(item))
            if not clean:
                return
            for index in range(1, len(values)):
                if values[index] <= values[index - 1]:
                    self.fail("E_NON_MONOTONIC_PTS",
                              f"time.times_s[{index}]",
                              f"explicit times must be strictly increasing "
                              f"({values[index - 1]!r} >= {values[index]!r})")
                    return
            self.time_spec = {"mode": mode, "times_s": values}
            self.times = values

    def validate_noise(self, noise: Any) -> None:
        if "noise" not in self.spec:
            return
        if not isinstance(noise, dict):
            self.fail("E_WRONG_TYPE", "noise",
                      f"expected an object, got {type(noise).__name__}")
            return
        mode = noise.get("mode")
        if "mode" not in noise:
            self.fail("E_MISSING_FIELD", "noise.mode",
                      "required key 'mode' is absent")
            return
        if mode is None:
            self.fail("E_NULL_NOT_ALLOWED", "noise.mode",
                      "value is null where a value is required")
            return
        if not isinstance(mode, str) or mode not in NOISE_KEYS:
            self.fail("E_BAD_ENUM", "noise.mode",
                      f"expected one of {sorted(NOISE_KEYS)}, got {mode!r}")
            return
        self.check_keys(noise, NOISE_KEYS[mode], "noise")
        self.noise_spec = {"mode": mode}
        if mode == "gaussian":
            sigma = self.read_float(noise, "sigma_px", "noise",
                                    allow_null=False, minimum=0.0)
            if sigma is not None:
                self.sigma = sigma
                self.noise_spec["sigma_px"] = sigma

    def validate_gaps(self, gaps: Any) -> None:
        if "gaps" not in self.spec:
            return
        if gaps is None:
            self.fail("E_NULL_NOT_ALLOWED", "gaps",
                      "value is null where a value is required")
            return
        if not isinstance(gaps, list):
            self.fail("E_WRONG_TYPE", "gaps",
                      f"expected a list, got {type(gaps).__name__}")
            return
        for index, entry in enumerate(gaps):
            field = f"gaps[{index}]"
            if (not isinstance(entry, list) or len(entry) != 2
                    or not all(_is_int(bound) for bound in entry)):
                self.fail("E_WRONG_TYPE", field,
                          "expected a [start, end] pair of ints")
                continue
            self.gaps.append((entry[0], entry[1]))

    def validate_outliers(self, outliers: Any) -> None:
        if "outliers" not in self.spec:
            return
        if outliers is None:
            self.fail("E_NULL_NOT_ALLOWED", "outliers",
                      "value is null where a value is required")
            return
        if not isinstance(outliers, list):
            self.fail("E_WRONG_TYPE", "outliers",
                      f"expected a list, got {type(outliers).__name__}")
            return
        for index, entry in enumerate(outliers):
            field = f"outliers[{index}]"
            if not isinstance(entry, dict):
                self.fail("E_WRONG_TYPE", field,
                          f"expected an object, got {type(entry).__name__}")
                continue
            self.check_keys(entry,
                            frozenset({"sample_index", "dx_px", "dy_px"}),
                            field)
            sample = self.read_int(entry, "sample_index", field)
            dx = self.read_float(entry, "dx_px", field, allow_null=False)
            dy = self.read_float(entry, "dy_px", field, allow_null=False)
            if sample is None or dx is None or dy is None:
                continue
            self.outliers.append({"sample_index": sample,
                                  "dx_px": dx, "dy_px": dy})

    def validate_cross_fields(self) -> None:
        count = len(self.times)
        for position, (start, end) in enumerate(self.gaps):
            field = f"gaps[{position}]"
            if start > end:
                self.fail("E_INCOHERENT_VALUE", field,
                          f"gap start ({start}) exceeds end ({end})")
            elif not (0 <= start <= end < count):
                self.fail("E_INCOHERENT_VALUE", field,
                          f"gap [{start}, {end}] is outside the grid "
                          f"[0, {count})")
            if position > 0 and self.gaps[position - 1][1] >= start:
                self.fail("E_INCOHERENT_VALUE", field,
                          "gaps must be sorted and non-overlapping")
        seen: set[int] = set()
        for position, entry in enumerate(self.outliers):
            field = f"outliers[{position}]"
            sample = entry["sample_index"]
            if not 0 <= sample < count:
                self.fail("E_INCOHERENT_VALUE", f"{field}.sample_index",
                          f"outlier index {sample} is outside the grid "
                          f"[0, {count})")
                continue
            if sample in seen:
                self.fail("E_INCOHERENT_VALUE", f"{field}.sample_index",
                          f"outlier index {sample} is listed twice")
                continue
            seen.add(sample)
            for (start, end) in self.gaps:
                if start <= sample <= end:
                    self.fail("E_INCOHERENT_VALUE",
                              f"{field}.sample_index",
                              f"outlier index {sample} falls inside gap "
                              f"[{start}, {end}]")
                    break


def _angle(spec: _Spec, time_s: float) -> float:
    value = spec.amplitude * math.cos(spec.omega * time_s + spec.phase)
    if spec.model == "damped":
        value *= math.exp(-spec.damping * time_s)
    return value


def generate_trajectory(spec: dict[str, Any]) -> dict[str, Any]:
    """Generate one deterministic synthetic trajectory from a spec dict.

    Pure function of its input: no I/O, no wall clock, one
    ``random.Random(seed)`` stream with the documented draw order.
    Raises ``ContractError`` (registered codes, full collection)
    for any malformed spec — never partial output.
    """
    parsed = _Spec(spec)
    parsed.validate()

    rng = random.Random(parsed.seed)
    times = list(parsed.times)
    if parsed.jitter is not None:
        half = parsed.jitter
        times = [moment + rng.uniform(-half, half) for moment in times]

    count = len(times)
    noise_x = [0.0] * count
    noise_y = [0.0] * count
    if parsed.sigma is not None:
        # Drawn for EVERY grid index (gap indices discard theirs) so
        # the noise stream does not depend on the gap list.
        for index in range(count):
            noise_x[index] = rng.gauss(0.0, parsed.sigma)
            noise_y[index] = rng.gauss(0.0, parsed.sigma)

    gapped = set()
    for (start, end) in parsed.gaps:
        gapped.update(range(start, end + 1))
    offsets = {entry["sample_index"]: (entry["dx_px"], entry["dy_px"])
               for entry in parsed.outliers}

    samples: list[dict[str, Any]] = []
    for index, moment in enumerate(times):
        if index in gapped:
            continue
        theta = _angle(parsed, moment)
        true_x = parsed.pivot_x + parsed.length * math.sin(theta)
        true_y = parsed.pivot_y + parsed.length * math.cos(theta)
        shift = offsets.get(index)
        samples.append({
            "sample_index": index,
            "t_seconds": moment,
            "theta_rad": theta,
            "true_x_px": true_x,
            "true_y_px": true_y,
            "x_px": true_x + noise_x[index]
            + (shift[0] if shift else 0.0),
            "y_px": true_y + noise_y[index]
            + (shift[1] if shift else 0.0),
            "is_outlier": shift is not None,
        })

    ground_gaps = [{
        "start_index": start,
        "end_index": end,
        "start_t_seconds": times[start],
        "end_t_seconds": times[end],
        "count": end - start + 1,
    } for (start, end) in parsed.gaps]
    ground_outliers = []
    for entry in parsed.outliers:
        index = entry["sample_index"]
        theta = _angle(parsed, times[index])
        ground_outliers.append({
            "sample_index": index,
            "t_seconds": times[index],
            "dx_px": entry["dx_px"],
            "dy_px": entry["dy_px"],
            "true_x_px": parsed.pivot_x + parsed.length * math.sin(theta),
            "true_y_px": parsed.pivot_y + parsed.length * math.cos(theta),
        })

    period = 2.0 * math.pi / parsed.omega
    return {
        "generator": GENERATOR_NAME,
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "model": parsed.model,
        "seed": parsed.seed,
        "ground_truth": {
            "model": parsed.model,
            "seed": parsed.seed,
            "amplitude_rad": parsed.amplitude,
            "angular_frequency_per_s": parsed.omega,
            "period_s": period,
            "omega_source": parsed.omega_source,
            "phase_rad": parsed.phase,
            "damping_per_s": (parsed.damping if parsed.model == "damped"
                              else None),
            "pivot_x_px": parsed.pivot_x,
            "pivot_y_px": parsed.pivot_y,
            "length_px": parsed.length,
            "time": parsed.time_spec,
            "noise": parsed.noise_spec,
            "gaps": ground_gaps,
            "outliers": ground_outliers,
        },
        "samples": samples,
    }


def export_trajectory_json(trajectory: dict[str, Any]) -> bytes:
    """Serialize a trajectory to canonical JSON bytes (lossless)."""
    if not isinstance(trajectory, dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None,
            "synthetic trajectory export requires a dict, got "
            f"{type(trajectory).__name__}")])
    text = json.dumps(trajectory, sort_keys=True, indent=JSON_INDENT,
                      ensure_ascii=True)
    return (text + "\n").encode("utf-8")


def parse_trajectory_json(data: bytes | str) -> dict[str, Any]:
    """Parse canonical JSON bytes back to a trajectory dict (inverse)."""
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
            "synthetic trajectory export must be a JSON object")])
    for key in ("generator", "synthetic", "disclaimer", "model", "seed",
                "ground_truth", "samples"):
        if key not in raw:
            raise ContractError([FieldError(
                "E_MISSING_FIELD", key,
                f"required key {key!r} is absent")])
    if not isinstance(raw["ground_truth"], dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "ground_truth",
            "expected an object, got "
            f"{type(raw['ground_truth']).__name__}")])
    if not isinstance(raw["samples"], list):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "samples",
            f"expected a list, got {type(raw['samples']).__name__}")])
    return raw


def _csv_cell(value: Any, field: str, *, boolean: bool = False) -> str:
    if boolean:
        if value is True:
            return "true"
        if value is False:
            return "false"
        raise ContractError([FieldError(
            "E_WRONG_TYPE", field,
            f"expected a bool, got {type(value).__name__}")])
    if isinstance(value, bool):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", field,
            f"expected a number, got {type(value).__name__}")])
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, int):
        return str(value)
    raise ContractError([FieldError(
        "E_WRONG_TYPE", field,
        f"expected a number, got {type(value).__name__}")])


def export_synthetic_csv(trajectory: dict[str, Any]) -> str:
    """Flatten samples to presentation-grade CSV text (LF, header always).

    The first line is a ``#``-prefixed disclaimer (part of the
    contract), then the ``CSV_COLUMNS`` header, then one row per
    sample in output order. No parser by design: JSON stays the
    lossless form.
    """
    if not isinstance(trajectory, dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None,
            "synthetic trajectory export requires a dict, got "
            f"{type(trajectory).__name__}")])
    samples = trajectory.get("samples")
    if samples is None:
        raise ContractError([FieldError(
            "E_MISSING_FIELD", "samples",
            "required key 'samples' is absent")])
    if not isinstance(samples, list):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "samples",
            f"expected a list, got {type(samples).__name__}")])
    buffer = io.StringIO(newline="")
    buffer.write(f"# {DISCLAIMER}\n")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for index, sample in enumerate(samples):
        where = f"samples[{index}]"
        if not isinstance(sample, dict):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", where,
                f"expected an object, got {type(sample).__name__}")])
        row = []
        for key in CSV_COLUMNS:
            if key not in sample:
                raise ContractError([FieldError(
                    "E_MISSING_FIELD", f"{where}.{key}",
                    f"required key {key!r} is absent")])
            row.append(_csv_cell(sample[key], f"{where}.{key}",
                                 boolean=(key == "is_outlier")))
        writer.writerow(row)
    return buffer.getvalue()
