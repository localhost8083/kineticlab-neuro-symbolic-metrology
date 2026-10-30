"""CLI entry-point tests (KL-0.3)."""

import contextlib
import io
import json
import os
import unittest
from pathlib import Path

from kineticlab import __version__
from kineticlab.cli import main
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent


class CliTest(unittest.TestCase):
    def run_main(self, argv):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(argv)
        return raised.exception.code, stdout.getvalue()

    def test_help_exits_zero(self):
        code, output = self.run_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage: kineticlab", output)

    def test_version_reports_package_version(self):
        code, output = self.run_main(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(__version__, output)

    def test_config_reports_effective_paths(self):
        previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(REPO_ROOT)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["config"])
        self.assertEqual(code, 0)
        effective = json.loads(stdout.getvalue())
        self.assertEqual(Path(effective["root"]), REPO_ROOT)
        self.assertFalse(effective["api_enabled"])
        for name, path in effective["paths"].items():
            with self.subTest(path=name):
                self.assertTrue(Path(path).is_absolute(), path)


class CaptureCliTest(unittest.TestCase):
    def setUp(self):
        previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(REPO_ROOT)
        previous = os.environ.get("MODEL_API_KEY")
        self.addCleanup(self._restore_key, previous)

    def _restore_key(self, previous):
        if previous is None:
            os.environ.pop("MODEL_API_KEY", None)
        else:
            os.environ["MODEL_API_KEY"] = previous

    def run_capture(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_help_lists_capture(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["capture", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("--card-width-mm", stdout.getvalue())

    def test_missing_required_option_is_misuse(self):
        with self.assertRaises(SystemExit) as raised:
            main(["capture", "--mode", "motion"])
        self.assertEqual(raised.exception.code, 2)

    def test_no_key_is_misuse(self):
        os.environ.pop("MODEL_API_KEY", None)
        code, _, stderr = self.run_capture(
            ["capture", "--clip", "Smoke/test_3.mp4",
             "--mode", "motion"])
        self.assertEqual(code, 2)
        self.assertIn("MODEL_API_KEY", stderr)
        self.assertIn("E_MISSING_FIELD", stderr)

    def test_motion_with_mm_is_misuse(self):
        # The CLI stats the clip before the mm-misuse gate fires.
        require_smoke(Path("Smoke/test_3.mp4"))
        os.environ["MODEL_API_KEY"] = "test-key"
        code, _, stderr = self.run_capture(
            ["capture", "--clip", "Smoke/test_3.mp4",
             "--mode", "motion", "--card-width-mm", "85.6"])
        self.assertEqual(code, 2)
        self.assertIn("E_INCOHERENT_VALUE", stderr)

    def test_full_without_mm_is_misuse(self):
        # The CLI stats the clip before the missing-mm gate fires.
        require_smoke(Path("Smoke/test_3.mp4"))
        os.environ["MODEL_API_KEY"] = "test-key"
        code, _, stderr = self.run_capture(
            ["capture", "--clip", "Smoke/test_3.mp4",
             "--mode", "full"])
        self.assertEqual(code, 2)
        self.assertIn("E_MISSING_FIELD", stderr)

    def test_missing_clip_is_misuse(self):
        os.environ["MODEL_API_KEY"] = "test-key"
        code, _, stderr = self.run_capture(
            ["capture", "--clip", "Smoke/absent.mp4",
             "--mode", "motion"])
        self.assertEqual(code, 2)
        self.assertIn("E_MISSING_FIELD", stderr)

    def test_chain_failure_exits_one_with_code(self):
        import kineticlab.capture.chain as chain_module
        from kineticlab.contracts import ContractError, FieldError

        os.environ["MODEL_API_KEY"] = "test-key"
        real = chain_module.run_live_chain

        def failing(*args, **kwargs):
            raise ContractError([FieldError(
                "E_EMPTY_STRING", "output_text:bob", "zero matches")])

        chain_module.run_live_chain = failing
        self.addCleanup(setattr, chain_module, "run_live_chain",
                        real)
        # The chain is mocked but the CLI still stats the clip first.
        require_smoke(Path("Smoke/test_3.mp4"))
        code, _, stderr = self.run_capture(
            ["capture", "--clip", "Smoke/test_3.mp4",
             "--mode", "motion"])
        self.assertEqual(code, 1)
        self.assertIn("E_EMPTY_STRING", stderr)

    def test_chain_success_exits_zero(self):
        import kineticlab.capture.chain as chain_module

        os.environ["MODEL_API_KEY"] = "test-key"
        real = chain_module.run_live_chain
        canned = {"summary": {"roles": {
                      "bob": {"valid": 10, "records": 10}}},
                  "status_line": "live motion run r: complete",
                  "written": ["a.json", "b.csv"]}

        def succeeding(*args, **kwargs):
            return dict(canned)

        chain_module.run_live_chain = succeeding
        self.addCleanup(setattr, chain_module, "run_live_chain",
                        real)
        # The chain is mocked but the CLI still stats the clip first.
        require_smoke(Path("Smoke/test_3.mp4"))
        code, stdout, _ = self.run_capture(
            ["capture", "--clip", "Smoke/test_3.mp4",
             "--mode", "motion"])
        self.assertEqual(code, 0)
        self.assertIn("captured: bob 10/10 valid", stdout)
        self.assertIn("live motion run r: complete", stdout)
        self.assertIn("wrote: a.json", stdout)


if __name__ == "__main__":
    unittest.main()
