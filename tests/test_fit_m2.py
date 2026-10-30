"""Bounded M2 fit tests (KL-5.3). Synthetic data only.

M2 exists because M1 recovery stands (KL-5.2 verified): the fitter
must recover planted (A, omega, phi, gamma) from pixel points
within documented tolerances on damped data, must warn honestly
(mismatch / non-convergence / bound hits, registered codes only),
must emit contract-valid M2 ``fit.v1`` records, and must be
deterministic. Measured clean-fit errors (~1e-10) sit 1000x+
below the 1e-6 tolerances. The byte pin is platform-caveated
(libm): do not assert it cross-machine. JSON export/parsing reuse
M1's shared envelope functions.
"""

import copy
import hashlib
import math
import unittest

from kineticlab.contracts import ContractError, FitRecord
from kineticlab.fit import (
    MISMATCH_MAX_DECAY,
    RECOVERY_TOL_AMPLITUDE_RAD,
    RECOVERY_TOL_GAMMA_PER_S,
    RECOVERY_TOL_OMEGA_PER_S,
    RECOVERY_TOL_PHASE_RAD,
    TEST_CONVENTION_NOTE,
    export_fit_json,
    fit_m2,
    generate_trajectory,
    parse_fit_json,
)
from kineticlab.fit.m2 import MISMATCH_DETAIL

# Byte pin for the pin-fit trajectory (noisy damped, seed 42, 60
# points, sigma 1.5 px, grid 150x40, budget 300). Measured on the
# verified Windows/CPython 3.15 platform; platform-bound.
FIT_JSON_SHA = "b84648314c40f79d594bccf35cc0a2ff9128eaa4f110a3566c6ff1297aeae135"

GRID_OMEGA = 150
GRID_GAMMA = 40
BUDGET = 300


def make_spec(**overrides):
    spec = {
        "model": "damped",
        "seed": 7,
        "amplitude_rad": 0.35,
        "angular_frequency_per_s": math.pi,
        "period_s": None,
        "phase_rad": 0.2,
        "damping_per_s": 0.1,
        "pivot_x_px": 512.0,
        "pivot_y_px": 288.0,
        "length_px": 200.0,
        "time": {"mode": "uniform", "t0_s": 0.0, "dt_s": 0.05, "n": 60},
        "noise": {"mode": "none"},
        "gaps": [],
        "outliers": [],
    }
    spec.update(overrides)
    return spec


def make_request(trajectory, bounds=None, grid_omega=GRID_OMEGA,
                 grid_gamma=GRID_GAMMA, budget=BUDGET, with_truth=True):
    ground = trajectory["ground_truth"]
    damping = ground["damping_per_s"]
    return {
        "points": [{"t_seconds": sample["t_seconds"],
                    "x_px": sample["x_px"],
                    "y_px": sample["y_px"]}
                   for sample in trajectory["samples"]],
        "pivot_x_px": ground["pivot_x_px"],
        "pivot_y_px": ground["pivot_y_px"],
        "bounds": ({"amplitude_rad": [0.0, 2.0],
                    "omega_per_s": [0.5, 8.0],
                    "gamma_per_s": [0.0, 2.0]}
                   if bounds is None else bounds),
        "grid_n_omega": grid_omega,
        "grid_n_gamma": grid_gamma,
        "max_refine_iterations": budget,
        "truth": ({"amplitude_rad": ground["amplitude_rad"],
                   "angular_frequency_per_s":
                   ground["angular_frequency_per_s"],
                   "phase_rad": ground["phase_rad"],
                   "damping_per_s": (damping if damping is not None
                                     else 0.0)}
                  if with_truth else None),
    }


def pin_trajectory():
    return generate_trajectory(make_spec(
        seed=42, noise={"mode": "gaussian", "sigma_px": 1.5}))


def warning_codes(result):
    return [entry["code"] for entry in result["fit"]["warnings"]]


def warning_details(result):
    return [entry["detail"] for entry in result["fit"]["warnings"]]


