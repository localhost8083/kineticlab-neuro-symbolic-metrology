"""Recovery/failure/repeatability matrix over the M1/M2 fits (KL-5.4).

CHARACTERIZATION ONLY — this module adds no estimators and no
statistical machinery. It runs the verified M1/M2 fitters
programmatically over seeded synthetic configs and reports the
outcomes as pure descriptive data: fitted-vs-truth errors,
tolerance-gate verdicts, termination/warning counts, and
repeatability facts. A stall is not a failure of honesty; it is a
fact the matrix shows.

The matrix exists to map WHERE the 1e-6 recovery tolerances hold
and where they do NOT — including the config-dependent M2
alternation stall (Fable-measured during KL-5.3 verification: a
clean 80-point/dt-0.04/omega-2.2/gamma-0.15 config stalls at
~2.6e-4 with converged:true regardless of budget, while a
200-point config recovers to 1e-11 and grid density correlates).
The stall boundary the matrix measures is reported in the
KL-5.4 completion log and handoff; ``KL-5-G5`` verifies "seeded
recovery within documented tolerance" against that matrix, not
against chosen configs.

Cell shape: each config names a synthetic trajectory spec (the
full KL-5.1 schema), a fitter (``"M1"``/``"M2"``), and fit
options (bounds, grid sizes, iteration budget). The matrix
generates the trajectory, assembles the fit request (points from
the trajectory, pivot geometry and truth from its ground truth —
damping truth defaults to 0.0 for ideal data, exactly as stated),
runs the fit, and records the FULL fit result plus computed
tolerance verdicts. Cross-model cells (M1 on damped data, M2 on
ideal data) are first-class: mismatch behavior is data.

Verdict vocabulary (fixed; the task pins it, so no guessing):

- per parameter: ``{"error", "tolerance", "within"}`` with
  ``within`` true iff the error is non-null and ``<=`` the
  applied tolerance. Non-converged best-iterate errors are
  gated factually (a best iterate CAN be within tolerance).
- cell ``recovery_pass`` true iff converged AND every parameter
  is within tolerance. Tolerances are the existing fitter
  constants (M1: amplitude/omega/phase; M2: plus gamma),
  echoed per cell with their provenance.

Failure coverage: budget-exhausted, flat-objective, and
bound/edge firing all arise from generator-produced configs and
appear as cells with counts/reasons in the summary.
``degenerate_design`` is UNREACHABLE from generator data (the
generator contract enforces strictly increasing times; only
pathological same-timestamp input triggers it) — it stays
covered by the fitter unit tests, and the matrix documents this
instead of faking a cell. Fit outcomes (including honest
non-convergence) are DATA; malformed matrix/config inputs raise
``ContractError`` with registered codes and cell-prefixed paths,
failing the whole run (never partial matrices).

Repeatability: the matrix run is a pure function of its request
(same request = identical bytes on a given platform, same libm
caveat as the fitters). Per-seed recovery facts appear as
descriptive counts/min/max/mean of errors ONLY — no confidence
intervals, no significance claims, no distribution assumptions.
The gate criterion "unsupported statistical claims absent" is
binding: this module computes no statistic beyond min/max/mean
of reported errors, and labels them descriptive.

Gravity and uncertainty honesty (KL-4.1 explicit-absence
pattern): no independent metric length exists in P-005, so the
matrix produces no gravity — every cell's ``gravity_m_s2`` is
null (asserted by audit tests, including a byte-level
``m/s^2``-absence check on exports). ``fit_uncertainty_method``
is ``"none"`` with ``W_UNCERTAINTY_UNAVAILABLE`` everywhere, and
the summary carries explicit ``uncertainty``/``gravity`` absence
records because no uncertainty is estimated (KL-6 owns real
uncertainty) — never a fabricated interval.

Request schema (strict keys; every key required):

- ``matrix_id``: non-empty string labeling the run.
- ``configs``: 1..``MAX_CELLS`` cells, unique non-empty
  ``config_id`` values, each with ``fitter`` (``"M1"``/``"M2"``),
  ``trajectory_spec`` (full synthetic spec), and ``fit_options``
  (``bounds`` + ``grid_n_omega`` [+ ``grid_n_gamma`` for M2] +
  ``max_refine_iterations``; fitter-specific keys, unknown keys
  rejected).

Failure map (registered codes only, full collection per cell):

- non-dict request/configs/options, bad scalar types ->
  ``E_WRONG_TYPE``; unknown keys -> ``E_UNEXPECTED_FIELD``;
  absent keys -> ``E_MISSING_FIELD``; nulls -> ``E_NULL_NOT_ALLOWED``.
- empty ``matrix_id``/``config_id`` -> ``E_EMPTY_STRING``;
  duplicated ``config_id`` -> ``E_INCOHERENT_VALUE``; empty or
  over-``MAX_CELLS`` config list -> ``E_OUT_OF_RANGE``; unknown
  ``fitter`` -> ``E_BAD_ENUM``.
- trajectory-spec violations propagate from the generator with
  ``configs[i].trajectory_spec.`` path prefixes; fit-option
  violations propagate from the fitter with
  ``configs[i].fit_options.`` prefixes — codes preserved.

Runtime bound: no hard grid caps are enforced (grid sizes are
caller-owned cost, like iteration budgets), but the shipped test
matrix caps M2 grids at 150x40 / M1 at 200 points so the matrix
suite adds bounded time (measured and recorded in tests).
Split sweeps larger than ``MAX_CELLS`` into several runs.

Exports follow the result style: ``export_matrix_json`` emits
canonical bytes and ``parse_matrix_json`` inverts them,
re-validating each cell's fit record through ``FitRecord``
(codes-preserved with cell paths) and re-checking verdict
coherence (stored ``within``/``recovery_pass`` must equal
recomputation, else ``E_INCOHERENT_VALUE``). No CSV export: the
task does not call for one.
"""

