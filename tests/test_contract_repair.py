"""Gate-repair tests for KL-1-G1 BLOCK findings.

Covers the blocking semantic gaps: locked unit vocabulary, fit
cross-field arithmetic, result support, metric bounds, valid
observation PTS, calibration dimension provenance, and negative PTS.
All numeric values are synthetic test constants, not measurements.
"""

import unittest

from kineticlab.contracts import (
    CalibrationRecord,
    ContractError,
    ERROR_CODES,
    FitRecord,
    FrameRecord,
    ObservationRecord,
    ResultContract,
    UNIT_VOCABULARY,
    validate_frame_table,
)
from tests.contract_samples import (
    valid_calibration,
    valid_fit,
    valid_frame,
    valid_observation,
    valid_result,
)


def valid_gravity_result():
    """Success result reporting gravity, with a consistent supporting fit."""
    data = valid_result()
    data["measurement_name"] = "pendulum_gravity"
    data["value"] = 9.75
    data["unit"] = "m/s^2"
    data["identifiable_quantity"] = {"name": "gravity", "value": 9.75, "unit": "m/s^2"}
    fit = data["fit"]
    fit["pivot_length_mm"] = 650.0
    fit["pivot_length_source"] = "independent_measurement"
    fit["gravity_m_s2"] = 9.75
    return data


class UnitVocabularyTest(unittest.TestCase):
    def test_locked_vocabulary_accepted(self):
        record = FitRecord.from_dict(valid_fit())
        self.assertEqual(record.parameter_units["g_over_l"], "1/s^2")

    def test_unit_outside_vocabulary_rejected(self):
        for bad in ("m", "furlongs", "1/s^2 "):
            with self.subTest(bad=bad):
                data = valid_fit()
                data["parameter_units"] = {"g_over_l": bad}
                with self.assertRaises(ContractError) as raised:
                    FitRecord.from_dict(data)
                self.assertIn("E_BAD_ENUM", raised.exception.codes)

    def test_dimensionally_false_binding_rejected(self):
        data = valid_fit()
        data["parameter_units"] = {"g_over_l": "m/s^2"}
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        self.assertTrue(any(error.field == "parameter_units.g_over_l"
                            for error in raised.exception.errors))

    def test_known_parameter_bindings(self):
        FitRecord.from_dict(valid_fit())
        bad = {"g_over_l": "m/s^2"}
        data = valid_fit()
        data["parameter_units"] = bad
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)


class FitCrossFieldTest(unittest.TestCase):
    def test_summary_requires_underlying_parameter(self):
        data = valid_fit()
        data["parameter_names"] = []
        data["parameters"] = {}
        data["parameter_units"] = {}
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_summary_must_equal_parameter(self):
        data = valid_fit()
        data["g_over_l_per_s2"] = 15.3
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_summary_required_when_parameter_present(self):
        data = valid_fit()
        data["g_over_l_per_s2"] = None
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_gravity_arithmetic_identity(self):
        data = valid_fit()
        data["pivot_length_mm"] = 650.0
        data["pivot_length_source"] = "independent_measurement"
        data["gravity_m_s2"] = 15.0 * 650.0 / 1000.0
        record = FitRecord.from_dict(data)
        self.assertEqual(record.gravity_m_s2, 9.75)

    def test_gravity_arithmetic_mismatch_rejected(self):
        data = valid_fit()
        data["pivot_length_mm"] = 650.0
        data["pivot_length_source"] = "independent_measurement"
        data["gravity_m_s2"] = 9.81
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_gravity_unverifiable_without_g_over_l(self):
        data = valid_fit()
        data["parameter_names"] = ["theta0"]
        data["parameters"] = {"theta0": 0.31}
        data["parameter_units"] = {"theta0": "rad"}
        data["g_over_l_per_s2"] = None
        data["pivot_length_mm"] = 650.0
        data["pivot_length_source"] = "independent_measurement"
        data["gravity_m_s2"] = 9.75
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_rmse_cannot_exceed_max_abs(self):
        data = valid_fit()
        data["residual_summary"] = {"rmse": 0.05, "max_abs": 0.03, "dof": 200}
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_rmse_equal_or_null_accepted(self):
        data = valid_fit()
        data["residual_summary"] = {"rmse": 0.03, "max_abs": 0.03, "dof": 200}
        FitRecord.from_dict(data)
        data = valid_fit()
        data["residual_summary"] = {"rmse": None, "max_abs": 0.03, "dof": None}
        FitRecord.from_dict(data)