class M2Recovery(unittest.TestCase):
    def test_clean_recovery_within_tolerance(self):
        result = fit_m2(make_request(
            generate_trajectory(make_spec())))
        fit = result["fit"]
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertEqual(diag["termination_reason"],
                         "refine_tolerance_met")
        errors = diag["errors_vs_truth"]
        # Measured on the verified platform: A 8.9e-11, omega
        # 1.2e-10, phi 1.3e-10, gamma 2.0e-10 — 5000x+ headroom.
        self.assertLessEqual(errors["amplitude_rad"],
                             RECOVERY_TOL_AMPLITUDE_RAD)
        self.assertLessEqual(errors["omega_per_s"],
                             RECOVERY_TOL_OMEGA_PER_S)
        self.assertLessEqual(errors["phase_rad"],
                             RECOVERY_TOL_PHASE_RAD)
        self.assertLessEqual(errors["gamma_per_s"],
                             RECOVERY_TOL_GAMMA_PER_S)
        fitted = diag["fitted"]
        self.assertEqual(fit["parameters"]["g_over_l"],
                         fitted["omega_per_s"] * fitted["omega_per_s"])
        self.assertEqual(fit["parameters"]["gamma"],
                         fitted["gamma_per_s"])
        self.assertEqual(fit["parameter_units"],
                         {"g_over_l": "1/s^2", "gamma": "1/s"})
        self.assertEqual(fit["g_over_l_per_s2"],
                         fit["parameters"]["g_over_l"])
        self.assertEqual(fitted["period_s"],
                         2.0 * math.pi / fitted["omega_per_s"])
        self.assertEqual(fit["initial_conditions"]["theta0_rad"],
                         fitted["amplitude_rad"]
                         * math.cos(fitted["phase_rad"]))
        self.assertEqual(
            fit["initial_conditions"]["omega0_rad_s"],
            -fitted["amplitude_rad"] * fitted["gamma_per_s"]
            * math.cos(fitted["phase_rad"])
            - fitted["amplitude_rad"] * fitted["omega_per_s"]
            * math.sin(fitted["phase_rad"]))
        residual = fit["residual_summary"]
        self.assertEqual(residual["dof"], 56)
        self.assertLessEqual(residual["rmse"], residual["max_abs"])
        # Explicit loop, not sum() (3.12+ compensated summation
        # differs by 1ulp from plain accumulation).
        total = 0.0
        for entry in diag["residuals"]:
            total += entry["residual_rad"] * entry["residual_rad"]
        self.assertEqual(residual["rmse"], math.sqrt(total / 60))
        self.assertEqual(diag["objectives"]["final_ssr"], total)
        self.assertEqual(fit["observation_count"], 60)
        self.assertEqual(fit["rejected_count"], 0)
        self.assertEqual(fit["fit_uncertainty_method"], "none")
        self.assertIsNone(fit["pivot_length_mm"])
        self.assertEqual(fit["pivot_length_source"], "not_provided")
        self.assertIsNone(fit["gravity_m_s2"])
        self.assertEqual(fit["model_id"], "M2")
        # Clean interior recovery: the uncertainty warning only.
        self.assertEqual(warning_codes(result),
                         ["W_UNCERTAINTY_UNAVAILABLE"])
        self.assertEqual(fit["solver"], "closed_form_small_angle_damped")
        self.assertEqual(
            fit["optimizer"],
            "separable_omega_gamma_grid_linear_lsq"
            "_alternating_golden_refine_v1")
        self.assertEqual(diag["bound_hits"], [])
        self.assertFalse(diag["omega_grid_best_at_lower_edge"])
        self.assertFalse(diag["omega_grid_best_at_upper_edge"])
        self.assertFalse(diag["gamma_grid_best_at_lower_edge"])
        self.assertFalse(diag["gamma_grid_best_at_upper_edge"])
        self.assertFalse(diag["omega_midpoint_singular_fallback"])
        self.assertEqual(diag["weights"], "uniform")
        self.assertAlmostEqual(diag["gamma_span_decay"],
                               fitted["gamma_per_s"] * diag["t_span_s"])
        self.assertGreaterEqual(diag["gamma_span_decay"],
                                MISMATCH_MAX_DECAY)
        self.assertEqual(result["test_convention_note"],
                         TEST_CONVENTION_NOTE)
        FitRecord.from_dict(fit)

    def test_clean_recovery_second_config(self):
        trajectory = generate_trajectory(make_spec(
            seed=3, amplitude_rad=0.9, angular_frequency_per_s=1.7,
            phase_rad=-1.1, damping_per_s=0.25,
            time={"mode": "jittered", "t0_s": 0.0, "dt_s": 0.05,
                  "n": 60, "jitter_s": 0.01}))
        result = fit_m2(make_request(trajectory))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        errors = diag["errors_vs_truth"]
        # Measured: A 1.8e-10, omega 4.0e-11, phi 8.7e-11,
        # gamma 1.7e-10.
        self.assertLessEqual(errors["amplitude_rad"],
                             RECOVERY_TOL_AMPLITUDE_RAD)
        self.assertLessEqual(errors["omega_per_s"],
                             RECOVERY_TOL_OMEGA_PER_S)
        self.assertLessEqual(errors["phase_rad"],
                             RECOVERY_TOL_PHASE_RAD)
        self.assertLessEqual(errors["gamma_per_s"],
                             RECOVERY_TOL_GAMMA_PER_S)
        self.assertEqual(warning_codes(result),
                         ["W_UNCERTAINTY_UNAVAILABLE"])

    def test_micro_case_hand_check(self):
        # Hand case: A=1, omega=1, phi=0, gamma=0.1 at peak times
        # t = 2*pi*k (k = 0..4) plus zero crossings at pi/2,
        # 5*pi/2, 13*pi/2 (8 points; the crossings break integer
        # frequency aliases). Peak thetas are exactly
        # exp(-0.1*2*pi*k), so consecutive peak ratios give gamma
        # by closed form: gamma = -ln(b/a)/(2*pi), an INDEPENDENT
        # hand path alongside the joint fit. (A 5-point variant
        # stalls alternation on a diagonal ravine — documented in
        # the module; 8 points recover to the optimizer floor.)
        times = [0.0, math.pi / 2, 2 * math.pi, 5 * math.pi / 2,
                 4 * math.pi, 6 * math.pi, 13 * math.pi / 2,
                 8 * math.pi]
        trajectory = generate_trajectory(make_spec(
            amplitude_rad=1.0, angular_frequency_per_s=1.0,
            phase_rad=0.0, damping_per_s=0.1,
            pivot_x_px=0.0, pivot_y_px=0.0, length_px=1.0,
            time={"mode": "explicit", "times_s": times}))
        peak_thetas = [math.atan2(sample["x_px"], sample["y_px"])
                       for sample in trajectory["samples"]
                       if sample["t_seconds"] in
                       (0.0, 2 * math.pi, 4 * math.pi, 6 * math.pi,
                        8 * math.pi)]
        self.assertEqual(len(peak_thetas), 5)
        for earlier, later in zip(peak_thetas, peak_thetas[1:]):
            hand_gamma = -math.log(later / earlier) / (2 * math.pi)
            self.assertAlmostEqual(hand_gamma, 0.1, places=9)
        result = fit_m2(make_request(trajectory))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        errors = diag["errors_vs_truth"]
        # Measured: A 4.9e-10, omega 1.2e-10, phi 4.0e-10,
        # gamma 2.0e-10, SSR 1.3e-18.
        self.assertLessEqual(errors["amplitude_rad"],
                             RECOVERY_TOL_AMPLITUDE_RAD)
        self.assertLessEqual(errors["omega_per_s"],
                             RECOVERY_TOL_OMEGA_PER_S)
        self.assertLessEqual(errors["phase_rad"],
                             RECOVERY_TOL_PHASE_RAD)
        self.assertLessEqual(errors["gamma_per_s"],
                             RECOVERY_TOL_GAMMA_PER_S)
        self.assertLess(diag["objectives"]["final_ssr"], 1e-15)
        self.assertEqual(result["fit"]["residual_summary"]["dof"], 4)
        self.assertEqual(result["fit"]["observation_count"], 8)
        fitted = diag["fitted"]
        self.assertEqual(result["fit"]["parameters"]["g_over_l"],
                         fitted["omega_per_s"] * fitted["omega_per_s"])
        self.assertEqual(result["fit"]["parameters"]["gamma"],
                         fitted["gamma_per_s"])

    def test_noise_case_runs_and_reports(self):
        trajectory = generate_trajectory(make_spec(
            seed=11, noise={"mode": "gaussian", "sigma_px": 2.0},
            time={"mode": "uniform", "t0_s": 0.0, "dt_s": 0.05,
                  "n": 100}))
        result = fit_m2(make_request(trajectory))
        diag = result["diagnostics"]
        # Measured: converged, errors (2.6e-4, 1.8e-3, 6.4e-3,
        # 1.2e-3), rmse 0.0111 rad ~= sigma/L — reported as data,
        # with NO tolerance verdict (KL-5.4 owns verdicts) and no
        # spurious mismatch (gamma*span = 0.495).
        self.assertTrue(diag["converged"])
        self.assertTrue(diag["residuals_available"])
        self.assertEqual(len(diag["residuals"]), 100)
        residual = result["fit"]["residual_summary"]
        self.assertGreater(residual["rmse"], 0.0)
        self.assertLessEqual(residual["rmse"], residual["max_abs"])
        self.assertEqual(residual["dof"], 96)
        for value in diag["errors_vs_truth"].values():
            self.assertIsInstance(value, float)
            self.assertTrue(math.isfinite(value))
        self.assertEqual(warning_codes(result),
                         ["W_UNCERTAINTY_UNAVAILABLE"])

    def test_fit_ignores_generative_angles(self):
        trajectory = generate_trajectory(make_spec())
        baseline = export_fit_json(fit_m2(make_request(trajectory)))
        corrupted = copy.deepcopy(trajectory)
        for sample in corrupted["samples"]:
            sample["theta_rad"] = 999.0
        self.assertEqual(
            export_fit_json(fit_m2(make_request(corrupted))), baseline)

    def test_truth_null_gives_null_errors(self):
        result = fit_m2(make_request(generate_trajectory(make_spec()),
                                     with_truth=False))
        self.assertTrue(result["diagnostics"]["converged"])
        self.assertIsNone(result["diagnostics"]["errors_vs_truth"])


