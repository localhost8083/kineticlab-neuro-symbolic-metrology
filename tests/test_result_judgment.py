"""Threshold judgment + trajectory/overlay tests (KL-4.2).

`assess_chain` must classify KL-4.1 reports with named, rationale-
backed thresholds (no new codes); trajectory CSV and SVG overlay
must be deterministic and byte-pinned. Real chains are expected
fit-worthy; constructed negatives (teleport, collapse, missing
PTS) must come out flagged with reasons — never silently passing,
never crashing. Display paths only in pins (2026-10-28 rule);
trajectory/overlay bytes carry no paths at all.
"""

import hashlib
import unittest

from kineticlab.contracts import (
    ContractError,
    FrameRecord,
    ObservationRecord,
)
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture
from kineticlab.result import (
    TRAJECTORY_COLUMNS,
    assess_chain,
    build_quality_report,
    export_overlay_svg,
    export_trajectory_csv,
)
from tests import require_smoke

BALL_DISPLAY = "Smoke/results/test_3_yellow_ball_raw.txt"
CARD_DISPLAY = "Smoke/results/test_3_white_card_raw.txt"
GEMINI_DISPLAY = "Smoke/results/card_raw.txt"
TEST_3_DISPLAY = "Smoke/test_3.mp4"
GEMINI_MEDIA_DISPLAY = "Smoke/gemini_generated_video_8eaef52c.mp4"
TEST_3_DIMS = (1024, 576)
GEMINI_DIMS = (1280, 720)

BALL_TRAJ_SHA = "f079b1215729b8510ec9f278ab9031845952e6ecfd16e67f2f206a662d9692d1"
BALL_SVG_SHA = "e4733c82b41c55637acb949b03bb37594be74c9498ddee174101b4e1d93a33ad"
CARD_TRAJ_SHA = "140a5487c8b2d3459bcfb9217a028e516ce2d868013726571dc093760a012714"
CARD_SVG_SHA = "afcf69951302ef084221d1f7307525728e507cd1a28da1cfd88ae65c442922a1"
GEMINI_TRAJ_SHA = "1c8ed630ea72d4da45c73590b757cd609d1794cb106a3c7f36389ec0b94cda88"
GEMINI_SVG_SHA = "fbc926c97a91a7dd697da6d8dc9e394bbdfb9d59afceb092a131e4080fbc9508"


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
                     valid=True, warnings=(), object_id="b"):
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


class ChainJudgmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(TEST_3_DISPLAY, GEMINI_MEDIA_DISPLAY,
                      BALL_DISPLAY, CARD_DISPLAY, GEMINI_DISPLAY)
        test_3_table = extract_frame_records(TEST_3_DISPLAY)
        gemini_table = extract_frame_records(GEMINI_MEDIA_DISPLAY)
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
        cls.ball_report = build_quality_report(test_3_table, cls.ball)
        cls.card_report = build_quality_report(test_3_table, cls.card)
        cls.gemini_report = build_quality_report(gemini_table, cls.gemini)

    def check_fit_worthy(self, records, report, dims, label,
                         traj_sha, svg_sha):
        assessment = assess_chain(report, records)
        self.assertTrue(assessment["assessable"])
        self.assertFalse(assessment["flagged"])
        self.assertTrue(assessment["fit_worthy"])
        self.assertEqual(assessment["reasons"], [])
        for dimension in assessment["dimensions"].values():
            self.assertTrue(dimension["assessable"])
            self.assertEqual(dimension["flagged_count"], 0)
        text = export_trajectory_csv(records, assessment)
        art = export_overlay_svg(records, dims[0], dims[1], assessment,
                                 label=label)
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(),
                         traj_sha)
        self.assertEqual(hashlib.sha256(art).hexdigest(), svg_sha)
        self.assertEqual(export_trajectory_csv(records, assessment), text)
        self.assertEqual(export_overlay_svg(records, dims[0], dims[1],
                                            assessment, label=label), art)
        return assessment, text, art

    def test_ball_fit_worthy_with_pins(self):
        _, text, art = self.check_fit_worthy(
            self.ball, self.ball_report, TEST_3_DIMS, "ball",
            BALL_TRAJ_SHA, BALL_SVG_SHA)
        lines = text.splitlines()
        self.assertEqual(lines[0], ",".join(TRAJECTORY_COLUMNS))
        self.assertEqual(len(lines), 235)
        self.assertEqual(
            lines[1],
            "0,0.0,565.7674053941041,366.6821032824587,9566.0,"
            f"{9566.0 / 11439.0},0.9532163739204407,,false,false")
        self.assertIn(b'viewBox="0 0 1024 576"', art)
        self.assertIn(b"fit_worthy", art)
        self.assertIn(b"<polyline", art)

    def test_card_fit_worthy_with_pins(self):
        self.check_fit_worthy(self.card, self.card_report, TEST_3_DIMS,
                              "card", CARD_TRAJ_SHA, CARD_SVG_SHA)

    def test_gemini_flagged_not_fit_worthy_with_pins(self):
        # KL-7.5 F2: 178 withdrawn-sourced records are invalid, so the
        # gemini chain is honestly flagged and not fit-worthy — the
        # complete-but-warning counterpart to the fit-worthy chains.
        assessment = assess_chain(self.gemini_report, self.gemini)
        self.assertTrue(assessment["assessable"])
        self.assertTrue(assessment["flagged"])
        self.assertFalse(assessment["fit_worthy"])
        self.assertEqual(assessment["reasons"],
                         ["178 retained invalid row(s)"])
        for dimension in assessment["dimensions"].values():
            self.assertTrue(dimension["assessable"])
            self.assertEqual(dimension["flagged_count"], 0)
        text = export_trajectory_csv(self.gemini, assessment)
        art = export_overlay_svg(self.gemini, GEMINI_DIMS[0], GEMINI_DIMS[1],
                                 assessment, label="gemini")
        self.assertEqual(hashlib.sha256(text.encode("utf-8")).hexdigest(),
                         GEMINI_TRAJ_SHA)
        self.assertEqual(hashlib.sha256(art).hexdigest(), GEMINI_SVG_SHA)
        self.assertEqual(len(text.splitlines()), 239)

class OverlaySyntheticTest(unittest.TestCase):
    # KL-9.6 B1: pure-synthetic empty-chain check, moved out of
    # ChainJudgmentTest so it still runs on clones without Smoke/.

    def test_overlay_empty_chain_valid_svg(self):
        assessment = assess_chain(build_quality_report([], []), [])
        art = export_overlay_svg([], 1024, 576, assessment, label="empty")
        self.assertTrue(art.startswith(b"<svg"))
        self.assertTrue(art.endswith(b"</svg>\n"))
        self.assertIn(b"0 record(s)", art)
        self.assertNotIn(b"<polyline", art)


