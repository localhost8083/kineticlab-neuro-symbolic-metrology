"""Trust-boundary validation and state tests (KL-1.2).

Covers the five result states and their coherence rules, the frame-table
collection rules, and the strictness matrix (types, nulls, versions,
enums, hashes, taxonomy codes). All rejection paths must raise
``ContractError`` with registered codes — never bare exceptions,
partial objects, or silent drops.
"""

import unittest

from kineticlab.contracts import (
    ERROR_CODES,
    CalibrationRecord,
    ContractError,
    FitRecord,
    FrameRecord,
    MediaMetadata,
    ObservationRecord,
    ResultContract,
    WARNING_CODES,
    parse_json,
    parse_record,
    validate_frame_table,
)
from tests.contract_samples import (
    valid_calibration,
    valid_fit,
    valid_frame,
    valid_media,
    valid_observation,
    valid_result,
)

FAILURE_STATES = ["insufficient_data", "unsupported_input", "processing_error"]


def failure_result(status):
    data = valid_result(status=status)
    data["value"] = None
    data["unit"] = None
    data["identifiable_quantity"] = {"name": "g/L_eff", "value": None, "unit": "1/s^2"}
    data["calibration"] = None
    data["fit"] = None
    data["quality_metrics"] = None
    data["reject_reasons"] = [
        {"code": "E_MISSING_MAPPING", "field": "frames", "detail": "no usable frames"}
    ]
    return data


class ResultStateTest(unittest.TestCase):
    def test_all_five_states_validate(self):
        self.assertEqual(ResultContract.from_dict(valid_result()).status.value, "success")
        warned = valid_result(status="success_with_warnings")
        warned["warnings"] = [{"code": "W_SHORT_TRACK", "detail": "only 40 usable frames"}]
        self.assertEqual(ResultContract.from_dict(warned).status.value,
                         "success_with_warnings")
        for status in FAILURE_STATES:
            with self.subTest(status=status):
                record = ResultContract.from_dict(failure_result(status))
                self.assertEqual(record.status.value, status)
                self.assertIsNone(record.value)

    def test_success_rejects_reasons(self):
        data = valid_result()
        data["reject_reasons"] = [
            {"code": "E_MISSING_MAPPING", "field": None, "detail": "stale reason"}
        ]
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_success_rejects_warnings(self):
        data = valid_result()
        data["warnings"] = [
            {"code": "W_SHORT_TRACK", "detail": "only 40 usable frames"}
        ]
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_success_requires_value(self):
        data = valid_result()
        data["value"] = None
        data["unit"] = None
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_warned_success_requires_warnings(self):
        data = valid_result(status="success_with_warnings")
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_failure_states_require_reasons_and_no_value(self):
        for status in FAILURE_STATES:
            with self.subTest(status=status, case="no-reasons"):
                data = failure_result(status)
                data["reject_reasons"] = []
                with self.assertRaises(ContractError) as raised:
                    ResultContract.from_dict(data)
                self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)
            with self.subTest(status=status, case="smuggled-value"):
                data = failure_result(status)
                data["value"] = 9.81
                data["unit"] = "m/s^2"
                with self.assertRaises(ContractError) as raised:
                    ResultContract.from_dict(data)
                self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)
            with self.subTest(status=status, case="smuggled-interval"):
                data = failure_result(status)
                data["interval"] = {"lower": 1.0, "upper": 2.0}
                data["interval_method"] = "analytic_linearized"
                with self.assertRaises(ContractError) as raised:
                    ResultContract.from_dict(data)
                self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_value_requires_unit(self):
        data = valid_result()
        data["unit"] = None
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_VALUE_WITHOUT_UNIT", raised.exception.codes)

    def test_interval_requires_method(self):
        data = valid_result()
        data["interval"] = {"lower": 14.0, "upper": 16.0}
        data["interval_method"] = None
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INTERVAL_WITHOUT_METHOD", raised.exception.codes)

    def test_interval_order_enforced(self):
        data = valid_result()
        data["interval"] = {"lower": 16.0, "upper": 14.0}
        data["interval_method"] = "analytic_linearized"
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INTERVAL_ORDER", raised.exception.codes)

    def test_unknown_status_rejected(self):
        data = valid_result()
        data["status"] = "almost_success"
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_BAD_ENUM", raised.exception.codes)

    def test_nested_calibration_errors_prefixed(self):
        data = valid_result()
        data["calibration"]["scale_mm_per_px"] = -1.0
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        fields = [error.field for error in raised.exception.errors]
        self.assertTrue(fields and all(field.startswith("calibration.")
                                       for field in fields), fields)

    def test_nested_fit_errors_prefixed(self):
        data = valid_result()
        data["fit"]["model_id"] = "M9"
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        fields = [error.field for error in raised.exception.errors]
        self.assertTrue(fields and all(field.startswith("fit.") for field in fields), fields)


