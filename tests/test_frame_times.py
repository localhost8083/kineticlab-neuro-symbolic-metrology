"""Per-frame PTS extraction tests (KL-2.2).

`extract_frame_times` / `extract_frame_records` must report real
sample-table timing (stts/ctts/stsz/stsc/stco) in decode order with an
explicit processing -> source -> PTS -> decoded mapping, preserve VFR
and finite negative PTS, retain withdrawn frames, and fail
contradictions with registered codes.

Structural pins below were measured by this stdlib parser on
2026-10-27 from the Smoke/ bytes (no ffprobe in this sandbox);
FFprobe re-verification stays a recorded follow-up. They act as
regression pins: identical bytes must yield identical numbers.
"""

import struct
import tempfile
import unittest
from pathlib import Path

from kineticlab.contracts import (
    ContractError,
    FrameRecord,
    validate_frame_table,
)
from kineticlab.ingest import (
    extract_frame_records,
    extract_frame_times,
    inspect_media,
)
from tests import require_smoke
from tests.contract_samples import valid_frame

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_3 = REPO_ROOT / "Smoke/test_3.mp4"
GEMINI = REPO_ROOT / "Smoke/gemini_generated_video_8eaef52c.mp4"


def write_temp_bytes(payload):
    handle = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    handle.write(payload)
    handle.close()
    return handle.name


def box(box_type, payload):
    return struct.pack(">I4s", 8 + len(payload), box_type.encode("ascii")) + payload


def full_box(box_type, version, payload):
    return box(box_type, bytes([version, 0, 0, 0]) + payload)


def synthetic_mp4(*, timescale=1000, stts_entries=((2, 40),),
                  stts_entry_count=None, include_stts=True,
                  ctts_entries=None, ctts_version=1,
                  sample_count=2, sizes=(10, 10),
                  stsc_runs=((1, 2, 1),), chunk_offsets=(8,),
                  with_co64=False, with_elst=False,
                  major_brand="isom", include_moov=True,
                  include_video_trak=True, with_mvhd=False,
                  mvhd_timescale=1000, mvhd_duration=80,
                  width=None, height=None, sample_format="avc1",
                  with_audio=False, extra_video_traks=0):
    """Build minimal MP4 bytes with a controllable sample table (KL-2.4: tracks/mvhd/stsd)."""
    if (width is None) != (height is None):
        raise ValueError("width and height must be set together")
    mdhd = full_box("mdhd", 0, struct.pack(">IIII", 0, 0, timescale, 100000))
    hdlr = box("hdlr", b"\x00" * 8 + b"vide")
    stbl_children = b""
    if width is not None:
        entry = (struct.pack(">I4s", 86, sample_format.encode("ascii"))
                 + b"\x00" * 24 + struct.pack(">HH", width, height)
                 + b"\x00" * 50)
        stbl_children += full_box("stsd", 0, struct.pack(">I", 1) + entry)
    if include_stts:
        stts_payload = struct.pack(">I", len(stts_entries) if stts_entry_count is None
                                   else stts_entry_count)
        for count, delta in stts_entries:
            stts_payload += struct.pack(">II", count, delta)
        stbl_children += full_box("stts", 0, stts_payload)
    if ctts_entries is not None:
        ctts_payload = struct.pack(">I", len(ctts_entries))
        offset_pack = ">i" if ctts_version == 1 else ">I"
        for count, offset in ctts_entries:
            ctts_payload += struct.pack(">I", count) + struct.pack(offset_pack, offset)
        stbl_children += full_box("ctts", ctts_version, ctts_payload)
    stsz_payload = struct.pack(">II", 0, sample_count)
    for size in sizes:
        stsz_payload += struct.pack(">I", size)
    stbl_children += full_box("stsz", 0, stsz_payload)
    stsc_payload = struct.pack(">I", len(stsc_runs))
    for first_chunk, per_chunk, desc_id in stsc_runs:
        stsc_payload += struct.pack(">III", first_chunk, per_chunk, desc_id)
    stbl_children += full_box("stsc", 0, stsc_payload)
    stco_payload = struct.pack(">I", len(chunk_offsets))
    for offset in chunk_offsets:
        stco_payload += struct.pack(">I", offset)
    stbl_children += full_box("stco", 0, stco_payload)
    if with_co64:
        stbl_children += full_box("co64", 0, struct.pack(">IQ", 1, 8))
    trak_children = b""
    if with_elst:
        elst = full_box("elst", 0, struct.pack(">IIiI", 1, 500, 200, 0x10000))
        trak_children += box("edts", elst)
    trak_children += box("mdia", mdhd + hdlr + box("minf", box("stbl", stbl_children)))
    ftyp = box("ftyp", major_brand.encode("ascii") + b"\x00\x00\x00\x00isom")
    if not include_moov:
        return ftyp
    moov_children = b""
    if with_mvhd:
        moov_children += full_box(
            "mvhd", 0, struct.pack(">IIII", 0, 0, mvhd_timescale, mvhd_duration))
    if include_video_trak:
        moov_children += box("trak", trak_children)
    if with_audio:
        audio_mdia = (box("hdlr", b"\x00" * 8 + b"soun") + box("minf", b""))
        moov_children += box("trak", box("mdia", audio_mdia))
    for _ in range(extra_video_traks):
        extra_mdia = (box("hdlr", b"\x00" * 8 + b"vide") + box("minf", b""))
        moov_children += box("trak", box("mdia", extra_mdia))
    return ftyp + box("moov", moov_children)