class M2Mismatch(unittest.TestCase):
    def test_ideal_data_raises_mismatch_warning(self):
        trajectory = generate_trajectory(
            make_spec(model="ideal", damping_per_s=None))
        result = fit_m2(make_request(trajectory))
        fit = result["fit"]
        diag = result["diagnostics"]
        # The fit is CORRECT (stationary, recovers A/omega/phi to
        # ~1e-10) but MUST NOT present as a confident damped fit:
        # gamma collapses to ~4.7e-10 with decay ~1.4e-9.
        self.assertTrue(diag["converged"])
        self.assertEqual(diag["termination_reason"],
                         "refine_tolerance_met")
        self.assertTrue(diag["gamma_grid_best_at_lower_edge"])
        self.assertLess(diag["gamma_span_decay"], MISMATCH_MAX_DECAY)
        self.assertEqual(
            warning_codes(result),
            ["W_UNCERTAINTY_UNAVAILABLE",
             "W_ASSUMPTION_UNVERIFIED",
             "W_ASSUMPTION_UNVERIFIED"])
        details = warning_details(result)
        self.assertIn("gamma grid best at the lower box edge",
                      details[1])
        self.assertEqual(details[2], MISMATCH_DETAIL)
        errors = diag["errors_vs_truth"]
        self.assertLessEqual(errors["amplitude_rad"],
                             RECOVERY_TOL_AMPLITUDE_RAD)
        self.assertLessEqual(errors["omega_per_s"],
                             RECOVERY_TOL_OMEGA_PER_S)
        self.assertLessEqual(errors["phase_rad"],
                             RECOVERY_TOL_PHASE_RAD)
        FitRecord.from_dict(fit)


