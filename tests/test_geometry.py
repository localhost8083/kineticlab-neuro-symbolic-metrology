"""Geometry, calibration, and M-3 diagnostics tests (P-006).

Matrix: synthetic oriented rectangles (axis-aligned + rotated 30
degrees, exact recovery), synthetic circles (exact arc recovery),
degenerate clouds (honest fitted:false, never crashes), malformed
wire bytes and inputs (registered codes only), and the live 591-frame
chains (pins are measured stdlib outputs with provenance comments;
float pins use isclose because libm varies by platform).

Live-data build runs once on first use (shared parse + decode +
PCA, memoized). Regeneration tests recompute the pinned
`fixtures/geometry/` artifacts and compare recursively (isclose per
float, exact otherwise); the overlay SVG is byte-pinned as
platform-bound.
"""

import copy
import json
import math
import os
import statistics
import tempfile
import unittest
from pathlib import Path

from kineticlab import __version__
from kineticlab.capture.chain import (
    MODEL_LIMITATION_NOTE,
    U3_FRESH_CLIP_STATEMENT,
    _arc_radius_caveat,
    _fresh_calibration,
)
from kineticlab.contracts import (
    CalibrationRecord,
    ContractError,
    ERROR_CODES,
)
from kineticlab.geometry import (
    blur_proxy,
    build_calibration,
    corner_jitter,
    decode_frame_masks,
    fit_arc,
    oriented_rectangle,
    oriented_rectangle_from_raster,
    overlap_frames,
)
from kineticlab.geometry.export import report_bytes
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture
from kineticlab.result.overlay import export_overlay_svg
from kineticlab.result.quality import build_quality_report
from kineticlab.result.thresholds import assess_chain
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = REPO_ROOT / "fixtures" / "live"
GEO_DIR = REPO_ROOT / "fixtures" / "geometry"
CLIP_SHA = "db5da89e06f74547f03a41a1ef2ff041c6b4b1948957538a8e4674f5ab1d9945"

# U-1 caller inputs (user-supplied, never measured here). The fresh
# clip provides no U-3 depth measurements, so there is no offset.
CARD_W_MM = 85.0
CARD_H_MM = 54.0

# Shared live build, memoized on first use (KL-9.6 B1: was
# import-time, which would fail collection on clones without the
# gitignored Smoke/ clip; the guard inside skips those tests with
# the missing path named, while synthetic tests never touch it).
_CLIP = REPO_ROOT / "Smoke" / "demo_test.mp4"
_BUILD = None


def _live():
    """The shared live build (frame table, records, masks, PCA)."""
    global _BUILD
    if _BUILD is None:
        require_smoke(_CLIP)
        table = extract_frame_records(str(_CLIP))
        bob = parse_raw_fixture(
            LIVE_DIR / "raw_bob_one_bit.txt", object_role="bob",
            object_id="live-ball", frame_table=table,
            model_name="sam-3.1")
        card = parse_raw_fixture(
            LIVE_DIR / "raw_card_one_bit.txt",
            object_role="reference_card",
            object_id="live-card", frame_table=table,
            model_name="sam-3.1")
        overlap = overlap_frames(bob, card)
        masks = decode_frame_masks(
            LIVE_DIR / "raw_card_one_bit.txt", card)
        _BUILD = {
            "table": table,
            "bob": bob,
            "card": card,
            "overlap": overlap,
            "clean": set(range(199, 591)) - set(overlap),
            "masks": masks,
            "oriented": [(mask.frame_index, oriented_rectangle(
                mask.set_pixels())) for mask in masks],
            "rects": {mask.frame_index: oriented_rectangle(
                mask.set_pixels()) for mask in masks},
            "bob_xy": [(record.centroid_x_px, record.centroid_y_px)
                       for record in bob],
            "bob_areas": [record.mask_area_px for record in bob],
        }
    return _BUILD


