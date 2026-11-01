"""Media matrix + stable artifact tests (KL-2.4).

Three data-driven matrices consolidate ingest behavior with exact
expected outcomes per cell — no bare "raises anything":

- media stage (`inspect_media`): real fixtures, full synthetic media
  (CFR/VFR x audio-absent/present), and every invalid shape (garbage,
  empty, truncated, no-moov, no-video-track, multi-video, count
  mismatch, non-MP4 brand, non-h264 codec, missing stsd/mvhd);
- timing stage (`extract_frame_records`): the same files through
  sample-table extraction, pinning counts/validity and the documented
  stage independence (timing needs neither mvhd, stsd, brand, nor
  codec);
- gate stage (`check_frame_table`): valid tables yield pinned reports,
  bad tables yield exact registered codes.

`StableArtifactTest` guards `fixtures/ingest/test_3_frame_table.json`:
regeneration from the real file must be byte-identical, so parser
drift breaks the pin loudly.
"""

import json
import unittest
from pathlib import Path

from kineticlab import __version__
from kineticlab.contracts import (
    ContractError,
    FrameRecord,
    MediaMetadata,
    validate_frame_table,
)
from kineticlab.ingest import (
    check_frame_table,
    extract_frame_records,
    inspect_media,
)
from tests import require_smoke
from tests.test_frame_times import synthetic_mp4, write_temp_bytes
from tests.test_ingest_gates import make_record, missing_record, withdrawn_record

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_3 = REPO_ROOT / "Smoke/test_3.mp4"
ARTIFACT = REPO_ROOT / "fixtures/ingest/test_3_frame_table.json"
TEST_3_PIN = REPO_ROOT / "fixtures/test_3.json"

FULL_MEDIA = {"with_mvhd": True, "width": 320, "height": 240}
GARBAGE = b"this is not a video file" + b"\x00" * 100
TRUNCATED_FTYP = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16

# (name, source, expectation). Source is ("file", path), ("synthetic",
# kwargs), ("raw", bytes), or ("missing", path). Expectation is ("ok",
# {pins}) or ("raise", [codes], field-or-None); multi-code cells compare
# sorted multisets.
MEDIA_CELLS = [
    ("real-test3-vfr-audio", ("file", TEST_3),
     ("ok", {"frames": 234, "audio": 1, "codec": "h264",
             "warnings": ["W_VFR_TIMING"]})),
    ("synth-cfr-noaudio", ("synthetic", dict(FULL_MEDIA)),
     ("ok", {"frames": 2, "audio": 0, "codec": "h264", "width": 320,
             "height": 240, "duration": 0.08, "time_base": "1/1000",
             "warnings": []})),
    ("synth-vfr-noaudio", ("synthetic", dict(FULL_MEDIA, stts_entries=((1, 40), (1, 80)))),
     ("ok", {"frames": 2, "audio": 0, "warnings": ["W_VFR_TIMING"]})),
    ("synth-cfr-audio", ("synthetic", dict(FULL_MEDIA, with_audio=True)),
     ("ok", {"frames": 2, "audio": 1, "warnings": []})),
    ("garbage-bytes", ("raw", GARBAGE), ("raise", ["E_NOT_AN_OBJECT"], None)),
    ("empty-file", ("raw", b""), ("raise", ["E_NOT_AN_OBJECT"], None)),
    ("truncated-ftyp", ("raw", TRUNCATED_FTYP), ("raise", ["E_NOT_AN_OBJECT"], None)),
    ("no-moov", ("synthetic", {"include_moov": False}),
     ("raise", ["E_NOT_AN_OBJECT"], None)),
    ("no-video-track", ("synthetic", {"include_video_trak": False,
                                      "with_audio": True, "with_mvhd": True}),
     ("raise", ["E_NOT_AN_OBJECT"], None)),
    ("multi-video-track", ("synthetic", dict(FULL_MEDIA, extra_video_traks=1)),
     ("raise", ["E_OUT_OF_RANGE"], "video_stream_count")),
    ("stsz-stts-mismatch", ("synthetic", dict(FULL_MEDIA, sample_count=3)),
     ("raise", ["E_NOT_AN_OBJECT"], None)),
    ("non-mp4-brand", ("synthetic", dict(FULL_MEDIA, major_brand="qt  ")),
     ("raise", ["E_BAD_ENUM"], "container")),
    ("non-h264-codec", ("synthetic", dict(FULL_MEDIA, sample_format="hev1")),
     ("raise", ["E_BAD_ENUM"], "codec")),
    ("missing-stsd-geometry", ("synthetic", {"with_mvhd": True}),
     ("raise", ["E_NULL_NOT_ALLOWED"] * 3 + ["E_INCOHERENT_VALUE"], None)),
    ("missing-mvhd", ("synthetic", {"width": 320, "height": 240}),
     ("raise", ["E_NOT_AN_OBJECT"], None)),
    ("missing-file", ("missing", REPO_ROOT / "Smoke/does_not_exist.mp4"),
     ("raise", ["E_MISSING_FIELD"], "source_path")),
]

