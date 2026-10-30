"""Recovery/failure/repeatability matrix tests (KL-5.4).

Synthetic data only. The full matrix runs once at import (shared
artifact; determinism is proven separately by rerun). The matrix
maps WHERE the 1e-6 recovery tolerances hold and where they do
NOT — including the config-dependent M2 alternation stall
(Fable-measured; characterized here at capped grids): short-span
/ few-cycle configs stall with converged:true, a gamma-0.05
island stalls amid recovering neighbors, and grid/box alignment
decides stall-vs-recovery non-monotonically. Stalls are facts the
matrix shows, not failures of honesty. The byte pin is
platform-caveated (libm): do not assert it cross-machine.

Runtime bound: the full matrix holds M2 grids at 150x40 or below
(one 512x128 alignment cell excepted) and M1 grids at 200, so the
matrix suite adds well under 60s (measured ~15s on the verified
platform: one shared build at import plus one determinism rerun).
"""

import copy
import hashlib
import math
import unittest

from kineticlab.contracts import ContractError
from kineticlab.fit import (
    export_matrix_json,
    parse_matrix_json,
    run_matrix,
)
from kineticlab.fit.m2 import MISMATCH_DETAIL

# Byte pin for FULL_REQUEST below (33 cells). Measured on the
# verified Windows/CPython 3.15 platform; platform-bound.
MATRIX_JSON_SHA = "65b9b10e37c225f9279b911450a82be402fcf048ee8c90507b5e6a8e5adb857e"

M1_BOUNDS = {"amplitude_rad": [0.0, 2.0], "omega_per_s": [0.5, 8.0]}
M2_BOUNDS = {"amplitude_rad": [0.0, 2.0], "omega_per_s": [0.5, 8.0],
             "gamma_per_s": [0.0, 2.0]}

M1_OPTIONS = {"bounds": M1_BOUNDS, "grid_n_omega": 200,
              "max_refine_iterations": 200}
M2_OPTIONS = {"bounds": M2_BOUNDS, "grid_n_omega": 150,
              "grid_n_gamma": 40, "max_refine_iterations": 300}