def _live_calibration():
    """Fresh-clip calibration record + lean report (chain-shaped).

    Mirrors `_measure_full` in kineticlab/capture/chain.py: the card
    dimensions are human-typed, both geometry assumptions stay
    unassessed (the record is honestly invalid), the scale is the
    user width over the median PCA long side of the clean frames, and
    the report is the lean {pivot_arc, calibration, model_limitations}
    shape with no borrowed U-3 bound.
    """
    live = _live()
    clean = sorted(live["clean"])
    longs = [live["rects"][frame]["long_side"] for frame in clean]
    shorts = [live["rects"][frame]["short_side"] for frame in clean]
    long_med = float(statistics.median(longs))
    short_med = float(statistics.median(shorts))
    scale = CARD_W_MM / long_med
    record_dict = _fresh_calibration(CLIP_SHA, long_med, short_med,
                                     CARD_W_MM, CARD_H_MM)
    record_dict["scale_mm_per_px"] = scale
    record = CalibrationRecord.from_dict(record_dict)
    arc = fit_arc(live["bob_xy"], areas=live["bob_areas"])
    report = {
        "pivot_arc": arc,
        "calibration": {
            "n_usable_frames": len(clean),
            "card_width_mm": CARD_W_MM,
            "card_width_mm_source": "user_supplied",
            "card_height_mm": CARD_H_MM,
            "card_height_mm_source": "user_supplied",
            "scale_mm_per_px": scale,
            "median_long_side_px": long_med,
            "median_short_side_px": short_med,
            "scale_note": ("Isotropic scale = user-supplied card width "
                           "/ median PCA long side over "
                           f"{len(clean)} clean (fitted, non-occluded) "
                           "card frames; the short side is reported but "
                           "never enters the scale."),
            "corners_note": ("observed_corners_px is null: PCA corners "
                             "are unlabeled and their order flips frame "
                             "to frame, so no median corner set is "
                             "honest."),
            "u3_bound": {"statement": U3_FRESH_CLIP_STATEMENT},
        },
        "model_limitations": [MODEL_LIMITATION_NOTE,
                              _arc_radius_caveat(arc, scale)],
    }
    return record, report


def _assert_close_tree(test_case, first, second, *, rel=1e-9, path=""):
    # Recursive regeneration compare: floats isclose, rest exact.
    if isinstance(first, float) or isinstance(second, float):
        test_case.assertTrue(
            math.isclose(first, second, rel_tol=rel, abs_tol=1e-12),
            f"{path}: {first!r} vs {second!r}")
    elif isinstance(first, dict):
        test_case.assertEqual(set(first), set(second), path)
        for key in first:
            _assert_close_tree(test_case, first[key], second[key],
                               rel=rel, path=f"{path}.{key}")
    elif isinstance(first, (list, tuple)):
        test_case.assertEqual(len(first), len(second), path)
        for index, (a, b) in enumerate(zip(first, second)):
            _assert_close_tree(test_case, a, b, rel=rel,
                               path=f"{path}[{index}]")
    else:
        test_case.assertEqual(first, second, path)


class MasksTests(unittest.TestCase):
    def test_live_card_masks_decode(self):
        masks = _live()["masks"]
        self.assertEqual(len(masks), 392)
        self.assertEqual([mask.frame_index for mask in masks],
                         list(range(199, 591)))
        first = masks[0]
        self.assertEqual((first.width, first.height), (208, 129))

    def test_set_pixels_match_record_area(self):
        # Independent cross-check: decoded raster population equals
        # the adapter's mask-derived area on every frame.
        live = _live()
        for mask, record in zip(live["masks"], live["card"]):
            with self.subTest(frame=mask.frame_index):
                self.assertEqual(len(mask.set_pixels()),
                                 record.mask_area_px)

    def test_mask_dims_match_box_spans_plus_one(self):
        live = _live()
        for mask, record in zip(live["masks"], live["card"]):
            with self.subTest(frame=mask.frame_index):
                self.assertEqual(
                    mask.width,
                    round(record.bbox[2] - record.bbox[0]) + 1)
                self.assertEqual(
                    mask.height,
                    round(record.bbox[3] - record.bbox[1]) + 1)

    def test_frame_mismatch_refused(self):
        class Fake:
            def __init__(self, frame_index):
                self.frame_index = frame_index

        records = [Fake(index) for index in range(199, 590)]
        with self.assertRaises(ContractError) as raised:
            decode_frame_masks(LIVE_DIR / "raw_card_one_bit.txt", records)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        records = [Fake(index) for index in range(199, 592)]
        with self.assertRaises(ContractError) as raised:
            decode_frame_masks(LIVE_DIR / "raw_card_one_bit.txt", records)
        self.assertIn("E_MISSING_MAPPING", raised.exception.codes)

    def test_malformed_wire_bytes_refused(self):
        line = (LIVE_DIR / "raw_card_one_bit.txt").read_text(
            encoding="utf-8").splitlines()[0]

        class Fake:
            frame_index = 199

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "w.txt")
            cases = [
                ("garbage-no-marker\n", "E_MISSING_FIELD"),
                (line.replace("box;", "bx;", 1) + "\n", "E_MISSING_FIELD"),
                (line.replace(";data=", ";dat=", 1) + "\n",
                 "E_MISSING_FIELD"),
            ]
            # Confidence mismatch: flip the mask c (second occurrence).
            head, sep, tail = line.partition(";data=")
            box_c = head.split("|><|")[0].split(";c=")[1].split(";")[0]
            flipped = ("0.5" if box_c != "0.5" else "0.6")
            mask_head = head.split("|><|")[1]
            bad_conf = head.split("|><|")[0] + "|><|" + mask_head.replace(
                ";c=" + box_c, ";c=" + flipped, 1) + sep + tail + "\n"
            cases.append((bad_conf, "E_INCOHERENT_VALUE"))
            for text, code in cases:
                with self.subTest(code=code):
                    with open(target, "w", encoding="utf-8") as handle:
                        handle.write(text)
                    with self.assertRaises(ContractError) as raised:
                        decode_frame_masks(target, [Fake()])
                    self.assertIn(code, raised.exception.codes)
                    for raised_code in raised.exception.codes:
                        self.assertIn(raised_code, ERROR_CODES)

    def test_missing_file_refused(self):
        card = _live()["card"]
        with self.assertRaises(ContractError) as raised:
            decode_frame_masks(LIVE_DIR / "no-such-file.txt", card[:1])
        self.assertIn("E_MALFORMED_JSON", raised.exception.codes)