# (name, source, expectation): ("ok", (count, valid)) or ("raise", [codes]).
TIMING_CELLS = [
    ("real-test3", ("file", TEST_3), ("ok", (234, 234))),
    ("synth-uniform", ("synthetic", {}), ("ok", (2, 2))),
    ("synth-vfr", ("synthetic", {"stts_entries": ((1, 40), (1, 80), (1, 40)),
                                          "sample_count": 3, "sizes": (10, 10, 10),
                                          "stsc_runs": ((1, 3, 1),)}),
     ("ok", (3, 3))),
    ("synth-audio-ignored", ("synthetic", {"with_audio": True}), ("ok", (2, 2))),
    ("synth-reorder", ("synthetic", {"ctts_entries": ((1, 80), (1, 0))}), ("ok", (2, 1))),
    ("timing-ignores-brand", ("synthetic", {"major_brand": "qt  "}), ("ok", (2, 2))),
    ("timing-ignores-codec", ("synthetic", {"sample_format": "hev1"}), ("ok", (2, 2))),
    ("timing-needs-no-stsd", ("synthetic", {"with_mvhd": True}), ("ok", (2, 2))),
    ("timing-needs-no-mvhd", ("synthetic", {"width": 320, "height": 240}), ("ok", (2, 2))),
    ("garbage-bytes", ("raw", GARBAGE), ("raise", ["E_NOT_AN_OBJECT"])),
    ("empty-file", ("raw", b""), ("raise", ["E_NOT_AN_OBJECT"])),
    ("no-moov", ("synthetic", {"include_moov": False}), ("raise", ["E_NOT_AN_OBJECT"])),
    ("no-video-track", ("synthetic", {"include_video_trak": False, "with_audio": True}),
     ("raise", ["E_NOT_AN_OBJECT"])),
    ("multi-video-track", ("synthetic", {"extra_video_traks": 1}),
     ("raise", ["E_NOT_AN_OBJECT"])),
    ("stsz-stts-mismatch", ("synthetic", {"sample_count": 3}),
     ("raise", ["E_NOT_AN_OBJECT"])),
    ("truncated-stts", ("synthetic", {"stts_entry_count": 3}),
     ("raise", ["E_NOT_AN_OBJECT"])),
    ("dual-chunk-tables", ("synthetic", {"with_co64": True}),
     ("raise", ["E_NOT_AN_OBJECT"])),
    ("missing-stts", ("synthetic", {"include_stts": False}),
     ("raise", ["E_NOT_AN_OBJECT"])),
]

