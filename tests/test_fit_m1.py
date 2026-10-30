"""Bounded M1 fit tests (KL-5.2). Synthetic data only.

The fitter must recover planted (A, omega, phi) from pixel points
within the documented 1e-6 tolerances on clean data, must report
bound hits and edge optima honestly, must return honest
non-converged states (never crashes, never silent garbage), must
emit contract-valid ``fit.v1`` records, and must be deterministic.
Measured clean-fit errors (~1e-10; see the recovery tests) sit
1000x+ below the tolerances and broken fits err at ~0.1+, so a
pass means genuine recovery. The byte pin is platform-caveated
(libm): do not assert it cross-machine.
"""

import copy
import hashlib
import math
import unittest

from kineticlab.contracts import ContractError, FitRecord
from kineticlab.fit import (
    RECOVERY_TOL_AMPLITUDE_RAD,
    RECOVERY_TOL_OMEGA_PER_S,
    RECOVERY_TOL_PHASE_RAD,
    TEST_CONVENTION_NOTE,
    export_fit_json,
    fit_m1,
    generate_trajectory,
    parse_fit_json,
)

# Byte pin for the pin-fit trajectory (noisy ideal, seed 42, 60
# points, sigma 1.5 px, grid 200, budget 200). Measured on the
# verified Windows/CPython 3.15 platform; platform-bound.
FIT_JSON_SHA = "209a6b643095f8feba380d038896625cc91d4484c0c055fc7e436134d65e0e9e"