# KL-10.10: see tests/test_fit_m1.py — same-platform byte pins.
PIN_SAME_PLATFORM = unittest.skipIf(
    os.environ.get("KL_CROSS_PLATFORM") == "1",
    "byte pins are same-platform determinism; cross-platform "
    "libm drifts in the last ulp (KL-10.10)")


class OrientedTests(unittest.TestCase):
    @PIN_SAME_PLATFORM
    def test_fused_pca_matches_classic_on_live_masks(self):
        # KL-9.2 item 4: the fused raster PCA must return
        # bit-identical dicts (exact float equality, not isclose)
        # to oriented_rectangle(set_pixels()) on every committed
        # live mask. Reuses the shared decoded masks +
        # classic rects, so only the fused path costs time here.
        live = _live()
        self.assertEqual(len(live["masks"]), len(live["oriented"]))
        for mask, (frame_index, classic) in zip(live["masks"],
                                               live["oriented"]):
            with self.subTest(frame=frame_index):
                self.assertEqual(mask.frame_index, frame_index)
                fused = oriented_rectangle_from_raster(
                    mask.raster, mask.width, mask.height,
                    mask.x1, mask.y1)
                self.assertEqual(fused, classic)

    def test_axis_aligned_rectangle_exact(self):
        points = [(x, y) for x in range(100, 201) for y in range(50, 101)]
        rect = oriented_rectangle(points)
        self.assertTrue(rect["fitted"])
        self.assertAlmostEqual(rect["angle_rad"], 0.0, places=9)
        self.assertAlmostEqual(rect["long_side"], 100.0, places=9)
        self.assertAlmostEqual(rect["short_side"], 50.0, places=9)
        corners = rect["corners"]
        self.assertEqual(len(corners), 4)
        for corner, want in zip(corners, [[100.0, 50.0], [200.0, 50.0],
                                               [200.0, 100.0], [100.0, 100.0]]):
            self.assertAlmostEqual(corner[0], want[0], places=9)
            self.assertAlmostEqual(corner[1], want[1], places=9)

    def test_rotated_rectangle_recovered(self):
        angle = math.radians(30.0)
        points = []
        for ix in range(-100, 101):
            for iy in range(-50, 51):
                points.append((
                    500.0 + ix * math.cos(angle) - iy * math.sin(angle),
                    300.0 + ix * math.sin(angle) + iy * math.cos(angle)))
        rect = oriented_rectangle(points)
        self.assertTrue(rect["fitted"])
        self.assertAlmostEqual(math.degrees(rect["angle_rad"]), 30.0,
                               places=9)
        self.assertAlmostEqual(rect["long_side"], 200.0, places=9)
        self.assertAlmostEqual(rect["short_side"], 100.0, places=9)
        # Contract corner order: origin-nearest leads, clockwise.
        first = rect["corners"][0]
        dists = [c[0] ** 2 + c[1] ** 2 for c in rect["corners"]]
        self.assertEqual(dists.index(min(dists)), 0)
        self.assertLess(first[0], 500.0)
        self.assertLess(first[1], 300.0)

    def test_degenerate_clouds_fail_honestly(self):
        for points in ([], [(1.0, 2.0)], [(1.0, 2.0), (1.0, 2.0)],
                        [(0.0, 0.0), (1.0, 1.0)]):
            with self.subTest(points=points):
                result = oriented_rectangle(points)
                self.assertFalse(result["fitted"])
                self.assertIn("reason", result)

    def test_malformed_inputs_rejected(self):
        for bad in ("nope", 42, [(0.0, float("nan"))], [(0.0, 1.0, 2.0)],
                    [[True, 0.0]], None):
            with self.subTest(bad=str(bad)[:30]):
                with self.assertRaises(ContractError) as raised:
                    oriented_rectangle(bad)
                for code in raised.exception.codes:
                    self.assertIn(code, ERROR_CODES)

    def test_live_first_card_frame_pins(self):
        # Measured stdlib output on the pinning platform (libm-bound).
        # The card enters mid-clip; its first frame is 199.
        rect = dict(_live()["oriented"][0][1])
        self.assertTrue(rect["fitted"])
        self.assertTrue(math.isclose(rect["long_side"], 206.8783,
                                     rel_tol=1e-4))
        self.assertTrue(math.isclose(rect["short_side"], 127.8802,
                                     rel_tol=1e-4))
        self.assertTrue(math.isclose(
            math.degrees(rect["angle_rad"]), 0.10539, rel_tol=1e-2))
        for corner, want in zip(
                rect["corners"],
                [[206.17302, 307.93594], [413.05092, 308.31646],
                 [412.81570, 436.19647], [205.93780, 435.81595]]):
            self.assertTrue(math.isclose(corner[0], want[0], rel_tol=1e-4))
            self.assertTrue(math.isclose(corner[1], want[1], rel_tol=1e-4))

    def test_all_live_frames_fit(self):
        oriented = _live()["oriented"]
        self.assertTrue(all(rect["fitted"] for _, rect in oriented))


