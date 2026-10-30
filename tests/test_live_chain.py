"""Live-chain orchestration tests (KL-8.4).

`run_detect` / `run_measure` / `run_live_chain` run against the real
test_3 clip with a mock transport serving the PINNED live raw bytes —
so the full chain must reproduce the pinned success value exactly
(same data, same arc fit, same M1). Covered per mode: detect summary
shape, measure outputs, mm validation, the motion nulls + reason,
confirm-before-measure gating (no summary, no measure), determinism
of measure outputs, and key hygiene over the run dir.
"""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from kineticlab.capture import BASE_URL, ROLE_FILENAMES
from kineticlab.capture.chain import (
    CALIBRATION_FILENAME,
    GEOMETRY_REPORT_FILENAME,
    MEASURE_REUSE_FILENAME,
    MOTION_CSV_FILENAME,
    MOTION_REPORT_FILENAME,
    PARSE_CHECK_FILENAME,
    SUMMARY_FILENAME,
    _parse_roles,
    _reuse_or_reparse,
    _write_measure_reuse,
    _write_parse_check,
    live_status_line,
    new_run_id,
    run_detect,
    run_live_chain,
    run_measure,
    validate_card_width_mm,
    validate_mode,
    validate_prompts,
    validate_run_id,
)
from kineticlab.contracts import ContractError
from kineticlab.ingest import extract_frame_records, inspect_media
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_3 = REPO_ROOT / "Smoke" / "test_3.mp4"
PIN_BOB = (REPO_ROOT / "fixtures" / "live"
           / "raw_bob_one_bit.txt").read_text(encoding="utf-8")
PIN_CARD = (REPO_ROOT / "fixtures" / "live"
            / "raw_card_one_bit.txt").read_text(encoding="utf-8")
PIN_VALUE = json.loads((REPO_ROOT / "fixtures" / "assembly"
                        / "result.json").read_text(encoding="utf-8"))
PIN_G_OVER_L = PIN_VALUE["identifiable_quantity"]["value"]
PIN_PERIOD = 1.1470397067318712
SECRET = "test-key-live-chain-probe-9f8e"


def pin_transport(texts):
    """Mock transport serving {prompt-substring: output_text}."""

    def send(request):
        url = request["url"]
        if url == f"{BASE_URL}/files":
            return {"status": 200, "body": b'{"id": "file-pin"}'}
        if request["method"] == "DELETE":
            return {"status": 200, "body": b"{}"}
        prompt = json.loads(request["body"].decode("utf-8"))
        text = prompt["input"][0]["content"][0]["text"]
        for key, value in texts.items():
            if key in text:
                chosen = value
                break
        else:
            chosen = ""
        payload = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": chosen}]}]}
        return {"status": 200, "body": json.dumps(payload).encode()}
    return send


FULL_TEXTS = {"ball": PIN_BOB, "card": PIN_CARD}


