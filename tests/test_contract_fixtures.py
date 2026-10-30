"""File-fixture contract tests (KL-1.3).

Drives `kineticlab.contracts` from `fixtures/contracts/`: valid records
parse and JSON-round-trip, the frame table retains its missing frame,
and every invalid case raises exactly its expected registered codes.
"""

import json
import unittest
from pathlib import Path

from kineticlab.contracts import (
    ERROR_CODES,
    ContractError,
    FrameRecord,
    parse_json,
    validate_frame_table,
)

CONTRACTS_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "contracts"
VALID_SCHEMAS = ["media", "frame", "observation", "calibration", "fit", "result"]


class ContractFixtureTest(unittest.TestCase):
    def test_valid_fixtures_round_trip(self):
        for schema in VALID_SCHEMAS:
            with self.subTest(schema=schema):
                path = CONTRACTS_DIR / f"valid_{schema}.json"
                self.assertTrue(path.is_file(), f"missing {path}")
                record = parse_json(schema, path.read_text(encoding="utf-8"))
                text = json.dumps(record.to_dict())
                self.assertEqual(parse_json(schema, text), record)

    def test_frame_table_retains_missing_frame(self):
        path = CONTRACTS_DIR / "frame_table.json"
        table = json.loads(path.read_text(encoding="utf-8"))
        records = [FrameRecord.from_dict(item) for item in table["frames"]]
        self.assertEqual(len(records), 5)
        retained = [record for record in records if not record.valid]
        self.assertEqual(len(retained), 1)
        self.assertIsNone(retained[0].pts_seconds)
        self.assertIsNone(retained[0].source_frame_index)
        self.assertEqual([warning.code for warning in retained[0].warnings],
                         ["W_MISSING_FRAMES_RETAINED"])
        validate_frame_table(records)

    def test_invalid_cases_raise_exact_codes(self):
        path = CONTRACTS_DIR / "invalid_cases.json"
        cases = json.loads(path.read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(cases), 20, "matrix must stay broad")
        names = [case["name"] for case in cases]
        self.assertEqual(len(names), len(set(names)), "case names must be unique")
        for case in cases:
            with self.subTest(case=case["name"]):
                for key in ("name", "schema", "record", "expect_codes"):
                    self.assertIn(key, case)
                with self.assertRaises(ContractError) as raised:
                    parse_json(case["schema"], json.dumps(case["record"]))
                raised_codes = sorted(raised.exception.codes)
                self.assertEqual(raised_codes, sorted(case["expect_codes"]))
                for code in raised_codes:
                    self.assertIn(code, ERROR_CODES)

    def test_negative_pts_fixture_round_trip(self):
        path = CONTRACTS_DIR / "valid_frame_negative_pts.json"
        record = parse_json("frame", path.read_text(encoding="utf-8"))
        self.assertEqual(record.pts_seconds, -0.033)
        self.assertEqual(parse_json("frame", json.dumps(record.to_dict())), record)

    def test_fixture_set_complete(self):
        for schema in VALID_SCHEMAS:
            self.assertTrue((CONTRACTS_DIR / f"valid_{schema}.json").is_file())
        self.assertTrue((CONTRACTS_DIR / "valid_frame_negative_pts.json").is_file())
        self.assertTrue((CONTRACTS_DIR / "frame_table.json").is_file())
        self.assertTrue((CONTRACTS_DIR / "invalid_cases.json").is_file())
        self.assertTrue((CONTRACTS_DIR / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
