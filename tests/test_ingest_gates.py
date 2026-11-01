"""Source/copy identity and timing-gate tests (KL-2.3).

`verify_copy_identity` must confirm a claimed processing copy only by
sha256 equality with the source bytes, record confirmed copies in the
media record, keep absent copies null (exactly `inspect_media`), and
fail differing bytes explicitly. `check_frame_table` must gate frame
tables in one deterministic pass — contract rules first (wrapped, never
bypassed), then missing timing, then the usable floor — and acknowledge
withdrawn frames in its report instead of failing them.
"""

import tempfile
import unittest
from pathlib import Path

from kineticlab.contracts import (
    ContractError,
    FrameRecord,
    MediaMetadata,
    validate_frame_table,
)
from kineticlab.ingest import (
    MINIMUM_USABLE_FRAMES,
    check_frame_table,
    extract_frame_records,
    inspect_media,
    verify_copy_identity,
)
from tests import require_smoke
from tests.contract_samples import valid_frame
from tests.test_frame_times import write_temp_bytes

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_3 = REPO_ROOT / "Smoke/test_3.mp4"


def make_record(index, **overrides):
    data = valid_frame(index)
    data.update(overrides)
    return FrameRecord.from_dict(data)


def withdrawn_record(index):
    return make_record(index, valid=False, warnings=[
        {"code": "W_MISSING_FRAMES_RETAINED", "detail": "synthetic withdrawal"}])


def missing_record(index):
    return make_record(index, source_frame_index=None, pts_seconds=None,
                       decoded_reference=None, valid=False, warnings=[
                           {"code": "W_MISSING_FRAMES_RETAINED",
                            "detail": "synthetic missing timing"}])


class CopyIdentityTest(unittest.TestCase):
    def temp_copy_of(self, payload):
        path = write_temp_bytes(payload)
        self.addCleanup(Path(path).unlink)
        return path

    def test_identical_copy_confirmed_and_recorded(self):
        require_smoke(TEST_3)
        copy = self.temp_copy_of(TEST_3.read_bytes())
        record = verify_copy_identity(TEST_3, copy)
        self.assertTrue(record.valid)
        self.assertEqual(record.processing_copy_path, copy)
        self.assertEqual(record.processing_copy_sha256, record.source_sha256)
        self.assertNotIn("W_DERIVED_COPY", [warning.code for warning in record.warnings])
        self.assertEqual(MediaMetadata.from_dict(record.to_dict()), record)

    def test_absent_copy_is_exactly_inspect_media(self):
        require_smoke(TEST_3)
        self.assertEqual(verify_copy_identity(TEST_3, None), inspect_media(TEST_3))
        record = verify_copy_identity(TEST_3)
        self.assertIsNone(record.processing_copy_path)
        self.assertIsNone(record.processing_copy_sha256)

    def test_modified_copy_fails_explicitly(self):
        require_smoke(TEST_3)
        tampered = bytearray(TEST_3.read_bytes())
        tampered[1000] ^= 0xFF
        copy = self.temp_copy_of(bytes(tampered))
        with self.assertRaises(ContractError) as raised:
            verify_copy_identity(TEST_3, copy)
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertEqual(raised.exception.errors[0].field, "processing_copy_path")

    def test_missing_copy_raises_registered_code(self):
        require_smoke(TEST_3)
        with self.assertRaises(ContractError) as raised:
            verify_copy_identity(TEST_3, REPO_ROOT / "Smoke/does_not_exist.mp4")
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])
        self.assertEqual(raised.exception.errors[0].field, "processing_copy_path")

    def test_missing_source_reported_first(self):
        require_smoke(TEST_3)
        copy = self.temp_copy_of(TEST_3.read_bytes())
        with self.assertRaises(ContractError) as raised:
            verify_copy_identity(REPO_ROOT / "Smoke/does_not_exist.mp4", copy)
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])
        self.assertEqual(raised.exception.errors[0].field, "source_path")

    def test_unparseable_source_still_fails_probe(self):
        payload = b"this is not a video file" + b"\x00" * 100
        source = self.temp_copy_of(payload)
        copy = self.temp_copy_of(payload)
        with self.assertRaises(ContractError) as raised:
            verify_copy_identity(source, copy)
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])


