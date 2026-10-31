"""End-to-end offline assembly tests (KL-7.1).

Covers: fit-point partitioning (null/invalid rows excluded with
frame lists, never silent); angle-series unwrap (hand-computed
micro-case) plus cross-check of assembly thetas against fitter
residuals + fitted curve (1e-9, kills formula drift); the live
success path (success_with_warnings, pinned g/L, M2 included with
justification, exports written + re-validated); rejection states
via the parts seam (starved input -> insufficient_data +
E_OUT_OF_RANGE; flat/pivot points -> insufficient_data +
E_INCOHERENT_VALUE with the non-converged fit embedded);
request/pin validation (registered codes); CSV contract + JSON
canonical bytes; pin regeneration (parsed isclose compare).

KL-7.2 adds: the critical/non-critical mapping lock (every locked
code covered, insufficient_data never a routing target);
upstream critical failures per stage (ingest garbage ->
unsupported_input, observation bad wire -> unsupported_input
with partial frames retained, geometry corrupt pin ->
unsupported_input with calibration retained + pivotless pin ->
processing_error); non-critical warnings staying in the
success family (pin-inspected, no refit); rejection exports
written; rejection-pin regeneration.

KL-7.3 adds: the human-auditable summary.md renderer (numbers
copied, never recomputed; export SHA-256 list; rejections
unmistakable). Render tests run pure from the pinned JSONs
(no assemble); file/hash/determinism tests reuse the
regeneration runs plus one explicit double-run on the
no-fit rejection path.

KL-7.4 adds: the pinned frame-0 audit walkthrough (README
citations asserted against the pins), summary verdicts for
the remaining rejection states, and the pinned statement
that plain success is structurally unreachable.
"""

import copy
import csv
import hashlib
import io
import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from kineticlab.assembly import (
    ARTIFACT_HASH_KEYS,
    HASHED_FILES,
    NON_CRITICAL_WARNINGS,
    REJECTION_STATE,
    SUMMARY_FILENAME,
    angle_series,
    assemble,
    assemble_parts,
    build_fit_points,
    export_angles_csv,
    export_diagnostics_json,
    export_result_json,
    m2_section,
    render_summary_md,
)
from kineticlab.contracts import (
    ERROR_CODES,
    WARNING_CODES,
    ContractError,
    ResultContract,
)
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
ASM_DIR = REPO_ROOT / "fixtures" / "assembly"

G_OVER_L_PIN = 30.00563573707589
GAMMA_PIN = 0.029794544246787853
RADIUS_MM_PIN = 298.2283771265327

REQUEST = {
    "clip_path": str(REPO_ROOT / "Smoke" / "test_3.mp4"),
    "raw_bob_path": str(REPO_ROOT / "fixtures" / "live"
                        / "raw_bob_one_bit.txt"),
    "raw_card_path": str(REPO_ROOT / "fixtures" / "live"
                         / "raw_card_one_bit.txt"),
    "calibration_path": str(REPO_ROOT / "fixtures" / "geometry"
                            / "calibration_live.json"),
    "geometry_report_path": str(REPO_ROOT / "fixtures" / "geometry"
                                / "geometry_report_live.json"),
}


def _assert_close_tree(test_case, first, second, *, rel=1e-9, path=""):
    if isinstance(first, float) or isinstance(second, float):
        test_case.assertTrue(
            math.isclose(first, second, rel_tol=rel, abs_tol=1e-12),
            f"{path}: {first!r} vs {second!r}")
    elif isinstance(first, dict):
        test_case.assertEqual(set(first), set(second), path)
        for key in first:
            _assert_close_tree(test_case, first[key], second[key],
                               rel=rel, path=f"{path}.{key}")
    elif isinstance(first, (list, tuple)):
        test_case.assertEqual(len(first), len(second), path)
        for index, (a, b) in enumerate(zip(first, second)):
            _assert_close_tree(test_case, a, b, rel=rel,
                               path=f"{path}[{index}]")
    else:
        test_case.assertEqual(first, second, path)


def _with_basename_exports(node):
    node = copy.deepcopy(node)
    for ref in node.get("exports", []):
        ref["path"] = os.path.basename(ref["path"])
    return node


_HASH_TAGS = {
    "raw_bob_sha256": "b0",
    "raw_card_sha256": "ca",
    "calibration_sha256": "1d",
    "geometry_report_sha256": "60",
}


def _synthetic_hashes():
    """Per-key distinct labeled digests for seam tests (not evidence)."""
    return {key: _HASH_TAGS[key] * 32 for key in ARTIFACT_HASH_KEYS}


def _blank_result_hash_line(text):
    # result.json embeds its own out-dir export refs (verified
    # KL-7.1 behavior), so its hash line legitimately varies with
    # the output directory. Everything else must be identical.
    return "\n".join(
        "- result.json: <out-dir-dependent>"
        if line.startswith("- result.json: ") else line
        for line in text.split("\n"))


def _blank_line_prefix(text, prefix, token):
    # KL-10.11: normalize one full summary line by prefix. Callers
    # assert the exact content before blanking; the byte-compare
    # then covers everything else.
    return "\n".join(
        token if line.startswith(prefix) else line
        for line in text.split("\n"))


class AnglesTests(unittest.TestCase):
    def test_partition_excludes_explicitly(self):
        records = [
            SimpleNamespace(frame_index=0, valid=True, pts_seconds=0.0,
                            centroid_x_px=1.0, centroid_y_px=2.0),
            SimpleNamespace(frame_index=1, valid=False, pts_seconds=0.1,
                            centroid_x_px=1.0, centroid_y_px=2.0),
            SimpleNamespace(frame_index=2, valid=True, pts_seconds=None,
                            centroid_x_px=1.0, centroid_y_px=2.0),
            SimpleNamespace(frame_index=3, valid=True, pts_seconds=0.3,
                            centroid_x_px=None, centroid_y_px=2.0),
        ]
        out = build_fit_points(records)
        self.assertEqual(len(out["points"]), 1)
        self.assertEqual(out["excluded_frames"], [1, 2, 3])
        self.assertEqual(out["n_total"], 4)

    def test_partition_rejects_malformed(self):
        with self.assertRaises(ContractError):
            build_fit_points("nope")
        bad = [SimpleNamespace(frame_index="x", valid=True,
                               pts_seconds=0.0, centroid_x_px=1.0,
                               centroid_y_px=2.0)]
        with self.assertRaises(ContractError) as raised:
            build_fit_points(bad)
        self.assertIn("E_WRONG_TYPE", raised.exception.codes)

    def test_unwrap_micro_case(self):
        # Hand-computed: atan2(x, y) about (0, 0), unwrapped.
        points = [{"t_seconds": 0.0, "x_px": 1.0, "y_px": 0.0,
                   "frame_index": 0},
                  {"t_seconds": 1.0, "x_px": 0.0, "y_px": -1.0,
                   "frame_index": 1},
                  {"t_seconds": 2.0, "x_px": -1.0, "y_px": 0.0,
                   "frame_index": 2}]
        rows = angle_series(points, 0.0, 0.0)
        self.assertAlmostEqual(rows[0]["theta_rad"], math.pi / 2, places=12)
        self.assertAlmostEqual(rows[1]["theta_rad"], math.pi, places=12)
        self.assertAlmostEqual(rows[2]["theta_rad"], 3 * math.pi / 2,
                               places=12)

    def test_angle_series_rejects_malformed(self):
        with self.assertRaises(ContractError):
            angle_series([{"t_seconds": 0.0}], 0.0, 0.0)
        with self.assertRaises(ContractError):
            angle_series([], float("nan"), 0.0)


class LiveChainTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(REQUEST["clip_path"])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = assemble(dict(REQUEST, out_dir=cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_success_path_pins(self):
        result = self.out["result"]
        # KL-10.11: the bootstrap ran, so the uncertainty warning
        # lifted and plain success is reachable again.
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["measurement_name"], "pendulum_g_over_l")
        # Measured stdlib output (libm-bound float).
        self.assertTrue(math.isclose(result["value"], G_OVER_L_PIN,
                                     rel_tol=1e-6))
        self.assertEqual(result["unit"], "1/s^2")
        self.assertEqual(result["identifiable_quantity"],
                         {"name": "g/L_eff", "value": result["value"],
                          "unit": "1/s^2"})
        band = self.out["diagnostics"]["fit_uncertainty"][
            "g_over_l_eff_per_s2"]
        self.assertEqual(result["interval"],
                         {"lower": band["low"], "upper": band["high"]})
        self.assertEqual(result["interval_method"], "block_bootstrap")
        self.assertEqual(result["fit"]["model_id"], "M1")
        self.assertTrue(result["fit"]["converged"])
        self.assertIsNone(result["fit"]["gravity_m_s2"])
        self.assertEqual(result["fit"]["fit_uncertainty_method"],
                         "block_bootstrap")
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["reject_reasons"], [])
        self.assertEqual(result["quality_metrics"],
                         {"frames_total": 234, "frames_usable": 234,
                          "observations_total": 468,
                          "observations_valid": 468,
                          "calibrated_frames": 117})
        assumptions = result["assumptions"]
        self.assertTrue(any("U-3" in text for text in assumptions))
        self.assertTrue(any("M-3e" in text for text in assumptions))
        self.assertTrue(any("phase" in text for text in assumptions))
        # Validated record round-trips exactly.
        checked = ResultContract.from_dict(copy.deepcopy(result))
        self.assertEqual(checked.to_dict(), result)

    def test_no_synthetic_wording_leaks(self):
        blob = json.dumps(self.out).lower()
        self.assertNotIn("synthetic", blob)
        self.assertNotIn("test_convention_note", blob)

    def test_m2_included_with_justification(self):
        m2 = self.out["diagnostics"]["m2"]
        self.assertTrue(m2["included"])
        self.assertIn("strictly inside", m2["justification"])
        self.assertTrue(math.isclose(m2["fitted"]["gamma_per_s"],
                                     GAMMA_PIN, rel_tol=1e-6))
        # Omega cross-checks M1 within 0.1%.
        m1_omega = self.out["diagnostics"]["m1"]["fitted"]["omega_per_s"]
        self.assertTrue(math.isclose(m2["fitted"]["omega_per_s"],
                                     m1_omega, rel_tol=1e-3))

    def test_radius_descriptive_only(self):
        radius = self.out["diagnostics"]["radius"]
        self.assertTrue(math.isclose(radius["radius_mm"], RADIUS_MM_PIN,
                                     rel_tol=1e-12))
        self.assertFalse(radius["independent_length"])
        self.assertTrue(radius["descriptive_only"])
        self.assertIn("U-3", radius["u3_bound"])

    def test_excluded_frames_empty_on_live_chain(self):
        self.assertEqual(self.out["diagnostics"]["excluded_frames"], [])
        self.assertEqual(len(self.out["angle_series"]), 234)

    def test_series_pts_are_real_and_increasing(self):
        # P-007 core: actual source PTS reaches the angle series.
        series = self.out["angle_series"]
        moments = [row["pts_seconds"] for row in series]
        self.assertTrue(all(isinstance(moment, float)
                            for moment in moments))
        self.assertTrue(all(b > a for a, b in zip(moments, moments[1:])))
        self.assertEqual(moments[0], 0.0)
        self.assertTrue(math.isclose(moments[-1], 7.832, rel_tol=1e-4))

    def test_angle_series_matches_fitter_internals(self):
        # Cross-check: assembly thetas == fitted curve + residuals.
        fitted = self.out["diagnostics"]["m1"]["fitted"]
        amplitude = fitted["amplitude_rad"]
        omega = fitted["omega_per_s"]
        phase = fitted["phase_rad"]
        series = self.out["angle_series"]
        residuals = self.out["diagnostics"]["m1"]["residuals"]
        self.assertEqual(len(residuals), len(series))
        worst = 0.0
        for entry in residuals:
            theta = series[entry["point_index"]]["theta_rad"]
            model = amplitude * math.cos(omega * entry["t_seconds"]
                                         + phase)
            worst = max(worst,
                        abs(theta - (model + entry["residual_rad"])))
        self.assertLess(worst, 1e-9)

    def test_exports_written_and_referenced(self):
        refs = self.out["export_refs"]
        for key, name in (("result_json", "result.json"),
                          ("diagnostics_json", "diagnostics.json"),
                          ("angles_csv", "angles.csv")):
            with self.subTest(key=key):
                target = os.path.join(self.tmp.name,
                                      os.path.basename(refs[key]))
                self.assertTrue(os.path.isfile(target))
        formats = {ref["format"] for ref in self.out["result"]["exports"]}
        self.assertEqual(formats, {"result-json", "diagnostics-json",
                                   "angles-csv"})
        pinned = json.loads(
            (ASM_DIR / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(
            {ref["format"] for ref in pinned["exports"]}, formats)


class RejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        cls.report = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "geometry_report_live.json").read_text(encoding="utf-8"))
        cls.clip_sha = "a" * 64  # synthetic stand-in, labeled
        # 234 rows keep metrics coherent with the real pin's
        # calibrated_frames=117 (bounds-checked by the contract).
        cls.table = [SimpleNamespace(frame_index=index,
                                     pts_seconds=index * 0.04,
                                     valid=True)
                     for index in range(234)]
        cls.card = [SimpleNamespace(frame_index=index, valid=True)
                    for index in range(234)]

    def _parts(self, bob, out_dir):
        return dict(
            bob=bob, card=self.card, frame_table=self.table,
            calibration_dict=copy.deepcopy(self.calibration),
            report_pin=copy.deepcopy(self.report),
            clip_sha256=self.clip_sha, out_dir=out_dir,
            raw_bob_display="synthetic-test", raw_card_display="synthetic",
            geometry_report_display="synthetic",
            artifact_hashes=_synthetic_hashes())

    def test_starved_input_insufficient_data(self):
        bob = [SimpleNamespace(frame_index=0, valid=True,
                               pts_seconds=0.0, centroid_x_px=1.0,
                               centroid_y_px=2.0),
               SimpleNamespace(frame_index=1, valid=True,
                               pts_seconds=0.04, centroid_x_px=1.0,
                               centroid_y_px=2.0)]
        with tempfile.TemporaryDirectory() as tmp:
            out = assemble_parts(**self._parts(bob, tmp))
        result = out["result"]
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIsNone(result["value"])
        self.assertIsNone(result["fit"])
        self.assertEqual(len(result["reject_reasons"]), 1)
        reason = result["reject_reasons"][0]
        self.assertEqual(reason["code"], "E_OUT_OF_RANGE")
        self.assertIn("2 fittable points", reason["detail"])
        checked = ResultContract.from_dict(copy.deepcopy(result))
        self.assertEqual(checked.to_dict(), result)

    def test_flat_objective_insufficient_data(self):
        # All points exactly on the pivot: every theta is 0.0, the
        # fitter reports flat_objective_unidentifiable honestly.
        pivot = self.report["pivot_arc"]["center_px"]
        bob = [SimpleNamespace(frame_index=index, valid=True,
                               pts_seconds=index * 0.04,
                               centroid_x_px=pivot[0],
                               centroid_y_px=pivot[1])
               for index in range(5)]
        with tempfile.TemporaryDirectory() as tmp:
            out = assemble_parts(**self._parts(bob, tmp))
        result = out["result"]
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["reject_reasons"][0]["code"],
                         "E_INCOHERENT_VALUE")
        self.assertIn("flat_objective_unidentifiable",
                      result["reject_reasons"][0]["detail"])
        self.assertIsNotNone(result["fit"])
        self.assertFalse(result["fit"]["converged"])
        checked = ResultContract.from_dict(copy.deepcopy(result))
        self.assertEqual(checked.to_dict(), result)


class M2RuleTests(unittest.TestCase):
    def _m2(self, converged, termination, gamma):
        return {
            "diagnostics": {
                "converged": converged,
                "termination_reason": termination,
                "fitted": {"gamma_per_s": gamma, "omega_per_s": 5.0},
                "bound_hits": [],
            },
            "fit": {"g_over_l_per_s2": 25.0, "warnings": []},
        }

    def test_interior_gamma_included(self):
        section = m2_section(self._m2(True, "refine_tolerance_met", 0.03))
        self.assertTrue(section["included"])
        self.assertIn("included", section["justification"])

    def test_non_converged_excluded(self):
        section = m2_section(self._m2(False, "refine_budget_exhausted",
                                      0.03))
        self.assertFalse(section["included"])
        self.assertIn("did not converge", section["justification"])

    def test_edge_gamma_excluded(self):
        for gamma in (0.0, 1.0, 1.5):
            with self.subTest(gamma=gamma):
                section = m2_section(
                    self._m2(True, "refine_tolerance_met", gamma))
                self.assertFalse(section["included"])
                self.assertIn("bounds", section["justification"])


class RequestValidationTests(unittest.TestCase):
    def test_malformed_requests_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = dict(REQUEST, out_dir=tmp)
            for bad in ("nope", None, 42):
                with self.subTest(bad=bad):
                    with self.assertRaises(ContractError):
                        assemble(bad)
            extra = dict(good, smuggled=True)
            with self.assertRaises(ContractError) as raised:
                assemble(extra)
            self.assertIn("E_UNEXPECTED_FIELD", raised.exception.codes)
            missing = {key: value for key, value in good.items()
                       if key != "clip_path"}
            with self.assertRaises(ContractError) as raised:
                assemble(missing)
            self.assertIn("E_MISSING_FIELD", raised.exception.codes)
            empty = dict(good, clip_path="")
            with self.assertRaises(ContractError) as raised:
                assemble(empty)
            self.assertIn("E_EMPTY_STRING", raised.exception.codes)

    def test_bad_pins_rejected(self):
        # KL-7.2 contract change (task-mandated): bad pins reject
        # as result states with the same codes, no longer raise.
        require_smoke(REQUEST["clip_path"])
        with tempfile.TemporaryDirectory() as tmp:
            garbage = os.path.join(tmp, "pin.json")
            with open(garbage, "w", encoding="utf-8") as handle:
                handle.write("{not json")
            bad = dict(REQUEST, out_dir=tmp,
                       calibration_path=garbage)
            result = assemble(bad)["result"]
            self.assertEqual(result["status"], "unsupported_input")
            self.assertEqual([item["code"]
                              for item in result["reject_reasons"]],
                             ["E_MALFORMED_JSON"])
            self.assertIsNone(result["calibration"])
            lst = os.path.join(tmp, "list.json")
            with open(lst, "w", encoding="utf-8") as handle:
                handle.write("[1, 2]")
            bad = dict(REQUEST, out_dir=tmp,
                       geometry_report_path=lst)
            result = assemble(bad)["result"]
            self.assertEqual(result["status"], "unsupported_input")
            self.assertEqual([item["code"]
                              for item in result["reject_reasons"]],
                             ["E_NOT_AN_OBJECT"])
            self.assertIsNotNone(result["calibration"])

    def test_unfitted_pivot_refused(self):
        # KL-7.2 contract change (task-mandated): the unfitted
        # pivot rejects as a state with the same code, no raise.
        require_smoke(REQUEST["clip_path"])
        report = json.loads((REPO_ROOT / "fixtures" / "geometry"
                             / "geometry_report_live.json").read_text(
                                 encoding="utf-8"))
        report["pivot_arc"] = {"fitted": False, "reason": "synthetic"}
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.json")
            with open(target, "w", encoding="utf-8") as handle:
                json.dump(report, handle)
            bad = dict(REQUEST, out_dir=tmp,
                       geometry_report_path=target)
            result = assemble(bad)["result"]
            self.assertEqual(result["status"], "processing_error")
            self.assertEqual([item["code"]
                              for item in result["reject_reasons"]],
                             ["E_INCOHERENT_VALUE"])

    def test_missing_clip_propagates_os_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = dict(REQUEST, out_dir=tmp,
                       clip_path=os.path.join(tmp, "nope.mp4"))
            with self.assertRaises(OSError):
                assemble(bad)


