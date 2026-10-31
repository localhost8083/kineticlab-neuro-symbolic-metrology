"""Demo front-door tests (KL-8.1 Part A, OG F8b).

Covers: pinned SAM replay counts (234/234 valid each role, no
fits); advisory replay matching the M-2 closure facts (+3
warnings, downgrade, narrative source model on recorded input);
success + rejection chains through the shared entry surface
(status, value, exports written, honest status lines); the demo
CLI (exit 0, printed paths + status line, bad chain rejected).
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kineticlab.cli import main
from kineticlab.demo import (
    demo_status_line,
    replay_advisory_pins,
    replay_sam_pins,
    run_demo_chain,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


class SamReplayTests(unittest.TestCase):
    def test_pinned_counts(self):
        sam = replay_sam_pins(REPO_ROOT)
        self.assertEqual(sam["clip"], "Smoke/test_3.mp4")
        self.assertEqual(sam["frames"], 234)
        for role in ("bob", "card"):
            with self.subTest(role=role):
                self.assertEqual(sam[role]["records"], 234)
                self.assertEqual(sam[role]["valid"], 234)


class AdvisoryReplayTests(unittest.TestCase):
    def test_matches_m2_closure(self):
        advisory = replay_advisory_pins(REPO_ROOT)
        setup = advisory["setup"]
        self.assertEqual(setup["label"], "live")
        self.assertEqual(setup["warnings_added"], 3)
        self.assertEqual(setup["codes"],
                         ["W_ASSUMPTION_UNVERIFIED"] * 3)
        self.assertEqual(setup["status_before"], "success")
        self.assertEqual(setup["status_after"],
                         "success_with_warnings")
        narrative = advisory["narrative"]
        self.assertEqual(narrative["label"], "live")
        self.assertEqual(narrative["source"], "model")
        self.assertEqual(
            narrative["input"],
            "fixtures/advisory/inputs/narrative_input_result.json")
        self.assertGreater(narrative["chars"], 0)


class DemoChainTests(unittest.TestCase):
    def test_rejection_chain_honest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_demo_chain(REPO_ROOT, chain="rejection",
                                 out_dir=Path(tmp) / "out")
        result = out["result"]
        self.assertEqual(result["status"], "unsupported_input")
        self.assertIsNone(result["value"])
        self.assertEqual([reason["code"]
                          for reason in result["reject_reasons"]],
                         ["E_MALFORMED_JSON"])
        self.assertEqual(len(out["written"]), 4)
        self.assertIn("unsupported_input", out["status_line"])
        self.assertIn("value null", out["status_line"])
        self.assertIn("4 exports in demo_out/rejection",
                      out["status_line"])
        self.assertNotRegex(out["status_line"], r"[A-Za-z]:[\\/]")
        advisory = out["advisory"]
        self.assertEqual(advisory["setup"]["warnings_added"], 3)
        self.assertEqual(advisory["setup"]["status_after"],
                         "success_with_warnings")
        self.assertEqual(advisory["narrative"]["source"], "model")

    def test_success_chain_matches_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_demo_chain(REPO_ROOT, chain="success",
                                 out_dir=Path(tmp) / "out")
            for path in out["written"]:
                self.assertTrue(Path(path).is_file())
        result = out["result"]
        # KL-10.11: the bootstrap ran, so the demo success chain
        # reaches plain success with a populated interval.
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["value"], 30.00563573707589)
        self.assertEqual(result["interval_method"], "block_bootstrap")
        self.assertLess(result["interval"]["lower"],
                        result["interval"]["upper"])
        self.assertIn("chain: success —", out["status_line"])
        self.assertIn("30.00563573707589", out["status_line"])
        self.assertIn("4 exports in demo_out/success",
                      out["status_line"])
        self.assertNotRegex(out["status_line"], r"[A-Za-z]:[\\/]")
        self.assertIn("advisory", out)

    def test_bad_chain_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                run_demo_chain(REPO_ROOT, chain="bogus",
                               out_dir=Path(tmp))

    def test_status_line_pure(self):
        line = demo_status_line(
            "rejection",
            {"status": "unsupported_input",
             "identifiable_quantity": {"name": "g/L_eff",
                                       "value": None,
                                       "unit": "1/s^2"},
             "reject_reasons": [{"code": "E_X", "field": "f",
                                 "detail": "d"}]})
        self.assertIn("unsupported_input", line)
        self.assertIn("value null", line)
        self.assertIn("E_X", line)
        self.assertIn("4 exports in demo_out/rejection", line)
        self.assertNotRegex(line, r"[A-Za-z]:[\\/]")

    def test_status_line_success_value(self):
        line = demo_status_line(
            "success",
            {"status": "success_with_warnings",
             "identifiable_quantity": {"name": "g/L_eff",
                                       "value": 30.00563573707589,
                                       "unit": "1/s^2"},
             "reject_reasons": []})
        self.assertIn("30.00563573707589", line)
        self.assertIn("4 exports in demo_out/success", line)
        self.assertNotIn("E:", line)


class DemoCliTests(unittest.TestCase):
    def setUp(self):
        previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(REPO_ROOT)

    def test_demo_rejection_exit_zero(self):
        stdout = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with redirect_stdout(stdout):
                code = main(["demo", "--chain", "rejection",
                             "--out-dir", tmp])
            self.assertEqual(code, 0)
            for name in ("result.json", "diagnostics.json",
                         "angles.csv", "summary.md"):
                self.assertTrue(
                    (Path(tmp) / "rejection" / name).is_file())
        text = stdout.getvalue()
        self.assertIn("234/234 valid", text)
        self.assertIn("source=model", text)
        self.assertIn("unsupported_input", text)
        self.assertEqual(text.count("wrote: "), 4)

    def test_demo_bad_chain_exits_two(self):
        with self.assertRaises(SystemExit) as raised:
            main(["demo", "--chain", "bogus"])
        self.assertEqual(raised.exception.code, 2)

    def test_demo_contract_failure_prints_message_not_crash(self):
        # KL-8.4 follow-up (Fable): the failure branch used
        # FieldError.detail, which does not exist — a ContractError
        # mid-demo would escape the handler as AttributeError
        # instead of the clean exit-1 line. Message text must be
        # printed and no traceback may escape.
        from contextlib import redirect_stderr, redirect_stdout
        from types import SimpleNamespace
        from unittest import mock
        from kineticlab import demo as demo_mod
        from kineticlab.cli import cmd_demo
        from kineticlab.contracts import ContractError, FieldError
        error = ContractError([FieldError(
            "E_MISSING_FIELD", "calibration_path",
            "injected failure for the failure branch")])
        advisory = {
            "setup": {"label": "live", "codes": [],
                      "warnings_added": 0,
                      "status_before": "success",
                      "status_after": "success"},
            "narrative": {"source": "model", "chars": 1},
        }
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(chain="success",
                                   out_dir=str(Path(tmp)))
            with mock.patch.object(demo_mod, "replay_sam_pins",
                                   return_value={
                                       "clip": "Smoke/test_3.mp4",
                                       "frames": 234,
                                       "bob": {"valid": 234,
                                               "records": 234},
                                       "card": {"valid": 234,
                                                "records": 234}}), \
                 mock.patch.object(demo_mod, "replay_advisory_pins",
                                   return_value=advisory), \
                 mock.patch.object(demo_mod, "run_demo_chain",
                                   side_effect=error):
                stderr = io.StringIO()
                stdout = io.StringIO()
                with redirect_stderr(stderr), redirect_stdout(stdout):
                    code = cmd_demo(args)
        self.assertEqual(code, 1)
        text = stderr.getvalue()
        self.assertIn("demo failed:", text)
        self.assertIn("E_MISSING_FIELD", text)
        self.assertIn("injected failure for the failure branch", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("detail", text)


if __name__ == "__main__":
    unittest.main()