from __future__ import annotations

import json
from typing import Any

from kineticlab.contracts import (
    ContractError,
    FieldError,
    FitRecord,
)
from kineticlab.fit.m1 import (
    RECOVERY_TOL_AMPLITUDE_RAD,
    RECOVERY_TOL_OMEGA_PER_S,
    RECOVERY_TOL_PHASE_RAD,
    TEST_CONVENTION_NOTE,
    fit_m1,
)
from kineticlab.fit.m2 import (
    RECOVERY_TOL_GAMMA_PER_S,
    fit_m2,
)
from kineticlab.fit.synthetic import (
    JSON_INDENT,
    generate_trajectory,
)

MATRIX_FITTER = "kineticlab.fit.matrix"

MAX_CELLS = 64
"""Structural bound on cells per run (split larger sweeps)."""

M1_TOLERANCES = {
    "amplitude_rad": RECOVERY_TOL_AMPLITUDE_RAD,
    "omega_per_s": RECOVERY_TOL_OMEGA_PER_S,
    "phase_rad": RECOVERY_TOL_PHASE_RAD,
}
"""M1 verdict tolerances (provenance: kineticlab.fit.m1 constants)."""

M2_TOLERANCES = {
    "amplitude_rad": RECOVERY_TOL_AMPLITUDE_RAD,
    "omega_per_s": RECOVERY_TOL_OMEGA_PER_S,
    "phase_rad": RECOVERY_TOL_PHASE_RAD,
    "gamma_per_s": RECOVERY_TOL_GAMMA_PER_S,
}
"""M2 verdict tolerances (m1 constants + m2 gamma constant)."""

REQUEST_KEYS = frozenset({"matrix_id", "configs"})

CONFIG_KEYS = frozenset({
    "config_id",
    "fitter",
    "trajectory_spec",
    "fit_options",
})

FIT_OPTION_KEYS = {
    "M1": frozenset({"bounds", "grid_n_omega", "max_refine_iterations"}),
    "M2": frozenset({"bounds", "grid_n_omega", "grid_n_gamma",
                     "max_refine_iterations"}),
}

M1_BOUNDS_KEYS = frozenset({"amplitude_rad", "omega_per_s"})
M2_BOUNDS_KEYS = frozenset({"amplitude_rad", "omega_per_s", "gamma_per_s"})