class RealFixtureTimingTest(unittest.TestCase):
    def test_test3_yields_234_strictly_increasing_vfr_frames(self):
        require_smoke(TEST_3)
        entries = extract_frame_times(TEST_3)
        # Structural pins: 234 samples, timescale 90000, no ctts/elst.
        self.assertEqual(len(entries), 234)
        self.assertTrue(all(entry["valid"] for entry in entries))
        pts = [entry["pts_seconds"] for entry in entries]
        self.assertTrue(all(later > earlier for earlier, later in zip(pts, pts[1:])))
        self.assertEqual(pts[0], 0.0)  # 0 / 90000
        self.assertEqual(pts[-1], 7.8319777777777775)  # 704878 / 90000
        gaps = {round(later - earlier, 12) for earlier, later in zip(pts, pts[1:])}
        self.assertGreater(len(gaps), 1)  # VFR: deltas 2999 and 9110 units
        for index, entry in enumerate(entries):
            self.assertEqual(entry["frame_index"], index)
            self.assertEqual(entry["source_frame_index"], index)

    def test_gemini_yields_240_frames_with_reorder_withdrawals(self):
        require_smoke(GEMINI)
        entries = extract_frame_times(GEMINI)
        # Structural pins: 240 samples, timescale 12288, ctts present.
        self.assertEqual(len(entries), 240)
        pts = [entry["pts_seconds"] for entry in entries]
        self.assertEqual(pts[0], 0.08333333333333333)  # 1024 / 12288
        self.assertEqual(pts[-1], 10.0)  # 122880 / 12288
        self.assertEqual(max(pts), 10.041666666666666)
        valid_pts = [entry["pts_seconds"] for entry in entries if entry["valid"]]
        self.assertEqual(len(valid_pts), 62)  # B-frame reorder withdraws the rest
        self.assertTrue(all(later > earlier
                            for earlier, later in zip(valid_pts, valid_pts[1:])))
        for index, entry in enumerate(entries):
            self.assertEqual(entry["frame_index"], index)

    def test_frame_count_agrees_with_media_record(self):
        for path in (TEST_3, GEMINI):
            with self.subTest(path=path.name):
                require_smoke(path)
                media = inspect_media(path)
                self.assertEqual(len(extract_frame_times(path)), media.frame_count)