# (name, table source, expectation): ("report", {...}) or ("raise", [codes]).
# Table source is ("records", [FrameRecord...]), ("file", path), or
# ("synthetic", kwargs) — the latter two extract live, chaining stages.
GATE_CELLS = [
    ("valid-pair", ("records", [make_record(0), make_record(1)]),
     ("report", {"total_frames": 2, "usable_frames": 2, "withdrawn_frames": 0,
                 "missing_frames": 0, "minimum_usable_frames": 2})),
    ("duplicate-processing", ("records", [make_record(0), make_record(
        0, source_frame_index=1, pts_seconds=0.033)]),
     ("raise", ["E_DUPLICATE_FRAME"])),
    ("duplicate-source", ("records", [make_record(0),
                                      make_record(1, source_frame_index=0)]),
     ("raise", ["E_DUPLICATE_FRAME"])),
    ("non-monotonic-pts", ("records", [make_record(0, pts_seconds=0.033),
                                       make_record(1)]),
     ("raise", ["E_NON_MONOTONIC_PTS"])),
    ("null-pts-missing", ("records", [make_record(0), missing_record(1),
                                      make_record(2)]),
     ("raise", ["E_NULL_NOT_ALLOWED"])),
    ("below-floor-single", ("records", [make_record(0)]),
     ("raise", ["E_OUT_OF_RANGE"])),
    ("below-floor-empty", ("records", []), ("raise", ["E_OUT_OF_RANGE"])),
    ("withdrawn-acknowledged", ("records", [make_record(0), make_record(1),
                                            withdrawn_record(2)]),
     ("report", {"total_frames": 3, "usable_frames": 2, "withdrawn_frames": 1,
                 "missing_frames": 0, "minimum_usable_frames": 2})),
    ("real-test3", ("file", TEST_3),
     ("report", {"total_frames": 234, "usable_frames": 234,
                 "withdrawn_frames": 0, "missing_frames": 0,
                 "minimum_usable_frames": 2})),
    ("synth-reorder-chain", ("synthetic", {"stts_entries": ((3, 40),),
                                                  "ctts_entries": ((1, 80), (1, 0), (1, 40)),
                                                  "sample_count": 3,
                                                  "sizes": (10, 10, 10),
                                                  "stsc_runs": ((1, 3, 1),)}),
     ("report", {"total_frames": 3, "usable_frames": 2, "withdrawn_frames": 1,
                 "missing_frames": 0, "minimum_usable_frames": 2})),
]


def resolve_source(testcase, source):
    """Materialize a matrix file source to a path (temp files auto-cleaned)."""
    kind, value = source
    if kind == "file":
        # KL-9.6 B1: a real-clip cell skips (inside its subTest) on
        # clones without Smoke/; ("missing", ...) cells still run —
        # they assert the missing-file behavior itself.
        require_smoke(value)
        return value
    if kind == "missing":
        return value
    payload = synthetic_mp4(**value) if kind == "synthetic" else value
    path = write_temp_bytes(payload)
    testcase.addCleanup(Path(path).unlink)
    return path


class MediaMatrixTest(unittest.TestCase):
    def test_media_matrix(self):
        for name, source, expect in MEDIA_CELLS:
            with self.subTest(cell=name):
                path = resolve_source(self, source)
                if expect[0] == "raise":
                    _, codes, field = expect
                    with self.assertRaises(ContractError) as raised:
                        inspect_media(path)
                    self.assertEqual(sorted(raised.exception.codes), sorted(codes))
                    if field is not None:
                        self.assertEqual(raised.exception.errors[0].field, field)
                    continue
                pins = expect[1]
                record = inspect_media(path)
                self.assertTrue(record.valid)
                self.assertEqual(record.frame_count, pins["frames"])
                self.assertEqual(record.audio_stream_count, pins["audio"])
                self.assertEqual([warning.code for warning in record.warnings],
                                 pins["warnings"])
                if "codec" in pins:
                    self.assertEqual(record.codec, pins["codec"])
                if "width" in pins:
                    self.assertEqual((record.width, record.height),
                                     (pins["width"], pins["height"]))
                if "duration" in pins:
                    self.assertEqual(record.duration_seconds, pins["duration"])
                if "time_base" in pins:
                    self.assertEqual(record.time_base, pins["time_base"])
                self.assertEqual(MediaMetadata.from_dict(record.to_dict()), record)
                # Media frame count agrees with extracted sample count.
                self.assertEqual(len(extract_frame_records(path)), record.frame_count)