class HandComputedAssessmentTest(unittest.TestCase):
    def test_threshold_case_asserted_value_for_value(self):
        records = [
            make_observation(0, 0.0, 0.5, (0.0, 0.0, 9.0, 9.0),
                             (10.0, 20.0), 50.0),
            make_observation(1, 0.1, None, (0.0, 0.0, 9.0, 9.0),
                             (110.0, 20.0), 5000.0, valid=False,
                             warnings=[("W_PARTIAL_OBSERVATION",
                                        "synthetic: no confidence")]),
        ]
        report = {
            "coverage": {"invalid_retained": [
                {"frame_index": 1, "pts_seconds": 0.1,
                 "warning_codes": ["W_PARTIAL_OBSERVATION"],
                 "has_geometry": True},
            ]},
            "jumps": [{"from_frame_index": 0, "to_frame_index": 1,
                       "frame_delta": 1, "centroid_distance_px": 100.0}],
            "area_shape": {"per_frame": [
                {"frame_index": 0, "mask_area_px": 50.0,
                 "bbox_fill_ratio": 0.4},
                {"frame_index": 1, "mask_area_px": 5000.0,
                 "bbox_fill_ratio": 0.9},
            ]},
            "confidence": {"per_frame": [
                {"frame_index": 0, "confidence": 0.5},
                {"frame_index": 1, "confidence": None},
            ]},
        }
        limit = 14.142135623730951
        self.assertEqual(assess_chain(report, records), {
            "assessable": True, "flagged": True, "fit_worthy": False,
            "reasons": ["1 jumps flag(s)", "2 area flag(s)",
                        "1 fill ratio flag(s)", "1 confidence flag(s)",
                        "1 retained invalid row(s)"],
            "dimensions": {
                "jumps": {
                    "assessable": True, "reason": None,
                    "flags": [{"from_frame_index": 0, "to_frame_index": 1,
                               "flagged": True,
                               "reason": (f"distance 100.0 exceeds "
                                          f"plausibility limit {limit} "
                                          f"(1.0 diagonals x 1 step(s))")}],
                    "flagged_count": 1,
                },
                "area": {
                    "assessable": True, "reason": None,
                    "flags": [
                        {"frame_index": 0, "flagged": True,
                         "reason": ("area 50.0 below near-zero floor "
                                    "100.0")},
                        {"frame_index": 1, "flagged": True,
                         "reason": ("area step ratio 100.0 from frame 0 "
                                    "exceeds 4.0")},
                    ],
                    "flagged_count": 2,
                },
                "fill": {
                    "assessable": True, "reason": None,
                    "flags": [
                        {"frame_index": 0, "flagged": True,
                         "reason": "fill ratio 0.4 below minimum 0.5"},
                        {"frame_index": 1, "flagged": False, "reason": None},
                    ],
                    "flagged_count": 1,
                },
                "confidence": {
                    "assessable": True, "reason": None,
                    "flags": [
                        {"frame_index": 0, "flagged": False, "reason": None},
                        {"frame_index": 1, "flagged": True,
                         "reason": ("confidence null; absence flagged, "
                                    "values unjudged")},
                    ],
                    "flagged_count": 1,
                },
            },
            "frames": [
                {"frame_index": 0, "jump_flagged": None, "area_flagged": True,
                 "fill_flagged": True, "flagged_any": True},
                {"frame_index": 1, "jump_flagged": True, "area_flagged": True,
                 "fill_flagged": False, "flagged_any": True},
            ],
        })