class ExportTests(unittest.TestCase):
    def test_csv_contract(self):
        rows = [{"frame_index": 0, "t_seconds": 0.0, "theta_rad": 0.5,
                 "centroid_x_px": 100.0, "centroid_y_px": 200.0},
                {"frame_index": 1, "t_seconds": 0.04, "theta_rad": None,
                 "centroid_x_px": 101.0, "centroid_y_px": 201.0}]
        blob = export_angles_csv(rows).decode("utf-8")
        lines = blob.splitlines()
        self.assertEqual(
            lines[0],
            "frame_index,pts_seconds,theta_rad,centroid_x_px,centroid_y_px")
        self.assertEqual(len(lines), 3)
        parsed = list(csv.reader(io.StringIO(blob)))
        self.assertEqual(parsed[2][2], "")
        self.assertEqual(parsed[1][0], "0")
        with self.assertRaises(TypeError):
            export_angles_csv("nope")
        with self.assertRaises(TypeError):
            export_angles_csv([{"frame_index": True}])

    def test_json_canonical_bytes(self):
        first = export_result_json({"b": 1, "a": [1.5]})
        second = export_result_json({"a": [1.5], "b": 1})
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertNotIn(b"\r", first)
        again = export_diagnostics_json({"a": [1.5], "b": 1})
        self.assertEqual(again, first)
        with self.assertRaises(TypeError):
            export_result_json("nope")

    def test_pinned_csv_matches_series(self):
        text = (ASM_DIR / "angles.csv").read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertEqual(len(lines), 235)
        self.assertEqual(
            lines[0],
            "frame_index,pts_seconds,theta_rad,centroid_x_px,centroid_y_px")


ZERO_OFFSET_ASSUMPTION = (
    "Angles measured from image +y about the arc-fit pivot; the "
    "zero is arbitrary and absorbed by the fit phase only up to "
    "a constant offset the M1 model does not represent "
    "(A*cos(wt+phi) has no theta_eq term) - stated uncorrected "
    "(no upright-camera assumption)."
)
"""Exact KL-9.6 M2 wording (a DC offset is NOT absorbed by phase)."""


SMALL_ANGLE_ASSUMPTION = (
    "M1 is the small-angle model: omega0 = omega*(1 - theta0^2/16 "
    "+ O(theta0^4)), so the reported g/L_eff = omega^2 understates "
    "the small-angle g/L by about theta0^2/8 (order 1% at the "
    "observed amplitudes) - stated, uncorrected."
)
"""Exact KL-10.6 wording (finite-amplitude bias disclosed, uncorrected)."""


MODEL_ADEQUACY_ASSUMPTION = (
    "M1 residuals are structured, not white noise (lag-1 "
    "autocorrelation ~0.88 on the replay; damping and the DC "
    "offset are omitted): M1 is a frequency estimator for omega, "
    "not a complete trajectory model. The reported value is a "
    "point estimate with fit_uncertainty_method=none (see the "
    "registered warning); the diagnostic damped fit M2 is a "
    "cross-check, not an error bar."
)
"""Exact KL-10.7 wording (residual adequacy + point-estimate framing)."""


ADEQUACY_BOOTSTRAP_ASSUMPTION = (
    "M1 residuals are structured, not white noise (lag-1 "
    "autocorrelation ~0.88 on the replay; damping and the DC "
    "offset are omitted): M1 is a frequency estimator for omega, "
    "not a complete trajectory model. The reported value is a "
    "point estimate with a resampling-based interval under M1 "
    "(fit_uncertainty_method=block_bootstrap; see Uncertainty); "
    "the diagnostic damped fit M2 is a cross-check, not an error bar."
)
"""Exact KL-10.11 success-path rewording (limitation + point framing kept)."""


BOOTSTRAP_NOISE_ASSUMPTION = (
    "The omega and g/L_eff intervals come from a seeded block "
    "bootstrap over measured frames (method block_bootstrap): they "
    "capture measurement noise under the M1 model, not M1 "
    "model-adequacy bias - the structured-residual limitation above "
    "stands unchanged."
)
"""Exact KL-10.11 honesty sentence (a): noise, not bias."""


BOOTSTRAP_RESAMPLING_ASSUMPTION = (
    "Block resampling preserves short-range time dependence; the "
    "interval is resampling-based (percentiles of M1 refits), not "
    "an analytic derivation. Endpoints extend to contain the point "
    "estimate if a percentile excludes it (flagged as "
    "extended_to_contain_point in fit_uncertainty)."
)
"""Exact KL-10.11 honesty sentence (b): resampling, not analytic."""


# KL-10.10: see tests/test_fit_m1.py — same-platform byte pins.
PIN_SAME_PLATFORM = unittest.skipIf(
    os.environ.get("KL_CROSS_PLATFORM") == "1",
    "byte pins are same-platform determinism; cross-platform "
    "libm drifts in the last ulp (KL-10.10)")