class FrameRecordTableTest(unittest.TestCase):
    def check_table(self, path, valid_count):
        require_smoke(path)
        records = extract_frame_records(path)
        self.assertEqual([record.frame_index for record in records],
                         list(range(len(records))))
        validate_frame_table(records)  # must pass on the returned table
        self.assertEqual(sum(record.valid for record in records), valid_count)
        for record in records:
            self.assertEqual(FrameRecord.from_dict(record.to_dict()), record)
            self.assertIsNone(record.duration_seconds)
            self.assertEqual(record.decoded_reference,
                             f"sample:{record.frame_index}")
            self.assertIsNotNone(record.provenance)
        media = inspect_media(path)
        for record in records:
            self.assertEqual(record.provenance.input_sha256, media.source_sha256)
        return records

    def test_test3_table_fully_valid(self):
        records = self.check_table(TEST_3, 234)
        self.assertTrue(all(list(record.warnings) == [] for record in records))

    def test_gemini_withdrawn_frames_retained_with_values_and_warning(self):
        records = self.check_table(GEMINI, 62)
        withdrawn = [record for record in records if not record.valid]
        self.assertTrue(withdrawn)
        for record in withdrawn:
            # Measured values stay for audit; only the valid flag is withdrawn.
            self.assertIsNotNone(record.source_frame_index)
            self.assertIsNotNone(record.pts_seconds)
            self.assertEqual([warning.code for warning in record.warnings],
                             ["W_MISSING_FRAMES_RETAINED"])


class SyntheticSampleTableTest(unittest.TestCase):
    def extract(self, payload):
        path = write_temp_bytes(payload)
        self.addCleanup(Path(path).unlink)
        return extract_frame_times(path)

    def test_no_ctts_pts_equals_dts(self):
        entries = self.extract(synthetic_mp4())
        self.assertEqual([(entry["pts_seconds"], entry["valid"]) for entry in entries],
                         [(0.0, True), (0.04, True)])

    def test_signed_ctts_v1_negative_pts_preserved(self):
        entries = self.extract(synthetic_mp4(ctts_entries=((1, -80), (1, 0))))
        # PTS units [-80, 40] at timescale 1000: strictly increasing,
        # finite negative first PTS preserved, never clamped or shifted.
        self.assertEqual([(entry["pts_seconds"], entry["valid"]) for entry in entries],
                         [(-0.08, True), (0.04, True)])

    def test_reordered_pts_withdrawn_but_retained(self):
        path = write_temp_bytes(synthetic_mp4(ctts_entries=((1, 80), (1, 0))))
        self.addCleanup(Path(path).unlink)
        records = extract_frame_records(path)
        validate_frame_table(records)
        self.assertEqual([(record.pts_seconds, record.valid) for record in records],
                         [(0.08, True), (0.04, False)])
        self.assertEqual(records[1].source_frame_index, 1)
        self.assertEqual([warning.code for warning in records[1].warnings],
                         ["W_MISSING_FRAMES_RETAINED"])

    def test_edit_list_is_ignored_not_applied(self):
        plain = self.extract(synthetic_mp4())
        with_list = self.extract(synthetic_mp4(with_elst=True))
        self.assertEqual(with_list, plain)

    def test_exact_integer_comparison_decides_validity(self):
        entries = self.extract(synthetic_mp4(
            timescale=90000, stts_entries=((2, 1),), sizes=(10, 10)))
        # One-unit gap (~11.1us) is still strictly increasing.
        self.assertEqual([entry["valid"] for entry in entries], [True, True])
        self.assertGreater(entries[1]["pts_seconds"], entries[0]["pts_seconds"])