MATRIX_EXPORT_KEYS = frozenset({
    "matrix_id",
    "fitter_surface",
    "test_convention_note",
    "cells",
    "summary",
})


class _MatrixRequest:
    """Validated matrix request envelope (shape only; content runs later).

    Shape errors across all cells are collected and raised together.
    Execution errors (trajectory/fit content) fail fast per cell, in
    order — a matrix run either completes whole or raises; partial
    matrices never escape.
    """

    def __init__(self, request: Any) -> None:
        self.errors: list[FieldError] = []
        self.request = request
        self.matrix_id = ""
        self.configs: list[dict[str, Any]] = []

    def fail(self, code: str, field: str | None, message: str) -> None:
        self.errors.append(FieldError(code, field, message))

    def validate(self) -> None:
        if not isinstance(self.request, dict):
            self.fail("E_WRONG_TYPE", None,
                      "matrix request must be an object, got "
                      f"{type(self.request).__name__}")
            raise ContractError(self.errors)
        request = self.request
        for key in sorted(set(request) - REQUEST_KEYS):
            self.fail("E_UNEXPECTED_FIELD", key, f"unknown key {key!r}")
        for key in sorted(REQUEST_KEYS - set(request)):
            self.fail("E_MISSING_FIELD", key,
                      f"required key {key!r} is absent")
        if "matrix_id" in request:
            value = request["matrix_id"]
            if value is None:
                self.fail("E_NULL_NOT_ALLOWED", "matrix_id",
                          "value is null where a value is required")
            elif not isinstance(value, str):
                self.fail("E_WRONG_TYPE", "matrix_id",
                          f"expected a string, got {type(value).__name__}")
            elif not value:
                self.fail("E_EMPTY_STRING", "matrix_id",
                          "matrix_id must not be empty")
            else:
                self.matrix_id = value
        if "configs" in request:
            self.validate_configs(request["configs"])
        if self.errors:
            raise ContractError(self.errors)

    def validate_configs(self, configs: Any) -> None:
        if configs is None:
            self.fail("E_NULL_NOT_ALLOWED", "configs",
                      "value is null where a value is required")
            return
        if not isinstance(configs, list):
            self.fail("E_WRONG_TYPE", "configs",
                      f"expected a list, got {type(configs).__name__}")
            return
        if not 1 <= len(configs) <= MAX_CELLS:
            self.fail("E_OUT_OF_RANGE", "configs",
                      f"expected 1..{MAX_CELLS} configs, got {len(configs)}")
            return
        seen: set[str] = set()
        clean: list[dict[str, Any]] = []
        failed = False
        for index, entry in enumerate(configs):
            where = f"configs[{index}]"
            if not isinstance(entry, dict):
                self.fail("E_WRONG_TYPE", where,
                          f"expected an object, got {type(entry).__name__}")
                failed = True
                continue
            entry_failed = False
            for key in sorted(set(entry) - CONFIG_KEYS):
                self.fail("E_UNEXPECTED_FIELD", f"{where}.{key}",
                          f"unknown key {key!r}")
                entry_failed = True
            for key in sorted(CONFIG_KEYS - set(entry)):
                self.fail("E_MISSING_FIELD", f"{where}.{key}",
                          f"required key {key!r} is absent")
                entry_failed = True
            config_id = entry.get("config_id")
            if "config_id" in entry:
                if config_id is None:
                    self.fail("E_NULL_NOT_ALLOWED", f"{where}.config_id",
                              "value is null where a value is required")
                    entry_failed = True
                elif not isinstance(config_id, str):
                    self.fail("E_WRONG_TYPE", f"{where}.config_id",
                              "expected a string, got "
                              f"{type(config_id).__name__}")
                    entry_failed = True
                elif not config_id:
                    self.fail("E_EMPTY_STRING", f"{where}.config_id",
                              "config_id must not be empty")
                    entry_failed = True
                elif config_id in seen:
                    self.fail("E_INCOHERENT_VALUE", f"{where}.config_id",
                              f"config_id {config_id!r} is already used")
                    entry_failed = True
                else:
                    seen.add(config_id)
            fitter = entry.get("fitter")
            if "fitter" in entry:
                if fitter is None:
                    self.fail("E_NULL_NOT_ALLOWED", f"{where}.fitter",
                              "value is null where a value is required")
                    entry_failed = True
                elif fitter not in ("M1", "M2"):
                    self.fail("E_BAD_ENUM", f"{where}.fitter",
                              f"expected 'M1' or 'M2', got {fitter!r}")
                    entry_failed = True
            if "trajectory_spec" in entry:
                spec = entry["trajectory_spec"]
                if spec is None:
                    self.fail("E_NULL_NOT_ALLOWED",
                              f"{where}.trajectory_spec",
                              "value is null where a value is required")
                    entry_failed = True
                elif not isinstance(spec, dict):
                    self.fail("E_WRONG_TYPE", f"{where}.trajectory_spec",
                              f"expected an object, got {type(spec).__name__}")
                    entry_failed = True
            if "fit_options" in entry:
                options = entry["fit_options"]
                if options is None:
                    self.fail("E_NULL_NOT_ALLOWED", f"{where}.fit_options",
                              "value is null where a value is required")
                    entry_failed = True
                elif not isinstance(options, dict):
                    self.fail("E_WRONG_TYPE", f"{where}.fit_options",
                              "expected an object, got "
                              f"{type(options).__name__}")
                    entry_failed = True
                elif fitter in FIT_OPTION_KEYS:
                    expected = FIT_OPTION_KEYS[fitter]
                    for key in sorted(set(options) - expected):
                        self.fail("E_UNEXPECTED_FIELD",
                                  f"{where}.fit_options.{key}",
                                  f"unknown key {key!r}")
                        entry_failed = True
                    for key in sorted(expected - set(options)):
                        self.fail("E_MISSING_FIELD",
                                  f"{where}.fit_options.{key}",
                                  f"required key {key!r} is absent")
                        entry_failed = True
            if entry_failed:
                failed = True
                continue
            clean.append(entry)
        if not failed:
            self.configs = clean