class RegenerationTests(unittest.TestCase):
    @PIN_SAME_PLATFORM
    def test_pins_regenerate(self):
        require_smoke(REQUEST["clip_path"])
        with tempfile.TemporaryDirectory() as tmp:
            out = assemble(dict(REQUEST, out_dir=tmp))
            summary_bytes = (Path(tmp) / SUMMARY_FILENAME).read_bytes()
            summary_hashes = {
                name: hashlib.sha256(
                    (Path(tmp) / name).read_bytes()).hexdigest()
                for name in HASHED_FILES}
        pinned_result = json.loads(
            (ASM_DIR / "result.json").read_text(encoding="utf-8"))
        for name in ("result.json", "diagnostics.json"):
            with self.subTest(name=name):
                pinned = pinned_result if name == "result.json" \
                    else json.loads(
                        (ASM_DIR / name).read_text(encoding="utf-8"))
                fresh = out["result"] if name == "result.json" \
                    else out["diagnostics"]
                if name == "result.json":
                    # KL-9.6 M2: the zero-offset sentence was
                    # reworded on purpose; the committed fixture
                    # keeps the old sentence (fixtures are
                    # read-only), so pin the new wording exactly
                    # here and compare everything else byte-stable.
                    self.assertEqual(fresh["assumptions"][0],
                                     ZERO_OFFSET_ASSUMPTION)
                    # KL-10.6: same pattern for the added
                    # finite-amplitude sentence (fixture predates it).
                    self.assertIn(SMALL_ANGLE_ASSUMPTION,
                                  fresh["assumptions"])
                    # KL-10.7 sentence is GONE on success (reworded
                    # by KL-10.11); the pin below asserts the new
                    # wording instead. The fixture keeps the old.
                    self.assertNotIn(MODEL_ADEQUACY_ASSUMPTION,
                                     fresh["assumptions"])
                    # KL-10.11: the bootstrap ran — verdict flip,
                    # lifted warning, populated interval, reworded
                    # adequacy + two honesty sentences. Asserted
                    # exactly here, normalized below for the
                    # byte-compare of everything else.
                    self.assertEqual(fresh["status"], "success")
                    self.assertEqual(fresh["warnings"], [])
                    self.assertEqual(fresh["interval_method"],
                                     "block_bootstrap")
                    band = out["diagnostics"]["fit_uncertainty"][
                        "g_over_l_eff_per_s2"]
                    self.assertEqual(
                        fresh["interval"],
                        {"lower": band["low"],
                         "upper": band["high"]})
                    self.assertEqual(
                        fresh["fit"]["fit_uncertainty_method"],
                        "block_bootstrap")
                    self.assertEqual(fresh["fit"]["warnings"], [])
                    self.assertIn(ADEQUACY_BOOTSTRAP_ASSUMPTION,
                                  fresh["assumptions"])
                    self.assertIn(BOOTSTRAP_NOISE_ASSUMPTION,
                                  fresh["assumptions"])
                    self.assertIn(BOOTSTRAP_RESAMPLING_ASSUMPTION,
                                  fresh["assumptions"])
                    fresh = dict(
                        fresh,
                        status=pinned["status"],
                        warnings=pinned["warnings"],
                        interval=pinned["interval"],
                        interval_method=pinned["interval_method"],
                        fit=dict(
                            fresh["fit"],
                            fit_uncertainty_method=pinned["fit"][
                                "fit_uncertainty_method"],
                            warnings=pinned["fit"]["warnings"]),
                        assumptions=["<zero-blanked>"]
                        + [text for text in fresh["assumptions"][1:]
                           if text != SMALL_ANGLE_ASSUMPTION
                           and text != ADEQUACY_BOOTSTRAP_ASSUMPTION
                           and text != BOOTSTRAP_NOISE_ASSUMPTION
                           and text != BOOTSTRAP_RESAMPLING_ASSUMPTION])
                    pinned = dict(
                        pinned,
                        assumptions=["<zero-blanked>"]
                        + pinned["assumptions"][1:])
                if name == "diagnostics.json":
                    # KL-10.11: the new free-form fit_uncertainty
                    # section, pinned exactly, then removed for the
                    # byte-compare of everything else.
                    fu = fresh["fit_uncertainty"]
                    self.assertEqual(fu["method"], "block_bootstrap")
                    self.assertEqual(fu["seed"], 20261103)
                    self.assertEqual(fu["n_boot"], 800)
                    self.assertEqual(fu["block_frames"], 35)
                    self.assertFalse(
                        fu["extended_to_contain_point"])
                    omega = fu["omega_per_s"]
                    band = fu["g_over_l_eff_per_s2"]
                    self.assertLess(omega["low"], omega["point"])
                    self.assertLess(omega["point"], omega["high"])
                    self.assertEqual(band["low"],
                                     omega["low"] * omega["low"])
                    self.assertEqual(band["high"],
                                     omega["high"] * omega["high"])
                    self.assertEqual(band["point"],
                                     out["result"]["value"])
                    fresh = {key: value for key, value in fresh.items()
                             if key != "fit_uncertainty"}
                _assert_close_tree(
                    self, _with_basename_exports(fresh)
                    if name == "result.json" else fresh,
                    _with_basename_exports(pinned)
                    if name == "result.json" else pinned)
        pinned_csv = (ASM_DIR / "angles.csv").read_text(
            encoding="utf-8").splitlines()
        fresh_rows = out["angle_series"]
        self.assertEqual(len(pinned_csv) - 1, len(fresh_rows))
        for line, row in zip(pinned_csv[1:], fresh_rows):
            cells = line.split(",")
            self.assertEqual(int(cells[0]), row["frame_index"])
            for cell, key in zip(cells[1:],
                                 ("pts_seconds", "theta_rad",
                                  "centroid_x_px", "centroid_y_px")):
                self.assertNotEqual(cell, "")
                self.assertTrue(
                    math.isclose(float(cell), row[key],
                                 rel_tol=1e-12, abs_tol=1e-15),
                    f"{key}: {cell} vs {row[key]}")
        # KL-7.3: the summary regenerates identically except
        # the out-dir-dependent result.json hash line; listed
        # hashes are verified against the freshly written files.
        # KL-9.6 M2: plus the reworded zero-offset sentence, blanked
        # on both sides (old wording read from the pin itself).
        # KL-10.6: plus the added finite-amplitude sentence, removed
        # from the fresh side (the pin predates it). KL-10.7: the
        # old adequacy sentence is gone on success (reworded by
        # KL-10.11); the new bullets are removed instead.
        fresh_summary = summary_bytes.decode("utf-8").replace(
            ZERO_OFFSET_ASSUMPTION, "<zero-blanked>").replace(
                "- " + SMALL_ANGLE_ASSUMPTION + "\n", "").replace(
                    "- " + ADEQUACY_BOOTSTRAP_ASSUMPTION + "\n",
                    "").replace(
                        "- " + BOOTSTRAP_NOISE_ASSUMPTION + "\n",
                        "").replace(
                            "- " + BOOTSTRAP_RESAMPLING_ASSUMPTION
                            + "\n", "")
        # KL-10.11: the Uncertainty section is new by design —
        # assert its exact lines, then remove the whole section.
        section_start = fresh_summary.index("## Uncertainty\n")
        section_end = fresh_summary.index("## M2 diagnostic")
        section = fresh_summary[section_start:section_end]
        fu = out["diagnostics"]["fit_uncertainty"]
        omega = fu["omega_per_s"]
        band = fu["g_over_l_eff_per_s2"]
        for line in (
                "## Uncertainty",
                "- method: block_bootstrap",
                f"- seed: {fu['seed']!r}",
                f"- n_boot: {fu['n_boot']!r}",
                f"- block_frames: {fu['block_frames']!r}",
                "- extended_to_contain_point: false",
                f"- omega_per_s (1/s): low {omega['low']!r}, "
                f"point {omega['point']!r}, high {omega['high']!r}",
                f"- g_over_l_eff_per_s2 (1/s^2): low {band['low']!r}, "
                f"point {band['point']!r}, high {band['high']!r}"):
            self.assertIn(line, section)
        fresh_summary = (fresh_summary[:section_start]
                         + fresh_summary[section_end:])
        # Verdict flip + lifted warning + populated interval:
        # asserted exactly above, normalized for the byte-compare.
        self.assertIn("# KineticLab result: SUCCESS (success)\n",
                      fresh_summary)
        self.assertIn(
            f"- interval: {{\"lower\": {band['low']!r}, "
            f"\"upper\": {band['high']!r}}}",
            fresh_summary)
        self.assertIn("- interval_method: block_bootstrap",
                      fresh_summary)
        self.assertIn("## Warnings\n\n- none", fresh_summary)
        fresh_summary = fresh_summary.replace(
            "SUCCESS (success)", "SUCCESS (<status>)").replace(
                "- status: success\n", "- status: <status>\n")
        fresh_summary = _blank_line_prefix(
            fresh_summary, "- interval: ", "- interval: <interval>")
        fresh_summary = _blank_line_prefix(
            fresh_summary, "- interval_method: ",
            "- interval_method: <interval_method>")
        pinned_summary = (
            ASM_DIR / SUMMARY_FILENAME).read_text(
                encoding="utf-8").replace(
                    pinned_result["assumptions"][0], "<zero-blanked>")
        pinned_summary = pinned_summary.replace(
            "SUCCESS (success_with_warnings)",
            "SUCCESS (<status>)").replace(
                "- status: success_with_warnings\n",
                "- status: <status>\n")
        self.assertIn("- interval: null", pinned_summary)
        self.assertIn("- interval_method: null", pinned_summary)
        pinned_summary = _blank_line_prefix(
            pinned_summary, "- interval: ", "- interval: <interval>")
        pinned_summary = _blank_line_prefix(
            pinned_summary, "- interval_method: ",
            "- interval_method: <interval_method>")
        pinned_bullet = ("- `W_UNCERTAINTY_UNAVAILABLE`: KL-7.1 estimates "
                         "no uncertainty; method is none.\n")
        self.assertIn(pinned_bullet, pinned_summary)
        pinned_summary = pinned_summary.replace(pinned_bullet,
                                                "- none\n")
        # diagnostics.json bytes intentionally changed (new
        # fit_uncertainty section); its hash line is blanked on
        # both sides while the listed hashes are still verified
        # against the freshly written files below.
        fresh_summary = _blank_line_prefix(
            fresh_summary, "- diagnostics.json: ",
            "- diagnostics.json: <bytes-changed>")
        pinned_summary = _blank_line_prefix(
            pinned_summary, "- diagnostics.json: ",
            "- diagnostics.json: <bytes-changed>")
        self.assertEqual(
            _blank_result_hash_line(fresh_summary),
            _blank_result_hash_line(pinned_summary))
        summary_text = summary_bytes.decode("utf-8")
        for name, digest in summary_hashes.items():
            self.assertIn(f"- {name}: {digest}", summary_text)


class MappingTests(unittest.TestCase):
    def test_rejection_map_covers_taxonomy_exactly(self):
        self.assertEqual(set(REJECTION_STATE), set(ERROR_CODES))
        self.assertEqual(len(REJECTION_STATE), 32)

    def test_warnings_never_critical(self):
        self.assertEqual(set(NON_CRITICAL_WARNINGS),
                         set(WARNING_CODES))
        self.assertEqual(len(NON_CRITICAL_WARNINGS), 9)

    def test_routing_principle_spots(self):
        self.assertEqual(REJECTION_STATE["E_MALFORMED_JSON"],
                         "unsupported_input")
        self.assertEqual(REJECTION_STATE["E_NOT_AN_OBJECT"],
                         "unsupported_input")
        self.assertEqual(REJECTION_STATE["E_MISSING_FIELD"],
                         "unsupported_input")
        self.assertEqual(REJECTION_STATE["E_INCOHERENT_VALUE"],
                         "processing_error")
        self.assertEqual(REJECTION_STATE["E_NON_MONOTONIC_PTS"],
                         "processing_error")
        self.assertEqual(REJECTION_STATE["E_DUPLICATE_FRAME"],
                         "processing_error")

    def test_insufficient_data_not_a_routing_target(self):
        self.assertEqual(set(REJECTION_STATE.values()),
                         {"unsupported_input", "processing_error"})


class IngestCriticalTests(unittest.TestCase):
    def test_garbage_clip_rejects_unsupported(self):
        # Synthetic garbage bytes (labeled); everything else live.
        garbage = b"not a video file" * 16
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / "garbage.mp4"
            clip.write_bytes(garbage)
            out_dir = Path(tmp) / "out"
            out = assemble(dict(REQUEST, clip_path=str(clip),
                                out_dir=str(out_dir)))
            result, diagnostics = out["result"], out["diagnostics"]
            self.assertEqual(result["status"], "unsupported_input")
            reasons = result["reject_reasons"]
            self.assertEqual([item["code"] for item in reasons],
                             ["E_NOT_AN_OBJECT"])
            self.assertTrue(reasons[0]["field"].startswith("ingest."))
            self.assertEqual(
                result["identifiable_quantity"],
                {"name": "g/L_eff", "value": None, "unit": "1/s^2"})
            self.assertEqual(len(result["assumptions"]), 1)
            self.assertIn("ingest", result["assumptions"][0])
            self.assertEqual([item["code"]
                              for item in result["warnings"]],
                             ["W_UNCERTAINTY_UNAVAILABLE"])
            self.assertEqual(result["quality_metrics"],
                             {"frames_total": None, "frames_usable": None,
                              "observations_total": None,
                              "observations_valid": None,
                              "calibrated_frames": None})
            self.assertIsNone(result["calibration"])
            self.assertIsNone(result["fit"])
            self.assertEqual(result["provenance"]["input_sha256"],
                             hashlib.sha256(garbage).hexdigest())
            self.assertEqual(diagnostics["failure"]["stage"], "ingest")
            self.assertEqual(diagnostics["failure"]["codes"],
                             ["E_NOT_AN_OBJECT"])
            names = sorted(os.path.basename(ref["path"])
                           for ref in result["exports"])
            self.assertEqual(names, ["angles.csv", "diagnostics.json",
                                     "result.json"])
            for name in names:
                self.assertTrue((out_dir / name).is_file())
            csv_lines = (out_dir / "angles.csv").read_text(
                encoding="utf-8").splitlines()
            self.assertEqual(csv_lines, [
                "frame_index,pts_seconds,theta_rad,centroid_x_px,"
                "centroid_y_px"])
            checked = ResultContract.from_dict(copy.deepcopy(result))
            self.assertEqual(checked.to_dict(), result)


