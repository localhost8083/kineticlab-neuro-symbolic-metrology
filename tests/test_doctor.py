"""Doctor CLI tests (KL-10.24).

Direct-invocation pattern from tests/test_cli.py; the key-shaped
scan reuses tests/test_key_hygiene.py so the doctor output is held
to the same no-secret-material law as the tree.
"""

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

from kineticlab.cli import main
from tests.test_key_hygiene import scan_text

REPO_ROOT = Path(__file__).resolve().parent.parent

SUMMARY_PATTERN = re.compile(r"^doctor: \d+ pass, \d+ skip, \d+ fail$")


class DoctorCliTest(unittest.TestCase):
    def run_doctor(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["doctor"])
        return code, stdout.getvalue()

    def test_repo_run_passes_with_summary_line(self):
        previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(REPO_ROOT)
        code, output = self.run_doctor()
        self.assertEqual(code, 0)
        self.assertIn("[PASS]", output)
        # Environment-varying checks (node) may SKIP, so only the
        # shape is pinned, never exact pass/skip counts.
        last = output.strip().splitlines()[-1]
        self.assertRegex(last, SUMMARY_PATTERN)
        self.assertIn("sha256 matches", output)
        self.assertIn("self-check parses", output)

    def test_help_documents_exit_codes(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as raised:
                main(["doctor", "--help"])
        self.assertEqual(raised.exception.code, 0)
        self.assertIn("exit", stdout.getvalue().lower())

    def test_outside_checkout_reports_package_only_mode(self):
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                code, output = self.run_doctor()
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(code, 0)
        self.assertIn("package-only mode", output)
        self.assertIn("full repository health not claimed", output)
        self.assertIn("repository fixture integrity skipped", output)
        self.assertNotIn("fixtures/test_3.json absent", output)

    def test_repo_without_fixtures_reports_skips(self):
        previous_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                (Path(tmp) / "kineticlab.toml").write_text("\n",
                                                               encoding="utf-8")
                code, output = self.run_doctor()
            finally:
                os.chdir(previous_cwd)
        self.assertEqual(code, 1)
        self.assertIn("valid_result.json absent", output)
        self.assertIn("fixtures/test_3.json absent", output)
        self.assertIn("doctor: ", output)

    def test_output_never_carries_key_material(self):
        previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(REPO_ROOT)
        previous_key = os.environ.get("MODEL_API_KEY")
        self.addCleanup(self._restore_key, previous_key)
        os.environ["MODEL_API_KEY"] = "sk-" + "x" * 24
        code, output = self.run_doctor()
        self.assertEqual(code, 0)
        self.assertIn("present", output)
        self.assertNotIn("sk-", output)
        self.assertEqual(scan_text("doctor-output", output), [])

    def test_env_file_in_root_fails_with_exit_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            previous_cwd = os.getcwd()
            os.chdir(tmp)
            self.addCleanup(os.chdir, previous_cwd)
            secret = "MODEL_API_KEY=" + "sk-" + "y" * 24
            (Path(tmp) / ".env").write_text(secret + "\n",
                                            encoding="utf-8")
            code, output = self.run_doctor()
            # Windows cannot delete a TemporaryDirectory that is a
            # live cwd — step out before the with-block cleanup.
            os.chdir(previous_cwd)
            self.assertEqual(code, 1)
            self.assertIn("[FAIL]", output)
            self.assertIn(".env", output)
            # The planted value must never surface, only the filename.
            self.assertNotIn("sk-", output)
            self.assertEqual(scan_text("doctor-output", output), [])
            last = output.strip().splitlines()[-1]
            self.assertRegex(last, SUMMARY_PATTERN)
            self.assertNotIn("0 fail", last)

    def _restore_key(self, previous):
        if previous is None:
            os.environ.pop("MODEL_API_KEY", None)
        else:
            os.environ["MODEL_API_KEY"] = previous


if __name__ == "__main__":
    unittest.main()