class NegativeChainTest(unittest.TestCase):
    def assess_records(self, records):
        table = [make_frame(record.frame_index, record.pts_seconds)
                 if record.pts_seconds is not None else make_frame(
                     record.frame_index, 0.0)
                 for record in records]
        report = build_quality_report(table, records)
        return assess_chain(report, records)

    def test_teleport_jump_flagged(self):
        records = [
            make_observation(0, 0.0, 0.9, (0.0, 0.0, 99.0, 99.0),
                             (100.0, 100.0), 5000.0),
            make_observation(1, 0.1, 0.9, (0.0, 0.0, 99.0, 99.0),
                             (900.0, 100.0), 5000.0),
        ]
        assessment = self.assess_records(records)
        self.assertTrue(assessment["assessable"])
        self.assertTrue(assessment["flagged"])
        self.assertFalse(assessment["fit_worthy"])
        self.assertIn("1 jumps flag(s)", assessment["reasons"])
        text = export_trajectory_csv(records, assessment)
        rows = text.splitlines()
        self.assertTrue(rows[2].endswith(",true,false,false"))
        art = export_overlay_svg(records, 1024, 576, assessment,
                                 label="teleport")
        self.assertIn(b"#cc0000", art)
        self.assertIn(b"not fit-worthy", art)

    def test_collapsed_area_flagged(self):
        records = [
            make_observation(0, 0.0, 0.9, (0.0, 0.0, 99.0, 99.0),
                             (50.0, 50.0), 5000.0),
            make_observation(1, 0.1, 0.9, (0.0, 0.0, 99.0, 99.0),
                             (50.0, 50.0), 40.0),
        ]
        assessment = self.assess_records(records)
        self.assertFalse(assessment["fit_worthy"])
        self.assertIn("1 area flag(s)", assessment["reasons"])
        self.assertIn("1 fill ratio flag(s)", assessment["reasons"])

    def test_missing_pts_run_flagged_not_fit_worthy(self):
        records = [
            make_observation(0, None, 0.9, (0.0, 0.0, 9.0, 9.0),
                             (10.0, 20.0), 80.0, valid=False,
                             warnings=[("W_MISSING_FRAMES_RETAINED", "no pts")]),
            make_observation(1, None, 0.9, (0.0, 0.0, 9.0, 9.0),
                             (11.0, 20.0), 80.0, valid=False,
                             warnings=[("W_MISSING_FRAMES_RETAINED", "no pts")]),
        ]
        assessment = self.assess_records(records)
        self.assertTrue(assessment["assessable"])
        self.assertTrue(assessment["flagged"])
        self.assertFalse(assessment["fit_worthy"])
        self.assertIn("2 retained invalid row(s)", assessment["reasons"])
        text = export_trajectory_csv(records, assessment)
        self.assertEqual(text.splitlines()[1].split(",")[1], "")

    def test_empty_report_honestly_unassessable(self):
        assessment = assess_chain({}, [])
        self.assertFalse(assessment["assessable"])
        self.assertFalse(assessment["fit_worthy"])
        self.assertTrue(assessment["flagged"])
        self.assertIn("chain holds no records", assessment["reasons"])
        self.assertTrue(any("jumps not assessable" in reason
                            for reason in assessment["reasons"]))

    def test_jumps_unassessable_without_records(self):
        report = build_quality_report(
            [make_frame(0, 0.0)],
            [make_observation(0, 0.0, 0.9, (0.0, 0.0, 9.0, 9.0),
                              (10.0, 20.0), 80.0)])
        assessment = assess_chain(report)
        self.assertFalse(assessment["assessable"])
        self.assertIn("jumps not assessable: jump plausibility needs "
                      "record bboxes as context", assessment["reasons"])

    def test_malformed_assessment_inputs_rejected(self):
        with self.assertRaises(ContractError) as raised:
            assess_chain([], [])
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        with self.assertRaises(ContractError) as raised:
            assess_chain({}, [None])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])
        self.assertEqual(raised.exception.errors[0].field, "records[0]")
        probe = make_observation(0, 0.0, 0.9, (0.0, 0.0, 9.0, 9.0),
                                   (10.0, 20.0), 80.0)
        with self.assertRaises(ContractError) as raised:
            assess_chain({"jumps": [{"from_frame_index": 0,
                                     "to_frame_index": 1,
                                     "frame_delta": 1,
                                     "centroid_distance_px": "far"}]},
                         [probe])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])

    def test_malformed_artifact_inputs_rejected(self):
        record = make_observation(0, 0.0, 0.9, (0.0, 0.0, 9.0, 9.0),
                                  (10.0, 20.0), 80.0)
        with self.assertRaises(ContractError) as raised:
            export_trajectory_csv([record], [])
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        with self.assertRaises(ContractError) as raised:
            export_overlay_svg([record], 0, 576, {})
        self.assertEqual(raised.exception.codes, ["E_OUT_OF_RANGE"])
        with self.assertRaises(ContractError) as raised:
            export_overlay_svg([record], 1024.5, 576, {})
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])
        with self.assertRaises(ContractError) as raised:
            export_overlay_svg("nope", 1024, 576, {})
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])

    def test_trajectory_flags_absent_when_unassessed(self):
        record = make_observation(0, 0.0, 0.9, (0.0, 0.0, 9.0, 9.0),
                                  (10.0, 20.0), 80.0)
        text = export_trajectory_csv([record], {})
        self.assertTrue(text.splitlines()[1].endswith(",,"))


if __name__ == "__main__":
    unittest.main()