def make_spec(model="ideal", **overrides):
    spec = {
        "model": model,
        "seed": 7,
        "amplitude_rad": 0.35,
        "angular_frequency_per_s": math.pi,
        "period_s": None,
        "phase_rad": 0.2,
        "damping_per_s": 0.1 if model == "damped" else None,
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


def stall_spec(n=80, dt=0.04, omega=2.2, gamma=0.15, **overrides):
    """Fable-probe family: damped, A 0.35, phi 0.2, clean uniform."""
    spec = make_spec(
        model="damped", angular_frequency_per_s=omega,
        damping_per_s=gamma,
        time={"mode": "uniform", "t0_s": 0.0, "dt_s": dt, "n": n})
    spec.update(overrides)
    return spec


def m1_cell(config_id, spec, options=None):
    return {"config_id": config_id, "fitter": "M1",
            "trajectory_spec": spec,
            "fit_options": copy.deepcopy(M1_OPTIONS if options is None
                                         else options)}


def m2_cell(config_id, spec, options=None):
    return {"config_id": config_id, "fitter": "M2",
            "trajectory_spec": spec,
            "fit_options": copy.deepcopy(M2_OPTIONS if options is None
                                         else options)}


def m2_options(grid_omega=150, grid_gamma=40, budget=300, bounds=None):
    return {"bounds": copy.deepcopy(M2_BOUNDS if bounds is None
                                    else bounds),
            "grid_n_omega": grid_omega, "grid_n_gamma": grid_gamma,
            "max_refine_iterations": budget}


MICRO_M1_TIMES = [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]
MICRO_M2_TIMES = [0.0, math.pi / 2, 2 * math.pi, 5 * math.pi / 2,
                  4 * math.pi, 6 * math.pi, 13 * math.pi / 2, 8 * math.pi]


def build_full_request():
    """The 33-cell characterization matrix (see module docstring)."""
    noisy_time = {"mode": "uniform", "t0_s": 0.0, "dt_s": 0.05, "n": 100}
    noisy = {"mode": "gaussian", "sigma_px": 2.0}
    configs = [
        # --- M1 recovery ---
        m1_cell("m1-base-60pt", make_spec()),
        m1_cell("m1-jittered", make_spec(
            time={"mode": "jittered", "t0_s": 0.0, "dt_s": 0.05,
                  "n": 60, "jitter_s": 0.01})),
        m1_cell("m1-noisy", make_spec(seed=11, noise=noisy,
                                      time=noisy_time)),
        m1_cell("m1-gaps-outliers", make_spec(
            gaps=[[10, 14], [40, 44]],
            outliers=[{"sample_index": 20, "dx_px": 8.0, "dy_px": -6.0},
                      {"sample_index": 50, "dx_px": -10.0,
                       "dy_px": 5.0}])),
        m1_cell("m1-on-damped", make_spec(model="damped")),
        m1_cell("m1-micro-4pt", make_spec(
            amplitude_rad=1.0, angular_frequency_per_s=1.0,
            phase_rad=0.0, pivot_x_px=0.0, pivot_y_px=0.0,
            length_px=1.0,
            time={"mode": "explicit", "times_s": MICRO_M1_TIMES})),
        # --- M1 failure ---
        m1_cell("m1-budget0", make_spec(),
                {"bounds": M1_BOUNDS, "grid_n_omega": 3,
                 "max_refine_iterations": 0}),
        m1_cell("m1-flat", make_spec(amplitude_rad=0.0)),
        m1_cell("m1-amp-hit", make_spec(),
                {"bounds": {"amplitude_rad": [0.0, 0.1],
                            "omega_per_s": [0.5, 8.0]},
                 "grid_n_omega": 200, "max_refine_iterations": 200}),
        m1_cell("m1-omega-edge", make_spec(),
                {"bounds": {"amplitude_rad": [0.0, 2.0],
                            "omega_per_s": [4.0, 6.0]},
                 "grid_n_omega": 200, "max_refine_iterations": 200}),
        # --- M2 recovery ---
        m2_cell("m2-base-60pt", make_spec(model="damped")),
        m2_cell("m2-jittered", make_spec(
            model="damped",
            time={"mode": "jittered", "t0_s": 0.0, "dt_s": 0.05,
                  "n": 60, "jitter_s": 0.01})),
        m2_cell("m2-noisy", make_spec(model="damped", seed=11,
                                      noise=noisy, time=noisy_time)),
        m2_cell("m2-mismatch-ideal", make_spec()),
        m2_cell("m2-micro-8pt", make_spec(
            model="damped", amplitude_rad=1.0,
            angular_frequency_per_s=1.0, phase_rad=0.0,
            damping_per_s=0.1, pivot_x_px=0.0, pivot_y_px=0.0,
            length_px=1.0,
            time={"mode": "explicit", "times_s": MICRO_M2_TIMES})),
        # --- M2 stall boundary (Fable-probe family) ---
        m2_cell("m2-stall-n48", stall_spec(n=48)),
        m2_cell("m2-recover-n64", stall_spec(n=64)),
        m2_cell("m2-stall-g005", stall_spec(gamma=0.05)),
        m2_cell("m2-recover-g0055", stall_spec(gamma=0.055)),
        m2_cell("m2-stall-w10", stall_spec(omega=1.0)),
        m2_cell("m2-grid-coarse", stall_spec(n=48),
                m2_options(grid_omega=75, grid_gamma=20)),
        m2_cell("m2-grid-fine", stall_spec(n=48),
                m2_options(grid_omega=300, grid_gamma=80)),
        m2_cell("m2-box-narrow", stall_spec(),
                m2_options(bounds={"amplitude_rad": [0.0, 2.0],
                                   "omega_per_s": [1.0, 4.0],
                                   "gamma_per_s": [0.0, 2.0]})),
        m2_cell("m2-recover-n200", stall_spec(n=200)),
        m2_cell("m2-grid-512", stall_spec(),
                m2_options(grid_omega=512, grid_gamma=128)),
        m2_cell("m2-stall-n48-bigbudget", stall_spec(n=48),
                m2_options(budget=3000)),
        # --- M2 failure ---
        m2_cell("m2-budget0", make_spec(model="damped"),
                m2_options(grid_omega=3, grid_gamma=2, budget=0)),
        m2_cell("m2-flat", make_spec(model="damped",
                                     amplitude_rad=0.0)),
        m2_cell("m2-amp-hit", make_spec(model="damped"),
                m2_options(bounds={"amplitude_rad": [0.0, 0.1],
                                   "omega_per_s": [0.5, 8.0],
                                   "gamma_per_s": [0.0, 2.0]})),
        m2_cell("m2-gamma-edge", make_spec(model="damped"),
                m2_options(bounds={"amplitude_rad": [0.0, 2.0],
                                   "omega_per_s": [0.5, 8.0],
                                   "gamma_per_s": [0.5, 2.0]})),
        # --- M2 repeatability trio (same noisy config, 3 seeds) ---
        m2_cell("m2-noise-seed11", make_spec(model="damped", seed=11,
                                             noise=noisy,
                                             time=noisy_time)),
        m2_cell("m2-noise-seed42", make_spec(model="damped", seed=42,
                                             noise=noisy,
                                             time=noisy_time)),
        m2_cell("m2-noise-seed99", make_spec(model="damped", seed=99,
                                             noise=noisy,
                                             time=noisy_time)),
    ]
    return {"matrix_id": "kl54-characterization-v1", "configs": configs}


FULL_REQUEST = build_full_request()
FULL_MATRIX = run_matrix(FULL_REQUEST)
FULL_BYTES = export_matrix_json(FULL_MATRIX)


def cell_by_id(matrix, config_id):
    for cell in matrix["cells"]:
        if cell["config_id"] == config_id:
            return cell
    raise AssertionError(f"missing cell {config_id}")


class MatrixShape(unittest.TestCase):
    def test_cell_count_and_ids(self):
        self.assertEqual(FULL_MATRIX["matrix_id"],
                         "kl54-characterization-v1")
        self.assertEqual(len(FULL_MATRIX["cells"]), 33)
        ids = [cell["config_id"] for cell in FULL_MATRIX["cells"]]
        self.assertEqual(len(set(ids)), 33)

    def test_summary_shape(self):
        summary = FULL_MATRIX["summary"]
        self.assertEqual(summary["n_cells"], 33)
        self.assertEqual(summary["by_fitter"]["M1"]["n_cells"], 10)
        self.assertEqual(summary["by_fitter"]["M2"]["n_cells"], 23)
        terminations = summary["terminations"]
        self.assertEqual(sum(terminations.values()), 33)
        # degenerate_design is unreachable from generator data
        # (strictly increasing times enforced); fitter unit tests
        # cover it. A nonzero count here would force a doc update.
        self.assertEqual(terminations["degenerate_design"], 0)
        self.assertEqual(
            len(summary["recovery_pass_cells"])
            + len(summary["recovery_fail_cells"]), 33)
        descriptives = summary["error_descriptives"]
        self.assertEqual(set(descriptives["M1"]),
                         {"amplitude_rad", "omega_per_s", "phase_rad"})
        self.assertEqual(set(descriptives["M2"]),
                         {"amplitude_rad", "omega_per_s", "phase_rad",
                          "gamma_per_s"})
        for fitter in ("M1", "M2"):
            for entry in descriptives[fitter].values():
                self.assertIsNotNone(entry)
                self.assertLessEqual(entry["min"], entry["mean"])
                self.assertLessEqual(entry["mean"], entry["max"])

    def test_uncertainty_and_gravity_absence_records(self):
        summary = FULL_MATRIX["summary"]
        self.assertEqual(summary["uncertainty"]["estimated"], False)
        self.assertEqual(summary["uncertainty"]["fit_uncertainty_method"],
                         "none")
        self.assertTrue(
            summary["uncertainty"]["method_none_in_every_cell"])
        self.assertTrue(
            summary["uncertainty"]["warning_present_in_every_cell"])
        self.assertEqual(summary["gravity"]["produced"], False)
        self.assertTrue(
            summary["gravity"]["gravity_m_s2_null_in_every_cell"])

    def test_pass_fail_split_is_the_boundary(self):
        # The tolerance boundary as data: exactly these cells pass.
        # Recovery holds on clean matched-model data (both fitters),
        # the 8-pt/4-pt micros, the mismatch cell (correct fit +
        # flag!), and the dense side of every stall pair. Fails are
        # noise, gaps/outliers, cross-model M1, bound/edge pressure,
        # non-convergence, and the six stall cells.
        summary = FULL_MATRIX["summary"]
        self.assertEqual(sorted(summary["recovery_pass_cells"]), [
            "m1-base-60pt",
            "m1-jittered",
            "m1-micro-4pt",
            "m2-base-60pt",
            "m2-jittered",
            "m2-micro-8pt",
            "m2-mismatch-ideal",
            "m2-recover-g0055",
            "m2-recover-n200",
            "m2-recover-n64",
        ])
        self.assertEqual(summary["nonconverged_cells"], [
            "m1-budget0",
            "m1-flat",
            "m2-budget0",
            "m2-flat",
        ])
        self.assertEqual(summary["warning_counts"], {
            "W_UNCERTAINTY_UNAVAILABLE": 33,
            "W_ASSUMPTION_UNVERIFIED": 7,
        })


def max_error(cell):
    errors = cell["result"]["diagnostics"]["errors_vs_truth"]
    return max(value for value in errors.values()
               if isinstance(value, float))


class MatrixStallBoundary(unittest.TestCase):
    def test_span_boundary_pair(self):
        # n=48 (span 1.88s, 0.66 cycles) stalls; n=64 (span 2.52s,
        # 0.88 cycles) recovers. BOTH converged:true — the stall is
        # a localization fact, honestly flagged by verdicts.
        stall = cell_by_id(FULL_MATRIX, "m2-stall-n48")
        recover = cell_by_id(FULL_MATRIX, "m2-recover-n64")
        self.assertTrue(stall["result"]["diagnostics"]["converged"])
        self.assertTrue(recover["result"]["diagnostics"]["converged"])
        self.assertFalse(stall["verdicts"]["recovery_pass"])
        self.assertTrue(recover["verdicts"]["recovery_pass"])
        # Measured stall magnitude 2.62e-3; bounds are wide enough
        # to survive libm wobble, tight enough to prove the split.
        self.assertLess(1e-3, max_error(stall))
        self.assertGreater(1e-2, max_error(stall))
        self.assertLess(max_error(recover), 1e-6)

    def test_stall_is_budget_independent(self):
        # 10x budget lands on the IDENTICAL stall point (same
        # iterations, same errors): structural ravine stall, not
        # budget starvation.
        base = cell_by_id(FULL_MATRIX, "m2-stall-n48")
        big = cell_by_id(FULL_MATRIX, "m2-stall-n48-bigbudget")
        self.assertEqual(
            big["result"]["diagnostics"]["errors_vs_truth"],
            base["result"]["diagnostics"]["errors_vs_truth"])
        self.assertEqual(
            big["result"]["diagnostics"]["refine_iterations"],
            base["result"]["diagnostics"]["refine_iterations"])
        self.assertFalse(big["verdicts"]["recovery_pass"])

    def test_grid_density_monotonic_on_span_stall(self):
        # On the n=48 span stall, finer grids halve the error
        # (6.03e-3 -> 2.62e-3 -> 1.30e-3) without curing it:
        # density correlates, alignment decides.
        coarse = cell_by_id(FULL_MATRIX, "m2-grid-coarse")
        base = cell_by_id(FULL_MATRIX, "m2-stall-n48")
        fine = cell_by_id(FULL_MATRIX, "m2-grid-fine")
        self.assertGreater(max_error(coarse), max_error(base))
        self.assertGreater(max_error(base), max_error(fine))
        for cell in (coarse, base, fine):
            self.assertTrue(cell["result"]["diagnostics"]["converged"])
            self.assertFalse(cell["verdicts"]["recovery_pass"])

    def test_gamma_island(self):
        # gamma=0.05 stalls (6.69e-4) with recovering neighbors
        # (0.045 and 0.055 both pass): a narrow stall island.
        stall = cell_by_id(FULL_MATRIX, "m2-stall-g005")
        recover = cell_by_id(FULL_MATRIX, "m2-recover-g0055")
        self.assertTrue(stall["result"]["diagnostics"]["converged"])
        self.assertFalse(stall["verdicts"]["recovery_pass"])
        self.assertLess(1e-4, max_error(stall))
        self.assertGreater(1e-3, max_error(stall))
        self.assertTrue(recover["verdicts"]["recovery_pass"])

    def test_cycles_and_box_alignment(self):
        # w=1.0 (0.5 cycles in span) stalls; the same Fable-family
        # data under a narrowed omega box stalls too (grid/valley
        # alignment, not data, decides); the 512x128 grid stalls
        # MARGINALLY (1.18e-6, just above tolerance) while both
        # coarser and finer grids recover — non-monotonic proof.
        for config_id, lo, hi in (
                ("m2-stall-w10", 1e-5, 1e-4),
                ("m2-box-narrow", 1e-4, 1e-3),
                ("m2-grid-512", 1e-6, 1e-5)):
            cell = cell_by_id(FULL_MATRIX, config_id)
            self.assertTrue(cell["result"]["diagnostics"]["converged"],
                            config_id)
            self.assertFalse(cell["verdicts"]["recovery_pass"],
                             config_id)
            self.assertLess(lo, max_error(cell), config_id)
            self.assertGreater(hi, max_error(cell), config_id)

    def test_dense_recovery_point(self):
        # Fable's recovery anchor: 200 points recover to 1e-10.
        cell = cell_by_id(FULL_MATRIX, "m2-recover-n200")
        self.assertTrue(cell["verdicts"]["recovery_pass"])
        self.assertLess(max_error(cell), 1e-6)


class MatrixVerdicts(unittest.TestCase):
    def test_verdict_logic_all_cells(self):
        # Independent recomputation of the ENTIRE verdict layer:
        # within == (float error <= tolerance); pass == converged
        # and all within. Any divergence is a matrix defect.
        for cell in FULL_MATRIX["cells"]:
            diagnostics = cell["result"]["diagnostics"]
            errors = diagnostics["errors_vs_truth"] or {}
            expected = {}
            for param, tolerance in cell["tolerances"].items():
                error = errors.get(param)
                expected[param] = (isinstance(error, float)
                                   and error <= tolerance)
            stored = cell["verdicts"]["per_parameter"]
            self.assertEqual(set(stored), set(expected),
                             cell["config_id"])
            for param, want in expected.items():
                self.assertIs(stored[param]["within"], want,
                              (cell["config_id"], param))
                self.assertEqual(stored[param]["error"],
                                 errors.get(param),
                                 (cell["config_id"], param))
            want_pass = (diagnostics["converged"] is True
                         and all(expected.values()))
            self.assertIs(cell["verdicts"]["recovery_pass"], want_pass,
                          cell["config_id"])

    def test_hand_subset_value_for_value(self):
        # The 4-pt M1 and 8-pt M2 micro cells are hand-checkable
        # (exact normal equations / peak-ratio closed forms in the
        # fitter suites): both pass, with errors far inside tol.
        for config_id in ("m1-micro-4pt", "m2-micro-8pt"):
            cell = cell_by_id(FULL_MATRIX, config_id)
            self.assertTrue(cell["verdicts"]["recovery_pass"],
                            config_id)
            for param, entry in cell["verdicts"][
                    "per_parameter"].items():
                self.assertTrue(entry["within"], (config_id, param))
                self.assertLess(entry["error"], 1e-6,
                                (config_id, param))

    def test_mismatch_cell_passes_but_flagged(self):
        # M2 on ideal data: the fit is CORRECT (all four params
        # within tol, gamma ~5e-10) AND honestly flagged (gamma
        # edge + mismatch warnings). Pass + flag compose.
        cell = cell_by_id(FULL_MATRIX, "m2-mismatch-ideal")
        self.assertTrue(cell["verdicts"]["recovery_pass"])
        details = [entry["detail"]
                   for entry in cell["result"]["fit"]["warnings"]]
        self.assertIn(MISMATCH_DETAIL, details)
        self.assertTrue(
            cell["result"]["diagnostics"]
            ["gamma_grid_best_at_lower_edge"])

    def test_descriptive_stats_recomputed(self):
        # One descriptive entry recomputed independently with a
        # plain loop (same algorithm -> exact equality).
        descriptives = FULL_MATRIX["summary"]["error_descriptives"]
        values = [cell["result"]["diagnostics"]["errors_vs_truth"]
                  ["amplitude_rad"]
                  for cell in FULL_MATRIX["cells"]
                  if cell["fitter"] == "M2"
                  and cell["result"]["diagnostics"]["converged"] is True]
        total = 0.0
        for value in values:
            total += value
        self.assertEqual(descriptives["M2"]["amplitude_rad"], {
            "n": len(values), "min": min(values), "max": max(values),
            "mean": total / len(values)})

    def test_repeatability_seeds_differ_descriptively(self):
        # Same noisy config under 3 seeds: all run converged (no
        # verdicts claimed beyond the data), errors differ per
        # seed (different noise draws), descriptives aggregate.
        errors = []
        for config_id in ("m2-noise-seed11", "m2-noise-seed42",
                          "m2-noise-seed99"):
            cell = cell_by_id(FULL_MATRIX, config_id)
            self.assertTrue(cell["result"]["diagnostics"]["converged"],
                            config_id)
            errors.append(tuple(sorted(
                cell["result"]["diagnostics"]["errors_vs_truth"].items())))
        self.assertEqual(len(set(errors)), 3)


class MatrixFailureCells(unittest.TestCase):
    def test_budget_and_flat_cells(self):
        for config_id, reason in (
                ("m1-budget0", "refine_budget_exhausted"),
                ("m1-flat", "flat_objective_unidentifiable"),
                ("m2-budget0", "refine_budget_exhausted"),
                ("m2-flat", "flat_objective_unidentifiable")):
            cell = cell_by_id(FULL_MATRIX, config_id)
            diagnostics = cell["result"]["diagnostics"]
            self.assertFalse(diagnostics["converged"], config_id)
            self.assertEqual(diagnostics["termination_reason"], reason,
                             config_id)
            self.assertFalse(cell["verdicts"]["recovery_pass"],
                             config_id)
            self.assertIsNone(cell["result"]["fit"]["residual_summary"],
                              config_id)

    def test_bound_and_edge_cells_warn(self):
        # M1 flags bounds in diagnostics (KL-5.2 design: no M1
        # bound warnings); M2 warns (KL-5.3 deliverable). The
        # matrix shows both surfaces faithfully.
        amp = cell_by_id(FULL_MATRIX, "m1-amp-hit")
        self.assertEqual(len(amp["result"]["diagnostics"]["bound_hits"]),
                         1)
        self.assertFalse(amp["verdicts"]["recovery_pass"])
        edge = cell_by_id(FULL_MATRIX, "m1-omega-edge")
        self.assertTrue(edge["result"]["diagnostics"]
                        ["omega_grid_best_at_lower_edge"])
        m2amp = cell_by_id(FULL_MATRIX, "m2-amp-hit")
        self.assertEqual(
            [entry["code"] for entry in
             m2amp["result"]["fit"]["warnings"]],
            ["W_UNCERTAINTY_UNAVAILABLE", "W_ASSUMPTION_UNVERIFIED"])
        m2edge = cell_by_id(FULL_MATRIX, "m2-gamma-edge")
        self.assertTrue(m2edge["result"]["diagnostics"]
                        ["gamma_grid_best_at_lower_edge"])
        self.assertIn("W_ASSUMPTION_UNVERIFIED",
                      [entry["code"] for entry in
                       m2edge["result"]["fit"]["warnings"]])

    def test_cross_model_m1_on_damped(self):
        cell = cell_by_id(FULL_MATRIX, "m1-on-damped")
        self.assertTrue(cell["result"]["diagnostics"]["converged"])
        self.assertFalse(cell["verdicts"]["recovery_pass"])
        # Envelope bias lands mostly on amplitude (4.8e-2).
        self.assertGreater(
            cell["result"]["diagnostics"]["errors_vs_truth"]
            ["amplitude_rad"], 1e-2)


class MatrixAudits(unittest.TestCase):
    def test_gravity_absent_everywhere(self):
        for cell in FULL_MATRIX["cells"]:
            fit = cell["result"]["fit"]
            self.assertIsNone(fit["gravity_m_s2"], cell["config_id"])
            self.assertIsNone(fit["pivot_length_mm"], cell["config_id"])
            self.assertEqual(fit["pivot_length_source"], "not_provided",
                             cell["config_id"])
            self.assertIn("TEST", cell["result"]["test_convention_note"],
                          cell["config_id"])
        # Byte-level: the gravity unit label appears NOWHERE in the
        # export (the absence note spells the unit out in words).
        self.assertNotIn(b"m/s^2", FULL_BYTES)
        # Positive controls: g/L units and the TEST note DO appear.
        self.assertIn(b"1/s^2", FULL_BYTES)
        self.assertIn(b"TEST RECOVERY", FULL_BYTES)

    def test_uncertainty_absent_everywhere(self):
        for cell in FULL_MATRIX["cells"]:
            fit = cell["result"]["fit"]
            self.assertEqual(fit["fit_uncertainty_method"], "none",
                             cell["config_id"])
            self.assertIn("W_UNCERTAINTY_UNAVAILABLE",
                          [entry["code"] for entry in fit["warnings"]],
                          cell["config_id"])
        summary = FULL_MATRIX["summary"]
        self.assertIn("KL-6", summary["uncertainty"]["note"])
        self.assertIn("fabricated", summary["uncertainty"]["note"])

    def test_no_banned_statistical_language(self):
        for phrase in (b"global optimum", b"scientifically accurate",
                       b"validated uncertainty", b"confidence interval",
                       b"p-value", b"significant"):
            self.assertNotIn(phrase, FULL_BYTES, phrase)


class MatrixDeterminism(unittest.TestCase):
    def test_byte_pin(self):
        self.assertEqual(hashlib.sha256(FULL_BYTES).hexdigest(),
                         MATRIX_JSON_SHA)

    def test_rerun_identical_bytes(self):
        rerun = export_matrix_json(run_matrix(FULL_REQUEST))
        self.assertEqual(rerun, FULL_BYTES)

    def test_round_trip_exact(self):
        self.assertEqual(parse_matrix_json(FULL_BYTES), FULL_MATRIX)

    def test_parse_rejects_tampered_verdicts(self):
        tampered = copy.deepcopy(FULL_MATRIX)
        cell = tampered["cells"][0]
        first = next(iter(cell["verdicts"]["per_parameter"].values()))
        first["within"] = not first["within"]
        with self.assertRaises(ContractError) as raised:
            parse_matrix_json(export_matrix_json(tampered))
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_parse_rejects_broken_fit(self):
        tampered = copy.deepcopy(FULL_MATRIX)
        del tampered["cells"][0]["result"]["fit"]["parameters"]
        with self.assertRaises(ContractError) as raised:
            parse_matrix_json(export_matrix_json(tampered))
        self.assertIn("E_MISSING_FIELD", raised.exception.codes)
        fields = [error.field for error in raised.exception.errors]
        self.assertTrue(all(field.startswith("cells[0].result.fit")
                            for field in fields))


class MatrixRejections(unittest.TestCase):
    def test_non_dict_request_rejected(self):
        with self.assertRaises(ContractError) as raised:
            run_matrix([])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])

    def test_shape_rejections(self):
        def base():
            # Deep copy: subtest mutations must never leak into
            # FULL_REQUEST (shared by the determinism rerun) or
            # across subtests.
            return {"matrix_id": "t",
                    "configs": [copy.deepcopy(
                        FULL_REQUEST["configs"][0])]}

        cells = []
        extra = base()
        extra["model"] = "M3"
        cells.append((extra, ["E_UNEXPECTED_FIELD"]))
        missing = base()
        del missing["matrix_id"]
        cells.append((missing, ["E_MISSING_FIELD"]))
        empty_id = base()
        empty_id["matrix_id"] = ""
        cells.append((empty_id, ["E_EMPTY_STRING"]))
        null_id = base()
        null_id["matrix_id"] = None
        cells.append((null_id, ["E_NULL_NOT_ALLOWED"]))
        bad_configs = base()
        bad_configs["configs"] = {}
        cells.append((bad_configs, ["E_WRONG_TYPE"]))
        empty_configs = base()
        empty_configs["configs"] = []
        cells.append((empty_configs, ["E_OUT_OF_RANGE"]))
        many_configs = base()
        many_configs["configs"] = [copy.deepcopy(
            FULL_REQUEST["configs"][0]) for _ in range(65)]
        for index, entry in enumerate(many_configs["configs"]):
            entry["config_id"] = f"cell-{index}"
        cells.append((many_configs, ["E_OUT_OF_RANGE"]))
        non_dict_cell = base()
        non_dict_cell["configs"] = [[]]
        cells.append((non_dict_cell, ["E_WRONG_TYPE"]))
        extra_key = base()
        extra_key["configs"][0]["seed"] = 1
        cells.append((extra_key, ["E_UNEXPECTED_FIELD"]))
        missing_key = base()
        del missing_key["configs"][0]["fitter"]
        cells.append((missing_key, ["E_MISSING_FIELD"]))
        empty_cell_id = base()
        empty_cell_id["configs"][0]["config_id"] = ""
        cells.append((empty_cell_id, ["E_EMPTY_STRING"]))
        dup_id = base()
        dup_id["configs"] = [copy.deepcopy(FULL_REQUEST["configs"][0]),
                             copy.deepcopy(FULL_REQUEST["configs"][0])]
        cells.append((dup_id, ["E_INCOHERENT_VALUE"]))
        bad_fitter = base()
        bad_fitter["configs"][0]["fitter"] = "M3"
        cells.append((bad_fitter, ["E_BAD_ENUM"]))
        null_spec = base()
        null_spec["configs"][0]["trajectory_spec"] = None
        cells.append((null_spec, ["E_NULL_NOT_ALLOWED"]))
        m1_gamma = base()
        m1_gamma["configs"][0]["fit_options"]["grid_n_gamma"] = 40
        cells.append((m1_gamma, ["E_UNEXPECTED_FIELD"]))
        missing_grid = base()
        missing_grid["configs"][0] = copy.deepcopy(
            FULL_REQUEST["configs"][10])
        del missing_grid["configs"][0]["fit_options"]["grid_n_gamma"]
        cells.append((missing_grid, ["E_MISSING_FIELD"]))
        for index, (request, codes) in enumerate(cells):
            with self.subTest(cell=index):
                with self.assertRaises(ContractError) as raised:
                    run_matrix(request)
                self.assertEqual(raised.exception.codes, codes)

    def test_execution_errors_prefixed(self):
        bad_spec = {"matrix_id": "t", "configs": [copy.deepcopy(
            FULL_REQUEST["configs"][0])]}
        bad_spec["configs"][0]["trajectory_spec"]["model"] = "M3"
        with self.assertRaises(ContractError) as raised:
            run_matrix(bad_spec)
        self.assertEqual(raised.exception.codes, ["E_BAD_ENUM"])
        self.assertTrue(all(
            error.field.startswith("configs[0].trajectory_spec")
            for error in raised.exception.errors))
        bad_bounds = {"matrix_id": "t", "configs": [copy.deepcopy(
            FULL_REQUEST["configs"][0])]}
        bad_bounds["configs"][0]["fit_options"]["bounds"][
            "omega_per_s"] = [8.0, 0.5]
        with self.assertRaises(ContractError) as raised:
            run_matrix(bad_bounds)
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertTrue(all(
            error.field.startswith("configs[0].fit_options")
            for error in raised.exception.errors))


if __name__ == "__main__":
    unittest.main()