class ValidatorsTest(unittest.TestCase):
    def test_run_id_round_trip(self):
        run_id = new_run_id()
        self.assertEqual(validate_run_id(run_id), run_id)
        for bad in ("", "live-20261029T063707Z-xyz", "../x",
                    "live-20261029T063707Z-44773902/..", None, 42,
                    "live-20261029T063707Z-4477390!"):
            with self.subTest(run_id=bad):
                with self.assertRaises(ContractError) as raised:
                    validate_run_id(bad)
                self.assertEqual(raised.exception.errors[0].code,
                                 "E_MISSING_FIELD")

    def test_mode_labels(self):
        self.assertEqual(validate_mode("full"), "full")
        self.assertEqual(validate_mode("motion"), "motion")
        with self.assertRaises(ContractError) as raised:
            validate_mode("sideways")
        self.assertEqual(raised.exception.errors[0].code, "E_BAD_ENUM")

    def test_prompts_per_mode(self):
        full = validate_prompts({"bob": "b", "card": "c"}, "full")
        self.assertEqual(full, {"bob": "b", "card": "c"})
        motion = validate_prompts({"bob": "b"}, "motion")
        self.assertEqual(motion, {"bob": "b"})
        with self.assertRaises(ContractError) as raised:
            validate_prompts({"bob": "b"}, "full")
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "prompt:card")
        with self.assertRaises(ContractError) as raised:
            validate_prompts({"bob": "b", "card": "c"}, "motion")
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_INCOHERENT_VALUE")
        self.assertEqual(error.field, "prompt:card")
        with self.assertRaises(ContractError) as raised:
            validate_prompts({"bob": "  "}, "motion")
        self.assertEqual(raised.exception.errors[0].code,
                         "E_EMPTY_STRING")

    def test_card_width_validation(self):
        self.assertEqual(validate_card_width_mm(85.6, "full"), 85.6)
        self.assertEqual(validate_card_width_mm("85.6", "full"), 85.6)
        self.assertIsNone(validate_card_width_mm(None, "motion"))
        with self.assertRaises(ContractError) as raised:
            validate_card_width_mm(None, "full")
        self.assertEqual(raised.exception.errors[0].code,
                         "E_MISSING_FIELD")
        with self.assertRaises(ContractError) as raised:
            validate_card_width_mm(85.6, "motion")
        self.assertEqual(raised.exception.errors[0].code,
                         "E_INCOHERENT_VALUE")
        for bad, code in (("abc", "E_WRONG_TYPE"), ("nan", "E_NON_FINITE"),
                          ("inf", "E_NON_FINITE"), (-1.0, "E_OUT_OF_RANGE"),
                          (0.0, "E_OUT_OF_RANGE"), (True, "E_WRONG_TYPE")):
            with self.subTest(value=bad):
                with self.assertRaises(ContractError) as raised:
                    validate_card_width_mm(bad, "full")
                self.assertEqual(raised.exception.errors[0].code, code)

    def test_status_line_carries_no_absolute_path(self):
        line = live_status_line(
            "full", "live-20261029T063707Z-44773902",
            {"status": "success_with_warnings",
             "identifiable_quantity": {"name": "g/L_eff",
                                       "value": 30.0, "unit": "1/s^2"}},
            4)
        self.assertNotIn("E:\\", line)
        self.assertNotRegex(line, r"[A-Za-z]:[\\/]")
        self.assertIn("live-20261029T063707Z-44773902", line)


class DetectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_detect_full_summary(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        out = run_detect(TEST_3, self.root / run_id, "full",
                         {"bob": "red ball",
                          "card": "white paper card"},
                         SECRET, transport=pin_transport(FULL_TEXTS))
        self.assertEqual(out["run_id"], run_id)
        summary = out["summary"]
        self.assertEqual(summary["mode"], "full")
        self.assertEqual(summary["prompts"],
                         {"bob": "red ball",
                          "card": "white paper card"})
        media = inspect_media(str(TEST_3))
        self.assertEqual(summary["video"]["width"], media.width)
        self.assertEqual(summary["video"]["height"], media.height)
        self.assertEqual(summary["video"]["frames"], 234)
        for role in ("bob", "card"):
            info = summary["roles"][role]
            self.assertGreater(info["valid"], 0)
            self.assertEqual(len(info["first_box"]), 4)
            self.assertTrue(
                all(isinstance(value, float)
                    for value in info["first_box"]))
        self.assertTrue((self.root / run_id / "clip.mp4").is_file())
        self.assertTrue(
            (self.root / run_id / SUMMARY_FILENAME).is_file())
        stored = json.loads((self.root / run_id / SUMMARY_FILENAME)
                            .read_text(encoding="utf-8"))
        self.assertEqual(stored, summary)

    def test_detect_motion_captures_bob_only(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        out = run_detect(TEST_3, self.root / run_id, "motion",
                         {"bob": "red ball"}, SECRET,
                         transport=pin_transport(FULL_TEXTS))
        self.assertEqual(sorted(out["summary"]["roles"]), ["bob"])
        self.assertTrue((self.root / run_id
                         / "raw_bob_one_bit.txt").is_file())
        self.assertFalse((self.root / run_id
                          / "raw_card_one_bit.txt").exists())

    def test_detect_empty_output_rejects(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        with self.assertRaises(ContractError) as raised:
            run_detect(TEST_3, self.root / run_id, "motion",
                       {"bob": "red ball"}, SECRET,
                       transport=pin_transport({}))
        self.assertEqual(raised.exception.errors[0].code,
                         "E_EMPTY_STRING")

    def test_detect_gate_rejects_zero_valid(self):
        from kineticlab.capture.chain import _gate_valid

        records = [SimpleNamespace(valid=False),
                   SimpleNamespace(valid=False)]
        with self.assertRaises(ContractError) as raised:
            _gate_valid(records, "bob")
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_EMPTY_STRING")
        self.assertEqual(error.field, "detections:bob")
        kept = _gate_valid([SimpleNamespace(valid=False),
                            SimpleNamespace(valid=True)], "bob")
        self.assertEqual(len(kept), 1)


class MeasureFullTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.run_id = new_run_id()
        run_detect(TEST_3, cls.root / cls.run_id, "full",
                   {"bob": "red ball", "card": "white paper card"},
                   SECRET, transport=pin_transport(FULL_TEXTS))
        cls.out = run_measure(cls.root / cls.run_id, 85.60)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_result_reproduces_pin(self):
        result = self.out["result"]
        self.assertEqual(result["status"], "success_with_warnings")
        quantity = result["identifiable_quantity"]
        self.assertEqual(quantity["name"], "g/L_eff")
        self.assertEqual(quantity["unit"], "1/s^2")
        self.assertAlmostEqual(quantity["value"], PIN_G_OVER_L,
                               delta=1e-12 * abs(PIN_G_OVER_L))

    def test_calibration_honest_fresh_clip(self):
        calibration = json.loads(
            (self.root / self.run_id / CALIBRATION_FILENAME)
            .read_text(encoding="utf-8"))
        self.assertFalse(calibration["valid"])
        self.assertEqual(calibration["reference_type"], "unknown")
        self.assertIsNone(
            calibration["reference_dimensions_mm"])
        self.assertEqual(calibration["dimension_source"],
                         "not_provided")
        self.assertIsNone(calibration["observed_corners_px"])
        self.assertIsNone(calibration["same_plane_assumption"])
        self.assertIsNone(calibration["camera_fixed_assumption"])
        self.assertGreater(calibration["scale_mm_per_px"], 0.0)
        codes = [item["code"] for item in calibration["warnings"]]
        self.assertEqual(codes, ["W_ASSUMPTION_UNVERIFIED",
                                 "W_ASSUMPTION_UNVERIFIED"])

    def test_geometry_report_pins(self):
        report = json.loads(
            (self.root / self.run_id / GEOMETRY_REPORT_FILENAME)
            .read_text(encoding="utf-8"))
        self.assertTrue(report["pivot_arc"]["fitted"])
        section = report["calibration"]
        self.assertEqual(section["n_usable_frames"], 117)
        self.assertEqual(section["card_width_mm"], 85.60)
        self.assertEqual(section["card_width_mm_source"],
                         "user_supplied")
        self.assertIn("U-3 applied to the pinned test_3 clip only",
                      section["u3_bound"]["statement"])

    def test_model_limitations_carry_arc_radius_caveat(self):
        # KL-9.6 M1: the live geometry report states the arc-fit
        # radius caveat with this run's own radius × scale value —
        # descriptive-only, frequency result unaffected.
        report = json.loads(
            (self.root / self.run_id / GEOMETRY_REPORT_FILENAME)
            .read_text(encoding="utf-8"))
        limitations = report["model_limitations"]
        self.assertIsInstance(limitations, list)
        self.assertEqual(len(limitations), 2)
        self.assertIn("M-3e", limitations[0])
        caveat = limitations[1]
        self.assertIn("descriptive-only", caveat)
        self.assertIn("frequency-based and unaffected", caveat)
        self.assertIn("Stated uncorrected", caveat)
        radius_mm = (report["pivot_arc"]["radius_px"]
                     * report["calibration"]["scale_mm_per_px"])
        self.assertIn(f"{radius_mm:.1f} mm on this run", caveat)

    def test_written_exports(self):
        self.assertEqual(len(self.out["written"]), 4)
        for path in self.out["written"]:
            self.assertTrue(Path(path).is_file())
        self.assertIn("success_with_warnings",
                      self.out["status_line"])

    def test_measure_outputs_deterministic(self):
        before = {name: (self.root / self.run_id / name).read_bytes()
                  for name in ("result.json", "diagnostics.json",
                               "angles.csv", "summary.md",
                               CALIBRATION_FILENAME,
                               GEOMETRY_REPORT_FILENAME)}
        run_measure(self.root / self.run_id, 85.60)
        for name, payload in before.items():
            with self.subTest(export=name):
                self.assertEqual(
                    (self.root / self.run_id / name).read_bytes(),
                    payload)

    def test_key_absent_from_run_dir(self):
        for path in sorted((self.root / self.run_id).iterdir()):
            if path.suffix in (".json", ".csv", ".md", ".txt"):
                with self.subTest(file=path.name):
                    self.assertNotIn(
                        SECRET, path.read_text(encoding="utf-8"))


class MeasureMotionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.run_id = new_run_id()
        run_detect(TEST_3, cls.root / cls.run_id, "motion",
                   {"bob": "red ball"}, SECRET,
                   transport=pin_transport(FULL_TEXTS))
        cls.out = run_measure(cls.root / cls.run_id)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_report_complete(self):
        report = self.out["report"]
        self.assertEqual(report["status"], "complete")
        self.assertAlmostEqual(report["g_over_l_per_s2"],
                               PIN_G_OVER_L,
                               delta=1e-12 * abs(PIN_G_OVER_L))
        self.assertAlmostEqual(report["period_s"], PIN_PERIOD,
                               delta=1e-12 * abs(PIN_PERIOD))
        self.assertIsNotNone(report["omega_per_s"])
        self.assertIsNotNone(report["pivot_px"])
        self.assertEqual(report["n_fit_points"], 234)
        self.assertEqual(report["excluded_frames"], [])

    def test_scale_fields_null_with_reason(self):
        report = self.out["report"]
        self.assertIsNone(report["scale_mm_per_px"])
        self.assertIsNone(report["pivot_length_mm"])
        self.assertIsNone(report["gravity_m_s2"])
        self.assertEqual(report["reason"],
                         "no reference card: no scale")
        self.assertFalse((self.root / self.run_id
                          / CALIBRATION_FILENAME).exists())

    def test_csv_shape(self):
        lines = (self.root / self.run_id / MOTION_CSV_FILENAME) \
            .read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "frame_index,pts_seconds,theta_rad,"
                                  "centroid_x_px,centroid_y_px")
        self.assertEqual(len(lines), 235)

    def test_written_exports(self):
        self.assertEqual(len(self.out["written"]), 2)
        for path in self.out["written"]:
            self.assertTrue(Path(path).is_file())

    def test_report_deterministic(self):
        before = {name: (self.root / self.run_id / name).read_bytes()
                  for name in (MOTION_REPORT_FILENAME,
                               MOTION_CSV_FILENAME)}
        run_measure(self.root / self.run_id)
        for name, payload in before.items():
            with self.subTest(export=name):
                self.assertEqual(
                    (self.root / self.run_id / name).read_bytes(),
                    payload)

    def test_zero_offset_assumption_wording(self):
        # KL-9.6 M2: motion carries the same corrected zero-offset
        # sentence as the assemble path (a DC offset is NOT
        # absorbed by the M1 phase); pinned exactly in one place.
        from tests.test_assembly import ZERO_OFFSET_ASSUMPTION

        report = self.out["report"]
        self.assertEqual(report["assumptions"][0],
                         ZERO_OFFSET_ASSUMPTION)

    def test_converged_report_strips_test_convention_note(self):
        # KL-9.6 B4: the synthetic-fixture note must not leak into
        # the published report; nested fit + diagnostics stay
        # verbatim (the page reads them for charts/RMS).
        report = self.out["report"]
        self.assertEqual(report["status"], "complete")
        self.assertNotIn("test_convention_note", report["m1"])
        self.assertIn("fit", report["m1"])
        self.assertIn("diagnostics", report["m1"])
        self.assertEqual(report["m1"]["diagnostics"]["converged"],
                         True)


class MotionHonestyTests(unittest.TestCase):
    """Non-converged M1 fits report incomplete, never a value (KL-9.6 B4)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def detect_motion(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        run_detect(TEST_3, self.root / run_id, "motion",
                   {"bob": "red ball"}, SECRET,
                   transport=pin_transport(FULL_TEXTS))
        return self.root / run_id

    def test_non_converged_fit_reports_incomplete_with_nulls(self):
        import kineticlab.capture.chain as chain_module

        run = self.detect_motion()
        real = chain_module.fit_m1
        canned = {
            "fitter": "m1-test-double",
            "model": "m1.v1",
            "test_convention_note": "input points are synthetic",
            "fit": {"g_over_l_per_s2": 29.9,
                    "residual_summary": {"rmse": 0.5}},
            "diagnostics": {
                "converged": False,
                "termination_reason": "budget_exhausted",
                "fitted": {"amplitude_rad": 0.3,
                           "omega_per_s": 5.4,
                           "period_s": 1.1,
                           "phase_rad": 0.1},
            },
        }

        def doubled(request):
            self.assertIn("points", request)
            return copy.deepcopy(canned)

        chain_module.fit_m1 = doubled
        self.addCleanup(setattr, chain_module, "fit_m1", real)
        out = run_measure(run)
        report = out["report"]
        # Status + reason: incomplete, free-form cause, no new code.
        self.assertEqual(report["status"], "incomplete")
        self.assertIn("did not converge", report["reason"])
        self.assertIn("budget_exhausted", report["reason"])
        # No grid-bound value published as a result.
        self.assertIsNone(report["g_over_l_per_s2"])
        self.assertIsNone(report["amplitude_rad"])
        self.assertIsNone(report["omega_per_s"])
        self.assertIsNone(report["period_s"])
        # The un-converged evidence stays for audit, minus the note.
        self.assertNotIn("test_convention_note", report["m1"])
        self.assertEqual(report["m1"]["diagnostics"]["converged"],
                         False)
        # Exports still land; the status line says incomplete.
        self.assertEqual(len(out["written"]), 2)
        self.assertIn("incomplete", out["status_line"])
        self.assertIn("value null", out["status_line"])


class MeasureGatingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_measure_without_detect_rejects(self):
        run_id = new_run_id()
        (self.root / run_id).mkdir()
        with self.assertRaises(ContractError) as raised:
            run_measure(self.root / run_id, 85.60)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "run_id")

    def test_full_without_mm_rejects(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        run_detect(TEST_3, self.root / run_id, "full",
                   {"bob": "red ball", "card": "white paper card"},
                   SECRET, transport=pin_transport(FULL_TEXTS))
        with self.assertRaises(ContractError) as raised:
            run_measure(self.root / run_id)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "card_width_mm")

    def test_motion_with_mm_rejects(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        run_detect(TEST_3, self.root / run_id, "motion",
                   {"bob": "red ball"}, SECRET,
                   transport=pin_transport(FULL_TEXTS))
        with self.assertRaises(ContractError) as raised:
            run_measure(self.root / run_id, 85.60)
        self.assertEqual(raised.exception.errors[0].code,
                         "E_INCOHERENT_VALUE")


class LiveChainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_one_shot_full(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        out = run_live_chain(TEST_3, "full",
                             {"bob": "red ball",
                              "card": "white paper card"},
                             85.60, self.root / run_id, SECRET,
                             transport=pin_transport(FULL_TEXTS))
        self.assertEqual(out["run_id"], run_id)
        self.assertEqual(out["mode"], "full")
        self.assertEqual(out["result"]["status"],
                         "success_with_warnings")
        self.assertEqual(out["summary"]["mode"], "full")

    def test_one_shot_motion(self):
        require_smoke(TEST_3)
        run_id = new_run_id()
        out = run_live_chain(TEST_3, "motion", {"bob": "red ball"},
                             None, self.root / run_id, SECRET,
                             transport=pin_transport(FULL_TEXTS))
        self.assertEqual(out["run_id"], run_id)
        self.assertEqual(out["mode"], "motion")
        self.assertEqual(out["report"]["status"], "complete")


class MeasureReuseUnitTests(unittest.TestCase):
    """Detect->measure parse reuse on tiny synthetic run dirs (KL-8.7)."""

    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3)
        cls.table = extract_frame_records(str(TEST_3))
        cls.lines = PIN_BOB.splitlines()[:2]

    def _run_dir(self, root):
        run = root / new_run_id()
        run.mkdir(parents=True)
        (run / ROLE_FILENAMES["bob"]).write_text(
            "\n".join(self.lines) + "\n", encoding="utf-8")
        return run

    def _checked_run(self, root):
        run = self._run_dir(root)
        parsed = _parse_roles(run, self.table, ("bob",))
        self.assertEqual([record.frame_index for record in parsed["bob"]],
                         [0, 1])
        check = _write_parse_check(run, parsed)
        return run, parsed, check

    def test_reuse_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, parsed, check = self._checked_run(Path(tmp))
            raw = (run / ROLE_FILENAMES["bob"]).read_bytes()
            entry = check["roles"]["bob"]
            self.assertEqual(entry["raw_sha256"],
                             hashlib.sha256(raw).hexdigest())
            self.assertEqual(entry["n_records"], 2)
            self.assertEqual(entry["n_valid"], 2)
            rebuilt, reused = _reuse_or_reparse(run, self.table,
                                                ("bob",))
            self.assertTrue(reused)
            self.assertEqual(
                [record.to_dict() for record in rebuilt["bob"]],
                [record.to_dict() for record in parsed["bob"]])

    def test_sha_mismatch_raises_coded_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _, _ = self._checked_run(Path(tmp))
            with (run / ROLE_FILENAMES["bob"]).open("ab") as handle:
                handle.write(b"\n")  # new bytes, same parse
            with self.assertRaises(ContractError) as raised:
                _reuse_or_reparse(run, self.table, ("bob",))
            error = raised.exception.errors[0]
            self.assertEqual(error.code, "E_INCOHERENT_VALUE")
            self.assertEqual(error.field, "parse_check.json.bob")

    def test_missing_check_raises_coded_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _, _ = self._checked_run(Path(tmp))
            (run / PARSE_CHECK_FILENAME).unlink()
            with self.assertRaises(ContractError) as raised:
                _reuse_or_reparse(run, self.table, ("bob",))
            error = raised.exception.errors[0]
            self.assertEqual(error.code, "E_MISSING_FIELD")
            self.assertEqual(error.field, "parse_check.json")

    def test_honesty_record_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, _, check = self._checked_run(Path(tmp))
            for reused in (True, False):
                with self.subTest(reused=reused):
                    record = _write_measure_reuse(run, check, reused)
                    on_disk = json.loads(
                        (run / MEASURE_REUSE_FILENAME).read_text(
                            encoding="utf-8"))
                    self.assertEqual(on_disk, record)
                    self.assertEqual(record["reused"], reused)
                    self.assertEqual(
                        record["checked"],
                        {"bob": check["roles"]["bob"]["raw_sha256"]})
                    self.assertEqual(record["parsed_at_utc"],
                                     check["parsed_at_utc"])
                    self.assertTrue(record["measured_at_utc"])


class MeasureReuseFallbackTest(unittest.TestCase):
    """Motion measure falls back to a full re-parse on SHA mismatch."""

    def test_fallback_reparses_and_records(self):
        require_smoke(TEST_3)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = new_run_id()
            run = root / run_id
            run_detect(TEST_3, run, "motion", {"bob": "red ball"},
                       SECRET, transport=pin_transport(FULL_TEXTS))
            run_measure(run)
            reuse = json.loads(
                (run / MEASURE_REUSE_FILENAME).read_text(
                    encoding="utf-8"))
            self.assertTrue(reuse["reused"])
            before = {name: (run / name).read_bytes()
                      for name in (MOTION_REPORT_FILENAME,
                                   MOTION_CSV_FILENAME)}
            with (run / ROLE_FILENAMES["bob"]).open("ab") as handle:
                handle.write(b"\n")  # new bytes, same parse
            run_measure(run)
            reuse = json.loads(
                (run / MEASURE_REUSE_FILENAME).read_text(
                    encoding="utf-8"))
            self.assertFalse(reuse["reused"])
            for name, payload in before.items():
                with self.subTest(export=name):
                    self.assertEqual((run / name).read_bytes(),
                                     payload)


if __name__ == "__main__":
    unittest.main()