class FrameTableTest(unittest.TestCase):
    def test_strictly_increasing_table_passes(self):
        records = [FrameRecord.from_dict(valid_frame(index=index)) for index in range(5)]
        validate_frame_table(records)

    def test_invalid_frames_skipped(self):
        records = [FrameRecord.from_dict(valid_frame(index=index)) for index in range(3)]
        dropped = valid_frame(index=3)
        dropped.update({"source_frame_index": None, "pts_seconds": None,
                        "decoded_reference": None, "valid": False})
        records.append(FrameRecord.from_dict(dropped))
        validate_frame_table(records)

    def test_duplicate_processing_index_rejected(self):
        records = [FrameRecord.from_dict(valid_frame(index=0)),
                   FrameRecord.from_dict(valid_frame(index=0))]
        with self.assertRaises(ContractError) as raised:
            validate_frame_table(records)
        self.assertIn("E_DUPLICATE_FRAME", raised.exception.codes)

    def test_duplicate_source_index_rejected(self):
        first = FrameRecord.from_dict(valid_frame(index=0))
        second_data = valid_frame(index=1)
        second_data["source_frame_index"] = 0
        second = FrameRecord.from_dict(second_data)
        with self.assertRaises(ContractError) as raised:
            validate_frame_table([first, second])
        self.assertIn("E_DUPLICATE_FRAME", raised.exception.codes)

    def test_non_monotonic_pts_rejected(self):
        first = FrameRecord.from_dict(valid_frame(index=0))
        second_data = valid_frame(index=1)
        second_data["pts_seconds"] = 0.0
        second = FrameRecord.from_dict(second_data)
        with self.assertRaises(ContractError) as raised:
            validate_frame_table([first, second])
        self.assertIn("E_NON_MONOTONIC_PTS", raised.exception.codes)


