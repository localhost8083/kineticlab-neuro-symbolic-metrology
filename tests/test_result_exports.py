"""Observation export + anomaly replay matrix (KL-3.3).

End-to-end chains (ingest -> adapter -> decode -> export) over the
real fixtures must produce deterministic, lossless JSON and
documented CSV with byte-stable output pinned by sha256. Constructed
anomaly cases (null PTS, corrupt payload, empty input, malformed
JSON) must behave exactly: retained invalid rows where data is
missing, file-level registered failure where data is corrupt, never
a crash, never a silent drop.

The chain tests feed the parser checkout-relative display paths so
``raw_refs`` (carried verbatim into provenance) are identical on any
machine, making the six sha256 byte pins machine-independent; the
export-twice regeneration assertions are the second, redundant half
of the stability contract.
"""

import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from kineticlab.contracts import ContractError, FrameRecord
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture
from kineticlab.result import (
    CSV_COLUMNS,
    export_observations_csv,
    export_observations_json,
    parse_observations_json,
)
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_3 = REPO_ROOT / "Smoke/test_3.mp4"
GEMINI = REPO_ROOT / "Smoke/gemini_generated_video_8eaef52c.mp4"
BALL_RAW = REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt"
CARD_RAW = REPO_ROOT / "Smoke/results/test_3_white_card_raw.txt"
GEMINI_CARD_RAW = REPO_ROOT / "Smoke/results/card_raw.txt"
BALL_DISPLAY = "Smoke/results/test_3_yellow_ball_raw.txt"
CARD_DISPLAY = "Smoke/results/test_3_white_card_raw.txt"
GEMINI_DISPLAY = "Smoke/results/card_raw.txt"