class ObservationCriticalTests(unittest.TestCase):
    def test_bad_wire_rejects_with_frames_retained(self):
        require_smoke(REQUEST["clip_path"])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad_raw.txt"
            # Synthetic corrupt wire (labeled): no frame marker.
            bad.write_text("garbage line with no frame marker\n",
                           encoding="utf-8")
            out_dir = Path(tmp) / "out"
            out = assemble(dict(REQUEST, raw_bob_path=str(bad),
                                out_dir=str(out_dir)))
            result = out["result"]
            self.assertEqual(result["status"], "unsupported_input")
            reasons = result["reject_reasons"]
            self.assertEqual([item["code"] for item in reasons],
                             ["E_MISSING_FIELD"])
            self.assertEqual(reasons[0]["field"],
                             "observation.frame_index")
            # Partial context: the frame table survived the failure.
            metrics = result["quality_metrics"]
            self.assertEqual(metrics["frames_total"], 234)
            self.assertEqual(metrics["frames_usable"], 234)
            self.assertIsNone(metrics["observations_total"])
            self.assertIsNone(metrics["observations_valid"])
            self.assertEqual(out["diagnostics"]["n_table_frames"], 234)
            self.assertIsNone(out["diagnostics"]["n_bob_records"])
            for name in ("result.json", "diagnostics.json", "angles.csv"):
                self.assertTrue((out_dir / name).is_file())
            checked = ResultContract.from_dict(copy.deepcopy(result))
            self.assertEqual(checked.to_dict(), result)


class ParsedInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(REQUEST["clip_path"])
        table = extract_frame_records(REQUEST["clip_path"])
        cls.bob = parse_raw_fixture(
            REQUEST["raw_bob_path"], object_role="bob",
            object_id="live-ball", frame_table=table,
            model_name="sam-3.1")
        cls.card = parse_raw_fixture(
            REQUEST["raw_card_path"], object_role="reference_card",
            object_id="live-card", frame_table=table,
            model_name="sam-3.1")

    def test_injected_records_skip_reparse(self):
        # KL-9.2 item 4: pre-parsed records for the request's exact
        # bytes skip assemble's own re-parse. Proof: point the
        # request at tampered raw files (which fail parsing on
        # their own) and show the injected run still succeeds with
        # the pinned value.
        with tempfile.TemporaryDirectory() as tmp:
            bad_bob = Path(tmp) / "bad_bob.txt"
            bad_card = Path(tmp) / "bad_card.txt"
            bad_bob.write_text("garbage line with no frame marker\n",
                               encoding="utf-8")
            bad_card.write_text("garbage line with no frame marker\n",
                                encoding="utf-8")
            out_dir = Path(tmp) / "out"
            request = dict(REQUEST, raw_bob_path=str(bad_bob),
                           raw_card_path=str(bad_card),
                           out_dir=str(out_dir))
            out = assemble(request, _parsed={"bob": self.bob,
                                             "card": self.card})
            result = out["result"]
            # KL-10.11: the injected run fits, bootstraps, and
            # reaches plain success like the direct run.
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["interval_method"],
                             "block_bootstrap")
            self.assertTrue(math.isclose(result["value"], G_OVER_L_PIN,
                                         rel_tol=1e-6))
            checked = ResultContract.from_dict(copy.deepcopy(result))
            self.assertEqual(checked.to_dict(), result)

    def test_tampered_control_rejects_without_injection(self):
        # Control: the same tampered request without _parsed must
        # reject at the observation stage (the injection above is
        # what bypasses the re-parse, not lax parsing).
        require_smoke(REQUEST["clip_path"])
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad_raw.txt"
            bad.write_text("garbage line with no frame marker\n",
                           encoding="utf-8")
            out_dir = Path(tmp) / "out"
            out = assemble(dict(REQUEST, raw_bob_path=str(bad),
                                out_dir=str(out_dir)))
            self.assertEqual(out["result"]["status"], "unsupported_input")


class GeometrySeamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        cls.report = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "geometry_report_live.json").read_text(encoding="utf-8"))

    def test_pivotless_report_processing_error(self):
        # Synthetic parts (labeled): report pin without a pivot.
        report = copy.deepcopy(self.report)
        del report["pivot_arc"]
        table = [SimpleNamespace(frame_index=index,
                                 pts_seconds=index * 0.04,
                                 valid=True)
                 for index in range(234)]
        card = [SimpleNamespace(frame_index=index, valid=True)
                for index in range(234)]
        bob = [SimpleNamespace(frame_index=index, valid=True,
                               pts_seconds=index * 0.04,
                               centroid_x_px=1.0, centroid_y_px=2.0)
               for index in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            out = assemble_parts(
                bob=bob, card=card, frame_table=table,
                calibration_dict=copy.deepcopy(self.calibration),
                report_pin=report, clip_sha256="b" * 64, out_dir=tmp,
                raw_bob_display="synthetic-test",
                raw_card_display="synthetic-test",
                geometry_report_display="synthetic-test",
                artifact_hashes=_synthetic_hashes())
        result = out["result"]
        self.assertEqual(result["status"], "processing_error")
        reasons = result["reject_reasons"]
        self.assertEqual([item["code"] for item in reasons],
                         ["E_INCOHERENT_VALUE"])
        self.assertTrue(reasons[0]["field"].startswith("geometry."))
        # The validated calibration is retained with its warnings.
        self.assertEqual(result["calibration"]["warnings"],
                         self.calibration["warnings"])
        metrics = result["quality_metrics"]
        self.assertEqual(metrics["calibrated_frames"], 117)
        self.assertEqual(metrics["observations_total"], 236)
        checked = ResultContract.from_dict(copy.deepcopy(result))
        self.assertEqual(checked.to_dict(), result)


class GeometryRejectionPinTests(unittest.TestCase):
    """Corrupt geometry-report pin -> unsupported_input (pinned)."""

    @classmethod
    def setUpClass(cls):
        require_smoke(REQUEST["clip_path"])
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = assemble(dict(
            REQUEST,
            geometry_report_path=str(
                ASM_DIR / "corrupt_geometry_report.json"),
            out_dir=cls.tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_state_and_codes(self):
        result = self.out["result"]
        self.assertEqual(result["status"], "unsupported_input")
        reasons = result["reject_reasons"]
        self.assertEqual([item["code"] for item in reasons],
                         ["E_MALFORMED_JSON"])
        self.assertEqual(reasons[0]["field"],
                         "geometry.geometry_report")

    def test_retained_sections(self):
        result = self.out["result"]
        live_calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        self.assertEqual(result["calibration"], live_calibration)
        self.assertEqual(len(result["calibration"]["warnings"]), 2)
        metrics = result["quality_metrics"]
        self.assertEqual((metrics["frames_total"],
                          metrics["frames_usable"],
                          metrics["observations_total"],
                          metrics["observations_valid"]),
                         (234, 234, 468, 468))
        self.assertIsNone(metrics["calibrated_frames"])
        self.assertEqual(result["identifiable_quantity"],
                         {"name": "g/L_eff", "value": None,
                          "unit": "1/s^2"})
        self.assertEqual(self.out["diagnostics"]["failure"]["stage"],
                         "geometry")

    def test_exports_written(self):
        out_dir = Path(self.tmp.name)
        for name in ("result.json", "diagnostics.json", "angles.csv"):
            self.assertTrue((out_dir / name).is_file())
        csv_lines = (out_dir / "angles.csv").read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(csv_lines, [
            "frame_index,pts_seconds,theta_rad,centroid_x_px,"
            "centroid_y_px"])

    def test_summary_regenerates(self):
        out_dir = Path(self.tmp.name)
        fresh = (out_dir / SUMMARY_FILENAME).read_bytes()
        pinned = (ASM_DIR / "rejection" / SUMMARY_FILENAME).read_bytes()
        self.assertEqual(_blank_result_hash_line(fresh.decode("utf-8")),
                         _blank_result_hash_line(pinned.decode("utf-8")))
        text = fresh.decode("utf-8")
        for name in HASHED_FILES:
            digest = hashlib.sha256(
                (out_dir / name).read_bytes()).hexdigest()
            self.assertIn(f"- {name}: {digest}", text)

    def test_pins_regenerate(self):
        pin_dir = ASM_DIR / "rejection"
        for name, key in (("result.json", "result"),
                          ("diagnostics.json", "diagnostics")):
            with self.subTest(name=name):
                pinned = json.loads(
                    (pin_dir / name).read_text(encoding="utf-8"))
                fresh = self.out[key]
                if key == "result":
                    fresh = _with_basename_exports(fresh)
                    pinned = _with_basename_exports(pinned)
                _assert_close_tree(self, fresh, pinned)
        pinned_csv = (pin_dir / "angles.csv").read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(pinned_csv, [
            "frame_index,pts_seconds,theta_rad,centroid_x_px,"
            "centroid_y_px"])


class SummaryRenderTests(unittest.TestCase):
    """Pure renderer tests from the pinned JSONs (no assemble)."""

    @classmethod
    def setUpClass(cls):
        cls.result = json.loads(
            (ASM_DIR / "result.json").read_text(encoding="utf-8"))
        cls.diagnostics = json.loads(
            (ASM_DIR / "diagnostics.json").read_text(encoding="utf-8"))
        cls.hashes = {
            name: hashlib.sha256(
                (ASM_DIR / name).read_bytes()).hexdigest()
            for name in HASHED_FILES}
        cls.text = render_summary_md(cls.result, cls.diagnostics,
                                     cls.hashes)
        rejection_dir = ASM_DIR / "rejection"
        cls.rejection_result = json.loads(
            (rejection_dir / "result.json").read_text(encoding="utf-8"))
        cls.rejection_diagnostics = json.loads(
            (rejection_dir / "diagnostics.json").read_text(
                encoding="utf-8"))
        cls.rejection_hashes = {
            name: hashlib.sha256(
                (rejection_dir / name).read_bytes()).hexdigest()
            for name in HASHED_FILES}
        cls.rejection_text = render_summary_md(
            cls.rejection_result, cls.rejection_diagnostics,
            cls.rejection_hashes)

    def test_success_title_and_section_order(self):
        lines = self.text.splitlines()
        self.assertEqual(
            lines[0],
            "# KineticLab result: SUCCESS (success_with_warnings)")
        headers = [
            "## Status and measurement",
            "## Identifiable quantity",
            "## Fit",
            "## M2 diagnostic",
            "## Quality metrics",
            "## Assumptions",
            "## Warnings",
            "## Reject reasons",
            "## Provenance",
            "## Export files",
        ]
        positions = [lines.index(header) for header in headers]
        self.assertEqual(positions, sorted(positions))

    def test_numbers_traceable_to_json(self):
        # Every spot value is repr-copied from the JSON sources.
        result, diagnostics = self.result, self.diagnostics
        for value in (result["value"],
                      result["identifiable_quantity"]["value"],
                      diagnostics["m1"]["fitted"]["omega_per_s"],
                      diagnostics["m1"]["fitted"]["amplitude_rad"],
                      result["fit"]["residual_summary"]["rmse"],
                      result["fit"]["residual_summary"]["max_abs"],
                      diagnostics["m1"]["objectives"]["final_ssr"],
                      diagnostics["m2"]["fitted"]["gamma_per_s"]):
            self.assertIn(repr(value), self.text)
        for count in ("frames_total", "frames_usable",
                      "observations_total", "observations_valid",
                      "calibrated_frames"):
            self.assertIn(
                f"- {count}: "
                f"{result['quality_metrics'][count]}", self.text)
        for name, digest in self.hashes.items():
            self.assertIn(f"- {name}: {digest}", self.text)
        self.assertIn(result["provenance"]["input_sha256"], self.text)

    def test_verbatim_carry(self):
        for assumption in self.result["assumptions"]:
            self.assertIn(assumption, self.text)
        for warning in self.result["warnings"]:
            self.assertIn(warning["code"], self.text)
            self.assertIn(warning["detail"], self.text)
        for ref in self.result["provenance"]["raw_refs"]:
            self.assertIn(ref, self.text)
        justification = self.diagnostics["m2"]["justification"]
        self.assertIn(justification, self.text)

    def test_rejection_unmistakable(self):
        lines = self.rejection_text.splitlines()
        self.assertEqual(
            lines[0], "# KineticLab result: REJECTED (unsupported_input)")
        self.assertNotIn("SUCCESS", self.rejection_text)
        self.assertIn("- fit: none (no fit output; see status)",
                      self.rejection_text)
        self.assertIn("- M2 diagnostic: not run (no M2 output)",
                      self.rejection_text)
        self.assertIn("E_MALFORMED_JSON", self.rejection_text)
        for reason in self.rejection_result["reject_reasons"]:
            self.assertIn(reason["detail"], self.rejection_text)

    def test_render_deterministic(self):
        again = render_summary_md(self.result, self.diagnostics,
                                  self.hashes)
        self.assertEqual(again, self.text)

    def test_pinned_hashes_match_pin_files(self):
        # The pinned summaries' hash lists agree with the pinned
        # files' actual bytes (success + rejection, no assemble).
        for pin_dir in (ASM_DIR, ASM_DIR / "rejection"):
            with self.subTest(pin_dir=str(pin_dir)):
                text = (pin_dir / SUMMARY_FILENAME).read_text(
                    encoding="utf-8")
                for name in HASHED_FILES:
                    digest = hashlib.sha256(
                        (pin_dir / name).read_bytes()).hexdigest()
                    self.assertIn(f"- {name}: {digest}", text)

    def test_malformed_inputs_rejected(self):
        with self.assertRaises(TypeError):
            render_summary_md([], self.diagnostics, self.hashes)
        with self.assertRaises(TypeError):
            render_summary_md(self.result, [], self.hashes)
        with self.assertRaises(TypeError):
            render_summary_md(self.result, self.diagnostics, {})
        with self.assertRaises(TypeError):
            render_summary_md(
                self.result, self.diagnostics,
                {"result.json": "x", "diagnostics.json": "y",
                 "angles.csv": ""})


class SummaryDeterminismTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # No-fit rejection path, one shared run per directory.
        require_smoke(REQUEST["clip_path"])
        request = dict(
            REQUEST,
            geometry_report_path=str(
                ASM_DIR / "corrupt_geometry_report.json"))
        cls.first = tempfile.TemporaryDirectory()
        cls.second = tempfile.TemporaryDirectory()
        assemble(dict(request, out_dir=cls.first.name))
        cls.first_run = (
            Path(cls.first.name) / SUMMARY_FILENAME).read_bytes()
        assemble(dict(request, out_dir=cls.first.name))
        cls.rerun = (
            Path(cls.first.name) / SUMMARY_FILENAME).read_bytes()
        assemble(dict(request, out_dir=cls.second.name))
        cls.texts = [
            (Path(cls.first.name) / SUMMARY_FILENAME).read_bytes(),
            (Path(cls.second.name) / SUMMARY_FILENAME).read_bytes()]
        # F-2026-10-28-1 follow-up (OG audit finding 7): keep the
        # export refs that CAUSE zero-or-one differences under
        # test, not just their summary side effect.
        cls.result_refs = [
            json.loads((Path(directory) / "result.json").read_text(
                encoding="utf-8"))["exports"]
            for directory in (cls.first.name, cls.second.name)]

    @classmethod
    def tearDownClass(cls):
        cls.first.cleanup()
        cls.second.cleanup()

    def test_same_request_rerun_byte_equal(self):
        # Same request (including out_dir) assembled twice: the
        # two writes are byte-identical.
        self.assertEqual(self.first_run, self.rerun)

    def test_cross_dir_differs_only_in_result_hash(self):
        first = self.texts[0].decode("utf-8").splitlines()
        second = self.texts[1].decode("utf-8").splitlines()
        self.assertEqual(len(first), len(second))
        differing = [index for index, (a, b) in enumerate(zip(first, second))
                     if a != b]
        # result.json embeds its own export refs; those refs degrade
        # to bare filenames when the out dir lies outside the working
        # directory (documented export.py fallback). Across two temp
        # dirs the summaries therefore differ in the result.json hash
        # line OR not at all — never anywhere else. diagnostics.json
        # and angles.csv hashes are stable in every environment.
        self.assertLessEqual(len(differing), 1)
        for index in differing:
            self.assertTrue(first[index].startswith("- result.json: "))
            self.assertTrue(second[index].startswith("- result.json: "))
        for index, (a, b) in enumerate(zip(first, second)):
            if index in differing:
                continue
            if a.startswith("- diagnostics.json: ") \
                    or a.startswith("- angles.csv: "):
                self.assertEqual(a, b)

    def test_export_refs_explain_cross_dir_behavior(self):
        # The CAUSE of zero-vs-one differing lines, in either
        # environment: export refs are CWD-relative paths when the
        # out dir lies inside the working directory, or bare
        # filenames via the documented export.py fallback when it
        # lies outside (sandbox tmpdirs may sit inside CWD, so
        # the fallback case cannot be assumed).
        first, second = self.result_refs
        self.assertEqual([ref["format"] for ref in first],
                         [ref["format"] for ref in second])
        self.assertEqual([Path(ref["path"]).name for ref in first],
                         [Path(ref["path"]).name for ref in second])
        if all(ref["path"] == Path(ref["path"]).name
               for ref in first):
            # Basename fallback: identical refs, identical summaries.
            self.assertEqual(first, second)
            self.assertEqual(self.texts[0], self.texts[1])
        else:
            # CWD-relative refs: one out-dir parent per run, and
            # the parent is the ONLY thing that differs.
            parents_first = {Path(ref["path"]).parent
                             for ref in first}
            parents_second = {Path(ref["path"]).parent
                              for ref in second}
            self.assertEqual(len(parents_first), 1)
            self.assertEqual(len(parents_second), 1)
            self.assertNotEqual(parents_first, parents_second)


class NonCriticalTests(unittest.TestCase):
    def test_upstream_warnings_stay_success(self):
        # Pin-inspected (no refit): the live calibration carries
        # warnings, yet the chain stays in the success family.
        result = json.loads(
            (ASM_DIR / "result.json").read_text(encoding="utf-8"))
        live_calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        self.assertEqual(len(live_calibration["warnings"]), 2)
        self.assertEqual(result["status"], "success_with_warnings")
        self.assertTrue(math.isclose(result["value"], G_OVER_L_PIN,
                                     rel_tol=1e-6))
        self.assertEqual(result["calibration"]["warnings"],
                         live_calibration["warnings"])
        self.assertEqual([item["code"] for item in result["warnings"]],
                         ["W_UNCERTAINTY_UNAVAILABLE"])


class AuditWalkthroughTests(unittest.TestCase):
    """Pins the README frame-0 walkthrough (KL-7.4)."""

    CITATIONS = [
        ("fixtures/ingest/test_3_frame_table.json", 7,
         '"frame_index": 0'),
        ("fixtures/ingest/test_3_frame_table.json", 16,
         '"pts_seconds": 0.0'),
        ("fixtures/ingest/test_3_frame_table.json", 18,
         '"source_frame_index": 0'),
        ("fixtures/ingest/test_3_frame_table.json", 5,
         '"sample:0"'),
        ("fixtures/assembly/angles.csv", 2,
         "0,0.0,0.12636167830883652,565.7244623655914,"
         "366.5494210090984"),
        ("fixtures/assembly/diagnostics.json", 25,
         '"point_index": 0'),
        ("fixtures/assembly/diagnostics.json", 26,
         '"residual_rad": -0.07864719822009777'),
        ("fixtures/assembly/diagnostics.json", 27,
         '"t_seconds": 0.0'),
        ("fixtures/assembly/diagnostics.json", 11,
         '"amplitude_rad": 0.29309715273018166'),
        ("fixtures/assembly/diagnostics.json", 12,
         '"omega_per_s": 5.47774002094622'),
        ("fixtures/assembly/diagnostics.json", 13,
         '"period_s": 1.1470397067318712'),
        ("fixtures/assembly/diagnostics.json", 14,
         '"phase_rad": 0.7961587971827984'),
        ("fixtures/assembly/result.json", 155,
         '"value": 30.00563573707589'),
        ("fixtures/assembly/result.json", 83,
         '"g_over_l_per_s2": 30.00563573707589'),
        ("fixtures/assembly/summary.md", 11,
         "- value: 30.00563573707589"),
        ("fixtures/assembly/summary.md", 35,
         "- omega_per_s: 5.47774002094622"),
    ]

    def test_walkthrough_citations_match_pins(self):
        for rel, lineno, snippet in self.CITATIONS:
            with self.subTest(rel=rel, line=lineno):
                lines = (REPO_ROOT / rel).read_text(
                    encoding="utf-8").splitlines()
                self.assertIn(snippet, lines[lineno - 1])

    def test_walkthrough_citations_in_readme(self):
        readme = (ASM_DIR / "README.md").read_text(encoding="utf-8")
        for _rel, _lineno, snippet in self.CITATIONS:
            with self.subTest(snippet=snippet[:40]):
                self.assertIn(snippet, readme)

    def test_frame_zero_chain_coherent(self):
        row = (ASM_DIR / "angles.csv").read_text(
            encoding="utf-8").splitlines()[1].split(",")
        self.assertEqual(int(row[0]), 0)
        self.assertEqual(float(row[1]), 0.0)
        diagnostics = json.loads(
            (ASM_DIR / "diagnostics.json").read_text(encoding="utf-8"))
        residual = diagnostics["m1"]["residuals"][0]
        self.assertEqual(residual["point_index"], 0)
        self.assertEqual(residual["t_seconds"], float(row[1]))
        result = json.loads(
            (ASM_DIR / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["value"],
                         result["fit"]["g_over_l_per_s2"])
        self.assertIsNone(result["fit"]["gravity_m_s2"])

    def test_plain_success_unreachable_note(self):
        # Pinned structural statement (KL-7.4): plain success
        # cannot occur in P-007 because the uncertainty warning
        # is always present and the contract requires
        # success_with_warnings whenever warnings are present.
        result = json.loads(
            (ASM_DIR / "result.json").read_text(encoding="utf-8"))
        codes = [item["code"] for item in result["warnings"]]
        self.assertIn("W_UNCERTAINTY_UNAVAILABLE", codes)
        self.assertEqual(result["status"], "success_with_warnings")
        self.assertNotEqual(result["status"], "success")


class InsufficientSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        cls.report = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "geometry_report_live.json").read_text(encoding="utf-8"))

    def test_starved_summary_rejected_with_nulls(self):
        # Synthetic starved parts (labeled): no fit runs.
        table = [SimpleNamespace(frame_index=index,
                                 pts_seconds=index * 0.04,
                                 valid=True)
                 for index in range(234)]
        card = [SimpleNamespace(frame_index=index, valid=True)
                for index in range(234)]
        bob = [SimpleNamespace(frame_index=index, valid=True,
                               pts_seconds=index * 0.04,
                               centroid_x_px=1.0, centroid_y_px=2.0)
               for index in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            out = assemble_parts(
                bob=bob, card=card, frame_table=table,
                calibration_dict=copy.deepcopy(self.calibration),
                report_pin=copy.deepcopy(self.report),
                clip_sha256="c" * 64, out_dir=tmp,
                raw_bob_display="synthetic-test",
                raw_card_display="synthetic-test",
                geometry_report_display="synthetic-test",
                artifact_hashes=_synthetic_hashes())
            result = out["result"]
            self.assertEqual(result["status"], "insufficient_data")
            self.assertIsNone(result["value"])
            self.assertIsNone(result["unit"])
            self.assertIsNone(result["interval"])
            self.assertIsNone(result["interval_method"])
            self.assertEqual(result["identifiable_quantity"],
                             {"name": "g/L_eff", "value": None,
                              "unit": "1/s^2"})
            for name in ("result.json", "diagnostics.json",
                         "angles.csv", SUMMARY_FILENAME):
                self.assertTrue((Path(tmp) / name).is_file())
            text = (Path(tmp) / SUMMARY_FILENAME).read_text(
                encoding="utf-8")
            self.assertTrue(text.startswith(
                "# KineticLab result: REJECTED (insufficient_data)"))
            self.assertNotIn("SUCCESS", text)
            self.assertIn("- fit: none (no fit output; see status)",
                          text)


class ProcessingSummaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        cls.report = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "geometry_report_live.json").read_text(encoding="utf-8"))

    def test_pivotless_summary_rejected_with_nulls(self):
        # Synthetic parts (labeled): report pin without a pivot.
        report = copy.deepcopy(self.report)
        del report["pivot_arc"]
        table = [SimpleNamespace(frame_index=index,
                                 pts_seconds=index * 0.04,
                                 valid=True)
                 for index in range(234)]
        card = [SimpleNamespace(frame_index=index, valid=True)
                for index in range(234)]
        bob = [SimpleNamespace(frame_index=index, valid=True,
                               pts_seconds=index * 0.04,
                               centroid_x_px=1.0, centroid_y_px=2.0)
               for index in range(2)]
        with tempfile.TemporaryDirectory() as tmp:
            out = assemble_parts(
                bob=bob, card=card, frame_table=table,
                calibration_dict=copy.deepcopy(self.calibration),
                report_pin=report, clip_sha256="d" * 64, out_dir=tmp,
                raw_bob_display="synthetic-test",
                raw_card_display="synthetic-test",
                geometry_report_display="synthetic-test",
                artifact_hashes=_synthetic_hashes())
            result = out["result"]
            self.assertEqual(result["status"], "processing_error")
            self.assertIsNone(result["value"])
            self.assertIsNone(result["unit"])
            self.assertIsNone(result["identifiable_quantity"]["value"])
            for name in ("result.json", "diagnostics.json",
                         "angles.csv", SUMMARY_FILENAME):
                self.assertTrue((Path(tmp) / name).is_file())
            text = (Path(tmp) / SUMMARY_FILENAME).read_text(
                encoding="utf-8")
            self.assertTrue(text.startswith(
                "# KineticLab result: REJECTED (processing_error)"))
            self.assertNotIn("SUCCESS", text)


class NonMonotonicTests(unittest.TestCase):
    """F3: reordered valid PTS rejects; never sorted, never fitted."""

    @classmethod
    def setUpClass(cls):
        cls.calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        cls.report = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "geometry_report_live.json").read_text(encoding="utf-8"))

    def _swapped_bob(self):
        records = [
            SimpleNamespace(frame_index=0, valid=True, pts_seconds=0.1012,
                            centroid_x_px=1.0, centroid_y_px=2.0),
            SimpleNamespace(frame_index=1, valid=True, pts_seconds=0.0,
                            centroid_x_px=3.0, centroid_y_px=4.0),
            SimpleNamespace(frame_index=2, valid=True, pts_seconds=0.2,
                            centroid_x_px=5.0, centroid_y_px=6.0),
        ]
        return records

    def test_build_fit_points_rejects_reorder(self):
        with self.assertRaises(ContractError) as raised:
            build_fit_points(self._swapped_bob())
        self.assertEqual(raised.exception.codes, ["E_NON_MONOTONIC_PTS"])
        self.assertIn("records[1].pts_seconds",
                      raised.exception.errors[0].field)

    def test_seam_rejects_with_null_value(self):
        table = [SimpleNamespace(frame_index=index,
                                 pts_seconds=index * 0.04,
                                 valid=True)
                 for index in range(234)]
        card = [SimpleNamespace(frame_index=index, valid=True)
                for index in range(234)]
        with tempfile.TemporaryDirectory() as tmp:
            out = assemble_parts(
                bob=self._swapped_bob(), card=card, frame_table=table,
                calibration_dict=copy.deepcopy(self.calibration),
                report_pin=copy.deepcopy(self.report),
                clip_sha256="e" * 64, out_dir=tmp,
                raw_bob_display="synthetic-test",
                raw_card_display="synthetic-test",
                geometry_report_display="synthetic-test",
                artifact_hashes=_synthetic_hashes())
            result = out["result"]
            self.assertEqual(result["status"], "processing_error")
            reasons = result["reject_reasons"]
            self.assertEqual([item["code"] for item in reasons],
                             ["E_NON_MONOTONIC_PTS"])
            self.assertTrue(reasons[0]["field"].startswith("observation."))
            self.assertIsNone(result["value"])
            self.assertIsNone(result["unit"])
            self.assertEqual(out["angle_series"], [])
            csv_lines = (Path(tmp) / "angles.csv").read_text(
                encoding="utf-8").splitlines()
            self.assertEqual(len(csv_lines), 1)
            for name in ("result.json", "diagnostics.json", "angles.csv"):
                self.assertTrue((Path(tmp) / name).is_file())
            checked = ResultContract.from_dict(copy.deepcopy(result))
            self.assertEqual(checked.to_dict(), result)

    def test_swapped_raw_lines_reject_end_to_end(self):
        require_smoke(REQUEST["clip_path"])
        lines = (REPO_ROOT / "fixtures" / "live"
                 / "raw_bob_one_bit.txt").read_text(
                     encoding="utf-8").splitlines(keepends=True)
        lines[0], lines[1] = lines[1], lines[0]
        with tempfile.TemporaryDirectory() as tmp:
            swapped = Path(tmp) / "swapped_raw.txt"
            swapped.write_text("".join(lines), encoding="utf-8")
            out = assemble(dict(REQUEST, raw_bob_path=str(swapped),
                                out_dir=str(Path(tmp) / "out")))
            result = out["result"]
            self.assertEqual(result["status"], "processing_error")
            self.assertEqual([item["code"]
                              for item in result["reject_reasons"]],
                             ["E_NON_MONOTONIC_PTS"])
            self.assertIsNone(result["value"])


