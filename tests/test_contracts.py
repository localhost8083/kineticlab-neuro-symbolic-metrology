"""Schema structure and convention tests (KL-1.1).

Covers the six versioned records: valid construction, in-memory and
JSON round-trips, locked units/coordinates/enums, and the headline
coherence rules. Trust-boundary depth (states, tables, strictness
matrix) lives in test_contract_validation.py; file fixtures in
test_contract_fixtures.py.
"""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from kineticlab.contracts import (
    CalibrationRecord,
    ContractError,
    ERROR_CODES,
    FitRecord,
    FrameRecord,
    MediaMetadata,
    ObservationRecord,
    ResultContract,
    ResultState,
    WARNING_CODES,
    parse_json,
    parse_record,
)
from tests.contract_samples import (
    valid_calibration,
    valid_fit,
    valid_frame,
    valid_media,
    valid_observation,
    valid_result,
)

SCHEMA_CASES = [
    ("media", MediaMetadata, valid_media),
    ("frame", FrameRecord, valid_frame),
    ("observation", ObservationRecord, valid_observation),
    ("calibration", CalibrationRecord, valid_calibration),
    ("fit", FitRecord, valid_fit),
    ("result", ResultContract, valid_result),
]


class SchemaStructureTest(unittest.TestCase):
    def test_schema_versions_locked(self):
        self.assertEqual(MediaMetadata.from_dict(valid_media()).schema_version, "media.v1")
        self.assertEqual(FrameRecord.from_dict(valid_frame()).schema_version, "frame.v1")
        self.assertEqual(ObservationRecord.from_dict(valid_observation()).schema_version,
                         "observation.v1")
        self.assertEqual(CalibrationRecord.from_dict(valid_calibration()).schema_version,
                         "calibration.v1")
        self.assertEqual(FitRecord.from_dict(valid_fit()).schema_version, "fit.v1")
        self.assertEqual(ResultContract.from_dict(valid_result()).schema_version, "result.v1")

    def test_result_states_exact(self):
        self.assertEqual([state.value for state in ResultState],
                         ["success", "success_with_warnings", "insufficient_data",
                          "unsupported_input", "processing_error"])

    def test_valid_records_round_trip_in_memory(self):
        for name, record_type, builder in SCHEMA_CASES:
            with self.subTest(schema=name):
                record = record_type.from_dict(builder())
                self.assertEqual(record_type.from_dict(record.to_dict()), record)

    def test_valid_records_round_trip_json(self):
        for name, record_type, builder in SCHEMA_CASES:
            with self.subTest(schema=name):
                record = record_type.from_dict(builder())
                text = json.dumps(record.to_dict())
                self.assertEqual(parse_json(name, text), record)
                self.assertEqual(parse_record(name, json.loads(text)), record)

    def test_parse_copies_input_containers(self):
        data = valid_observation()
        record = ObservationRecord.from_dict(data)
        data["bbox"].append(999.0)
        data["warnings"].append({"code": "W_SHORT_TRACK", "detail": "late"})
        self.assertEqual(record.to_dict()["bbox"], [100.0, 200.0, 140.0, 260.0])
        self.assertEqual(record.to_dict()["warnings"], [])

    def test_taxonomy_registries_cover_error_paths(self):
        for code in WARNING_CODES:
            self.assertTrue(code.startswith("W_"), code)
        for code in ERROR_CODES:
            self.assertTrue(code.startswith("E_"), code)
        self.assertIn("E_GRAVITY_WITHOUT_LENGTH", ERROR_CODES)
        self.assertIn("E_NON_MONOTONIC_PTS", ERROR_CODES)
        self.assertIn("E_INCOHERENT_STATE", ERROR_CODES)

    def test_media_mirrors_plan_v1_scope(self):
        record = MediaMetadata.from_dict(valid_media())
        self.assertEqual(record.container, "mp4")
        self.assertEqual(record.codec, "h264")
        self.assertEqual((record.width, record.height), (1024, 576))
        self.assertIsNone(record.nominal_frame_rate)

    def test_frame_index_zero_based(self):
        record = FrameRecord.from_dict(valid_frame(index=0))
        self.assertEqual((record.frame_index, record.source_frame_index), (0, 0))

    def test_bbox_order_locked(self):
        data = valid_observation()
        data["bbox"] = [140.0, 200.0, 100.0, 260.0]
        with self.assertRaises(ContractError) as raised:
            ObservationRecord.from_dict(data)
        self.assertIn("E_BBOX_ORDER", raised.exception.codes)

    def test_centroid_pair_rule(self):
        data = valid_observation()
        data["centroid_y_px"] = None
        with self.assertRaises(ContractError) as raised:
            ObservationRecord.from_dict(data)
        self.assertIn("E_CENTROID_PAIR", raised.exception.codes)

    def test_confirmed_card_requires_user_dimensions(self):
        data = valid_calibration()
        data["reference_type"] = "iso_id1_confirmed"
        with self.assertRaises(ContractError) as raised:
            CalibrationRecord.from_dict(data)
        self.assertIn("E_UNCONFIRMED_DIMENSIONS", raised.exception.codes)

    def test_scale_xor_transform(self):
        data = valid_calibration()
        data["plane_transform"] = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        with self.assertRaises(ContractError) as raised:
            CalibrationRecord.from_dict(data)
        self.assertIn("E_SCALE_AMBIGUOUS", raised.exception.codes)

    def test_gravity_requires_independent_length(self):
        data = valid_fit()
        data["gravity_m_s2"] = 9.81
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_GRAVITY_WITHOUT_LENGTH", raised.exception.codes)

    def test_gravity_allowed_with_independent_length(self):
        data = valid_fit()
        data["pivot_length_mm"] = 650.0
        data["pivot_length_source"] = "independent_measurement"
        data["gravity_m_s2"] = 9.75
        record = FitRecord.from_dict(data)
        self.assertEqual(record.gravity_m_s2, 9.75)

    def test_parameter_keys_must_agree(self):
        data = valid_fit()
        data["parameter_units"] = {"g_over_l": "1/s^2", "extra": "m"}
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_PARAMETER_MISMATCH", raised.exception.codes)

    def test_all_errors_collected_not_first_only(self):
        data = valid_frame()
        del data["decoded_reference"]
        data["frame_index"] = "zero"
        data["bogus"] = 1
        with self.assertRaises(ContractError) as raised:
            FrameRecord.from_dict(data)
        self.assertEqual(len(raised.exception.errors), 4)
        self.assertEqual(sorted(raised.exception.codes),
                         ["E_MISSING_FIELD", "E_MISSING_MAPPING", "E_UNEXPECTED_FIELD",
                          "E_WRONG_TYPE"])

    def test_contract_error_serializes_to_json(self):
        data = valid_media()
        data["width"] = -5
        with self.assertRaises(ContractError) as raised:
            MediaMetadata.from_dict(data)
        text = json.dumps(raised.exception.to_dict())
        self.assertIn("E_OUT_OF_RANGE", text)

    def test_unknown_schema_rejected(self):
        with self.assertRaises(ContractError) as raised:
            parse_record("telemetry", {})
        self.assertIn("E_BAD_SCHEMA", raised.exception.codes)

    def test_malformed_json_rejected(self):
        with self.assertRaises(ContractError) as raised:
            parse_json("frame", "{not json")
        self.assertIn("E_MALFORMED_JSON", raised.exception.codes)

    def test_bool_rejected_for_int_field(self):
        data = valid_frame()
        data["frame_index"] = True
        with self.assertRaises(ContractError) as raised:
            FrameRecord.from_dict(data)
        self.assertIn("E_WRONG_TYPE", raised.exception.codes)


