"""Observation quality reporting tests (KL-4.1, report only).

`build_quality_report` must derive coverage/gaps/jumps/area/shape/
confidence/identity facts as plain data over real chains (test_3
ball/card) plus constructed anomalies — no thresholds, no
verdicts. Every number is pinned as a measured fact; the small
hand-computed case below re-derives each formula independently.

Byte pins use checkout-relative display paths (per the 2026-10-28
rule); quality reports carry frame indices and numbers only, so the
pins are machine-independent either way.
"""

import hashlib
import json
import unittest

from kineticlab.contracts import (
    ContractError,
    FrameRecord,
    ObservationRecord,
)
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture
from kineticlab.result import build_quality_report, export_quality_json
from tests import require_smoke

BALL_DISPLAY = "Smoke/results/test_3_yellow_ball_raw.txt"
CARD_DISPLAY = "Smoke/results/test_3_white_card_raw.txt"
TEST_3_DISPLAY = "Smoke/test_3.mp4"

BALL_REPORT_SHA = "e81b234630649ecad51173f5a11329de73098d8d0069fe66a17ef63550f6a756"
CARD_REPORT_SHA = "d2f65047cb0729711bdf162b23d2884e0c24b88014e0dcac2611db6947c39a54"


def make_frame(index, pts):
    return FrameRecord.from_dict({
        "schema_version": "frame.v1",
        "frame_index": index,
        "source_frame_index": index,
        "pts_seconds": pts,
        "duration_seconds": None,
        "decoded_reference": f"d{index}",
        "valid": True,
        "warnings": [],
        "provenance": None,
    })


def make_observation(frame_index, pts, confidence, bbox, centroid, area,
                     valid, warnings, object_id="b"):
    centroid_x, centroid_y = centroid
    return ObservationRecord.from_dict({
        "schema_version": "observation.v1",
        "frame_index": frame_index,
        "pts_seconds": pts,
        "object_role": "bob",
        "object_id": object_id,
        "confidence": confidence,
        "bbox": list(bbox) if bbox is not None else None,
        "centroid_x_px": centroid_x,
        "centroid_y_px": centroid_y,
        "mask_area_px": area,
        "mask_reference": f"m{frame_index}",
        "valid": valid,
        "source": "sam_fixture",
        "warnings": [{"code": code, "detail": detail}
                     for code, detail in warnings],
        "provenance": None,
    })


class ChainReportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3_DISPLAY, BALL_DISPLAY, CARD_DISPLAY)
        test_3_table = extract_frame_records(TEST_3_DISPLAY)
        cls.test_3_table = test_3_table
        cls.ball = parse_raw_fixture(BALL_DISPLAY, object_role="bob",
                                     object_id="yellow-ball",
                                     frame_table=test_3_table)
        cls.card = parse_raw_fixture(CARD_DISPLAY,
                                     object_role="reference_card",
                                     object_id="white-card",
                                     frame_table=test_3_table)

    def check_report(self, table, records, expected_sha):
        report = build_quality_report(table, records)
        payload = export_quality_json(report)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), expected_sha)
        self.assertEqual(export_quality_json(report), payload)
        self.assertEqual(json.loads(payload.decode("utf-8")), report)
        return report

    def test_ball_chain_report_pins(self):
        report = self.check_report(self.test_3_table, self.ball,
                                   BALL_REPORT_SHA)
        self.assertEqual(report["frame_table"]["size"], 234)
        self.assertEqual(report["frame_table"]["valid_count"], 234)
        self.assertEqual(report["coverage"]["observed_count"], 234)
        self.assertEqual(report["coverage"]["valid_count"], 234)
        self.assertEqual(report["coverage"]["invalid_retained"], [])
        self.assertEqual(report["span"],
                         {"first_frame_index": 0, "last_frame_index": 233})
        self.assertEqual(report["gaps"], {"missing_within_span": [], "count": 0})
        self.assertEqual(len(report["jumps"]), 233)
        self.assertTrue(all(jump["frame_delta"] == 1
                            for jump in report["jumps"]))
        distances = [jump["centroid_distance_px"] for jump in report["jumps"]]
        self.assertEqual(min(distances), 0.7577718222333931)
        self.assertEqual(max(distances), 62.62699125713271)
        self.assertEqual(report["area_shape"]["mask_area_px"],
                         {"count": 234, "min": 5417.0, "max": 10551.0,
                          "mean": 7707.8675213675215})
        self.assertEqual(report["area_shape"]["bbox_fill_ratio"],
                         {"count": 234, "min": 0.7716929232308077,
                          "max": 0.8797442244224423,
                          "mean": 0.8106597332066612})
        self.assertEqual(report["confidence"]["present_count"], 234)
        self.assertEqual(report["confidence"]["missing_count"], 0)
        self.assertEqual(report["confidence"]["min"], 0.9532163739204407)
        self.assertEqual(report["identity"]["object_ids"],
                         [{"object_id": "yellow-ball",
                           "frame_indices": list(range(234))}])
        self.assertIs(report["identity"]["id_switch_detectable"], False)

    def test_card_chain_report_pins(self):
        report = self.check_report(self.test_3_table, self.card,
                                   CARD_REPORT_SHA)
        self.assertEqual(report["coverage"]["observed_count"], 234)
        self.assertEqual(report["coverage"]["valid_count"], 234)
        self.assertEqual(report["gaps"]["count"], 0)
        self.assertEqual(len(report["jumps"]), 233)
        distances = [jump["centroid_distance_px"] for jump in report["jumps"]]
        self.assertEqual(min(distances), 0.03637626925342766)
        self.assertEqual(max(distances), 21.175799308562656)
        self.assertEqual(report["area_shape"]["mask_area_px"],
                         {"count": 234, "min": 34616.0, "max": 42880.0,
                          "mean": 40953.86324786325})
        self.assertEqual(report["area_shape"]["bbox_fill_ratio"],
                         {"count": 234, "min": 0.7847831508308962,
                          "max": 0.9659111721611722,
                          "mean": 0.9273837450574174})
        self.assertEqual(report["confidence"]["min"], 0.8947368264198303)