class PivotTests(unittest.TestCase):
    def test_exact_circle_recovered(self):
        points = [(3.0 + 5.0 * math.cos(t), -2.0 + 5.0 * math.sin(t))
                  for t in [i * math.pi / 4 for i in range(8)]]
        arc = fit_arc(points)
        self.assertTrue(arc["fitted"])
        self.assertAlmostEqual(arc["center_px"][0], 3.0, places=9)
        self.assertAlmostEqual(arc["center_px"][1], -2.0, places=9)
        self.assertAlmostEqual(arc["radius_px"], 5.0, places=9)
        self.assertLess(arc["mean_abs_residual_px"], 1e-9)
        self.assertAlmostEqual(arc["arc_span_rad"], 2.0 * math.pi
                               - math.pi / 4, places=9)

    def test_collinear_and_degenerate_fail_honestly(self):
        line = fit_arc([(float(i), 2.0 * float(i)) for i in range(10)])
        self.assertFalse(line["fitted"])
        self.assertIn("reason", line)
        few = fit_arc([(0.0, 0.0), (1.0, 1.0)])
        self.assertFalse(few["fitted"])

    def test_malformed_inputs_rejected(self):
        for bad in ("nope", [(0.0, float("inf"))], [(0.0,)],
                    None):
            with self.subTest(bad=str(bad)[:30]):
                with self.assertRaises(ContractError) as raised:
                    fit_arc(bad)
                for code in raised.exception.codes:
                    self.assertIn(code, ERROR_CODES)
        with self.assertRaises(ContractError):
            fit_arc([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)], areas=[1.0])

    def test_live_bob_arc_pins(self):
        # Measured stdlib output; the fitted arc is the descriptive
        # pivot evidence for the fresh clip (libm-bound floats).
        live = _live()
        arc = fit_arc(live["bob_xy"], areas=live["bob_areas"])
        self.assertTrue(arc["fitted"])
        self.assertTrue(math.isclose(arc["center_px"][0], 467.30924,
                                     rel_tol=1e-4))
        self.assertTrue(math.isclose(arc["center_px"][1], -430.61623,
                                     rel_tol=1e-4))
        self.assertTrue(math.isclose(arc["radius_px"], 800.96617,
                                     rel_tol=1e-4))
        self.assertTrue(math.isclose(arc["mean_abs_residual_px"], 4.695833,
                                     rel_tol=1e-3))
        self.assertEqual(arc["max_residual_index"], 505)
        self.assertEqual(len(arc["top_residual_frames"]), 10)
        self.assertTrue(all("mask_area_px" in entry
                            for entry in arc["top_residual_frames"]))