class TaxonomySizeTest(unittest.TestCase):
    def test_locked_taxonomy_counts(self):
        self.assertEqual(len(ERROR_CODES), 32)
        self.assertEqual(len(WARNING_CODES), 9)
        for code in ERROR_CODES:
            self.assertTrue(code.startswith("E_"), code)
        for code in WARNING_CODES:
            self.assertTrue(code.startswith("W_"), code)


class RequireSmokeTests(unittest.TestCase):
    # KL-9.6 B1: the skip-when-absent guard's own contract — a
    # present file passes silently, a missing path raises SkipTest
    # naming the path (never a failure, never silent).

    def test_present_file_passes(self):
        from tests import require_smoke

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "clip.mp4"
            target.write_bytes(b"fake")
            self.assertIsNone(require_smoke(target))

    def test_missing_path_skips_naming_it(self):
        from tests import require_smoke

        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.mp4"
            with self.assertRaises(unittest.SkipTest) as raised:
                require_smoke(missing)
            self.assertIn("Smoke file absent", str(raised.exception))
            self.assertIn("nope.mp4", str(raised.exception))


class ResultCoherenceTest(unittest.TestCase):
    """KL-10.21: adversarial-audit hardening on result.v1 coherence.

    A success verdict must never carry a non-physical magnitude and
    must never rest on an invalid calibration record."""

    @staticmethod
    def _with_value(data, value):
        data["value"] = value
        data["fit"]["g_over_l_per_s2"] = value
        data["fit"]["parameters"]["g_over_l"] = value
        data["identifiable_quantity"]["value"] = value
        return data

    def test_negative_value_rejected(self):
        data = self._with_value(valid_result(), -5.0)
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_zero_value_rejected(self):
        data = self._with_value(valid_result(), 0.0)
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_invalid_calibration_with_success_stays_valid(self):
        # KL-10.21 triage reversal: the battery proved the live pipeline
        # legitimately emits success with an invalid calibration record
        # (g/L is masks+timing; the card never enters it). No
        # calibration-validity rule exists at result level.
        data = valid_result()
        data["calibration"]["valid"] = False
        record = ResultContract.from_dict(data)
        self.assertFalse(record.calibration.valid)

    def test_extreme_value_stays_schema_valid(self):
        # Contracts enforce coherence, not physical plausibility: a
        # huge but self-consistent magnitude still parses (KL-10.21
        # triage of the adversarial audit's 1e9 probe).
        record = ResultContract.from_dict(
            self._with_value(valid_result(), 1e9))
        self.assertEqual(record.value, 1e9)


if __name__ == "__main__":
    unittest.main()
