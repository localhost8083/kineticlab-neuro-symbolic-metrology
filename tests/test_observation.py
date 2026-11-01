"""Saved SAM fixture adapter tests (KL-3.1 + KL-3.2 record upgrade).

`parse_raw_fixture` must normalize the real `Smoke/results/*_raw.txt`
vendor lines into contract-shaped `observation.v1` records with
mask-derived centroid/area (one_bit decode + canonical gate; never
bbox centers), join real source PTS from the ingest frame table,
retain the raw file reference and caller-declared version in
provenance, and reject malformed input with exact registered codes
naming the raw file. Valid records carry no warnings; records whose
frame lacks source PTS are retained invalid with geometry decoded,
as are records whose source row was withdrawn (measured PTS kept).

Structural pins below were measured from the Smoke/ bytes on
2026-10-27 (test_3 files: 234 contiguous frames 0..233; uniform
per-file confidence; first-record centroid/area from the decode).
They act as regression pins: identical bytes must yield identical
records.
"""

import hashlib
import tempfile
import unittest
from pathlib import Path

from kineticlab import __version__
from kineticlab.contracts import ContractError, FrameRecord, ObservationRecord
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import (
    find_multisegment_lines,
    parse_raw_fixture,
)
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_3 = REPO_ROOT / "Smoke/test_3.mp4"
BALL_RAW = REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt"
CARD_RAW = REPO_ROOT / "Smoke/results/test_3_white_card_raw.txt"

BALL_CONFIDENCE = 0.9532163739204407
CARD_CONFIDENCE = 0.8947368264198303


def write_temp_text(payload):
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                         mode="w", encoding="utf-8")
    handle.write(payload)
    handle.close()
    return handle.name


def write_temp_bytes(payload):
    handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    handle.write(payload)
    handle.close()
    return handle.name


def first_ball_line():
    require_smoke(BALL_RAW)
    return BALL_RAW.read_text(encoding="utf-8").splitlines()[0]


class RealFixtureAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3, BALL_RAW, CARD_RAW)
        cls.table = extract_frame_records(TEST_3)

    def check_real_file(self, path, role, object_id, confidence):
        records = parse_raw_fixture(path, object_role=role,
                                    object_id=object_id,
                                    frame_table=self.table)
        # Structural pins: 234 contiguous frames 0..233, uniform confidence.
        self.assertEqual(len(records), 234)
        self.assertEqual([record.frame_index for record in records],
                         list(range(234)))
        self.assertTrue(all(record.confidence == confidence for record in records))
        self.assertTrue(all(record.object_role.value == role for record in records))
        self.assertTrue(all(record.object_id == object_id for record in records))
        self.assertTrue(all(record.source.value == "sam_fixture"
                            for record in records))
        # Upgraded by decode: mask-derived centroid/area, valid, no warnings.
        self.assertTrue(all(record.valid is True for record in records))
        self.assertTrue(all(record.warnings == () for record in records))
        for record in records:
            self.assertIsNotNone(record.centroid_x_px)
            self.assertIsNotNone(record.centroid_y_px)
            self.assertIsNotNone(record.mask_area_px)
            self.assertGreater(record.mask_area_px, 0.0)
            self.assertLessEqual(record.mask_area_px,
                                 (record.bbox[2] - record.bbox[0] + 1)
                                 * (record.bbox[3] - record.bbox[1] + 1))
            self.assertGreaterEqual(record.centroid_x_px, record.bbox[0])
            self.assertLessEqual(record.centroid_x_px, record.bbox[2])
            self.assertGreaterEqual(record.centroid_y_px, record.bbox[1])
            self.assertLessEqual(record.centroid_y_px, record.bbox[3])
        # PTS join is exact on every frame.
        for record, frame in zip(records, self.table):
            self.assertEqual(record.pts_seconds, frame.pts_seconds)
        # Provenance retains the raw bytes' identity; version stays null.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        for record in records:
            provenance = record.provenance
            self.assertEqual(provenance.software_name, "kineticlab")
            self.assertEqual(provenance.software_version, __version__)
            self.assertEqual(provenance.input_sha256, digest)
            self.assertIsNone(provenance.model_name)
            self.assertIsNone(provenance.model_version)
            self.assertEqual(list(provenance.raw_refs), [str(path)])
        for record, line_no in zip(records, range(1, 235)):
            self.assertEqual(record.mask_reference, f"{path}#L{line_no}")
            self.assertEqual(ObservationRecord.from_dict(record.to_dict()), record)
        return records

    def test_yellow_ball_normalizes_to_bob(self):
        records = self.check_real_file(BALL_RAW, "bob", "yellow-ball", BALL_CONFIDENCE)
        self.assertEqual(records[0].bbox, (505.0, 321.0, 627.0, 413.0))
        self.assertEqual(records[0].pts_seconds, 0.0)
        self.assertEqual(records[0].mask_area_px, 9566.0)
        self.assertEqual(records[0].centroid_x_px, 565.7674053941041)
        self.assertEqual(records[0].centroid_y_px, 366.6821032824587)

    def test_white_card_normalizes_to_reference_card(self):
        records = self.check_real_file(CARD_RAW, "reference_card", "white-card",
                                       CARD_CONFIDENCE)
        self.assertEqual(records[0].bbox, (131.0, 294.0, 389.0, 461.0))
        self.assertEqual(records[0].mask_area_px, 41572.0)
        self.assertEqual(records[0].centroid_x_px, 260.29820552294814)
        self.assertEqual(records[0].centroid_y_px, 377.77715770229963)

    def test_caller_declared_version_passes_through(self):
        records = parse_raw_fixture(BALL_RAW, object_role="bob",
                                    object_id="yellow-ball",
                                    frame_table=self.table,
                                    model_name="sam-3.1",
                                    model_version="smoke-2026-10-27")
        self.assertEqual(len(records), 234)
        for record in records:
            self.assertEqual(record.provenance.model_name, "sam-3.1")
            self.assertEqual(record.provenance.model_version, "smoke-2026-10-27")

    def test_null_pts_retained_invalid_with_geometry(self):
        row = self.table[0].to_dict()
        row["pts_seconds"] = None
        row["valid"] = False
        null_table = [FrameRecord.from_dict(row)]
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                             mode="w", encoding="utf-8")
        handle.write(first_ball_line() + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        records = parse_raw_fixture(handle.name, object_role="bob",
                                    object_id="bob-1", frame_table=null_table)
        self.assertEqual(len(records), 1)
        self.assertIs(records[0].valid, False)
        self.assertEqual([warning.code for warning in records[0].warnings],
                         ["W_MISSING_FRAMES_RETAINED"])
        self.assertEqual(records[0].mask_area_px, 9566.0)
        self.assertEqual(records[0].centroid_x_px, 565.7674053941041)

    def test_withdrawn_timed_frame_invalid_with_pts_retained(self):
        row = self.table[0].to_dict()
        row["valid"] = False
        withdrawn_table = [FrameRecord.from_dict(row)]
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                             mode="w", encoding="utf-8")
        handle.write(first_ball_line() + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        records = parse_raw_fixture(handle.name, object_role="bob",
                                    object_id="bob-1",
                                    frame_table=withdrawn_table)
        self.assertEqual(len(records), 1)
        self.assertIs(records[0].valid, False)
        self.assertEqual(records[0].pts_seconds, 0.0)
        self.assertEqual([warning.code for warning in records[0].warnings],
                         ["W_MISSING_FRAMES_RETAINED"])
        self.assertIn("withdrawn", records[0].warnings[0].detail)
        self.assertEqual(records[0].mask_area_px, 9566.0)


class AdapterFailureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3)
        cls.table = extract_frame_records(TEST_3)

    def temp_path(self, payload):
        path = write_temp_text(payload)
        self.addCleanup(Path(path).unlink)
        return path

    def parse_text(self, payload, **kwargs):
        path = self.temp_path(payload)
        arguments = {"object_role": "bob", "object_id": "bob-1",
                     "frame_table": self.table}
        arguments.update(kwargs)
        return path, arguments

    def assert_fails(self, payload, codes, field=None, **kwargs):
        path, arguments = self.parse_text(payload, **kwargs)
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(path, **arguments)
        self.assertEqual(raised.exception.codes, codes)
        if field is not None:
            self.assertEqual(raised.exception.errors[0].field, field)
        for error in raised.exception.errors:
            self.assertIn(str(path), error.message)
        return path

    def test_garbage_line_has_no_frame_marker(self):
        self.assert_fails("hello world\n", ["E_MISSING_FIELD"], "frame_index")

    def test_truncated_line_lacks_mask_segment(self):
        line = first_ball_line()
        cut = line[:line.index(";x2=")]
        self.assert_fails(cut + "\n", ["E_MISSING_FIELD"], "mask_reference")

    def test_dropped_box_key_rejected(self):
        line = first_ball_line().replace(";x2=627", "")
        self.assert_fails(line + "\n", ["E_MISSING_FIELD"], "bbox")

    def test_dropped_mask_data_rejected(self):
        line = first_ball_line()
        head, _, _ = line.partition(";data=")
        self.assert_fails(head + "|>\n", ["E_MISSING_FIELD"], "mask_reference")

    def test_multisegment_line_rejected_with_delimiter_code(self):
        # Backstop (kept by KL-9.2 item 2): a second box segment on
        # one line fails canonical parsing with E_NOT_AN_OBJECT.
        line = first_ball_line()
        double = (line + "|><|box;x1=936;y1=503;x2=995;y2=719;c=0.75")
        path, arguments = self.parse_text(double + "\n")
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(path, **arguments)
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        self.assertEqual(raised.exception.errors[0].field, "line 1")
        self.assertIn("extra segment delimiters",
                      raised.exception.errors[0].message)

    def test_multisegment_scan_flags_exactly_bad_lines(self):
        # The detect-stage pre-validation mirror: flags exactly the
        # lines the canonical parser would reject for extra
        # delimiters, and nothing else.
        good = first_ball_line()
        bad = good + "|><|box;x1=936;y1=503;x2=995;y2=719;c=0.75"
        self.assertEqual(find_multisegment_lines(good + "\n"), [])
        self.assertEqual(
            find_multisegment_lines(good + "\n" + bad + "\n"), [2])
        self.assertEqual(find_multisegment_lines("hello world\n"), [])
        self.assertEqual(find_multisegment_lines("<0f>0<|nope\n"), [])
        self.assertEqual(find_multisegment_lines(""), [])

    def test_empty_version_rejected(self):
        self.assert_fails(first_ball_line() + "\n", ["E_EMPTY_STRING"],
                          "provenance.model_version", model_version="")

    def test_confidence_above_one_rejected(self):
        line = first_ball_line().replace("c=0.9532163739204407", "c=1.5")
        # Full error collection: range violation plus valid-requires-coherence.
        self.assert_fails(line + "\n", ["E_OUT_OF_RANGE", "E_INCOHERENT_VALUE"],
                          "confidence")

    def test_non_numeric_confidence_rejected(self):
        line = first_ball_line().replace("c=0.9532163739204407", "c=abc")
        self.assert_fails(line + "\n", ["E_WRONG_TYPE"], "confidence")

    def test_disordered_bbox_rejected(self):
        line = first_ball_line().replace("x1=505", "x1=999")
        self.assert_fails(line + "\n", ["E_BBOX_ORDER"], "bbox")

    def test_unknown_role_rejected(self):
        # Contract vocabulary is "reference_card": bare "card" must fail.
        self.assert_fails(first_ball_line() + "\n", ["E_BAD_ENUM"],
                          "object_role", object_role="card")

    def test_empty_object_id_rejected(self):
        self.assert_fails(first_ball_line() + "\n", ["E_EMPTY_STRING"],
                          "object_id", object_id="")

    def test_frame_without_source_match_rejected(self):
        line = first_ball_line().replace("<0f>", "<999f>", 1)
        self.assert_fails(line + "\n", ["E_OUT_OF_RANGE"], "frame_index")

    def test_empty_table_matches_nothing(self):
        self.assert_fails(first_ball_line() + "\n", ["E_OUT_OF_RANGE"],
                          "frame_index", frame_table=[])

    def test_confidence_disagreement_rejected(self):
        line = first_ball_line().replace("c=0.9532163739204407", "c=0.5", 1)
        self.assert_fails(line + "\n", ["E_INCOHERENT_VALUE"], "confidence")

    def test_mixed_tracks_rejected(self):
        first = first_ball_line()
        second = first.replace("<0f>0<|", "<1f>2<|", 1)
        self.assert_fails(first + "\n" + second + "\n",
                          ["E_INCOHERENT_VALUE"], "object_id")

    def test_duplicate_table_index_rejected(self):
        table = [self.table[0], self.table[0]]
        self.assert_fails(first_ball_line() + "\n", ["E_DUPLICATE_FRAME"],
                          "frame_index=0", frame_table=table)

    def test_repeated_raw_marker_rejected(self):
        line = first_ball_line()
        path = self.temp_path(line + "\n" + line + "\n")
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(path, object_role="bob", object_id="bob-1",
                              frame_table=self.table)
        self.assertEqual(raised.exception.codes, ["E_DUPLICATE_FRAME"])
        self.assertEqual(raised.exception.errors[0].field, "frame_index")
        self.assertIn("line 2", raised.exception.errors[0].message)

    def test_missing_file_rejected(self):
        missing = REPO_ROOT / "Smoke/results/does_not_exist_raw.txt"
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(missing, object_role="bob", object_id="bob-1",
                              frame_table=self.table)
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])
        self.assertEqual(raised.exception.errors[0].field, "raw_path")

    def test_non_utf8_bytes_rejected(self):
        path = write_temp_bytes(b"<0f>0<|\xff\xfe not text |>")
        self.addCleanup(Path(path).unlink)
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(path, object_role="bob", object_id="bob-1",
                              frame_table=self.table)
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        self.assertEqual(raised.exception.errors[0].field, "raw_path")

    def test_empty_file_parses_to_no_records(self):
        path = self.temp_path("")
        records = parse_raw_fixture(path, object_role="bob", object_id="bob-1",
                                    frame_table=self.table)
        self.assertEqual(records, [])

    def test_blank_lines_carry_no_records(self):
        payload = "\n  \n" + first_ball_line() + "\n\n"
        path = self.temp_path(payload)
        records = parse_raw_fixture(path, object_role="bob", object_id="bob-1",
                                    frame_table=self.table)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].mask_reference, f"{path}#L3")


if __name__ == "__main__":
    unittest.main()
