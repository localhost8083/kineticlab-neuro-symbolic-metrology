"""Offline smoke-command tests (KL-0.3).

Runs `scripts/media_check.py` as a subprocess against the pinned fixtures.
A passing suite means the probe reproduces the independently recorded
ffprobe/README structure for both source clips.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "media_check.py"


def run_media_check(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


class MediaCheckTest(unittest.TestCase):
    def check_fixture(self, name):
        # KL-9.6 B1: the pinned video lives under gitignored
        # Smoke/; resolve it from the fixture file itself so the
        # guard can never drift from the path the script reads.
        fixture = json.loads(
            (REPO_ROOT / name).read_text(encoding="utf-8"))
        require_smoke(REPO_ROOT / fixture["video"])
        completed = run_media_check("--fixture", name)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIn("PASS", completed.stdout)

    def test_demo_fixture_passes(self):
        self.check_fixture("fixtures/demo_test.json")

    def test_missing_video_fails_explicitly(self):
        fixture = {"name": "missing", "video": "Smoke/does_not_exist.mp4",
                   "provenance": "negative test", "expect": {}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(fixture, handle)
            temp_fixture = handle.name
        self.addCleanup(Path(temp_fixture).unlink)
        completed = run_media_check("--fixture", temp_fixture)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("not found", (completed.stdout + completed.stderr).lower())


if __name__ == "__main__":
    unittest.main()