def make_spec(**overrides):
    spec = {
        "model": "ideal",
        "seed": 7,
        "amplitude_rad": 0.35,
        "angular_frequency_per_s": math.pi,
        "period_s": None,
        "phase_rad": 0.2,
        "damping_per_s": None,
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


def make_request(trajectory, bounds=None, grid=200, budget=200,
                 with_truth=True):
    ground = trajectory["ground_truth"]
    return {
        "points": [{"t_seconds": sample["t_seconds"],
                    "x_px": sample["x_px"],
                    "y_px": sample["y_px"]}
                   for sample in trajectory["samples"]],
        "pivot_x_px": ground["pivot_x_px"],
        "pivot_y_px": ground["pivot_y_px"],
        "bounds": ({"amplitude_rad": [0.0, 2.0],
                    "omega_per_s": [0.5, 8.0]}
                   if bounds is None else bounds),
        "grid_n_omega": grid,
        "max_refine_iterations": budget,
        "truth": ({"amplitude_rad": ground["amplitude_rad"],
                   "angular_frequency_per_s":
                   ground["angular_frequency_per_s"],
                   "phase_rad": ground["phase_rad"]}
                  if with_truth else None),
    }


def pin_trajectory():
    return generate_trajectory(make_spec(
        seed=42, noise={"mode": "gaussian", "sigma_px": 1.5}))


class M1Recovery(unittest.TestCase):
    def test_clean_recovery_within_tolerance(self):
        result = fit_m1(make_request(
            generate_trajectory(make_spec())))
        fit = result["fit"]
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertEqual(diag["termination_reason"],
                         "refine_tolerance_met")
        errors = diag["errors_vs_truth"]
        # Measured on the verified platform: A 8.9e-12, omega
        # 1.6e-10, phi 2.4e-10 — 6000x+ headroom under the tolerances.
        self.assertLessEqual(errors["amplitude_rad"],
                             RECOVERY_TOL_AMPLITUDE_RAD)
        self.assertLessEqual(errors["omega_per_s"],
                             RECOVERY_TOL_OMEGA_PER_S)
        self.assertLessEqual(errors["phase_rad"],
                             RECOVERY_TOL_PHASE_RAD)
        fitted = diag["fitted"]
        self.assertEqual(fit["parameters"]["g_over_l"],
                         fitted["omega_per_s"] * fitted["omega_per_s"])
        self.assertEqual(fit["g_over_l_per_s2"],
                         fit["parameters"]["g_over_l"])
        self.assertEqual(fitted["period_s"],
                         2.0 * math.pi / fitted["omega_per_s"])
        self.assertEqual(fit["initial_conditions"]["theta0_rad"],
                         fitted["amplitude_rad"]
                         * math.cos(fitted["phase_rad"]))
        self.assertEqual(fit["initial_conditions"]["omega0_rad_s"],
                         -fitted["amplitude_rad"] * fitted["omega_per_s"]
                         * math.sin(fitted["phase_rad"]))
        residual = fit["residual_summary"]
        self.assertEqual(residual["dof"], 57)
        self.assertLessEqual(residual["rmse"], residual["max_abs"])
        # Explicit loop, not sum(): CPython 3.12+ sum() uses
        # compensated summation and differs by 1ulp from the
        # module's plain accumulation. Same algorithm here proves
        # the residuals list matches the summary exactly.
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
        self.assertEqual(fit["warnings"], [{
            "code": "W_UNCERTAINTY_UNAVAILABLE",
            "detail": "KL-5.2 estimates no uncertainty; method is "
                      "none (KL-5.4 owns uncertainty)."}])
        self.assertEqual(fit["solver"], "closed_form_small_angle")
        self.assertEqual(
            fit["optimizer"],
            "separable_omega_grid_linear_lsq_golden_refine_v1")
        self.assertEqual(diag["bound_hits"], [])
        self.assertFalse(diag["omega_grid_best_at_lower_edge"])
        self.assertFalse(diag["omega_grid_best_at_upper_edge"])
        self.assertFalse(diag["omega_midpoint_singular_fallback"])
        self.assertEqual(diag["weights"], "uniform")
        self.assertEqual(result["test_convention_note"],
                         TEST_CONVENTION_NOTE)
        # The emitted record is contract-valid by construction;
        # re-validate independently to prove it.
        FitRecord.from_dict(fit)

    def test_clean_recovery_second_config(self):
        trajectory = generate_trajectory(make_spec(
            seed=3, amplitude_rad=0.9, angular_frequency_per_s=1.7,
            phase_rad=-1.1,
            time={"mode": "jittered", "t0_s": 0.0, "dt_s": 0.05,
                  "n": 60, "jitter_s": 0.01}))
        result = fit_m1(make_request(trajectory))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        errors = diag["errors_vs_truth"]
        # Measured: A 2.3e-11, omega 1.9e-10, phi 2.8e-10.
        self.assertLessEqual(errors["amplitude_rad"],
                             RECOVERY_TOL_AMPLITUDE_RAD)
        self.assertLessEqual(errors["omega_per_s"],
                             RECOVERY_TOL_OMEGA_PER_S)
        self.assertLessEqual(errors["phase_rad"],
                             RECOVERY_TOL_PHASE_RAD)

    def test_period_source_equivalence(self):
        by_omega = fit_m1(make_request(
            generate_trajectory(make_spec())))
        by_period = fit_m1(make_request(generate_trajectory(
            make_spec(angular_frequency_per_s=None, period_s=2.0))))
        for result in (by_omega, by_period):
            self.assertTrue(result["diagnostics"]["converged"])
        omega_a = by_omega["diagnostics"]["fitted"]["omega_per_s"]
        omega_b = by_period["diagnostics"]["fitted"]["omega_per_s"]
        self.assertLessEqual(abs(omega_a - omega_b), 1e-9)

    def test_micro_case_hand_check(self):
        # Hand case: A=1, omega=1, phi=0 at t = {0, pi/2, pi,
        # 3pi/2} gives theta = {1, 0, -1, 0}. At omega=1 the normal
        # equations are sum_cc=2, sum_ss=2, sum_cs=0, sum_cy=2,
        # sum_sy=0 in exact arithmetic, i.e. C=1, S=0. Float trig
        # round-trips cost ~1e-16, refinement ~1e-10; measured
        # errors under the default wide box: A exactly 0.0, omega
        # 1.2e-10, phi 3.8e-10. (Sparse data narrows the SSR
        # valley in general, but the singularity guard keeps this
        # 4-point case on the true valley; see module docstring.)
        trajectory = generate_trajectory(make_spec(
            amplitude_rad=1.0, angular_frequency_per_s=1.0,
            phase_rad=0.0, pivot_x_px=0.0, pivot_y_px=0.0,
            length_px=1.0,
            time={"mode": "explicit",
                  "times_s": [0.0, math.pi / 2, math.pi,
                              3 * math.pi / 2]}))
        result = fit_m1(make_request(trajectory))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        errors = diag["errors_vs_truth"]
        self.assertLessEqual(errors["amplitude_rad"], 1e-9)
        self.assertLessEqual(errors["omega_per_s"], 1e-9)
        self.assertLessEqual(errors["phase_rad"], 1e-9)
        self.assertLess(diag["objectives"]["final_ssr"], 1e-18)
        self.assertEqual(result["fit"]["residual_summary"]["dof"], 1)
        self.assertEqual(result["fit"]["observation_count"], 4)
        fitted = diag["fitted"]
        self.assertEqual(result["fit"]["parameters"]["g_over_l"],
                         fitted["omega_per_s"] * fitted["omega_per_s"])

    def test_noise_case_runs_and_reports(self):
        trajectory = generate_trajectory(make_spec(
            seed=11, noise={"mode": "gaussian", "sigma_px": 2.0},
            time={"mode": "uniform", "t0_s": 0.0, "dt_s": 0.05,
                  "n": 100}))
        result = fit_m1(make_request(trajectory))
        diag = result["diagnostics"]
        # Measured: converged, errors (6.4e-4, 1.8e-3, 6.1e-3),
        # rmse 0.0112 rad ~= sigma/length_px = 0.01 — reported as
        # data, with NO tolerance verdict (KL-5.4 owns verdicts).
        self.assertTrue(diag["converged"])
        self.assertTrue(diag["residuals_available"])
        self.assertEqual(len(diag["residuals"]), 100)
        self.assertEqual({entry["point_index"]
                          for entry in diag["residuals"]}, set(range(100)))
        residual = result["fit"]["residual_summary"]
        self.assertGreater(residual["rmse"], 0.0)
        self.assertLessEqual(residual["rmse"], residual["max_abs"])
        self.assertEqual(residual["dof"], 97)
        for value in diag["errors_vs_truth"].values():
            self.assertIsInstance(value, float)
            self.assertTrue(math.isfinite(value))

    def test_fit_ignores_generative_angles(self):
        trajectory = generate_trajectory(make_spec())
        baseline = export_fit_json(fit_m1(make_request(trajectory)))
        corrupted = copy.deepcopy(trajectory)
        for sample in corrupted["samples"]:
            sample["theta_rad"] = 999.0
        self.assertEqual(
            export_fit_json(fit_m1(make_request(corrupted))), baseline)
        stripped = copy.deepcopy(trajectory)
        for sample in stripped["samples"]:
            del sample["theta_rad"]
        self.assertEqual(
            export_fit_json(fit_m1(make_request(stripped))), baseline)

    def test_truth_null_gives_null_errors(self):
        result = fit_m1(make_request(generate_trajectory(make_spec()),
                                     with_truth=False))
        self.assertTrue(result["diagnostics"]["converged"])
        self.assertIsNone(result["diagnostics"]["errors_vs_truth"])


class M1Bounds(unittest.TestCase):
    def test_amplitude_bound_hit_recorded(self):
        trajectory = generate_trajectory(make_spec())
        result = fit_m1(make_request(
            trajectory, bounds={"amplitude_rad": [0.0, 0.1],
                                "omega_per_s": [0.5, 8.0]}))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertEqual(len(diag["bound_hits"]), 1)
        hit = diag["bound_hits"][0]
        self.assertEqual(hit["parameter"], "amplitude_rad")
        self.assertEqual(hit["bound"], "upper")
        self.assertEqual(hit["bound_value"], 0.1)
        # Unclamped value is the true fitted amplitude (~0.35).
        self.assertAlmostEqual(hit["unclamped_value"], 0.35)
        self.assertEqual(diag["fitted"]["amplitude_rad"], 0.1)
        # Residuals are evaluated at the REPORTED (projected) values.
        # Explicit loop (see the recovery test: sum() differs by 1ulp).
        residual = result["fit"]["residual_summary"]
        total = 0.0
        for entry in diag["residuals"]:
            total += entry["residual_rad"] * entry["residual_rad"]
        self.assertEqual(residual["rmse"], math.sqrt(total / 60))

    def test_omega_edge_flags_fire_honestly(self):
        trajectory = generate_trajectory(make_spec())
        below = fit_m1(make_request(
            trajectory, bounds={"amplitude_rad": [0.0, 2.0],
                                "omega_per_s": [4.0, 6.0]}))
        diag = below["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertTrue(diag["omega_grid_best_at_lower_edge"])
        self.assertFalse(diag["omega_grid_best_at_upper_edge"])
        # Measured omega 4.0000000004: refinement presses the bound.
        self.assertGreaterEqual(diag["fitted"]["omega_per_s"], 4.0)
        above = fit_m1(make_request(
            trajectory, bounds={"amplitude_rad": [0.0, 2.0],
                                "omega_per_s": [1.0, 2.0]}))
        diag = above["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertFalse(diag["omega_grid_best_at_lower_edge"])
        self.assertTrue(diag["omega_grid_best_at_upper_edge"])
        # Measured omega 1.9999999997: refinement presses the bound.
        self.assertLessEqual(diag["fitted"]["omega_per_s"], 2.0)


class M1NonConvergence(unittest.TestCase):
    def test_flat_objective_zero_amplitude(self):
        trajectory = generate_trajectory(
            make_spec(amplitude_rad=0.0))
        result = fit_m1(make_request(trajectory))
        fit = result["fit"]
        diag = result["diagnostics"]
        self.assertFalse(diag["converged"])
        self.assertFalse(fit["converged"])
        self.assertEqual(diag["termination_reason"],
                         "flat_objective_unidentifiable")
        self.assertIsNone(fit["residual_summary"])
        self.assertIsNone(diag["residuals"])
        self.assertFalse(diag["residuals_available"])
        self.assertIsNone(fit["initial_conditions"]["theta0_rad"])
        self.assertIsNone(fit["initial_conditions"]["omega0_rad_s"])
        # Degenerate iterate: A = 0, first grid omega; g_over_l is
        # the iterate value (0.5^2), honestly labeled non-converged.
        self.assertEqual(diag["fitted"]["amplitude_rad"], 0.0)
        self.assertEqual(diag["fitted"]["omega_per_s"], 0.5)
        self.assertEqual(diag["fitted"]["phase_rad"], 0.0)
        self.assertEqual(fit["parameters"]["g_over_l"], 0.25)
        self.assertEqual(diag["errors_vs_truth"]["amplitude_rad"], 0.0)
        self.assertEqual(diag["errors_vs_truth"]["omega_per_s"],
                         abs(0.5 - math.pi))
        self.assertAlmostEqual(diag["errors_vs_truth"]["phase_rad"], 0.2)
        self.assertEqual(fit["observation_count"], 60)
        FitRecord.from_dict(fit)

    def test_budget_exhausted(self):
        trajectory = generate_trajectory(make_spec())
        result = fit_m1(make_request(trajectory, grid=3, budget=0))
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
        fitted = diag["fitted"]
        self.assertTrue(math.isfinite(fitted["amplitude_rad"]))
        self.assertTrue(0.5 <= fitted["omega_per_s"] <= 8.0)
        FitRecord.from_dict(fit)

    def test_degenerate_design_identical_times(self):
        points = [
            {"t_seconds": 1.0, "x_px": 600.0, "y_px": 400.0},
            {"t_seconds": 1.0, "x_px": 610.0, "y_px": 390.0},
            {"t_seconds": 1.0, "x_px": 590.0, "y_px": 410.0},
        ]
        result = fit_m1({
            "points": points,
            "pivot_x_px": 512.0,
            "pivot_y_px": 288.0,
            "bounds": {"amplitude_rad": [0.0, 2.0],
                       "omega_per_s": [0.5, 8.0]},
            "grid_n_omega": 50,
            "max_refine_iterations": 50,
            "truth": {"amplitude_rad": 0.35,
                      "angular_frequency_per_s": math.pi,
                      "phase_rad": 0.2},
        })
        fit = result["fit"]
        diag = result["diagnostics"]
        self.assertFalse(diag["converged"])
        self.assertEqual(diag["termination_reason"],
                         "degenerate_design")
        self.assertIsNone(diag["fitted"]["amplitude_rad"])
        self.assertEqual(diag["fitted"]["omega_per_s"], 0.5)
        self.assertIsNone(diag["fitted"]["phase_rad"])
        self.assertEqual(fit["parameters"]["g_over_l"], 0.25)
        errors = diag["errors_vs_truth"]
        self.assertIsNone(errors["amplitude_rad"])
        self.assertEqual(errors["omega_per_s"], abs(0.5 - math.pi))
        self.assertIsNone(errors["phase_rad"])
        self.assertEqual(diag["grid_evaluations"], 50)
        self.assertEqual(diag["refine_iterations"], 0)
        FitRecord.from_dict(fit)


class M1Determinism(unittest.TestCase):
    def test_fit_byte_pin(self):
        result = fit_m1(make_request(pin_trajectory()))
        diag = result["diagnostics"]
        self.assertTrue(diag["converged"])
        self.assertEqual(len(diag["residuals"]), 60)
        payload = export_fit_json(result)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         FIT_JSON_SHA)

    def test_same_request_identical_bytes(self):
        first = export_fit_json(fit_m1(make_request(pin_trajectory())))
        second = export_fit_json(fit_m1(make_request(pin_trajectory())))
        self.assertEqual(first, second)

    def test_json_round_trip_exact(self):
        result = fit_m1(make_request(pin_trajectory()))
        self.assertEqual(parse_fit_json(export_fit_json(result)),
                         result)

    def test_export_failures(self):
        with self.assertRaises(ContractError) as raised:
            export_fit_json([])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])
        with self.assertRaises(ContractError) as raised:
            export_fit_json({"fit": {}, "diagnostics": {}})
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])
        with self.assertRaises(ContractError) as raised:
            parse_fit_json(b"\xff\xfe not json")
        self.assertEqual(raised.exception.codes, ["E_MALFORMED_JSON"])
        with self.assertRaises(ContractError) as raised:
            parse_fit_json(b"[1, 2]")
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        broken = {"fitter": "x", "model": "M1",
                  "test_convention_note": "x",
                  "fit": {"schema_version": "fit.v1"}, "diagnostics": {}}
        with self.assertRaises(ContractError) as raised:
            parse_fit_json(export_fit_json(broken))
        codes = raised.exception.codes
        self.assertIn("E_MISSING_FIELD", codes)
        self.assertTrue(all(code.startswith("E_") for code in codes))
        broken["fit"] = {"schema_version": "fit.v1",
                         "model_id": "M1",
                         "parameter_names": ["g_over_l"],
                         "parameters": {},
                         "parameter_units": {"g_over_l": "1/s^2"}}
        with self.assertRaises(ContractError) as raised:
            parse_fit_json(export_fit_json(broken))
        self.assertIn("E_PARAMETER_MISMATCH", raised.exception.codes)
        fields = [error.field for error in raised.exception.errors]
        self.assertTrue(all(field.startswith("fit.")
                            for field in fields))
        good = fit_m1(make_request(pin_trajectory()))
        good["diagnostics"] = []
        with self.assertRaises(ContractError) as raised:
            parse_fit_json(export_fit_json(good))
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])


