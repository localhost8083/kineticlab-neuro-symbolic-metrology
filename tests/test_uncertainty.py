"""Seeded block-bootstrap uncertainty tests (KL-10.11).

Covers kineticlab.fit.uncertainty in isolation (determinism,
block math, percentiles, fail-closed paths) on fast synthetic
records, plus the demo-replay integration through assemble():
the interval is present, contains the point, maps omega->g/L by
x^2, and the uncertainty warning lifts exactly when it should.

Exact float pins are same-platform (libm drifts cross-platform);
structural assertions run everywhere.
"""

import hashlib
import json
import math
import os
import tempfile
import unittest
from pathlib import Path

from kineticlab.assembly import assemble, render_summary_md
from kineticlab.assembly import build as build_module
from kineticlab.fit.synthetic import generate_trajectory
from kineticlab.fit.uncertainty import (
    BOOTSTRAP_SEED,
    N_BOOT,
    omega_interval,
    period_block_frames,
)
from kineticlab.fit.uncertainty import (
    _percentile as _bootstrap_percentile,
)
from kineticlab.fit.uncertainty import (
    _TEMPLATE_BOUNDS,
    _TEMPLATE_GRID_N_OMEGA,
    _TEMPLATE_MAX_REFINE,
)
from tests import require_smoke
from tests.test_assembly import G_OVER_L_PIN, REQUEST

REPO_ROOT = Path(__file__).resolve().parent.parent

PIN_SAME_PLATFORM = unittest.skipIf(
    os.environ.get("KL_CROSS_PLATFORM") == "1",
    "byte pins are same-platform determinism; cross-platform "
    "libm drifts in the last ulp (KL-10.10)")


def _synthetic_records():
    """100 noisy ideal points, ~5 one-second periods, fixed pivot."""
    trajectory = generate_trajectory({
        "model": "ideal",
        "seed": 11,
        "amplitude_rad": 0.3,
        "angular_frequency_per_s": 2.0 * math.pi,
        "period_s": None,
        "phase_rad": 0.1,
        "damping_per_s": None,
        "pivot_x_px": 512.0,
        "pivot_y_px": 288.0,
        "length_px": 200.0,
        "time": {"mode": "uniform", "t0_s": 0.0, "dt_s": 0.05,
                 "n": 100},
        "noise": {"mode": "gaussian", "sigma_px": 1.5},
        "gaps": [],
        "outliers": [],
    })
    ground = trajectory["ground_truth"]
    records = [{"t_seconds": sample["t_seconds"],
                "x_px": sample["x_px"], "y_px": sample["y_px"]}
               for sample in trajectory["samples"]]
    return records, ground["pivot_x_px"], ground["pivot_y_px"]


class TemplateLockTests(unittest.TestCase):
    def test_replicate_template_matches_main_fit(self):
        # Replicates must run the SAME estimator/termination as the
        # assembly main fit: the module mirrors build.py's request
        # template (a direct import would invert the layering), and
        # this test locks the mirror.
        self.assertEqual(_TEMPLATE_BOUNDS["amplitude_rad"],
                         list(build_module.AMP_BOUNDS))
        self.assertEqual(_TEMPLATE_BOUNDS["omega_per_s"],
                         list(build_module.OMEGA_BOUNDS))
        self.assertEqual(_TEMPLATE_GRID_N_OMEGA,
                         build_module.GRID_N_OMEGA)
        self.assertEqual(_TEMPLATE_MAX_REFINE, build_module.MAX_REFINE)


class BlockMathTests(unittest.TestCase):
    def test_period_block_formula(self):
        # 100 frames over 4.95 s, 1 s period: 100*1/4.95 = 20.2..
        # -> 21 frames per block.
        self.assertEqual(period_block_frames(100, 1.0, 4.95), 21)
        self.assertEqual(period_block_frames(234, 1.147, 7.7), 35)
        self.assertEqual(period_block_frames(10, 0.5, 10.0), 1)

    def test_period_block_garbage_is_none(self):
        for args in ((1, 1.0, 1.0), (0, 1.0, 1.0),
                     (100, 0.0, 1.0), (100, -1.0, 1.0),
                     (100, 1.0, 0.0), (100, 1.0, -2.0),
                     (100, float("nan"), 1.0),
                     (100, 1.0, float("inf")),
                     ("100", 1.0, 1.0), (True, 1.0, 1.0)):
            with self.subTest(args=args):
                self.assertIsNone(period_block_frames(*args))

    def test_percentile_linear_interpolation(self):
        self.assertEqual(_bootstrap_percentile([4.0], 2.5), 4.0)
        self.assertEqual(_bootstrap_percentile([0.0, 10.0], 50.0), 5.0)
        vals = [float(i) for i in range(101)]
        self.assertEqual(_bootstrap_percentile(vals, 2.5), 2.5)
        self.assertEqual(_bootstrap_percentile(vals, 97.5), 97.5)