class TimingGateTest(unittest.TestCase):
    def test_duplicate_processing_index_rejected(self):
        records = [make_record(0),
                   make_record(0, source_frame_index=1, pts_seconds=0.033)]
        with self.assertRaises(ContractError) as raised:
            check_frame_table(records)
        self.assertEqual(raised.exception.codes, ["E_DUPLICATE_FRAME"])

    def test_duplicate_source_index_rejected(self):
        records = [make_record(0), make_record(1, source_frame_index=0)]
        with self.assertRaises(ContractError) as raised:
            check_frame_table(records)
        self.assertEqual(raised.exception.codes, ["E_DUPLICATE_FRAME"])

    def test_non_monotonic_pts_rejected(self):
        records = [make_record(0, pts_seconds=0.033), make_record(1)]
        with self.assertRaises(ContractError) as raised:
            check_frame_table(records)
        self.assertEqual(raised.exception.codes, ["E_NON_MONOTONIC_PTS"])

    def test_missing_timing_retained_by_contract_rejected_by_gate(self):
        records = [make_record(0), missing_record(1), make_record(2)]
        validate_frame_table(records)  # retention: contract accepts
        with self.assertRaises(ContractError) as raised:
            check_frame_table(records)  # rejection: gate refuses to run
        self.assertEqual(raised.exception.codes, ["E_NULL_NOT_ALLOWED"])
        self.assertEqual(raised.exception.errors[0].field,
                         "frame_index=1.pts_seconds")

    def test_single_usable_frame_below_floor(self):
        with self.assertRaises(ContractError) as raised:
            check_frame_table([make_record(0)])
        self.assertEqual(raised.exception.codes, ["E_OUT_OF_RANGE"])
        self.assertEqual(raised.exception.errors[0].field, "usable_frame_count")

    def test_empty_table_below_floor(self):
        with self.assertRaises(ContractError) as raised:
            check_frame_table([])
        self.assertEqual(raised.exception.codes, ["E_OUT_OF_RANGE"])

    def test_two_usable_frames_meet_floor(self):
        self.assertEqual(MINIMUM_USABLE_FRAMES, 2)
        report = check_frame_table([make_record(0), make_record(1)])
        self.assertEqual(report, {"total_frames": 2, "usable_frames": 2,
                                 "withdrawn_frames": 0, "missing_frames": 0,
                                 "minimum_usable_frames": 2})

    def test_minimum_override_is_honored(self):
        records = [make_record(0), make_record(1)]
        with self.assertRaises(ContractError) as raised:
            check_frame_table(records, minimum_usable_frames=3)
        self.assertEqual(raised.exception.codes, ["E_OUT_OF_RANGE"])

    def test_missing_gate_precedes_usable_floor(self):
        records = [make_record(0), missing_record(1)]
        with self.assertRaises(ContractError) as raised:
            check_frame_table(records)
        self.assertEqual(raised.exception.codes, ["E_NULL_NOT_ALLOWED"])

    def test_withdrawn_frames_acknowledged_not_failed(self):
        records = [make_record(0), make_record(1), withdrawn_record(2)]
        report = check_frame_table(records)
        self.assertEqual(report, {"total_frames": 3, "usable_frames": 2,
                                 "withdrawn_frames": 1, "missing_frames": 0,
                                 "minimum_usable_frames": 2})

    def test_test3_table_passes_all_gates(self):
        require_smoke(TEST_3)
        report = check_frame_table(extract_frame_records(TEST_3))
        self.assertEqual(report, {"total_frames": 234, "usable_frames": 234,
                                 "withdrawn_frames": 0, "missing_frames": 0,
                                 "minimum_usable_frames": 2})


if __name__ == "__main__":
    unittest.main()