class ResultUnitTest(unittest.TestCase):
    def test_result_unit_restricted(self):
        data = valid_result()
        data["unit"] = "rad"
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_BAD_ENUM", raised.exception.codes)

    def test_quantity_unit_restricted(self):
        data = valid_result()
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": 15.0, "unit": "m"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_BAD_ENUM", raised.exception.codes)

    def test_interval_method_without_interval_rejected(self):
        data = valid_result()
        data["interval_method"] = "analytic_linearized"
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_interval_method_vocabulary(self):
        data = valid_result()
        data["interval"] = {"lower": 14.0, "upper": 16.0}
        data["interval_method"] = "analytic_linearized"
        ResultContract.from_dict(data)
        data["interval_method"] = "bootstrap"
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_BAD_ENUM", raised.exception.codes)

    def test_value_must_lie_within_interval(self):
        data = valid_result()
        data["interval"] = {"lower": 14.0, "upper": 16.0}
        data["interval_method"] = "analytic_linearized"
        ResultContract.from_dict(data)
        data["value"] = 20.0
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": 20.0,
                                         "unit": "1/s^2"}
        data["fit"]["parameters"] = {"g_over_l": 20.0}
        data["fit"]["g_over_l_per_s2"] = 20.0
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)


class ResultSupportTest(unittest.TestCase):
    def test_value_quantity_agreement(self):
        data = valid_result()
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": 15.3,
                                         "unit": "1/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        data = valid_result()
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": 15.0,
                                         "unit": "m/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_value_fit_agreement_g_over_l(self):
        data = valid_result()
        data["fit"]["g_over_l_per_s2"] = 15.9
        data["fit"]["parameters"] = {"g_over_l": 15.9}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_value_fit_agreement_gravity(self):
        record = ResultContract.from_dict(valid_gravity_result())
        self.assertEqual(record.value, 9.75)
        data = valid_gravity_result()
        data["value"] = 9.81
        data["identifiable_quantity"] = {"name": "gravity", "value": 9.81,
                                         "unit": "m/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_success_requires_fit(self):
        data = valid_result()
        data["fit"] = None
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_success_requires_positive_observations(self):
        data = valid_result()
        data["fit"]["observation_count"] = 0
        data["fit"]["rejected_count"] = 0
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_success_requires_converged_fit(self):
        data = valid_result()
        data["fit"]["converged"] = False
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_STATE", raised.exception.codes)

    def test_failure_without_fit_still_valid(self):
        data = valid_result(status="insufficient_data")
        data["value"] = None
        data["unit"] = None
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": None,
                                         "unit": "1/s^2"}
        data["calibration"] = None
        data["fit"] = None
        data["quality_metrics"] = None
        data["reject_reasons"] = [{"code": "E_MISSING_MAPPING", "field": "frames",
                                   "detail": "no usable frames"}]
        record = ResultContract.from_dict(data)
        self.assertIsNone(record.fit)


class ModelParameterSetTest(unittest.TestCase):
    def test_m2_requires_g_over_l_and_gamma(self):
        data = valid_fit()
        data["model_id"] = "M2"
        data["parameter_names"] = ["g_over_l", "gamma"]
        data["parameters"] = {"g_over_l": 15.0, "gamma": 0.02}
        data["parameter_units"] = {"g_over_l": "1/s^2", "gamma": "1/s"}
        FitRecord.from_dict(data)
        data["parameter_names"] = ["g_over_l"]
        data["parameters"] = {"g_over_l": 15.0}
        data["parameter_units"] = {"g_over_l": "1/s^2"}
        with self.assertRaises(ContractError) as raised:
            FitRecord.from_dict(data)
        self.assertIn("E_PARAMETER_MISMATCH", raised.exception.codes)


