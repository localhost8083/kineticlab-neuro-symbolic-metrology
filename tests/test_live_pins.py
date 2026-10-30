"""Live-artifact hash pins (KL-9.2 item 3).

The SHA-256 digests (and byte counts) of the committed canonical
live artifacts must equal the pins in
``fixtures/live/run_metadata.json``.

Comparand choice (deliberate): the committed files under
``fixtures/live/`` plus the pinned input clip — NOT any
``live_out/`` run directory. ``live_out/`` holds ephemeral
per-run outputs that tests create and delete (and the pinned
2026-10-28 WSL run's own directory was never retained), so
pinning against it would be nondeterministic. The fixture pins
and the fixture bytes are versioned together; this test fails
only if one changes without the other. The fixture itself is
read-only here — never modified.
"""

import hashlib
import json
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_FIXTURES = REPO_ROOT / "fixtures" / "live"


class LiveArtifactPinTest(unittest.TestCase):
    def test_raw_artifact_hashes_match_pins(self):
        pins = json.loads(
            (LIVE_FIXTURES / "run_metadata.json").read_text(
                encoding="utf-8"))
        for name in ("raw_bob_one_bit.txt", "raw_card_one_bit.txt"):
            with self.subTest(artifact=name):
                entry = pins["artifacts"][name]
                data = (LIVE_FIXTURES / name).read_bytes()
                self.assertEqual(len(data), entry["bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(),
                                 entry["sha256"])

    def test_input_clip_hash_matches_pin(self):
        pins = json.loads(
            (LIVE_FIXTURES / "run_metadata.json").read_text(
                encoding="utf-8"))
        clip = pins["input_clip"]
        data = (REPO_ROOT / clip["path"]).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         clip["sha256"])


if __name__ == "__main__":
    unittest.main()