class HandComputedReportTest(unittest.TestCase):
    def test_small_chain_matches_hand_derivation(self):
        table = [make_frame(index, index / 10.0) for index in range(4)]
        records = [
            make_observation(0, 0.0, 0.5, (0.0, 0.0, 3.0, 3.0),
                             (10.0, 20.0), 8.0, True, []),
            make_observation(1, 0.1, 0.75, (0.0, 0.0, 3.0, 3.0),
                             (13.0, 24.0), 12.0, True, []),
            make_observation(3, None, None, None,
                             (13.0, 24.0), 12.0, False,
                             [("W_MISSING_FRAMES_RETAINED", "no pts")]),
        ]
        self.assertEqual(build_quality_report(table, records), {
            "frame_table": {
                "size": 4, "valid_count": 4, "invalid_count": 0,
                "null_pts_count": 0, "frame_indices": [0, 1, 2, 3],
            },
            "coverage": {
                "observed_frame_indices": [0, 1, 3],
                "observed_count": 3, "record_count": 3,
                "valid_count": 2, "invalid_count": 1,
                "invalid_retained": [{
                    "frame_index": 3, "pts_seconds": None,
                    "warning_codes": ["W_MISSING_FRAMES_RETAINED"],
                    "has_geometry": True,
                }],
            },
            "span": {"first_frame_index": 0, "last_frame_index": 3},
            "gaps": {"missing_within_span": [2], "count": 1},
            "jumps": [
                {"from_frame_index": 0, "to_frame_index": 1,
                 "frame_delta": 1, "centroid_distance_px": 5.0},
                {"from_frame_index": 1, "to_frame_index": 3,
                 "frame_delta": 2, "centroid_distance_px": 0.0},
            ],
            "area_shape": {
                "per_frame": [
                    {"frame_index": 0, "mask_area_px": 8.0,
                     "bbox_fill_ratio": 0.5},
                    {"frame_index": 1, "mask_area_px": 12.0,
                     "bbox_fill_ratio": 0.75},
                    {"frame_index": 3, "mask_area_px": 12.0,
                     "bbox_fill_ratio": None},
                ],
                "mask_area_px": {"count": 3, "min": 8.0, "max": 12.0,
                                 "mean": 10.666666666666666},
                "bbox_fill_ratio": {"count": 2, "min": 0.5, "max": 0.75,
                                    "mean": 0.625},
            },
            "confidence": {
                "per_frame": [
                    {"frame_index": 0, "confidence": 0.5},
                    {"frame_index": 1, "confidence": 0.75},
                    {"frame_index": 3, "confidence": None},
                ],
                "present_count": 2, "missing_count": 1,
                "count": 2, "min": 0.5, "max": 0.75, "mean": 0.625,
            },
            "identity": {
                "object_ids": [{"object_id": "b",
                                "frame_indices": [0, 1, 3]}],
                "object_roles": ["bob"],
                "id_switch_detectable": False,
                "note": ("object_id is caller-declared per file, so no "
                         "ID-switch verdict is derivable from one chain; "
                         "per-id frame lists above are the continuity facts"),
            },
        })

    def test_multiple_ids_grouped_without_verdict(self):
        table = [make_frame(index, index / 10.0) for index in range(2)]
        records = [
            make_observation(0, 0.0, 0.5, (0.0, 0.0, 3.0, 3.0),
                             (10.0, 20.0), 8.0, True, [], object_id="b"),
            make_observation(1, 0.1, 0.5, (0.0, 0.0, 3.0, 3.0),
                             (10.0, 20.0), 8.0, True, [], object_id="a"),
        ]
        report = build_quality_report(table, records)
        self.assertEqual(report["identity"]["object_ids"], [
            {"object_id": "a", "frame_indices": [1]},
            {"object_id": "b", "frame_indices": [0]},
        ])
        self.assertIs(report["identity"]["id_switch_detectable"], False)


class ReportAnomalyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3_DISPLAY, BALL_DISPLAY)
        cls.table = extract_frame_records(TEST_3_DISPLAY)
        cls.ball = parse_raw_fixture(BALL_DISPLAY, object_role="bob",
                                     object_id="yellow-ball",
                                     frame_table=cls.table)

    def test_dropped_frame_reports_gap(self):
        records = [record for record in self.ball if record.frame_index != 5]
        report = build_quality_report(self.table, records)
        self.assertEqual(report["coverage"]["observed_count"], 233)
        self.assertEqual(report["gaps"],
                         {"missing_within_span": [5], "count": 1})
        deltas = {(jump["from_frame_index"], jump["to_frame_index"]):
                  jump["frame_delta"] for jump in report["jumps"]}
        self.assertEqual(deltas[(4, 6)], 2)
        self.assertEqual(len(report["jumps"]), 232)

    def test_single_record_chain(self):
        report = build_quality_report(self.table, self.ball[:1])
        self.assertEqual(report["coverage"]["observed_count"], 1)
        self.assertEqual(report["span"],
                         {"first_frame_index": 0, "last_frame_index": 0})
        self.assertEqual(report["gaps"], {"missing_within_span": [], "count": 0})
        self.assertEqual(report["jumps"], [])
        self.assertEqual(report["area_shape"]["mask_area_px"],
                         {"count": 1, "min": 9566.0, "max": 9566.0,
                          "mean": 9566.0})

class ReportSyntheticTest(unittest.TestCase):
    # KL-9.6 B1: pure-synthetic builder checks, moved out of
    # ReportAnomalyTest so they still run on clones without Smoke/.

    def test_empty_chain_valid_empty_report(self):
        report = build_quality_report([], [])
        self.assertEqual(report["coverage"]["observed_count"], 0)
        self.assertEqual(report["span"],
                         {"first_frame_index": None, "last_frame_index": None})
        self.assertEqual(report["gaps"], {"missing_within_span": [], "count": 0})
        self.assertEqual(report["jumps"], [])
        self.assertEqual(report["area_shape"]["mask_area_px"]["count"], 0)
        self.assertIsNone(report["confidence"]["mean"])
        payload = export_quality_json(report)
        self.assertEqual(export_quality_json(report), payload)
        self.assertEqual(json.loads(payload.decode("utf-8")), report)

    def test_malformed_builder_inputs_rejected(self):
        with self.assertRaises(ContractError) as raised:
            build_quality_report("not-a-table", [])
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        with self.assertRaises(ContractError) as raised:
            build_quality_report([], {"not": "a-list"})
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        with self.assertRaises(ContractError) as raised:
            build_quality_report([{"frame_index": 0}], [])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])
        self.assertEqual(raised.exception.errors[0].field, "frame_table[0]")
        with self.assertRaises(ContractError) as raised:
            build_quality_report([], [None])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])
        self.assertEqual(raised.exception.errors[0].field, "records[0]")
        with self.assertRaises(ContractError) as raised:
            export_quality_json([])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])


if __name__ == "__main__":
    unittest.main()