def _prefix_errors(error: ContractError, prefix: str) -> ContractError:
    return ContractError([
        FieldError(item.code,
                   prefix + (f".{item.field}" if item.field else ""),
                   item.message)
        for item in error.errors
    ])


def _run_cell(config: dict[str, Any], index: int) -> dict[str, Any]:
    """Generate, fit, and gate one cell (fail-fast on bad content)."""
    where = f"configs[{index}]"
    try:
        trajectory = generate_trajectory(config["trajectory_spec"])
    except ContractError as error:
        raise _prefix_errors(error, f"{where}.trajectory_spec") from error
    ground = trajectory["ground_truth"]
    damping = ground["damping_per_s"]
    truth: dict[str, float] = {
        "amplitude_rad": ground["amplitude_rad"],
        "angular_frequency_per_s": ground["angular_frequency_per_s"],
        "phase_rad": ground["phase_rad"],
    }
    fitter = config["fitter"]
    if fitter == "M2":
        truth["damping_per_s"] = damping if damping is not None else 0.0
    options = config["fit_options"]
    fit_request: dict[str, Any] = {
        "points": [{"t_seconds": sample["t_seconds"],
                    "x_px": sample["x_px"],
                    "y_px": sample["y_px"]}
                   for sample in trajectory["samples"]],
        "pivot_x_px": ground["pivot_x_px"],
        "pivot_y_px": ground["pivot_y_px"],
        "bounds": options["bounds"],
        "grid_n_omega": options["grid_n_omega"],
        "max_refine_iterations": options["max_refine_iterations"],
        "truth": truth,
    }
    if fitter == "M2":
        fit_request["grid_n_gamma"] = options["grid_n_gamma"]
    try:
        result = fit_m1(fit_request) if fitter == "M1" else fit_m2(fit_request)
    except ContractError as error:
        raise _prefix_errors(error, f"{where}.fit_options") from error
    tolerances = dict(M1_TOLERANCES if fitter == "M1" else M2_TOLERANCES)
    errors = result["diagnostics"]["errors_vs_truth"] or {}
    per_parameter: dict[str, dict[str, Any]] = {}
    for param, tolerance in tolerances.items():
        error = errors.get(param)
        within = (isinstance(error, float) and error <= tolerance)
        per_parameter[param] = {"error": error, "tolerance": tolerance,
                                "within": within}
    recovery_pass = (result["diagnostics"]["converged"] is True
                     and all(item["within"]
                             for item in per_parameter.values()))
    return {
        "config_id": config["config_id"],
        "fitter": fitter,
        "generator_model": trajectory["model"],
        "seed": trajectory["seed"],
        "trajectory_spec": config["trajectory_spec"],
        "fit_options": options,
        "result": result,
        "tolerances": tolerances,
        "verdicts": {"per_parameter": per_parameter,
                     "recovery_pass": recovery_pass},
    }