class StrictnessMatrixTest(unittest.TestCase):
    SCHEMAS = [
        ("media", MediaMetadata, valid_media),
        ("frame", FrameRecord, valid_frame),
        ("observation", ObservationRecord, valid_observation),
        ("calibration", CalibrationRecord, valid_calibration),
        ("fit", FitRecord, valid_fit),
        ("result", ResultContract, valid_result),
    ]

    def test_non_object_input_rejected(self):
        for name, record_type, _ in self.SCHEMAS:
            with self.subTest(schema=name):
                for bad in ([], "x", 42, None):
                    with self.subTest(bad=repr(bad)):
                        with self.assertRaises(ContractError) as raised:
                            record_type.from_dict(bad)
                        self.assertIn("E_NOT_AN_OBJECT", raised.exception.codes)

    def test_wrong_version_rejected(self):
        for name, record_type, builder in self.SCHEMAS:
            with self.subTest(schema=name):
                data = builder()
                data["schema_version"] = "v2"
                with self.assertRaises(ContractError) as raised:
                    record_type.from_dict(data)
                self.assertIn("E_BAD_VERSION", raised.exception.codes)

    def test_empty_object_rejected(self):
        for name, record_type, _ in self.SCHEMAS:
            with self.subTest(schema=name):
                with self.assertRaises(ContractError) as raised:
                    record_type.from_dict({})
                self.assertIn("E_MISSING_FIELD", raised.exception.codes)

    def test_null_where_forbidden(self):
        data = valid_frame()
        data["frame_index"] = None
        with self.assertRaises(ContractError) as raised:
            FrameRecord.from_dict(data)
        self.assertIn("E_NULL_NOT_ALLOWED", raised.exception.codes)

    def test_bad_sha256_rejected(self):
        for bad in ("abc", "A" * 64, "zz" * 32, "a" * 63):
            with self.subTest(bad=bad[:8]):
                data = valid_media()
                data["source_sha256"] = bad
                with self.assertRaises(ContractError) as raised:
                    MediaMetadata.from_dict(data)
                self.assertIn("E_BAD_SHA256", raised.exception.codes)

    def test_bad_time_base_rejected(self):
        for bad in ("abc", "1/0", "1/2/3", "1.5/2", "/2"):
            with self.subTest(bad=bad):
                data = valid_media()
                data["time_base"] = bad
                with self.assertRaises(ContractError) as raised:
                    MediaMetadata.from_dict(data)
                self.assertIn("E_BAD_TIME_BASE", raised.exception.codes)

    def test_unknown_warning_code_rejected(self):
        data = valid_frame()
        data["warnings"] = [{"code": "W_VIBES", "detail": "made up"}]
        with self.assertRaises(ContractError) as raised:
            FrameRecord.from_dict(data)
        self.assertIn("E_UNKNOWN_WARNING_CODE", raised.exception.codes)

    def test_unknown_reason_code_rejected(self):
        data = failure_result("processing_error")
        data["reject_reasons"] = [{"code": "E_BROKEN", "field": None, "detail": "made up"}]
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_UNKNOWN_REASON_CODE", raised.exception.codes)

    def test_bad_enum_values_rejected(self):
        cases = [
            (ObservationRecord, valid_observation(), "object_role", "pendulum"),
            (ObservationRecord, valid_observation(), "source", "sam_telepathy"),
            (FitRecord, valid_fit(), "model_id", "M3"),
            (FitRecord, valid_fit(), "fit_uncertainty_method", "bootstrap"),
            (CalibrationRecord, valid_calibration(), "reference_type", "id1_probably"),
        ]
        for record_type, data, key, bad in cases:
            with self.subTest(key=key, bad=bad):
                data[key] = bad
                with self.assertRaises(ContractError) as raised:
                    record_type.from_dict(data)
                self.assertIn("E_BAD_ENUM", raised.exception.codes)

    def test_empty_string_rejected(self):
        data = valid_observation()
        data["object_id"] = ""
        with self.assertRaises(ContractError) as raised:
            ObservationRecord.from_dict(data)
        self.assertIn("E_EMPTY_STRING", raised.exception.codes)

    def test_non_finite_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                data = valid_observation()
                data["confidence"] = bad
                with self.assertRaises(ContractError) as raised:
                    ObservationRecord.from_dict(data)
                self.assertIn("E_NON_FINITE", raised.exception.codes)

    def test_int_rejected_for_bool_field(self):
        data = valid_frame()
        data["valid"] = 1
        with self.assertRaises(ContractError) as raised:
            FrameRecord.from_dict(data)
        self.assertIn("E_WRONG_TYPE", raised.exception.codes)

    def test_float_rejected_for_int_field(self):
        data = valid_frame()
        data["frame_index"] = 3.0
        with self.assertRaises(ContractError) as raised:
            FrameRecord.from_dict(data)
        self.assertIn("E_WRONG_TYPE", raised.exception.codes)

    def test_dispatcher_type_guards(self):
        with self.assertRaises(ContractError) as raised:
            parse_record({"not": "a string"}, {})
        self.assertIn("E_BAD_SCHEMA", raised.exception.codes)
        with self.assertRaises(ContractError) as raised:
            parse_json("frame", ["not", "a string"])
        self.assertIn("E_MALFORMED_JSON", raised.exception.codes)

    def test_media_scope_locked(self):
        data = valid_media()
        data["container"] = "mov"
        with self.assertRaises(ContractError) as raised:
            MediaMetadata.from_dict(data)
        self.assertIn("E_BAD_ENUM", raised.exception.codes)
        data = valid_media()
        data["codec"] = "hevc"
        with self.assertRaises(ContractError) as raised:
            MediaMetadata.from_dict(data)
        self.assertIn("E_BAD_ENUM", raised.exception.codes)
        data = valid_media()
        data["video_stream_count"] = 2
        with self.assertRaises(ContractError) as raised:
            MediaMetadata.from_dict(data)
        self.assertIn("E_OUT_OF_RANGE", raised.exception.codes)

    def test_fit_count_rules(self):
        data = valid_fit()
        data["rejected_count"] = 235
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        data = valid_fit()
        data["initial_conditions"] = {"theta0_rad": 0.3, "omega0_rad_s": None}
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        data = valid_fit()
        data["initial_conditions"] = {"theta0_rad": None, "omega0_rad_s": None}
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_validity_gates(self):
        frame = valid_frame()
        frame.update({"pts_seconds": None, "valid": True})
        with self.assertRaises(ContractError) as raised:
            FrameRecord.from_dict(frame)
        self.assertIn("E_MISSING_MAPPING", raised.exception.codes)
        media = valid_media()
        media.update({"source_sha256": None, "valid": True})
        with self.assertRaises(ContractError) as raised:
            MediaMetadata.from_dict(media)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        observation = valid_observation()
        observation.update({"confidence": None, "valid": True})
        with self.assertRaises(ContractError) as raised:
            ObservationRecord.from_dict(observation)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        calibration = valid_calibration()
        calibration.update({"same_plane_assumption": None, "valid": True})
        with self.assertRaises(ContractError) as raised:
            CalibrationRecord.from_dict(calibration)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_taxonomy_meanings_present(self):
        for code, meaning in list(WARNING_CODES.items()) + list(ERROR_CODES.items()):
            with self.subTest(code=code):
                self.assertIsInstance(meaning, str)
                self.assertTrue(meaning.strip(), code)


if __name__ == "__main__":
    unittest.main()