class MetricBoundsTest(unittest.TestCase):
    def test_usable_cannot_exceed_total(self):
        data = valid_result()
        data["quality_metrics"]["frames_usable"] = 235
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_valid_cannot_exceed_total(self):
        data = valid_result()
        data["quality_metrics"]["observations_valid"] = 469
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_calibrated_cannot_exceed_usable(self):
        data = valid_result()
        data["quality_metrics"]["calibrated_frames"] = 231
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_null_counts_skip_bounds(self):
        data = valid_result()
        data["quality_metrics"] = {"frames_total": None, "frames_usable": 230,
                                   "observations_total": None,
                                   "observations_valid": None,
                                   "calibrated_frames": None}
        ResultContract.from_dict(data)


class ObservationPtsTest(unittest.TestCase):
    def test_valid_observation_requires_pts(self):
        data = valid_observation()
        data["pts_seconds"] = None
        with self.assertRaises(ContractError) as raised:
            ObservationRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_invalid_observation_may_omit_pts(self):
        data = valid_observation()
        data["pts_seconds"] = None
        data["valid"] = False
        record = ObservationRecord.from_dict(data)
        self.assertIsNone(record.pts_seconds)


class CalibrationProvenanceTest(unittest.TestCase):
    def test_dimensions_require_confirmed_source(self):
        data = valid_calibration()
        data["reference_dimensions_mm"] = {"width_mm": 85.6, "height_mm": 53.98}
        with self.assertRaises(ContractError) as raised:
            CalibrationRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_confirmed_source_requires_dimensions(self):
        data = valid_calibration()
        data["dimension_source"] = "user_confirmed"
        with self.assertRaises(ContractError) as raised:
            CalibrationRecord.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_coherent_combinations_pass(self):
        data = valid_calibration()
        data["reference_type"] = "iso_id1_confirmed"
        data["reference_dimensions_mm"] = {"width_mm": 85.6, "height_mm": 53.98}
        data["dimension_source"] = "user_confirmed"
        record = CalibrationRecord.from_dict(data)
        self.assertEqual(record.dimension_source.value, "user_confirmed")
        data = valid_calibration()
        data["reference_dimensions_mm"] = {"width_mm": 90.0, "height_mm": 55.0}
        data["dimension_source"] = "user_confirmed"
        CalibrationRecord.from_dict(data)


class NegativePtsTest(unittest.TestCase):
    def test_negative_pts_preserved(self):
        frame = valid_frame()
        frame["pts_seconds"] = -0.033
        self.assertEqual(FrameRecord.from_dict(frame).pts_seconds, -0.033)
        observation = valid_observation()
        observation["pts_seconds"] = -0.033
        self.assertEqual(ObservationRecord.from_dict(observation).pts_seconds, -0.033)

    def test_negative_pts_table_orders(self):
        first = valid_frame(index=0)
        first["pts_seconds"] = -0.033
        second = valid_frame(index=1)
        validate_frame_table([FrameRecord.from_dict(first),
                              FrameRecord.from_dict(second)])

    def test_non_finite_pts_still_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(bad=bad):
                data = valid_frame()
                data["pts_seconds"] = bad
                with self.assertRaises(ContractError) as raised:
                    FrameRecord.from_dict(data)
                self.assertIn("E_NON_FINITE", raised.exception.codes)


class TaxonomyStableTest(unittest.TestCase):
    def test_no_new_error_codes_added(self):
        self.assertEqual(
            set(ERROR_CODES),
            {"E_MALFORMED_JSON", "E_BAD_SCHEMA", "E_NOT_AN_OBJECT", "E_BAD_VERSION",
             "E_MISSING_FIELD", "E_UNEXPECTED_FIELD", "E_NULL_NOT_ALLOWED",
             "E_WRONG_TYPE", "E_BAD_ENUM", "E_EMPTY_STRING", "E_NON_FINITE",
             "E_OUT_OF_RANGE", "E_BAD_SHA256", "E_BAD_TIME_BASE", "E_BBOX_ORDER",
             "E_CENTROID_PAIR", "E_CORNERS_SHAPE", "E_TRANSFORM_SHAPE",
             "E_PARAMETER_MISMATCH", "E_INCOHERENT_VALUE", "E_MISSING_MAPPING",
             "E_NON_MONOTONIC_PTS", "E_DUPLICATE_FRAME", "E_UNCONFIRMED_DIMENSIONS",
             "E_SCALE_AMBIGUOUS", "E_GRAVITY_WITHOUT_LENGTH", "E_VALUE_WITHOUT_UNIT",
             "E_INTERVAL_WITHOUT_METHOD", "E_INTERVAL_ORDER", "E_INCOHERENT_STATE",
             "E_UNKNOWN_WARNING_CODE", "E_UNKNOWN_REASON_CODE"})