class M2BoundWarnings(unittest.TestCase):
    def test_amplitude_hit_warns(self):
        trajectory = generate_trajectory(make_spec())
        result = fit_m2(make_request(
            trajectory, bounds={"amplitude_rad": [0.0, 0.1],
                                "omega_per_s": [0.5, 8.0],
                                "gamma_per_s": [0.0, 2.0]}))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertEqual(
            warning_codes(result),
            ["W_UNCERTAINTY_UNAVAILABLE", "W_ASSUMPTION_UNVERIFIED"])
        details = warning_details(result)
        self.assertIn("amplitude_rad projected onto the upper box bound",
                      details[1])
        self.assertEqual(len(diag["bound_hits"]), 1)
        hit = diag["bound_hits"][0]
        self.assertEqual(hit["bound_value"], 0.1)
        self.assertAlmostEqual(hit["unclamped_value"], 0.35)
        self.assertEqual(diag["fitted"]["amplitude_rad"], 0.1)

    def test_omega_edge_warns(self):
        trajectory = generate_trajectory(make_spec())
        result = fit_m2(make_request(
            trajectory, bounds={"amplitude_rad": [0.0, 2.0],
                                "omega_per_s": [4.0, 6.0],
                                "gamma_per_s": [0.0, 2.0]}))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertTrue(diag["omega_grid_best_at_lower_edge"])
        self.assertIn("W_ASSUMPTION_UNVERIFIED",
                      warning_codes(result))
        details = warning_details(result)
        self.assertTrue(any("omega grid best at the lower box edge"
                            in detail for detail in details))
        evidence = diag["edge_evidence"]["omega_lower"]
        self.assertIsNotNone(evidence)
        assert evidence is not None
        # Descent evidence: edge SSR below neighbor SSR.
        self.assertLess(evidence["edge_ssr"], evidence["neighbor_ssr"])

    def test_gamma_edge_warns_without_mismatch(self):
        # Gamma box excluding zero: fitted gamma presses 0.5, the
        # edge warning fires, but NO mismatch fires (gamma*span =
        # 1.475 >> 0.01: gamma 0.5 IS damped). Each warning means
        # exactly what it says.
        trajectory = generate_trajectory(make_spec())
        result = fit_m2(make_request(
            trajectory, bounds={"amplitude_rad": [0.0, 2.0],
                                "omega_per_s": [0.5, 8.0],
                                "gamma_per_s": [0.5, 2.0]}))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertTrue(diag["gamma_grid_best_at_lower_edge"])
        self.assertAlmostEqual(diag["fitted"]["gamma_per_s"], 0.5)
        self.assertGreaterEqual(diag["gamma_span_decay"],
                                MISMATCH_MAX_DECAY)
        details = warning_details(result)
        self.assertTrue(any("gamma grid best at the lower box edge"
                            in detail for detail in details))
        self.assertNotIn(MISMATCH_DETAIL, details)