class CardGateTests(unittest.TestCase):
    """F4: card usability gate at both seams + count validation."""

    @classmethod
    def setUpClass(cls):
        cls.calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        cls.report = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "geometry_report_live.json").read_text(encoding="utf-8"))

    def _parts(self, tmp, *, card, table=None, report=None, bob=None):
        if table is None:
            table = [SimpleNamespace(frame_index=index,
                                     pts_seconds=index * 0.04,
                                     valid=True)
                     for index in range(234)]
        if bob is None:
            bob = [SimpleNamespace(frame_index=index, valid=True,
                                   pts_seconds=index * 0.04,
                                   centroid_x_px=1.0, centroid_y_px=2.0)
                   for index in range(2)]
        return assemble_parts(
            bob=bob, card=card, frame_table=table,
            calibration_dict=copy.deepcopy(self.calibration),
            report_pin=copy.deepcopy(self.report) if report is None
            else report,
            clip_sha256="f" * 64, out_dir=tmp,
            raw_bob_display="synthetic-test",
            raw_card_display="synthetic-test",
            geometry_report_display="synthetic-test",
            artifact_hashes=_synthetic_hashes())

    def test_empty_card_parts_seam_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self._parts(tmp, card=[])["result"]
            self.assertEqual(result["status"], "unsupported_input")
            reasons = result["reject_reasons"]
            self.assertEqual([item["code"] for item in reasons],
                             ["E_OUT_OF_RANGE"])
            self.assertEqual(reasons[0]["field"],
                             "observation.reference_card")
            self.assertIsNone(result["value"])

    def test_all_invalid_card_parts_seam_rejects(self):
        card = [SimpleNamespace(frame_index=index, valid=False,
                                pts_seconds=index * 0.04)
                for index in range(234)]
        with tempfile.TemporaryDirectory() as tmp:
            result = self._parts(tmp, card=card)["result"]
            self.assertEqual(result["status"], "unsupported_input")
            self.assertEqual([item["code"]
                              for item in result["reject_reasons"]],
                             ["E_OUT_OF_RANGE"])

    def test_empty_card_file_seam_rejects(self):
        require_smoke(REQUEST["clip_path"])
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "empty_card.txt"
            empty.write_text("", encoding="utf-8")
            out = assemble(dict(REQUEST, raw_card_path=str(empty),
                                out_dir=str(Path(tmp) / "out")))
            result = out["result"]
            self.assertEqual(result["status"], "unsupported_input")
            self.assertEqual([item["code"]
                              for item in result["reject_reasons"]],
                             ["E_OUT_OF_RANGE"])
            self.assertIsNone(result["value"])

    def test_withdrawn_timed_excluded_from_usable(self):
        table = [SimpleNamespace(
            frame_index=index, pts_seconds=index * 0.04,
            valid=index >= 10) for index in range(234)]
        card = [SimpleNamespace(frame_index=index, valid=True)
                for index in range(234)]
        with tempfile.TemporaryDirectory() as tmp:
            result = self._parts(tmp, card=card, table=table)["result"]
            self.assertEqual(result["status"], "insufficient_data")
            metrics = result["quality_metrics"]
            self.assertEqual(metrics["frames_total"], 234)
            self.assertEqual(metrics["frames_usable"], 224)

    def test_malformed_counts_rejected(self):
        card = [SimpleNamespace(frame_index=index, valid=True)
                for index in range(234)]
        cases = {"string": "117", "bool": True, "negative": -1,
                 "too_big": 235, "null": None, "missing": "MISSING",
                 "non_object_section": "NON_OBJECT"}
        for name, bad in cases.items():
            with self.subTest(count=name), \
                    tempfile.TemporaryDirectory() as tmp:
                report = copy.deepcopy(self.report)
                if bad == "MISSING":
                    del report["calibration"]["n_usable_frames"]
                elif bad == "NON_OBJECT":
                    report["calibration"] = [117]
                else:
                    report["calibration"]["n_usable_frames"] = bad
                result = self._parts(tmp, card=card,
                                     report=report)["result"]
                self.assertEqual(result["status"], "processing_error")
                reasons = result["reject_reasons"]
                self.assertEqual([item["code"] for item in reasons],
                                 ["E_INCOHERENT_VALUE"])
                self.assertEqual(
                    reasons[0]["field"],
                    "geometry.geometry_report.n_usable_frames")