class DiagnosticsTests(unittest.TestCase):
    def test_overlap_recomputed(self):
        # Independent recompute of M-1's 120-frame finding (cross-check).
        overlap = _live()["overlap"]
        self.assertEqual(len(overlap), 120)
        bands = [(199, 203), (211, 215), (234, 238), (246, 250),
                 (269, 273), (281, 285), (304, 308), (316, 320),
                 (340, 344), (351, 355), (375, 379), (386, 390),
                 (410, 414), (421, 425), (445, 449), (456, 460),
                 (480, 484), (490, 495), (515, 519), (525, 530),
                 (550, 554), (560, 565), (584, 590)]
        for start, end in bands:
            for frame in range(start, end + 1):
                self.assertIn(frame, overlap)
        self.assertEqual(sum(end - start + 1 for start, end in bands), 120)

    def test_jitter_static_and_shifted(self):
        base = [[0.0, 0.0], [10.0, 0.0], [10.0, 5.0], [0.0, 5.0]]
        static = corner_jitter([(0, base), (1, copy.deepcopy(base))])
        self.assertEqual(static["n_pairs"], 1)
        self.assertEqual(static["max_px"], 0.0)
        moved = [[c[0] + 3.0, c[1] + 4.0] for c in base]
        shift = corner_jitter([(0, base), (1, moved)])
        self.assertAlmostEqual(shift["max_px"], 5.0, places=9)
        # Non-consecutive pairs are skipped, never interpolated.
        gap = corner_jitter([(0, base), (5, moved)])
        self.assertEqual(gap["n_pairs"], 0)

    def test_jitter_malformed_rejected(self):
        with self.assertRaises(ContractError):
            corner_jitter("nope")
        with self.assertRaises(ContractError):
            corner_jitter([(0, [[0.0, 0.0]] * 3)])

    def test_live_jitter_splits(self):
        # Measured: occlusion contaminates corners; clean split is the
        # camera-stability evidence (libm-bound floats).
        live = _live()
        corners_all = [(frame, rect["corners"])
                       for frame, rect in live["oriented"]
                       if rect["fitted"]]
        everywhere = corner_jitter(corners_all)
        self.assertEqual(everywhere["n_pairs"], 391)
        self.assertTrue(math.isclose(everywhere["mean_px"], 4.333977,
                                     rel_tol=1e-3))
        clean = corner_jitter([(frame, corners) for frame, corners in
                               corners_all
                               if frame not in set(live["overlap"])])
        self.assertEqual(clean["n_pairs"], 250)
        self.assertTrue(math.isclose(clean["mean_px"], 0.799931,
                                     rel_tol=1e-3))
        self.assertTrue(math.isclose(clean["max_px"], 5.535061,
                                     rel_tol=1e-2))
        self.assertEqual(clean["stationary_counts"]["1.0"], 144)
        self.assertEqual(clean["stationary_counts"]["2.0"], 243)
        occluded = corner_jitter([(frame, corners) for frame, corners in
                                  corners_all
                                  if frame in set(live["overlap"])])
        self.assertEqual(occluded["n_pairs"], 97)
        self.assertTrue(math.isclose(occluded["mean_px"], 13.847699,
                                     rel_tol=1e-3))

    def test_blur_proxy_synthetic(self):
        class Fake:
            def __init__(self, frame_index, bbox, area):
                self.frame_index = frame_index
                self.bbox = bbox
                self.mask_area_px = area

        records = [Fake(0, [0.0, 0.0, 10.0, 10.0], 80.0),
                   Fake(1, [0.0, 0.0, 20.0, 10.0], 160.0)]
        proxy = blur_proxy(records)
        self.assertEqual(proxy["median_area_px"], 120.0)
        self.assertEqual(proxy["per_frame"][0]["bbox_elongation"], 1.0)
        self.assertEqual(proxy["per_frame"][1]["bbox_elongation"], 2.0)

    def test_live_blur_proxy_pins(self):
        proxy = blur_proxy(_live()["bob"])
        self.assertEqual(proxy["n"], 591)
        self.assertEqual(proxy["median_area_px"], 4653.0)
        self.assertTrue(math.isclose(proxy["elongation"]["max"],
                                     1.6666666666666667, rel_tol=1e-4))
        self.assertTrue(math.isclose(proxy["elongation"]["mean"],
                                     1.1919990125016446, rel_tol=1e-4))
        self.assertEqual(len(proxy["top_elongation_frames"]), 10)