class M2NonConvergence(unittest.TestCase):
    def test_budget_exhausted_warns(self):
        trajectory = generate_trajectory(make_spec())
        result = fit_m2(make_request(trajectory, grid_omega=3,
                                     grid_gamma=2, budget=0))
        fit = result["fit"]
        diag = result["diagnostics"]
        self.assertFalse(diag["converged"])
        self.assertFalse(fit["converged"])
        self.assertEqual(diag["termination_reason"],
                         "refine_budget_exhausted")
        self.assertEqual(diag["refine_iterations"], 0)
        self.assertIsNone(fit["residual_summary"])
        self.assertIsNone(diag["residuals"])
        self.assertIsNone(fit["initial_conditions"]["theta0_rad"])
        details = warning_details(result)
        self.assertTrue(any("refine_budget_exhausted" in detail
                            for detail in details))
        self.assertTrue(all(code.startswith("W_")
                            for code in warning_codes(result)))
        fitted = diag["fitted"]
        self.assertTrue(math.isfinite(fitted["amplitude_rad"]))
        self.assertTrue(0.5 <= fitted["omega_per_s"] <= 8.0)
        self.assertTrue(0.0 <= fitted["gamma_per_s"] <= 2.0)
        FitRecord.from_dict(fit)

    def test_flat_objective_warns(self):
        trajectory = generate_trajectory(
            make_spec(amplitude_rad=0.0))
        result = fit_m2(make_request(trajectory))
        fit = result["fit"]
        diag = result["diagnostics"]
        self.assertFalse(diag["converged"])
        self.assertEqual(diag["termination_reason"],
                         "flat_objective_unidentifiable")
        self.assertEqual(fit["parameters"],
                         {"g_over_l": 0.25, "gamma": 0.0})
        details = warning_details(result)
        self.assertTrue(any("flat_objective_unidentifiable" in detail
                            for detail in details))
        # Nothing was fitted: no mismatch warning on degenerate data.
        self.assertNotIn(MISMATCH_DETAIL, details)
        self.assertIsNone(fit["residual_summary"])
        FitRecord.from_dict(fit)

    def test_degenerate_design_warns(self):
        points = [
            {"t_seconds": 1.0, "x_px": 600.0, "y_px": 400.0},
            {"t_seconds": 1.0, "x_px": 610.0, "y_px": 390.0},
            {"t_seconds": 1.0, "x_px": 590.0, "y_px": 410.0},
            {"t_seconds": 1.0, "x_px": 605.0, "y_px": 395.0},
        ]
        result = fit_m2({
            "points": points,
            "pivot_x_px": 512.0,
            "pivot_y_px": 288.0,
            "bounds": {"amplitude_rad": [0.0, 2.0],
                       "omega_per_s": [0.5, 8.0],
                       "gamma_per_s": [0.0, 2.0]},
            "grid_n_omega": 10,
            "grid_n_gamma": 5,
            "max_refine_iterations": 50,
            "truth": None,
        })
        fit = result["fit"]
        diag = result["diagnostics"]
        self.assertFalse(diag["converged"])
        self.assertEqual(diag["termination_reason"],
                         "degenerate_design")
        details = warning_details(result)
        self.assertTrue(any("degenerate_design" in detail
                            for detail in details))
        # No finite grid best exists: edge flags stay False and no
        # edge warnings fire (only uncertainty + non-convergence).
        self.assertEqual(
            warning_codes(result),
            ["W_UNCERTAINTY_UNAVAILABLE", "W_ASSUMPTION_UNVERIFIED"])
        self.assertFalse(diag["omega_grid_best_at_lower_edge"])
        self.assertFalse(diag["gamma_grid_best_at_lower_edge"])
        self.assertEqual(fit["parameters"],
                         {"g_over_l": 0.25, "gamma": 0.0})
        self.assertIsNone(diag["fitted"]["amplitude_rad"])
        self.assertIsNone(diag["errors_vs_truth"])
        FitRecord.from_dict(fit)