def fit_without_g_over_l():
    """Raw invalid fit whose g/L summary has no underlying fitted parameter."""
    data = valid_fit()
    data["parameter_names"] = ["theta0"]
    data["parameters"] = {"theta0": 0.31}
    data["parameter_units"] = {"theta0": "rad"}
    return data


class QuantityNameBindingTest(unittest.TestCase):
    def test_locked_name_unit_pairs_pass(self):
        ResultContract.from_dict(valid_result())
        ResultContract.from_dict(valid_gravity_result())

    def test_measurement_name_locks_unit(self):
        data = valid_result()
        data["unit"] = "m/s^2"
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": 15.0,
                                         "unit": "m/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        data = valid_gravity_result()
        data["unit"] = "1/s^2"
        data["identifiable_quantity"] = {"name": "gravity", "value": 9.75,
                                         "unit": "1/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_mismatched_name_unit_rejected(self):
        data = valid_result()
        data["identifiable_quantity"] = {"name": "gravity", "value": 15.0,
                                         "unit": "1/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)
        data = valid_gravity_result()
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": 9.75,
                                         "unit": "m/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)

    def test_unknown_quantity_name_rejected(self):
        data = valid_result()
        data["identifiable_quantity"] = {"name": "pendulum_period", "value": 15.0,
                                         "unit": "1/s^2"}
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_BAD_ENUM", raised.exception.codes)

    def test_binding_applies_on_failure_states(self):
        data = valid_result(status="insufficient_data")
        data["value"] = None
        data["unit"] = None
        data["identifiable_quantity"] = {"name": "gravity", "value": None,
                                         "unit": "1/s^2"}
        data["calibration"] = None
        data["fit"] = None
        data["quality_metrics"] = None
        data["reject_reasons"] = [{"code": "E_MISSING_MAPPING", "field": "frames",
                                   "detail": "no usable frames"}]
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_INCOHERENT_VALUE", raised.exception.codes)


class FitParameterSupportTest(unittest.TestCase):
    def test_g_over_l_result_requires_parameter(self):
        data = valid_result()
        data["fit"] = fit_without_g_over_l()
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_PARAMETER_MISMATCH", raised.exception.codes)

    def test_gravity_result_requires_parameter(self):
        data = valid_gravity_result()
        fit = fit_without_g_over_l()
        fit["pivot_length_mm"] = 650.0
        fit["pivot_length_source"] = "independent_measurement"
        fit["gravity_m_s2"] = 15.0 * 650.0 / 1000.0
        data["fit"] = fit
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_PARAMETER_MISMATCH", raised.exception.codes)

    def test_full_support_chains_pass(self):
        g_over_l = ResultContract.from_dict(valid_result())
        self.assertIn("g_over_l", g_over_l.fit.parameters)
        gravity = ResultContract.from_dict(valid_gravity_result())
        self.assertIn("g_over_l", gravity.fit.parameters)
        self.assertEqual(gravity.value, gravity.fit.gravity_m_s2)

    def test_failure_with_parameterless_fit_preserved(self):
        data = valid_result(status="insufficient_data")
        data["value"] = None
        data["unit"] = None
        data["identifiable_quantity"] = {"name": "g/L_eff", "value": None,
                                         "unit": "1/s^2"}
        data["calibration"] = None
        data["fit"] = fit_without_g_over_l()
        data["quality_metrics"] = None
        data["reject_reasons"] = [{"code": "E_MISSING_MAPPING", "field": "frames",
                                   "detail": "no usable frames"}]
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_PARAMETER_MISMATCH", raised.exception.codes)


if __name__ == "__main__":
    unittest.main()