def _synthetic_oriented():
    """One fitted axis-aligned 100x50 rect on frame 0."""
    rect = oriented_rectangle([(x, y) for x in range(100, 201)
                               for y in range(50, 101)])
    return [(0, rect)]


def _synthetic_calibration(**overrides):
    """build_calibration over synthetic U-1/U-3 inputs (no live data)."""
    base = dict(
        card_width_mm=100.0, card_height_mm=50.0,
        oriented=_synthetic_oriented(), clean_frames={0},
        same_plane=False, camera_fixed=True,
        depth_offset_mm=25.0, camera_distance_mm=1500.0,
        video_width=400, video_height=300,
        provenance={
            "software_name": "kineticlab",
            "software_version": __version__,
            "input_sha256": None,
            "model_name": None,
            "model_version": None,
            "raw_refs": [],
        })
    return build_calibration(**{**base, **overrides})


class CalibrationTests(unittest.TestCase):
    def test_record_validates_and_pins(self):
        record, report = _synthetic_calibration()
        self.assertTrue(record.valid)
        as_dict = record.to_dict()
        round_tripped = CalibrationRecord.from_dict(
            copy.deepcopy(as_dict))
        self.assertEqual(round_tripped.to_dict(), as_dict)
        self.assertEqual(as_dict["reference_type"], "iso_id1_confirmed")
        self.assertEqual(as_dict["reference_dimensions_mm"],
                         {"width_mm": 100.0, "height_mm": 50.0})
        self.assertEqual(as_dict["dimension_source"], "user_confirmed")
        self.assertIsNone(as_dict["plane_transform"])
        self.assertIsNone(as_dict["scale_uncertainty_mm_per_px"])
        self.assertFalse(as_dict["same_plane_assumption"] is None)
        self.assertTrue(as_dict["camera_fixed_assumption"])
        self.assertEqual([warning["code"] for warning in as_dict["warnings"]],
                         ["W_UNCERTAINTY_UNAVAILABLE",
                          "W_ASSUMPTION_UNVERIFIED"])
        # Synthetic exact geometry: scale is exactly 1.0 mm/px.
        self.assertTrue(math.isclose(as_dict["scale_mm_per_px"], 1.0,
                                     rel_tol=1e-12))
        self.assertTrue(math.isclose(report["anisotropy"], 0.0,
                                     abs_tol=1e-12))
        self.assertTrue(math.isclose(report["aspect_measured"], 2.0,
                                     rel_tol=1e-12))
        self.assertTrue(math.isclose(report["aspect_nominal"], 2.0,
                                     rel_tol=1e-12))
        self.assertTrue(math.isclose(
            report["u3_bound"]["bound_percent"], 1.6666666666666667,
            rel_tol=1e-9))
        self.assertEqual(report["n_usable_frames"], 1)

    def test_assumptions_explicit(self):
        _, report = _synthetic_calibration()
        assumptions = report["assumptions"]
        self.assertFalse(assumptions["same_plane"]["value"])
        self.assertIn("25", assumptions["same_plane"]["basis"])
        self.assertTrue(assumptions["camera_fixed"]["value"])
        for name in ("tilt", "blur", "length"):
            with self.subTest(assumption=name):
                self.assertIsNone(assumptions[name]["value"])
                self.assertTrue(assumptions[name]["reason"])
        self.assertTrue(assumptions["truncation"]["value"])
        self.assertTrue(any("M-3e" in line
                            for line in report["model_limitations"]))

    def test_unassessed_inputs_yield_invalid_record(self):
        _, report = _synthetic_calibration(same_plane=None)
        self.assertFalse(report["record_valid"])

    def test_empty_clean_frames_refused(self):
        with self.assertRaises(ContractError) as raised:
            _synthetic_calibration(clean_frames=set())
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_bad_inputs_rejected_with_registered_codes(self):
        base_cases = [
            (dict(card_width_mm=-1.0), "E_OUT_OF_RANGE"),
            (dict(card_height_mm="big"), "E_WRONG_TYPE"),
            (dict(depth_offset_mm=0.0), "E_OUT_OF_RANGE"),
            (dict(video_width=0), "E_OUT_OF_RANGE"),
            (dict(video_width="1024"), "E_WRONG_TYPE"),
            (dict(same_plane="no"), "E_WRONG_TYPE"),
            (dict(clean_frames="all"), "E_WRONG_TYPE"),
            (dict(oriented="rects"), "E_WRONG_TYPE"),
        ]
        for overrides, code in base_cases:
            with self.subTest(code=code):
                with self.assertRaises(ContractError) as raised:
                    _synthetic_calibration(**overrides)
                self.assertIn(code, raised.exception.codes)
                for raised_code in raised.exception.codes:
                    self.assertIn(raised_code, ERROR_CODES)