class FrameTimingFailureTest(unittest.TestCase):
    def extract_path(self, payload):
        path = write_temp_bytes(payload)
        self.addCleanup(Path(path).unlink)
        return path

    def test_missing_file_raises_registered_code(self):
        with self.assertRaises(ContractError) as raised:
            extract_frame_times(REPO_ROOT / "Smoke/does_not_exist.mp4")
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])

    def test_missing_file_records_raise_registered_code(self):
        with self.assertRaises(ContractError) as raised:
            extract_frame_records(REPO_ROOT / "Smoke/does_not_exist.mp4")
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])

    def assert_not_an_object(self, payload):
        with self.assertRaises(ContractError) as raised:
            extract_frame_times(self.extract_path(payload))
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        self.assertEqual(raised.exception.errors[0].field, "source_path")

    def test_garbage_bytes_raise_registered_code(self):
        self.assert_not_an_object(b"this is not a video file" + b"\x00" * 100)

    def test_truncated_stts_raises_registered_code(self):
        payload = synthetic_mp4(stts_entries=((2, 40),), stts_entry_count=3)
        self.assert_not_an_object(payload)

    def test_sample_count_mismatch_raises_registered_code(self):
        payload = synthetic_mp4(sample_count=3)
        self.assert_not_an_object(payload)

    def test_dual_chunk_offset_tables_raise_registered_code(self):
        payload = synthetic_mp4(with_co64=True)
        self.assert_not_an_object(payload)

    def test_out_of_range_chunk_offset_raises_registered_code(self):
        payload = synthetic_mp4(chunk_offsets=(10 ** 9,))
        self.assert_not_an_object(payload)

    def test_missing_stts_raises_registered_code(self):
        payload = synthetic_mp4(include_stts=False)
        self.assert_not_an_object(payload)


class ValidateFrameTableTest(unittest.TestCase):
    def test_duplicate_source_index_rejected(self):
        first = valid_frame(0)
        second = valid_frame(1)
        second["source_frame_index"] = 0
        records = [FrameRecord.from_dict(first), FrameRecord.from_dict(second)]
        with self.assertRaises(ContractError) as raised:
            validate_frame_table(records)
        self.assertIn("E_DUPLICATE_FRAME", raised.exception.codes)

    def test_non_monotonic_pts_rejected(self):
        first = valid_frame(0)
        second = valid_frame(1)
        second["pts_seconds"] = 0.0
        records = [FrameRecord.from_dict(first), FrameRecord.from_dict(second)]
        with self.assertRaises(ContractError) as raised:
            validate_frame_table(records)
        self.assertIn("E_NON_MONOTONIC_PTS", raised.exception.codes)

    def test_duplicate_processing_index_rejected(self):
        records = [FrameRecord.from_dict(valid_frame(0)),
                   FrameRecord.from_dict(valid_frame(0))]
        with self.assertRaises(ContractError) as raised:
            validate_frame_table(records)
        self.assertIn("E_DUPLICATE_FRAME", raised.exception.codes)

    def test_invalid_frames_skipped_but_retained(self):
        kept = valid_frame(0)
        missing = valid_frame(1)
        missing.update({"source_frame_index": None, "pts_seconds": None,
                        "decoded_reference": None, "valid": False,
                        "warnings": [{"code": "W_MISSING_FRAMES_RETAINED",
                                      "detail": "synthetic withdrawal"}]})
        resumed = valid_frame(2)
        records = [FrameRecord.from_dict(data)
                   for data in (kept, missing, resumed)]
        validate_frame_table(records)  # must not raise
        self.assertEqual(len(records), 3)


class StszBoundTests(unittest.TestCase):
    """Uniform-stsz counts bound before allocation (KL-9.6 M8)."""

    def test_oversized_uniform_count_raises_without_allocation(self):
        from kineticlab.ingest.mp4 import ProbeError, _read_stsz

        data = b"\x00" * 4 + struct.pack(">II", 100, 4000000000)
        # A 4-billion-element list would need ~32 GiB: this test
        # returning at all proves the bound fired before any
        # allocation (same ProbeError style as the per-sample path).
        with self.assertRaises(ProbeError) as raised:
            _read_stsz(data, 0, len(data))
        self.assertIn("exceeds file size", str(raised.exception))

    def test_legitimate_uniform_table_still_parses(self):
        from kineticlab.ingest.mp4 import _read_stsz

        data = b"\x00" * 4 + struct.pack(">II", 100, 3)
        count, sizes = _read_stsz(data, 0, len(data))
        self.assertEqual((count, sizes), (3, [100, 100, 100]))


if __name__ == "__main__":
    unittest.main()