class M1Rejections(unittest.TestCase):
    def assert_codes(self, request, codes):
        with self.assertRaises(ContractError) as raised:
            fit_m1(request)
        self.assertEqual(raised.exception.codes, codes)

    def base(self):
        return make_request(generate_trajectory(make_spec()))

    def test_non_dict_request_rejected(self):
        with self.assertRaises(ContractError) as raised:
            fit_m1([])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])

    def test_shape_rejections(self):
        template = self.base()
        cells = []
        missing = copy.deepcopy(template)
        del missing["truth"]
        cells.append((missing, ["E_MISSING_FIELD"]))
        extra = copy.deepcopy(template)
        extra["model"] = "M2"
        cells.append((extra, ["E_UNEXPECTED_FIELD"]))
        null_points = copy.deepcopy(template)
        null_points["points"] = None
        cells.append((null_points, ["E_NULL_NOT_ALLOWED"]))
        bad_points = copy.deepcopy(template)
        bad_points["points"] = {}
        cells.append((bad_points, ["E_WRONG_TYPE"]))
        few_points = copy.deepcopy(template)
        few_points["points"] = few_points["points"][:2]
        cells.append((few_points, ["E_OUT_OF_RANGE"]))
        bad_entry = copy.deepcopy(template)
        bad_entry["points"][0] = []
        cells.append((bad_entry, ["E_WRONG_TYPE"]))
        extra_key = copy.deepcopy(template)
        extra_key["points"][0]["theta_rad"] = 0.0
        cells.append((extra_key, ["E_UNEXPECTED_FIELD"]))
        missing_key = copy.deepcopy(template)
        del missing_key["points"][0]["x_px"]
        cells.append((missing_key, ["E_MISSING_FIELD"]))
        null_value = copy.deepcopy(template)
        null_value["points"][1]["t_seconds"] = None
        cells.append((null_value, ["E_NULL_NOT_ALLOWED"]))
        str_value = copy.deepcopy(template)
        str_value["points"][1]["x_px"] = "512"
        cells.append((str_value, ["E_WRONG_TYPE"]))
        inf_value = copy.deepcopy(template)
        inf_value["points"][1]["y_px"] = float("inf")
        cells.append((inf_value, ["E_NON_FINITE"]))
        bool_pivot = copy.deepcopy(template)
        bool_pivot["pivot_x_px"] = True
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
        bad_bounds = copy.deepcopy(template)
        bad_bounds["bounds"] = []
        cells.append((bad_bounds, ["E_WRONG_TYPE"]))
        extra = copy.deepcopy(template)
        extra["bounds"]["phase_rad"] = [-1.0, 1.0]
        cells.append((extra, ["E_UNEXPECTED_FIELD"]))
        missing = copy.deepcopy(template)
        del missing["bounds"]["omega_per_s"]
        cells.append((missing, ["E_MISSING_FIELD"]))
        str_pair = copy.deepcopy(template)
        str_pair["bounds"]["amplitude_rad"] = "wide"
        cells.append((str_pair, ["E_WRONG_TYPE"]))
        null_end = copy.deepcopy(template)
        null_end["bounds"]["amplitude_rad"] = [None, 2.0]
        cells.append((null_end, ["E_NULL_NOT_ALLOWED"]))
        neg_amp = copy.deepcopy(template)
        neg_amp["bounds"]["amplitude_rad"] = [-1.0, 2.0]
        cells.append((neg_amp, ["E_OUT_OF_RANGE"]))
        flip_amp = copy.deepcopy(template)
        flip_amp["bounds"]["amplitude_rad"] = [2.0, 1.0]
        cells.append((flip_amp, ["E_INCOHERENT_VALUE"]))
        zero_omega = copy.deepcopy(template)
        zero_omega["bounds"]["omega_per_s"] = [0.0, 5.0]
        cells.append((zero_omega, ["E_OUT_OF_RANGE"]))
        flip_omega = copy.deepcopy(template)
        flip_omega["bounds"]["omega_per_s"] = [5.0, 4.0]
        cells.append((flip_omega, ["E_INCOHERENT_VALUE"]))
        inf_omega = copy.deepcopy(template)
        inf_omega["bounds"]["omega_per_s"] = [0.5, float("inf")]
        cells.append((inf_omega, ["E_NON_FINITE"]))
        for index, (request, codes) in enumerate(cells):
            with self.subTest(cell=index):
                self.assert_codes(request, codes)

    def test_scalar_and_truth_rejections(self):
        template = self.base()
        cells = []
        thin_grid = copy.deepcopy(template)
        thin_grid["grid_n_omega"] = 1
        cells.append((thin_grid, ["E_OUT_OF_RANGE"]))
        bool_grid = copy.deepcopy(template)
        bool_grid["grid_n_omega"] = True
        cells.append((bool_grid, ["E_WRONG_TYPE"]))
        null_grid = copy.deepcopy(template)
        null_grid["grid_n_omega"] = None
        cells.append((null_grid, ["E_NULL_NOT_ALLOWED"]))
        neg_budget = copy.deepcopy(template)
        neg_budget["max_refine_iterations"] = -1
        cells.append((neg_budget, ["E_OUT_OF_RANGE"]))
        bad_truth = copy.deepcopy(template)
        bad_truth["truth"] = []
        cells.append((bad_truth, ["E_WRONG_TYPE"]))
        extra_truth = copy.deepcopy(template)
        extra_truth["truth"]["gamma"] = 0.1
        cells.append((extra_truth, ["E_UNEXPECTED_FIELD"]))
        missing_truth = copy.deepcopy(template)
        del missing_truth["truth"]["phase_rad"]
        cells.append((missing_truth, ["E_MISSING_FIELD"]))
        neg_truth_amp = copy.deepcopy(template)
        neg_truth_amp["truth"]["amplitude_rad"] = -0.5
        cells.append((neg_truth_amp, ["E_OUT_OF_RANGE"]))
        zero_truth_omega = copy.deepcopy(template)
        zero_truth_omega["truth"]["angular_frequency_per_s"] = 0.0
        cells.append((zero_truth_omega, ["E_OUT_OF_RANGE"]))
        for index, (request, codes) in enumerate(cells):
            with self.subTest(cell=index):
                self.assert_codes(request, codes)


if __name__ == "__main__":
    unittest.main()