def _describe(values: list[float]) -> dict[str, Any] | None:
    """Descriptive min/max/mean over converged-cell errors (or null)."""
    if not values:
        return None
    total = 0.0
    for value in values:
        total += value
    return {"n": len(values), "min": min(values), "max": max(values),
            "mean": total / len(values)}


def _summarize(cells: list[dict[str, Any]]) -> dict[str, Any]:
    """Pure descriptive summary over cells (no verdicts beyond gates)."""
    by_fitter: dict[str, dict[str, int]] = {
        name: {"n_cells": 0, "n_converged": 0, "n_recovery_pass": 0}
        for name in ("M1", "M2")
    }
    terminations = {"refine_tolerance_met": 0,
                    "refine_budget_exhausted": 0,
                    "flat_objective_unidentifiable": 0,
                    "degenerate_design": 0}
    warning_counts: dict[str, int] = {}
    pass_cells: list[str] = []
    fail_cells: list[str] = []
    nonconverged_cells: list[str] = []
    for cell in cells:
        fitter = cell["fitter"]
        by_fitter[fitter]["n_cells"] += 1
        diagnostics = cell["result"]["diagnostics"]
        reason = diagnostics["termination_reason"]
        if reason in terminations:
            terminations[reason] += 1
        for warning in cell["result"]["fit"]["warnings"]:
            code = warning["code"]
            warning_counts[code] = warning_counts.get(code, 0) + 1
        if cell["verdicts"]["recovery_pass"]:
            pass_cells.append(cell["config_id"])
        else:
            fail_cells.append(cell["config_id"])
        if diagnostics["converged"] is not True:
            nonconverged_cells.append(cell["config_id"])
        else:
            by_fitter[fitter]["n_converged"] += 1
        if cell["verdicts"]["recovery_pass"]:
            by_fitter[fitter]["n_recovery_pass"] += 1
    descriptives: dict[str, dict[str, Any]] = {}
    for fitter, tolerances in (("M1", M1_TOLERANCES),
                               ("M2", M2_TOLERANCES)):
        per_param: dict[str, Any] = {}
        for param in tolerances:
            values = [cell["result"]["diagnostics"]["errors_vs_truth"][param]
                      for cell in cells
                      if cell["fitter"] == fitter
                      and cell["result"]["diagnostics"]["converged"] is True
                      and isinstance(cell["result"]["diagnostics"]
                                     ["errors_vs_truth"].get(param), float)]
            per_param[param] = _describe(values)
        descriptives[fitter] = per_param
    uncertainty_everywhere = all(
        any(entry["code"] == "W_UNCERTAINTY_UNAVAILABLE"
            for entry in cell["result"]["fit"]["warnings"])
        for cell in cells)
    gravity_null_everywhere = all(
        cell["result"]["fit"]["gravity_m_s2"] is None for cell in cells)
    method_none_everywhere = all(
        cell["result"]["fit"]["fit_uncertainty_method"] == "none"
        for cell in cells)
    return {
        "n_cells": len(cells),
        "by_fitter": by_fitter,
        "terminations": terminations,
        "warning_counts": warning_counts,
        "recovery_pass_cells": pass_cells,
        "recovery_fail_cells": fail_cells,
        "nonconverged_cells": nonconverged_cells,
        "error_descriptives": descriptives,
        "uncertainty": {
            "estimated": False,
            "fit_uncertainty_method": "none",
            "method_none_in_every_cell": method_none_everywhere,
            "warning_present_in_every_cell": uncertainty_everywhere,
            "note": ("KL-5.4 estimates no uncertainty; real "
                     "uncertainty belongs to KL-6; intervals here "
                     "would be fabricated."),
        },
        "gravity": {
            "produced": False,
            "gravity_m_s2_null_in_every_cell": gravity_null_everywhere,
            # NOTE: this text deliberately avoids the literal unit
            # label "m/s^2" (spelled out instead) so the audit test
            # can assert byte-level absence of that label across the
            # whole export: no gravity quantity is ever reported.
            "note": ("No independent metric length exists in P-005; "
                     "g_over_l is TEST-convention omega^2; gravity "
                     "(SI meters per second squared) is never "
                     "produced from synthetic data."),
        },
    }