class DeterminismTests(unittest.TestCase):
    @PIN_SAME_PLATFORM
    def test_same_seed_twice_identical(self):
        records, pivot_x, pivot_y = _synthetic_records()
        first = omega_interval(records, pivot_x_px=pivot_x,
                               pivot_y_px=pivot_y, seed=7,
                               n_boot=64)
        second = omega_interval(records, pivot_x_px=pivot_x,
                                pivot_y_px=pivot_y, seed=7,
                                n_boot=64)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)

    def test_interval_structure(self):
        records, pivot_x, pivot_y = _synthetic_records()
        out = omega_interval(records, pivot_x_px=pivot_x,
                             pivot_y_px=pivot_y, seed=7, n_boot=64)
        self.assertIsNotNone(out)
        self.assertEqual(out["method"], "block_bootstrap")
        self.assertEqual(out["seed"], 7)
        self.assertEqual(out["n_boot"], 64)
        self.assertIs(type(out["block_frames"]), int)
        self.assertGreater(out["block_frames"], 0)
        omega = out["omega_per_s"]
        band = out["g_over_l_eff_per_s2"]
        for part in (omega, band):
            self.assertLessEqual(part["low"], part["point"])
            self.assertLessEqual(part["point"], part["high"])
            self.assertGreater(part["high"], part["low"])
        # g/L endpoints are the omega endpoints through x -> x^2
        # (same operation, bit-exact within the run).
        self.assertEqual(band["low"], omega["low"] * omega["low"])
        self.assertEqual(band["high"],
                         omega["high"] * omega["high"])
        self.assertIs(type(out["extended_to_contain_point"]), bool)


class FailClosedTests(unittest.TestCase):
    def test_insufficient_data_returns_none(self):
        records, pivot_x, pivot_y = _synthetic_records()
        tiny = records[:2]
        self.assertIsNone(omega_interval(
            tiny, pivot_x_px=pivot_x, pivot_y_px=pivot_y,
            seed=1, n_boot=8))
        self.assertIsNone(omega_interval(
            [], pivot_x_px=pivot_x, pivot_y_px=pivot_y,
            seed=1, n_boot=8))
        self.assertIsNone(omega_interval(
            "nope", pivot_x_px=pivot_x, pivot_y_px=pivot_y,
            seed=1, n_boot=8))
        # Degenerate span: every frame at the same instant.
        frozen = [dict(record, t_seconds=1.0) for record in records]
        self.assertIsNone(omega_interval(
            frozen, pivot_x_px=pivot_x, pivot_y_px=pivot_y,
            seed=1, n_boot=8))
        # Non-finite cell anywhere fails the interval closed.
        bad = [dict(record) for record in records]
        bad[10]["x_px"] = float("nan")
        self.assertIsNone(omega_interval(
            bad, pivot_x_px=pivot_x, pivot_y_px=pivot_y,
            seed=1, n_boot=8))

    def test_bad_arguments_raise(self):
        records, pivot_x, pivot_y = _synthetic_records()
        with self.assertRaises(ValueError):
            omega_interval(records, pivot_x_px=pivot_x,
                           pivot_y_px=pivot_y, seed="7", n_boot=8)
        with self.assertRaises(ValueError):
            omega_interval(records, pivot_x_px=pivot_x,
                           pivot_y_px=pivot_y, seed=True, n_boot=8)
        for n_boot in (0, -3, 2.5):
            with self.subTest(n_boot=n_boot):
                with self.assertRaises(ValueError):
                    omega_interval(
                        records, pivot_x_px=pivot_x,
                        pivot_y_px=pivot_y, seed=1, n_boot=n_boot)


class DemoReplayUncertaintyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(REQUEST["clip_path"])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.out = assemble(dict(REQUEST, out_dir=cls.tmp.name))

    def test_status_method_warnings_flip(self):
        result = self.out["result"]
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["interval_method"], "block_bootstrap")
        self.assertEqual(result["fit"]["fit_uncertainty_method"],
                         "block_bootstrap")
        self.assertEqual(result["fit"]["warnings"], [])
        codes = [warning["code"]
                 for warning in result["warnings"]]
        self.assertNotIn("W_UNCERTAINTY_UNAVAILABLE", codes)
        # The reported value itself is untouched by the bootstrap.
        self.assertTrue(math.isclose(result["value"], G_OVER_L_PIN,
                                     rel_tol=1e-9))

    def test_interval_containment_and_mapping(self):
        result = self.out["result"]
        band = self.out["diagnostics"]["fit_uncertainty"][
            "g_over_l_eff_per_s2"]
        omega = self.out["diagnostics"]["fit_uncertainty"][
            "omega_per_s"]
        self.assertEqual(result["interval"],
                         {"lower": band["low"], "upper": band["high"]})
        self.assertLess(band["low"], band["point"])
        self.assertLess(band["point"], band["high"])
        self.assertLess(omega["low"], omega["point"])
        self.assertLess(omega["point"], omega["high"])
        self.assertEqual(band["low"], omega["low"] * omega["low"])
        self.assertEqual(band["high"],
                         omega["high"] * omega["high"])
        self.assertEqual(band["point"], result["value"])
        self.assertFalse(self.out["diagnostics"]["fit_uncertainty"][
            "extended_to_contain_point"])

    def test_fit_uncertainty_echo(self):
        fu = self.out["diagnostics"]["fit_uncertainty"]
        self.assertEqual(fu["method"], "block_bootstrap")
        self.assertEqual(fu["seed"], BOOTSTRAP_SEED)
        self.assertEqual(fu["n_boot"], N_BOOT)
        self.assertGreater(fu["block_frames"], 1)
        self.assertLess(fu["block_frames"], 234)

    @PIN_SAME_PLATFORM
    def test_block_frames_pin(self):
        fu = self.out["diagnostics"]["fit_uncertainty"]
        self.assertEqual(fu["block_frames"], 36)

    def test_assumptions_honesty_sentences(self):
        assumptions = self.out["result"]["assumptions"]
        joined = "\n".join(assumptions)
        # The stale =none adequacy sentence is gone on success.
        self.assertNotIn("fit_uncertainty_method=none", joined)
        # Point-estimate framing + limitation survive (c).
        self.assertIn("point estimate", joined)
        self.assertIn("structured-residual limitation", joined)
        # Honesty sentences (a) measurement noise, not bias ...
        self.assertIn("measurement noise under the M1 model",
                      joined)
        self.assertIn("not M1 model-adequacy bias", joined)
        # ... and (b) resampling, not analytic.
        self.assertIn("not an analytic derivation", joined)
        self.assertIn("preserves short-range time dependence",
                      joined)

    def test_summary_uncertainty_section(self):
        hashes = {name: hashlib.sha256(
            f"kl1011-{name}".encode("utf-8")).hexdigest()
            for name in ("result.json", "diagnostics.json",
                         "angles.csv")}
        text = render_summary_md(self.out["result"],
                                 self.out["diagnostics"], hashes)
        self.assertIn("## Uncertainty", text)
        fu = self.out["diagnostics"]["fit_uncertainty"]
        omega = fu["omega_per_s"]
        band = fu["g_over_l_eff_per_s2"]
        self.assertIn(f"- method: {fu['method']}", text)
        self.assertIn(f"- seed: {fu['seed']!r}", text)
        self.assertIn(f"- n_boot: {fu['n_boot']!r}", text)
        self.assertIn(f"- block_frames: {fu['block_frames']!r}",
                      text)
        self.assertIn(f"low {omega['low']!r}, "
                      f"point {omega['point']!r}, "
                      f"high {omega['high']!r}", text)
        self.assertIn(f"low {band['low']!r}, "
                      f"point {band['point']!r}, "
                      f"high {band['high']!r}", text)
        section = text.split("## Uncertainty")[1].split("## ")[0]
        self.assertNotIn("standard error", section)
        self.assertNotIn("confidence", section)


if __name__ == "__main__":
    unittest.main()
