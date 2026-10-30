"""Media ingest tests (KL-2.1).

`inspect_media` must reproduce the independently pinned fixture values
(ffprobe-derived pins in `fixtures/*.json`) for both real clips, keep
unknowns null, and fail explicitly with registered codes on missing or
malformed input. Every produced record round-trips `MediaMetadata`.
"""

import json
import tempfile
import unittest
from pathlib import Path

from kineticlab.contracts import ContractError, MediaMetadata
from kineticlab.ingest import inspect_media
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent

PINNED = {
    "test_3": "fixtures/test_3.json",
    "gemini_clean": "fixtures/gemini_clean.json",
}


def load_pin(name):
    fixture = json.loads((REPO_ROOT / PINNED[name]).read_text(encoding="utf-8"))
    return fixture["video"], fixture["expect"]


class IngestPinAgreementTest(unittest.TestCase):
    def check_against_pins(self, name):
        video, expect = load_pin(name)
        require_smoke(REPO_ROOT / video)
        record = inspect_media(REPO_ROOT / video)
        self.assertTrue(record.valid)
        self.assertEqual(record.source_sha256, expect["sha256"])
        self.assertEqual(record.container, "mp4")
        self.assertEqual(record.codec, expect["codec"])
        self.assertEqual(record.width, expect["width"])
        self.assertEqual(record.height, expect["height"])
        self.assertEqual(record.frame_count, expect["frames"])
        self.assertEqual(record.video_stream_count, 1)
        self.assertEqual(record.audio_stream_count, 1 if expect["has_audio"] else 0)
        self.assertIsNotNone(record.duration_seconds)
        self.assertLessEqual(abs(record.duration_seconds - expect["duration_s"]),
                             expect["duration_tol_s"])
        self.assertIsNone(record.nominal_frame_rate)
        self.assertIsNone(record.pixel_format)
        self.assertIsNone(record.processing_copy_path)
        self.assertIsNone(record.processing_copy_sha256)
        self.assertIsNotNone(record.time_base)
        numerator, _, denominator = record.time_base.partition("/")
        self.assertEqual((numerator, denominator.isdigit() and int(denominator) > 0),
                         ("1", True))
        self.assertEqual(MediaMetadata.from_dict(record.to_dict()), record)
        return record

    def test_test3_matches_pins(self):
        record = self.check_against_pins("test_3")
        self.assertEqual([warning.code for warning in record.warnings], ["W_VFR_TIMING"])

    def test_gemini_matches_pins(self):
        record = self.check_against_pins("gemini_clean")
        self.assertEqual(list(record.warnings), [])

    def test_source_path_recorded_as_given(self):
        require_smoke(Path("Smoke/test_3.mp4"))
        record = inspect_media("Smoke/test_3.mp4")
        self.assertEqual(record.source_path, "Smoke/test_3.mp4")

    def test_provenance_identifies_software_and_bytes(self):
        require_smoke(REPO_ROOT / "Smoke/test_3.mp4")
        record = inspect_media(REPO_ROOT / "Smoke/test_3.mp4")
        provenance = record.provenance
        self.assertIsNotNone(provenance)
        self.assertEqual(provenance.software_name, "kineticlab")
        self.assertEqual(provenance.input_sha256, record.source_sha256)


class IngestFailureTest(unittest.TestCase):
    def test_missing_file_raises_registered_code(self):
        with self.assertRaises(ContractError) as raised:
            inspect_media(REPO_ROOT / "Smoke/does_not_exist.mp4")
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])
        self.assertEqual(raised.exception.errors[0].field, "source_path")

    def write_temp_bytes(self, payload):
        handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        handle.write(payload)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_garbage_bytes_raise_registered_code(self):
        path = self.write_temp_bytes(b"this is not a video file" + b"\x00" * 100)
        with self.assertRaises(ContractError) as raised:
            inspect_media(path)
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])

    def test_empty_file_raises_registered_code(self):
        path = self.write_temp_bytes(b"")
        with self.assertRaises(ContractError) as raised:
            inspect_media(path)
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])

    def test_truncated_mp4_raises_registered_code(self):
        path = self.write_temp_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16)
        with self.assertRaises(ContractError) as raised:
            inspect_media(path)
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])


if __name__ == "__main__":
    unittest.main()