def run_matrix(request: dict[str, Any]) -> dict[str, Any]:
    """Run a recovery/failure/repeatability matrix (deterministic).

    Pure function of its input: cells run in list order through the
    verified generator + fitters, verdicts gate against the fitter
    tolerance constants, and the summary aggregates pure
    descriptive data. Raises ``ContractError`` (registered codes)
    for malformed requests — never partial matrices.
    """
    parsed = _MatrixRequest(request)
    parsed.validate()
    cells = [_run_cell(config, index)
             for index, config in enumerate(parsed.configs)]
    return {
        "matrix_id": parsed.matrix_id,
        "fitter_surface": MATRIX_FITTER,
        "test_convention_note": TEST_CONVENTION_NOTE,
        "cells": cells,
        "summary": _summarize(cells),
    }


def export_matrix_json(matrix: dict[str, Any]) -> bytes:
    """Serialize a matrix to canonical JSON bytes (lossless)."""
    if not isinstance(matrix, dict):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None,
            "matrix export requires a dict, got "
            f"{type(matrix).__name__}")])
    for key in ("matrix_id", "fitter_surface", "test_convention_note",
                "cells", "summary"):
        if key not in matrix:
            raise ContractError([FieldError(
                "E_MISSING_FIELD", key,
                f"required key {key!r} is absent")])
    text = json.dumps(matrix, sort_keys=True, indent=JSON_INDENT,
                      ensure_ascii=True)
    return (text + "\n").encode("utf-8")


def _check_verdicts(cell: dict[str, Any], where: str,
                    errors: list[FieldError]) -> None:
    """Recompute tolerance verdicts; stored values must match exactly."""
    tolerances = cell.get("tolerances")
    verdicts = cell.get("verdicts")
    diagnostics = cell.get("result", {}).get("diagnostics", {})
    reported = (diagnostics.get("errors_vs_truth")
                if isinstance(diagnostics, dict) else None)
    if not isinstance(tolerances, dict):
        errors.append(FieldError("E_WRONG_TYPE", f"{where}.tolerances",
                                 "expected an object, got "
                                 f"{type(tolerances).__name__}"))
        return
    if not isinstance(verdicts, dict):
        errors.append(FieldError("E_WRONG_TYPE", f"{where}.verdicts",
                                 "expected an object, got "
                                 f"{type(verdicts).__name__}"))
        return
    per_parameter = verdicts.get("per_parameter")
    if not isinstance(per_parameter, dict):
        errors.append(FieldError(
            "E_WRONG_TYPE", f"{where}.verdicts.per_parameter",
            "expected an object, got "
            f"{type(per_parameter).__name__}"))
        return
    coherent = True
    for param, tolerance in tolerances.items():
        if isinstance(tolerance, bool) or not isinstance(
                tolerance, (int, float)):
            errors.append(FieldError(
                "E_WRONG_TYPE", f"{where}.tolerances.{param}",
                "expected a number, got "
                f"{type(tolerance).__name__}"))
            coherent = False
            continue
        entry = per_parameter.get(param)
        if not isinstance(entry, dict) or not isinstance(
                entry.get("within"), bool):
            errors.append(FieldError(
                "E_WRONG_TYPE", f"{where}.verdicts.per_parameter.{param}",
                "expected an object with a bool 'within'"))
            coherent = False
            continue
        error = reported.get(param) if isinstance(reported, dict) else None
        expected = (isinstance(error, float) and error <= float(tolerance))
        if entry["within"] is not expected:
            coherent = False
    expected_pass = (diagnostics.get("converged") is True
                     and coherent
                     and all(item["within"] for item in per_parameter.values()
                             if isinstance(item, dict)
                             and isinstance(item.get("within"), bool))
                     and len(per_parameter) == len(tolerances))
    stored_pass = verdicts.get("recovery_pass")
    if not isinstance(stored_pass, bool):
        errors.append(FieldError(
            "E_WRONG_TYPE", f"{where}.verdicts.recovery_pass",
            f"expected a bool, got {type(stored_pass).__name__}"))
    elif stored_pass is not expected_pass or not coherent:
        errors.append(FieldError(
            "E_INCOHERENT_VALUE", f"{where}.verdicts",
            "stored verdicts disagree with recomputation from "
            "reported errors and tolerances"))