class FreshClipCalibrationTests(unittest.TestCase):
    def test_live_record_pins(self):
        # Chain-shaped fresh-clip record: human-typed card, unassessed
        # assumptions (honestly invalid), width-over-median scale.
        record, report = _live_calibration()
        self.assertFalse(record.valid)
        as_dict = record.to_dict()
        CalibrationRecord.from_dict(copy.deepcopy(as_dict))
        self.assertEqual(as_dict["reference_type"], "unknown")
        self.assertEqual(as_dict["reference_dimensions_mm"],
                         {"width_mm": 85.0, "height_mm": 54.0})
        self.assertEqual(as_dict["dimension_source"], "user_confirmed")
        self.assertIsNone(as_dict["same_plane_assumption"])
        self.assertIsNone(as_dict["camera_fixed_assumption"])
        self.assertEqual([warning["code"] for warning in as_dict["warnings"]],
                         ["W_ASSUMPTION_UNVERIFIED",
                          "W_ASSUMPTION_UNVERIFIED"])
        self.assertTrue(math.isclose(as_dict["scale_mm_per_px"],
                                     0.4063304685046935, rel_tol=1e-9))
        self.assertEqual(report["calibration"]["n_usable_frames"], 272)
        self.assertEqual(as_dict["observed_oriented_dimensions_px"],
                         {"long_side_px": 209.18933377750915,
                          "short_side_px": 128.34633924757009})


class RegenerationTests(unittest.TestCase):
    def test_calibration_pin_regenerates(self):
        with open(GEO_DIR / "calibration_live.json",
                  encoding="utf-8") as handle:
            pinned = json.load(handle)
        record, _ = _live_calibration()
        _assert_close_tree(self, record.to_dict(), pinned)

    def test_report_pin_regenerates(self):
        with open(GEO_DIR / "geometry_report_live.json",
                  encoding="utf-8") as handle:
            pinned = json.load(handle)
        _, report = _live_calibration()
        rebuilt = {
            "calibration": report["calibration"],
            "model_limitations": report["model_limitations"],
            "pivot_arc": report["pivot_arc"],
        }
        _assert_close_tree(self, rebuilt, pinned)

    def test_overlay_bytes_pinned(self):
        # Platform-bound: float repr of libm-derived geometry.
        pinned = (GEO_DIR / "overlay_live_ball.svg").read_bytes()
        live = _live()
        quality = build_quality_report(live["table"], live["bob"])
        assessment = assess_chain(quality, live["bob"])
        regenerated = export_overlay_svg(live["bob"], 1024, 576, assessment,
                                         label="live-ball P-006")
        self.assertEqual(regenerated, pinned)

    def test_report_bytes_canonical(self):
        first = report_bytes({"b": 1, "a": [1.5]})
        second = report_bytes({"a": [1.5], "b": 1})
        self.assertEqual(first, second)
        self.assertTrue(first.endswith(b"\n"))
        self.assertNotIn(b"\r", first)
        with self.assertRaises(TypeError):
            report_bytes("nope")


if __name__ == "__main__":
    unittest.main()