class TimingMatrixTest(unittest.TestCase):
    def test_timing_matrix(self):
        for name, source, expect in TIMING_CELLS:
            with self.subTest(cell=name):
                path = resolve_source(self, source)
                if expect[0] == "raise":
                    with self.assertRaises(ContractError) as raised:
                        extract_frame_records(path)
                    self.assertEqual(raised.exception.codes, expect[1])
                    continue
                count, valid = expect[1]
                records = extract_frame_records(path)
                self.assertEqual(len(records), count)
                self.assertEqual(sum(record.valid for record in records), valid)
                validate_frame_table(records)
                for record in records:
                    self.assertEqual(FrameRecord.from_dict(record.to_dict()), record)
                if name == "synth-uniform":
                    gaps = {b.pts_seconds - a.pts_seconds
                            for a, b in zip(records, records[1:])}
                    self.assertEqual(len(gaps), 1)
                if name == "synth-vfr":
                    gaps = {round(b.pts_seconds - a.pts_seconds, 12)
                            for a, b in zip(records, records[1:])}
                    self.assertEqual(len(gaps), 2)
                if name == "synth-reorder":
                    self.assertEqual([warning.code
                                      for warning in records[1].warnings],
                                     ["W_MISSING_FRAMES_RETAINED"])


class GateMatrixTest(unittest.TestCase):
    def test_gate_matrix(self):
        for name, source, expect in GATE_CELLS:
            with self.subTest(cell=name):
                kind, value = source
                if kind == "records":
                    records = value
                else:
                    records = extract_frame_records(resolve_source(self, source))
                if expect[0] == "raise":
                    with self.assertRaises(ContractError) as raised:
                        check_frame_table(records)
                    self.assertEqual(raised.exception.codes, expect[1])
                else:
                    self.assertEqual(check_frame_table(records), expect[1])


class StableArtifactTest(unittest.TestCase):
    ARTIFACT_NOTE = ("Pinned structural measurement by the kineticlab stdlib MP4 "
                     "parser on 2026-10-27. NOT ffprobe ground truth; FFprobe "
                     "re-verification stays a recorded follow-up.")

    def regenerate_envelope(self):
        records = extract_frame_records(TEST_3)
        return {
            "artifact": "test_3_frame_table",
            "source": "Smoke/test_3.mp4",
            "source_sha256": records[0].provenance.input_sha256,
            "measured_utc": "2026-10-27",
            "generator": {"name": "kineticlab", "version": __version__,
                          "function": "extract_frame_records"},
            "provenance_note": self.ARTIFACT_NOTE,
            "frames": [record.to_dict() for record in records],
        }

    def test_artifact_regenerates_byte_identical(self):
        require_smoke(TEST_3)
        expected = (json.dumps(self.regenerate_envelope(), indent=2,
                               sort_keys=True) + "\n").encode("utf-8")
        self.assertEqual(ARTIFACT.read_bytes(), expected)

    def test_artifact_frames_validate_and_gate(self):
        envelope = json.loads(ARTIFACT.read_text(encoding="utf-8"))
        self.assertEqual(envelope["artifact"], "test_3_frame_table")
        self.assertEqual(envelope["measured_utc"], "2026-10-27")
        self.assertIn("NOT ffprobe ground truth", envelope["provenance_note"])
        pin = json.loads(TEST_3_PIN.read_text(encoding="utf-8"))
        self.assertEqual(envelope["source_sha256"], pin["expect"]["sha256"])
        records = [FrameRecord.from_dict(item) for item in envelope["frames"]]
        self.assertEqual(len(records), 234)
        validate_frame_table(records)
        self.assertEqual(check_frame_table(records),
                         {"total_frames": 234, "usable_frames": 234,
                          "withdrawn_frames": 0, "missing_frames": 0,
                          "minimum_usable_frames": 2})


if __name__ == "__main__":
    unittest.main()