class M2Determinism(unittest.TestCase):
    def test_fit_byte_pin(self):
        result = fit_m2(make_request(pin_trajectory()))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertEqual(len(diag["residuals"]), 60)
        payload = export_fit_json(result)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         FIT_JSON_SHA)

    def test_same_request_identical_bytes(self):
        first = export_fit_json(fit_m2(make_request(pin_trajectory())))
        second = export_fit_json(fit_m2(make_request(pin_trajectory())))
        self.assertEqual(first, second)

    def test_json_round_trip_exact_shared_envelope(self):
        # M2 results travel through M1's shared export/parsing
        # envelope; the round trip re-validates the M2 fit.v1
        # record through the contract (parameter coherence for
        # {g_over_l, gamma} enforced, not bypassed).
        result = fit_m2(make_request(pin_trajectory()))
        self.assertEqual(result["model"], "M2")
        self.assertEqual(parse_fit_json(export_fit_json(result)),
                         result)


class M2Rejections(unittest.TestCase):
    def assert_codes(self, request, codes):
        with self.assertRaises(ContractError) as raised:
            fit_m2(request)
        self.assertEqual(raised.exception.codes, codes)

    def base(self):
        return make_request(generate_trajectory(make_spec()))

    def test_non_dict_request_rejected(self):
        with self.assertRaises(ContractError) as raised:
            fit_m2([])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])

    def test_unrepresentable_span_rejected(self):
        # Finite but unrepresentable: gamma_hi=2.0 with
        # t=-1e10 overflows every in-bounds envelope probe.
        request = self.base()
        for index, point in enumerate(request["points"]):
            point["t_seconds"] = -1.0e10 + index
        self.assert_codes(request, ["E_OUT_OF_RANGE"])

    def test_nonfinite_span_rejected(self):
        request = self.base()
        request["points"][0]["t_seconds"] = -1.7e308
        request["points"][-1]["t_seconds"] = 1.7e308
        self.assert_codes(request, ["E_OUT_OF_RANGE"])

    def test_envelope_pair_overflow_returns_none(self):
        from kineticlab.fit.m2 import _envelope_pair
        self.assertIsNone(
            _envelope_pair([0.0, -1.0e10], [1.0, 1.0], 5.0, 1.0))

    def test_extreme_runnable_timestamps_no_uncaught(self):
        # All-positive extreme span passes validation (every
        # in-bounds envelope is finite) and runs to an honest
        # non-converged outcome: no uncaught exception, no
        # numeric fit claim (no residuals published).
        trajectory = generate_trajectory(make_spec())
        for index, sample in enumerate(trajectory["samples"]):
            sample["t_seconds"] = 1.0e10 + index
        request = make_request(trajectory, grid_omega=4, grid_gamma=4,
                               budget=10)
        result = fit_m2(request)
        self.assertFalse(result["diagnostics"]["converged"])
        self.assertEqual(
            result["diagnostics"]["termination_reason"],
            "refine_budget_exhausted")
        self.assertIsNone(result["diagnostics"]["residuals"])

    def test_shape_rejections(self):
        template = self.base()
        cells = []
        missing = copy.deepcopy(template)
        del missing["grid_n_gamma"]
        cells.append((missing, ["E_MISSING_FIELD"]))
        extra = copy.deepcopy(template)
        extra["model"] = "M1"
        cells.append((extra, ["E_UNEXPECTED_FIELD"]))
        few_points = copy.deepcopy(template)
        few_points["points"] = few_points["points"][:3]
        cells.append((few_points, ["E_OUT_OF_RANGE"]))
        bad_entry = copy.deepcopy(template)
        bad_entry["points"][0] = []
        cells.append((bad_entry, ["E_WRONG_TYPE"]))
        missing_key = copy.deepcopy(template)
        del missing_key["points"][0]["y_px"]
        cells.append((missing_key, ["E_MISSING_FIELD"]))
        inf_value = copy.deepcopy(template)
        inf_value["points"][1]["t_seconds"] = float("inf")
        cells.append((inf_value, ["E_NON_FINITE"]))
        bool_pivot = copy.deepcopy(template)
        bool_pivot["pivot_y_px"] = False
        cells.append((bool_pivot, ["E_WRONG_TYPE"]))
        for index, (request, codes) in enumerate(cells):
            with self.subTest(cell=index):
                self.assert_codes(request, codes)

    def test_bounds_rejections(self):
        template = self.base()
        cells = []
        null_bounds = copy.deepcopy(template)
        null_bounds["bounds"] = None
        cells.append((null_bounds, ["E_NULL_NOT_ALLOWED"]))
        missing = copy.deepcopy(template)
        del missing["bounds"]["gamma_per_s"]
        cells.append((missing, ["E_MISSING_FIELD"]))
        str_pair = copy.deepcopy(template)
        str_pair["bounds"]["gamma_per_s"] = "wide"
        cells.append((str_pair, ["E_WRONG_TYPE"]))
        neg_gamma = copy.deepcopy(template)
        neg_gamma["bounds"]["gamma_per_s"] = [-0.5, 2.0]
        cells.append((neg_gamma, ["E_OUT_OF_RANGE"]))
        flip_gamma = copy.deepcopy(template)
        flip_gamma["bounds"]["gamma_per_s"] = [2.0, 1.0]
        cells.append((flip_gamma, ["E_INCOHERENT_VALUE"]))
        flip_amp = copy.deepcopy(template)
        flip_amp["bounds"]["amplitude_rad"] = [2.0, 1.0]
        cells.append((flip_amp, ["E_INCOHERENT_VALUE"]))
        zero_omega = copy.deepcopy(template)
        zero_omega["bounds"]["omega_per_s"] = [0.0, 5.0]
        cells.append((zero_omega, ["E_OUT_OF_RANGE"]))
        for index, (request, codes) in enumerate(cells):
            with self.subTest(cell=index):
                self.assert_codes(request, codes)

    def test_scalar_and_truth_rejections(self):
        template = self.base()
        cells = []
        thin_gamma = copy.deepcopy(template)
        thin_gamma["grid_n_gamma"] = 1
        cells.append((thin_gamma, ["E_OUT_OF_RANGE"]))
        bool_grid = copy.deepcopy(template)
        bool_grid["grid_n_omega"] = True
        cells.append((bool_grid, ["E_WRONG_TYPE"]))
        neg_budget = copy.deepcopy(template)
        neg_budget["max_refine_iterations"] = -1
        cells.append((neg_budget, ["E_OUT_OF_RANGE"]))
        bad_truth = copy.deepcopy(template)
        bad_truth["truth"] = []
        cells.append((bad_truth, ["E_WRONG_TYPE"]))
        missing_truth = copy.deepcopy(template)
        del missing_truth["truth"]["damping_per_s"]
        cells.append((missing_truth, ["E_MISSING_FIELD"]))
        neg_damping = copy.deepcopy(template)
        neg_damping["truth"]["damping_per_s"] = -0.1
        cells.append((neg_damping, ["E_OUT_OF_RANGE"]))
        zero_truth_omega = copy.deepcopy(template)
        zero_truth_omega["truth"]["angular_frequency_per_s"] = 0.0
        cells.append((zero_truth_omega, ["E_OUT_OF_RANGE"]))
        for index, (request, codes) in enumerate(cells):
            with self.subTest(cell=index):
                self.assert_codes(request, codes)


if __name__ == "__main__":
    unittest.main()