def parse_matrix_json(data: bytes | str) -> dict[str, Any]:
    """Parse canonical JSON bytes back to a matrix (honest inverse).

    Each cell's fit record re-validates through ``FitRecord`` and
    each cell's verdicts re-check against recomputation — a
    tampered matrix fails with registered codes, never parses
    silently.
    """
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
            "matrix export must be a JSON object")])
    errors: list[FieldError] = []
    for key in ("matrix_id", "fitter_surface", "test_convention_note",
                "cells", "summary"):
        if key not in raw:
            errors.append(FieldError(
                "E_MISSING_FIELD", key,
                f"required key {key!r} is absent"))
    if errors:
        raise ContractError(errors)
    cells = raw["cells"]
    if not isinstance(cells, list):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "cells",
            f"expected a list, got {type(cells).__name__}")])
    parsed_cells: list[dict[str, Any]] = []
    for index, cell in enumerate(cells):
        where = f"cells[{index}]"
        if not isinstance(cell, dict):
            errors.append(FieldError(
                "E_WRONG_TYPE", where,
                f"expected an object, got {type(cell).__name__}"))
            continue
        for key in ("config_id", "fitter", "generator_model", "seed",
                    "trajectory_spec", "fit_options", "result",
                    "tolerances", "verdicts"):
            if key not in cell:
                errors.append(FieldError(
                    "E_MISSING_FIELD", f"{where}.{key}",
                    f"required key {key!r} is absent"))
        if cell.get("fitter") not in ("M1", "M2"):
            errors.append(FieldError(
                "E_BAD_ENUM", f"{where}.fitter",
                f"expected 'M1' or 'M2', got {cell.get('fitter')!r}"))
        result = cell.get("result")
        if not isinstance(result, dict):
            errors.append(FieldError(
                "E_WRONG_TYPE", f"{where}.result",
                f"expected an object, got {type(result).__name__}"))
            continue
        if not isinstance(result.get("fit"), dict):
            errors.append(FieldError(
                "E_WRONG_TYPE", f"{where}.result.fit",
                "expected an object, got "
                f"{type(result.get('fit')).__name__}"))
            continue
        try:
            record = FitRecord.from_dict(result["fit"])
        except ContractError as error:
            errors.extend(
                FieldError(item.code,
                           f"{where}.result.fit"
                           + (f".{item.field}" if item.field else ""),
                           item.message)
                for item in error.errors)
            continue
        if not isinstance(result.get("diagnostics"), dict):
            errors.append(FieldError(
                "E_WRONG_TYPE", f"{where}.result.diagnostics",
                "expected an object, got "
                f"{type(result.get('diagnostics')).__name__}"))
            continue
        _check_verdicts(cell, where, errors)
        parsed_cells.append({**cell, "result": {**result,
                                                "fit": record.to_dict()}})
    if not isinstance(raw["summary"], dict):
        errors.append(FieldError(
            "E_WRONG_TYPE", "summary",
            f"expected an object, got {type(raw['summary']).__name__}"))
    if errors:
        raise ContractError(errors)
    return {"matrix_id": raw["matrix_id"],
            "fitter_surface": raw["fitter_surface"],
            "test_convention_note": raw["test_convention_note"],
            "cells": parsed_cells,
            "summary": raw["summary"]}