class ArtifactHashesSeamTests(unittest.TestCase):
    """F6: parts-seam digest validation + verbatim passthrough."""

    @classmethod
    def setUpClass(cls):
        cls.calibration = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "calibration_live.json").read_text(encoding="utf-8"))
        cls.report = json.loads(
            (REPO_ROOT / "fixtures" / "geometry"
             / "geometry_report_live.json").read_text(encoding="utf-8"))

    def _parts(self, tmp, *, hashes):
        # Starved bob (labeled synthetic): no fit runs, so the
        # digest validation + passthrough is all this exercises.
        table = [SimpleNamespace(frame_index=index,
                                 pts_seconds=index * 0.04,
                                 valid=True)
                 for index in range(234)]
        card = [SimpleNamespace(frame_index=index, valid=True)
                for index in range(234)]
        bob = [SimpleNamespace(frame_index=index, valid=True,
                               pts_seconds=index * 0.04,
                               centroid_x_px=1.0, centroid_y_px=2.0)
               for index in range(2)]
        return assemble_parts(
            bob=bob, card=card, frame_table=table,
            calibration_dict=copy.deepcopy(self.calibration),
            report_pin=copy.deepcopy(self.report),
            clip_sha256="0f" * 32, out_dir=tmp,
            raw_bob_display="synthetic-test",
            raw_card_display="synthetic-test",
            geometry_report_display="synthetic-test",
            artifact_hashes=hashes)

    def test_valid_hashes_land_verbatim(self):
        expected = _synthetic_hashes()
        with tempfile.TemporaryDirectory() as tmp:
            result = self._parts(tmp, hashes=expected)["result"]
        self.assertEqual(result["status"], "insufficient_data")
        self.assertEqual(result["provenance"]["artifact_hashes"],
                         expected)
        checked = ResultContract.from_dict(copy.deepcopy(result))
        self.assertEqual(checked.to_dict(), result)

    def test_null_digests_accepted(self):
        hashes = dict.fromkeys(ARTIFACT_HASH_KEYS)
        with tempfile.TemporaryDirectory() as tmp:
            result = self._parts(tmp, hashes=hashes)["result"]
        self.assertEqual(result["provenance"]["artifact_hashes"],
                         hashes)

    def test_malformed_hashes_rejected(self):
        good = _synthetic_hashes()
        missing = {key: value for key, value in good.items()
                   if key != "raw_card_sha256"}
        cases = {
            "non_object": "b0" * 32,
            "null_object": None,
            "missing_key": missing,
            "extra_key": dict(good, extra_sha256="a0" * 32),
        }
        for name, bad in cases.items():
            with self.subTest(hashes=name), \
                    tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(TypeError):
                    self._parts(tmp, hashes=bad)
        per_key = {"short": "b0" * 31, "long": "b0" * 32 + "b0",
                   "uppercase": "B0" * 32, "non_hex": "zz" * 32,
                   "non_string": 42}
        for key in ARTIFACT_HASH_KEYS:
            for name, bad in per_key.items():
                with self.subTest(key=key, value=name), \
                        tempfile.TemporaryDirectory() as tmp:
                    hashes = dict(good)
                    hashes[key] = bad
                    with self.assertRaises(TypeError):
                        self._parts(tmp, hashes=hashes)


class ArtifactHashesRenderTests(unittest.TestCase):
    """F6: renderer digest validation (pure, no assemble)."""

    def _render(self, provenance):
        result = {"status": "success_with_warnings",
                  "provenance": provenance}
        hashes = {name: "0f" * 32 for name in HASHED_FILES}
        return render_summary_md(result, {}, hashes)

    def test_valid_digests_render_verbatim(self):
        expected = _synthetic_hashes()
        text = self._render({"software_name": "kineticlab",
                             "artifact_hashes": expected})
        self.assertIn("- artifact_hashes (input digests, copied):",
                      text)
        for key, digest in expected.items():
            self.assertIn(f"  - {key}: {digest}", text)

    def test_absent_hashes_render_null(self):
        text = self._render({"software_name": "kineticlab"})
        self.assertIn("- artifact_hashes: null (absent)", text)

    def test_null_digest_renders_null(self):
        hashes = dict.fromkeys(ARTIFACT_HASH_KEYS)
        text = self._render({"artifact_hashes": hashes})
        self.assertIn("  - raw_bob_sha256: null", text)

    def test_malformed_digests_rejected(self):
        good = _synthetic_hashes()
        missing = {key: value for key, value in good.items()
                   if key != "geometry_report_sha256"}
        cases = {
            "non_object": "b0" * 32,
            "missing_key": missing,
            "extra_key": dict(good, extra_sha256="a0" * 32),
        }
        for name, bad in cases.items():
            with self.subTest(hashes=name):
                with self.assertRaises(TypeError):
                    self._render({"artifact_hashes": bad})
        per_value = {"short": "b0" * 31, "uppercase": "B0" * 32,
                     "non_hex": "zz" * 32, "non_string": 42}
        for name, bad in per_value.items():
            with self.subTest(value=name):
                hashes = dict(good)
                hashes["raw_bob_sha256"] = bad
                with self.assertRaises(TypeError):
                    self._render({"artifact_hashes": hashes})


if __name__ == "__main__":
    unittest.main()