BALL_JSON_SHA = "2e9bc70332139ef922e44755950bb7ba717d7c271d4411d5b73ba2d699d8630b"
BALL_CSV_SHA = "28142b39bfb98ef612716e535012b0fa9cf2f0c335d5e7eb8314b933e71d3e96"
CARD_JSON_SHA = "93ccfef76e3d8ec96026defaf82c0d2c4ab61f07f9750ff448d068928f2f2ab4"
CARD_CSV_SHA = "1b31f7c8a7cf31d0242de7e9cbe5d6f9c658b265ad55adbff254aa19f084031c"
GEMINI_JSON_SHA = "628b50d4377cbcd4cd49f82e78e52b5eb864f6010a8a69d70e80c320168b7785"
GEMINI_CSV_SHA = "d92cc454906f81a6160b6d36fed5e0638c25a807d9b646bc5ea1b397ac19194c"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ChainExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3, GEMINI, BALL_RAW, CARD_RAW,
                      GEMINI_CARD_RAW)
        test_3_table = extract_frame_records(TEST_3)
        gemini_table = extract_frame_records(GEMINI)
        cls.ball = parse_raw_fixture(BALL_DISPLAY, object_role="bob",
                                     object_id="yellow-ball",
                                     frame_table=test_3_table)
        cls.card = parse_raw_fixture(CARD_DISPLAY,
                                     object_role="reference_card",
                                     object_id="white-card",
                                     frame_table=test_3_table)
        cls.gemini = parse_raw_fixture(GEMINI_DISPLAY,
                                       object_role="reference_card",
                                       object_id="card",
                                       frame_table=gemini_table)

    def check_chain(self, records, count, json_sha, csv_sha):
        self.assertEqual(len(records), count)
        payload = export_observations_json(records)
        text = export_observations_csv(records)
        self.assertEqual(sha256_hex(payload), json_sha)
        self.assertEqual(sha256_hex(text.encode("utf-8")), csv_sha)
        self.assertEqual(export_observations_json(records), payload)
        self.assertEqual(export_observations_csv(records), text)
        self.assertEqual(parse_observations_json(payload), records)
        return payload, text

    def test_ball_chain_export_pins(self):
        payload, _ = self.check_chain(self.ball, 234, BALL_JSON_SHA, BALL_CSV_SHA)
        first = json.loads(payload.decode("utf-8"))[0]
        self.assertTrue(first["valid"])
        self.assertEqual(first["warnings"], [])
        self.assertEqual(first["mask_area_px"], 9566.0)
        self.assertEqual(first["centroid_x_px"], 565.7674053941041)
        self.assertEqual(first["centroid_y_px"], 366.6821032824587)

    def test_card_chain_export_pins(self):
        payload, _ = self.check_chain(self.card, 234, CARD_JSON_SHA, CARD_CSV_SHA)
        first = json.loads(payload.decode("utf-8"))[0]
        self.assertTrue(first["valid"])
        self.assertEqual(first["mask_area_px"], 41572.0)
        self.assertEqual(first["centroid_x_px"], 260.29820552294814)
        self.assertEqual(first["centroid_y_px"], 377.77715770229963)

    def test_gemini_chain_counts(self):
        # Measured outcome, documented deliberately: record validity
        # follows the source row's ingest decision (KL-7.5 F2), so
        # the 62-valid / 178-withdrawn table split surfaces here as
        # 60 valid + 178 retained-invalid observations (frames 0/1
        # valid but undetected). Withdrawn rows keep measured PTS.
        payload, _ = self.check_chain(self.gemini, 238, GEMINI_JSON_SHA,
                                      GEMINI_CSV_SHA)
        self.assertEqual(sum(1 for record in self.gemini if record.valid),
                         60)
        self.assertEqual([record.frame_index for record in self.gemini],
                         list(range(2, 240)))
        for record in self.gemini:
            if record.valid:
                self.assertEqual(record.warnings, ())
            else:
                self.assertIsNotNone(record.pts_seconds)
                self.assertEqual([warning.code for warning in record.warnings],
                                 ["W_MISSING_FRAMES_RETAINED"])
        first = json.loads(payload.decode("utf-8"))[0]
        self.assertEqual(first["frame_index"], 2)
        self.assertEqual(first["mask_area_px"], 49852.0)

    def test_csv_column_contract(self):
        text = export_observations_csv(self.ball[:2])
        rows = list(csv.reader(io.StringIO(text)))
        self.assertEqual(rows[0], list(CSV_COLUMNS))
        self.assertEqual(len(rows), 3)
        header = rows[0]
        first = dict(zip(header, rows[1]))
        self.assertEqual(first["schema_version"], "observation.v1")
        self.assertEqual(first["frame_index"], "0")
        self.assertEqual(first["pts_seconds"], "0.0")
        self.assertEqual(first["centroid_x_px"], "565.7674053941041")
        self.assertEqual(first["mask_area_px"], "9566.0")
        self.assertEqual(first["valid"], "true")
        self.assertEqual(first["warning_codes"], "")
        provenance = json.loads(first["provenance_json"])
        self.assertEqual(provenance["software_name"], "kineticlab")
        self.assertEqual(first["bbox_x_min"], "505.0")
        self.assertEqual(first["bbox_y_max"], "413.0")


class AnomalyMatrixTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3, BALL_RAW)
        cls.table = extract_frame_records(TEST_3)
        cls.ball_line = BALL_RAW.read_text(encoding="utf-8").splitlines()[0]

    def null_pts_records(self):
        row = self.table[0].to_dict()
        row["pts_seconds"] = None
        row["valid"] = False
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                             mode="w", encoding="utf-8")
        handle.write(self.ball_line + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return parse_raw_fixture(handle.name, object_role="bob",
                                 object_id="bob-1",
                                 frame_table=[FrameRecord.from_dict(row)])

    def test_null_pts_rows_exported_and_flagged(self):
        records = self.null_pts_records()
        self.assertEqual(len(records), 1)
        self.assertIs(records[0].valid, False)
        payload = export_observations_json(records)
        back = parse_observations_json(payload)
        self.assertEqual(back, records)
        self.assertIs(back[0].valid, False)
        self.assertIsNone(back[0].pts_seconds)
        self.assertEqual([warning.code for warning in back[0].warnings],
                         ["W_MISSING_FRAMES_RETAINED"])
        self.assertEqual(back[0].mask_area_px, 9566.0)
        rows = list(csv.reader(io.StringIO(export_observations_csv(records))))
        flagged = dict(zip(rows[0], rows[1]))
        self.assertEqual(flagged["valid"], "false")
        self.assertEqual(flagged["pts_seconds"], "")
        self.assertEqual(flagged["warning_codes"], "W_MISSING_FRAMES_RETAINED")
        self.assertEqual(flagged["mask_area_px"], "9566.0")

    def test_mixed_validity_distinguishable_without_context(self):
        valid = parse_raw_fixture(BALL_DISPLAY, object_role="bob",
                                  object_id="bob-1",
                                  frame_table=self.table)[:1]
        mixed = valid + self.null_pts_records()
        items = json.loads(export_observations_json(mixed).decode("utf-8"))
        self.assertEqual([item["valid"] for item in items], [True, False])
        self.assertEqual(items[0]["warnings"], [])
        self.assertEqual([warning["code"] for warning in items[1]["warnings"]],
                         ["W_MISSING_FRAMES_RETAINED"])

    def test_corrupt_payload_fails_file_nothing_partial(self):
        head, data = self.ball_line.split(";data=", 1)
        height, width, body = data[:-2].split(",", 2)
        bad = f"{head};data={height},{width}," + body[:4] + "#" + body[5:] + "|>"
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                             mode="w", encoding="utf-8")
        handle.write(bad + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(handle.name, object_role="bob", object_id="bob-1",
                              frame_table=self.table)
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertIn(f"{handle.name}#L1",
                      raised.exception.errors[0].message)
        # The failed parse yields no record list at all: the only
        # writable outcome is a valid empty export, pinned exactly.
        self.assertEqual(export_observations_json([]), b"[]\n")
        self.assertEqual(export_observations_csv([]),
                         ",".join(CSV_COLUMNS) + "\n")

    def test_parse_item_errors_indexed_codes_preserved(self):
        records = parse_raw_fixture(str(BALL_RAW), object_role="bob",
                                    object_id="bob-1",
                                    frame_table=self.table)[:3]
        items = [record.to_dict() for record in records]
        items[1]["confidence"] = 1.5
        tampered = json.dumps(items).encode("utf-8")
        with self.assertRaises(ContractError) as raised:
            parse_observations_json(tampered)
        self.assertEqual(raised.exception.codes,
                         ["E_OUT_OF_RANGE", "E_INCOHERENT_VALUE"])
        self.assertEqual(raised.exception.errors[0].field, "[1].confidence")

class ExportSyntheticTest(unittest.TestCase):
    # KL-9.6 B1: pure-synthetic export checks (no corpus bytes),
    # moved out of AnomalyMatrixTest so they still run on clones
    # without Smoke/.

    def test_empty_export_round_trip(self):
        self.assertEqual(parse_observations_json(b"[]\n"), [])
        self.assertEqual(parse_observations_json("[]"), [])

    def test_parse_rejects_garbage(self):
        with self.assertRaises(ContractError) as raised:
            parse_observations_json(b"\xff\xfe not json")
        self.assertEqual(raised.exception.codes, ["E_MALFORMED_JSON"])
        with self.assertRaises(ContractError) as raised:
            parse_observations_json(b'{"not": "an array"}')
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        with self.assertRaises(ContractError) as raised:
            parse_observations_json(b"[]garbage")
        self.assertEqual(raised.exception.codes, ["E_MALFORMED_JSON"])

    def test_export_rejects_non_records(self):
        with self.assertRaises(ContractError) as raised:
            export_observations_json([{"frame_index": 0}])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])
        with self.assertRaises(ContractError) as raised:
            export_observations_csv([None])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])


if __name__ == "__main__":
    unittest.main()
