"""Deterministic synthetic trajectory tests (KL-5.1).

The generator must be seeded-deterministic (same seed + spec =
identical bytes), must reproduce hand-computed angle/projection
values, must record every imperfection in ground truth, and must
reject malformed specs with registered codes only. All parameters
below are TEST constants; nothing here is a measurement or a
physical claim.
"""

import copy
import hashlib
import math
import os
import unittest

from kineticlab.contracts import ContractError
from kineticlab.fit import (
    CSV_COLUMNS,
    DISCLAIMER,
    export_synthetic_csv,
    export_trajectory_json,
    generate_trajectory,
    parse_trajectory_json,
)
from kineticlab.fit import synthetic as synthetic_module

# Hand case: ideal, A=0.5, omega=2.0, phi=0.1, pivot (512, 288),
# L=200, uniform t0=0 dt=0.033 n=5. theta(t) = 0.5*cos(2t+0.1);
# x = 512+200*sin(theta); y = 288+200*cos(theta).
IDEAL_THETA = (
    0.4975020826390129,
    0.493126804916798,
    0.4866042464650668,
    0.4779628092362802,
    0.4672401216689084,
)
IDEAL_TRUE_X = (
    607.4463832915853,
    606.6764931529588,
    605.5253991162798,
    603.994248140397,
    602.0847887406811,
)
IDEAL_TRUE_Y = (
    463.75547762888004,
    464.1713984852756,
    464.7851795828501,
    465.5867627642417,
    466.5629604300591,
)

# Byte pins for full_spec() (damped, 234-grid jittered/noisy/gapped
# trajectory): canonical JSON + CSV sha256. Byte-stability holds on
# a given platform/CPython+libm build (see module docstring); these
# pins were measured on the verified Windows/CPython 3.15 platform.
FULL_JSON_SHA = "25a8aaeafcc319ee697bc515dc7b38db6eef8fab647d47dfe92646b7c30b526c"
FULL_CSV_SHA = "9c54bee8fc2c21936cd05bfc8d9ee622ee7af5828247fb50d9ba129f233a5a8f"


# Same spec but damped with gamma=0.3:
# theta(t) = 0.5*exp(-0.3t)*cos(2t+0.1).
DAMPED_THETA = (
    0.4975020826390129,
    0.48826893567743873,
    0.47706424011786663,
    0.4639760453624202,
    0.44909897811585175,
)
DAMPED_TRUE_X = (
    607.4463832915853,
    605.8195617734117,
    603.8346370417195,
    601.5014667572906,
    598.8308070229955,
)
DAMPED_TRUE_Y = (
    463.75547762888004,
    464.62924397914685,
    465.66935424944745,
    466.85605231105154,
    468.1677300510147,
)


def make_spec(**overrides):
    spec = {
        "model": "ideal",
        "seed": 7,
        "amplitude_rad": 0.5,
        "angular_frequency_per_s": 2.0,
        "period_s": None,
        "phase_rad": 0.1,
        "damping_per_s": None,
        "pivot_x_px": 512.0,
        "pivot_y_px": 288.0,
        "length_px": 200.0,
        "time": {"mode": "uniform", "t0_s": 0.0, "dt_s": 0.033, "n": 5},
        "noise": {"mode": "none"},
        "gaps": [],
        "outliers": [],
    }
    for key, value in overrides.items():
        # Dict overrides REPLACE wholesale: time/noise specs have
        # mode-dependent key sets, so merging would smuggle stale keys.
        spec[key] = value
    return spec


def full_spec():
    """Realistic-scale TEST trajectory: 234 samples at ~30fps framing
    (test_3 has 234 frames over ~7.83 s at 1024x576), jittered time,
    seeded noise, two gaps, two outliers."""
    return {
        "model": "damped",
        "seed": 20261028,
        "amplitude_rad": 0.35,
        "angular_frequency_per_s": None,
        "period_s": 2.0,
        "phase_rad": 0.0,
        "damping_per_s": 0.05,
        "pivot_x_px": 512.0,
        "pivot_y_px": 288.0,
        "length_px": 200.0,
        "time": {"mode": "jittered", "t0_s": 0.0, "dt_s": 1.0 / 30.0,
                 "n": 234, "jitter_s": 0.005},
        "noise": {"mode": "gaussian", "sigma_px": 1.5},
        "gaps": [[50, 59], [200, 209]],
        "outliers": [
            {"sample_index": 100, "dx_px": 8.0, "dy_px": -6.0},
            {"sample_index": 150, "dx_px": -12.0, "dy_px": 4.0},
        ],
    }


class SyntheticHandCases(unittest.TestCase):
    def test_ideal_hand_computed_five_points(self):
        traj = generate_trajectory(make_spec())
        self.assertEqual(len(traj["samples"]), 5)
        for index, sample in enumerate(traj["samples"]):
            self.assertEqual(sample["sample_index"], index)
            self.assertAlmostEqual(sample["t_seconds"], index * 0.033)
            self.assertEqual(sample["theta_rad"], IDEAL_THETA[index])
            self.assertEqual(sample["true_x_px"], IDEAL_TRUE_X[index])
            self.assertEqual(sample["true_y_px"], IDEAL_TRUE_Y[index])
            # No noise, no outliers: observed equals clean truth exactly.
            self.assertEqual(sample["x_px"], IDEAL_TRUE_X[index])
            self.assertEqual(sample["y_px"], IDEAL_TRUE_Y[index])
            self.assertIs(sample["is_outlier"], False)
        truth = traj["ground_truth"]
        self.assertEqual(truth["angular_frequency_per_s"], 2.0)
        self.assertEqual(truth["period_s"], math.pi)
        self.assertEqual(truth["omega_source"], "angular_frequency_per_s")
        self.assertIsNone(truth["damping_per_s"])
        self.assertEqual(truth["gaps"], [])
        self.assertEqual(truth["outliers"], [])

    def test_zero_amplitude_is_exact_pivot(self):
        traj = generate_trajectory(make_spec(amplitude_rad=0.0))
        for sample in traj["samples"]:
            self.assertEqual(sample["theta_rad"], 0.0)
            self.assertEqual(sample["true_x_px"], 512.0)
            self.assertEqual(sample["true_y_px"], 488.0)
            self.assertEqual(sample["x_px"], 512.0)
            self.assertEqual(sample["y_px"], 488.0)

    def test_damped_hand_computed_five_points(self):
        spec = make_spec(model="damped", damping_per_s=0.3)
        traj = generate_trajectory(spec)
        for index, sample in enumerate(traj["samples"]):
            self.assertEqual(sample["theta_rad"], DAMPED_THETA[index])
            self.assertEqual(sample["true_x_px"], DAMPED_TRUE_X[index])
            self.assertEqual(sample["true_y_px"], DAMPED_TRUE_Y[index])
        truth = traj["ground_truth"]
        self.assertEqual(truth["damping_per_s"], 0.3)
        # Sample 0 is un-decayed (exp(0) == 1): models agree exactly.
        self.assertEqual(DAMPED_THETA[0], IDEAL_THETA[0])

    def test_damped_envelope_matches_decay_law(self):
        ideal = generate_trajectory(make_spec())
        damped = generate_trajectory(
            make_spec(model="damped", damping_per_s=0.3))
        for ideal_sample, damped_sample in zip(ideal["samples"],
                                               damped["samples"]):
            moment = ideal_sample["t_seconds"]
            self.assertAlmostEqual(
                damped_sample["theta_rad"],
                ideal_sample["theta_rad"] * math.exp(-0.3 * moment))

    def test_damped_decays_over_a_run(self):
        long_time = {"mode": "uniform", "t0_s": 0.0, "dt_s": 0.05, "n": 60}
        ideal = generate_trajectory(make_spec(time=long_time))
        damped = generate_trajectory(
            make_spec(model="damped", damping_per_s=0.3, time=long_time))
        ideal_peak = max(abs(sample["theta_rad"])
                         for sample in ideal["samples"])
        damped_peak = max(abs(sample["theta_rad"])
                          for sample in damped["samples"])
        self.assertLess(damped_peak, ideal_peak)

    def test_period_source_gives_same_curve(self):
        by_omega = generate_trajectory(make_spec())
        by_period = generate_trajectory(make_spec(
            angular_frequency_per_s=None, period_s=math.pi))
        truth = by_period["ground_truth"]
        self.assertEqual(truth["omega_source"], "period_s")
        self.assertAlmostEqual(truth["angular_frequency_per_s"], 2.0)
        for omega_sample, period_sample in zip(by_omega["samples"],
                                               by_period["samples"]):
            self.assertAlmostEqual(period_sample["theta_rad"],
                                   omega_sample["theta_rad"], places=12)


# KL-10.10: see tests/test_fit_m1.py — same-platform byte pins.
PIN_SAME_PLATFORM = unittest.skipIf(
    os.environ.get("KL_CROSS_PLATFORM") == "1",
    "byte pins are same-platform determinism; cross-platform "
    "libm drifts in the last ulp (KL-10.10)")


class SyntheticDeterminism(unittest.TestCase):
    def test_same_seed_identical_bytes(self):
        first = export_trajectory_json(generate_trajectory(full_spec()))
        second = export_trajectory_json(generate_trajectory(full_spec()))
        self.assertEqual(first, second)
        first_csv = export_synthetic_csv(generate_trajectory(full_spec()))
        second_csv = export_synthetic_csv(generate_trajectory(full_spec()))
        self.assertEqual(first_csv, second_csv)

    @PIN_SAME_PLATFORM
    def test_full_spec_byte_pins(self):
        traj = generate_trajectory(full_spec())
        self.assertEqual(len(traj["samples"]), 214)  # 234 grid - 20 gapped
        payload = export_trajectory_json(traj)
        self.assertEqual(hashlib.sha256(payload).hexdigest(), FULL_JSON_SHA)
        text = export_synthetic_csv(traj)
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest(), FULL_CSV_SHA)

    def test_different_seed_different_data(self):
        base = export_trajectory_json(generate_trajectory(full_spec()))
        other_spec = full_spec()
        other_spec["seed"] = 1
        other = export_trajectory_json(generate_trajectory(other_spec))
        self.assertNotEqual(base, other)

    def test_noise_independent_of_gaps(self):
        with_gaps = generate_trajectory(full_spec())
        spec = full_spec()
        spec["gaps"] = []
        without_gaps = generate_trajectory(spec)
        shared = {sample["sample_index"]: sample
                  for sample in without_gaps["samples"]}
        for sample in with_gaps["samples"]:
            twin = shared[sample["sample_index"]]
            self.assertEqual(sample["x_px"], twin["x_px"])
            self.assertEqual(sample["y_px"], twin["y_px"])


class SyntheticImperfections(unittest.TestCase):
    def test_jittered_time_strictly_increasing_nonuniform(self):
        spec = make_spec(time={"mode": "jittered", "t0_s": 0.0,
                               "dt_s": 0.033, "n": 25, "jitter_s": 0.005})
        traj = generate_trajectory(spec)
        moments = [sample["t_seconds"] for sample in traj["samples"]]
        for earlier, later in zip(moments, moments[1:]):
            self.assertLess(earlier, later)
        steps = {round(later - earlier, 12)
                 for earlier, later in zip(moments, moments[1:])}
        self.assertGreater(len(steps), 1)
        # Jitter actually moved the grid (not secretly uniform).
        for index, moment in enumerate(moments):
            if abs(moment - index * 0.033) > 1e-9:
                break
        else:
            self.fail("jittered times equal the uniform grid")

    def test_explicit_times_used_verbatim(self):
        moments = [0.0, 0.02, 0.05, 0.051, 1.25]
        spec = make_spec(time={"mode": "explicit", "times_s": moments})
        traj = generate_trajectory(spec)
        self.assertEqual([sample["t_seconds"] for sample in traj["samples"]],
                         moments)
        self.assertEqual([sample["sample_index"]
                          for sample in traj["samples"]], [0, 1, 2, 3, 4])

    def test_zero_sigma_noise_is_clean(self):
        spec = make_spec(noise={"mode": "gaussian", "sigma_px": 0.0})
        traj = generate_trajectory(spec)
        for sample in traj["samples"]:
            self.assertEqual(sample["x_px"], sample["true_x_px"])
            self.assertEqual(sample["y_px"], sample["true_y_px"])

    def test_gaussian_noise_moves_every_sample(self):
        spec = make_spec(noise={"mode": "gaussian", "sigma_px": 5.0})
        traj = generate_trajectory(spec)
        for sample in traj["samples"]:
            moved = (sample["x_px"] != sample["true_x_px"]
                     or sample["y_px"] != sample["true_y_px"])
            self.assertTrue(moved, f"sample {sample['sample_index']} unmoved")
        # ... and the same seed reproduces the same noise.
        twin = generate_trajectory(spec)
        self.assertEqual(traj["samples"], twin["samples"])

    def test_gaps_absent_from_samples_listed_in_truth(self):
        spec = make_spec(
            time={"mode": "uniform", "t0_s": 1.0, "dt_s": 0.5, "n": 8},
            gaps=[[2, 3], [6, 6]])
        traj = generate_trajectory(spec)
        self.assertEqual([sample["sample_index"]
                          for sample in traj["samples"]], [0, 1, 4, 5, 7])
        self.assertEqual(traj["ground_truth"]["gaps"], [
            {"start_index": 2, "end_index": 3, "start_t_seconds": 2.0,
             "end_t_seconds": 2.5, "count": 2},
            {"start_index": 6, "end_index": 6, "start_t_seconds": 4.0,
             "end_t_seconds": 4.0, "count": 1},
        ])

    def test_outliers_applied_and_listed_with_truth(self):
        spec = make_spec(
            outliers=[{"sample_index": 1, "dx_px": 10.0, "dy_px": -4.0}])
        traj = generate_trajectory(spec)
        flagged = [sample for sample in traj["samples"]
                   if sample["is_outlier"]]
        self.assertEqual([sample["sample_index"] for sample in flagged], [1])
        sample = flagged[0]
        self.assertEqual(sample["x_px"], sample["true_x_px"] + 10.0)
        self.assertEqual(sample["y_px"], sample["true_y_px"] - 4.0)
        self.assertEqual(traj["ground_truth"]["outliers"], [{
            "sample_index": 1,
            "t_seconds": sample["t_seconds"],
            "dx_px": 10.0,
            "dy_px": -4.0,
            "true_x_px": sample["true_x_px"],
            "true_y_px": sample["true_y_px"],
        }])

    def test_outlier_offset_applies_after_noise(self):
        noisy = make_spec(noise={"mode": "gaussian", "sigma_px": 2.0})
        plain = generate_trajectory(noisy)
        shifted_spec = make_spec(
            noise={"mode": "gaussian", "sigma_px": 2.0},
            outliers=[{"sample_index": 3, "dx_px": 7.0, "dy_px": 7.0}])
        shifted = generate_trajectory(shifted_spec)
        for plain_sample, shifted_sample in zip(plain["samples"],
                                                shifted["samples"]):
            if plain_sample["sample_index"] == 3:
                self.assertEqual(shifted_sample["x_px"],
                                 plain_sample["x_px"] + 7.0)
                self.assertEqual(shifted_sample["y_px"],
                                 plain_sample["y_px"] + 7.0)
            else:
                self.assertEqual(shifted_sample["x_px"],
                                 plain_sample["x_px"])
                self.assertEqual(shifted_sample["y_px"],
                                 plain_sample["y_px"])


class SyntheticExports(unittest.TestCase):
    def test_module_and_exports_state_test_data(self):
        self.assertIn("NOT MEASUREMENTS", synthetic_module.__doc__)
        traj = generate_trajectory(make_spec())
        payload = export_trajectory_json(traj)
        # Canonical JSON is ASCII-only (ensure_ascii), so the em dash
        # in DISCLAIMER is \u2014-escaped in bytes; the parsed-back
        # text must carry the disclaimer verbatim.
        self.assertIn(b"SYNTHETIC TEST DATA", payload)
        self.assertEqual(parse_trajectory_json(payload)["disclaimer"],
                         DISCLAIMER)
        self.assertTrue(traj["synthetic"])
        text = export_synthetic_csv(traj)
        lines = text.splitlines()
        self.assertEqual(lines[0], f"# {DISCLAIMER}")
        self.assertEqual(lines[1], ",".join(CSV_COLUMNS))

    def test_json_round_trip_exact(self):
        traj = generate_trajectory(full_spec())
        self.assertEqual(parse_trajectory_json(
            export_trajectory_json(traj)), traj)

    def test_csv_contract_and_cells(self):
        traj = generate_trajectory(make_spec(
            outliers=[{"sample_index": 0, "dx_px": 1.0, "dy_px": 2.0}]))
        rows = export_synthetic_csv(traj).splitlines()
        self.assertEqual(len(rows), 2 + 5)
        first = rows[2].split(",")
        self.assertEqual(first[0], "0")
        self.assertEqual(first[1], repr(0.0))
        self.assertEqual(first[2], repr(IDEAL_THETA[0]))
        self.assertEqual(first[5], repr(IDEAL_TRUE_X[0] + 1.0))
        self.assertEqual(first[7], "true")
        self.assertEqual(rows[3].split(",")[7], "false")

    def test_empty_sample_export_is_valid(self):
        spec = make_spec(time={"mode": "uniform", "t0_s": 0.0,
                               "dt_s": 0.033, "n": 2},
                         gaps=[[0, 1]])
        traj = generate_trajectory(spec)
        self.assertEqual(traj["samples"], [])
        text = export_synthetic_csv(traj)
        self.assertEqual(text.splitlines(),
                         [f"# {DISCLAIMER}", ",".join(CSV_COLUMNS)])
        self.assertEqual(parse_trajectory_json(
            export_trajectory_json(traj)), traj)


class SyntheticRejections(unittest.TestCase):
    def assert_codes(self, spec, codes):
        with self.assertRaises(ContractError) as raised:
            generate_trajectory(spec)
        self.assertEqual(raised.exception.codes, codes)

    def mutate(self, path, value):
        """Copy make_spec() and set one nested path (unset = delete)."""
        spec = make_spec()
        target = spec
        *parents, leaf = path
        for key in parents:
            target = target[key]
        if value == "unset":
            del target[leaf]
        else:
            target[leaf] = value
        return spec

    def test_non_dict_spec_rejected(self):
        with self.assertRaises(ContractError) as raised:
            generate_trajectory([])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])

    def test_shape_rejections(self):
        cells = [
            (("model",), "unset", ["E_MISSING_FIELD"]),
            (("seed",), None, ["E_NULL_NOT_ALLOWED"]),
            (("seed",), True, ["E_WRONG_TYPE"]),
            (("seed",), 1.5, ["E_WRONG_TYPE"]),
            (("model",), "M1", ["E_BAD_ENUM"]),
            (("model",), None, ["E_NULL_NOT_ALLOWED"]),
            (("amplitude_rad",), "x", ["E_WRONG_TYPE"]),
            (("time",), [], ["E_WRONG_TYPE"]),
            (("time", "mode"), "vfr", ["E_BAD_ENUM"]),
            (("time", "mode"), "unset", ["E_MISSING_FIELD"]),
            (("time", "dt_s"), "unset", ["E_MISSING_FIELD"]),
            (("noise", "mode"), "poisson", ["E_BAD_ENUM"]),
            (("gaps",), {}, ["E_WRONG_TYPE"]),
            (("gaps",), None, ["E_NULL_NOT_ALLOWED"]),
            (("outliers",), {}, ["E_WRONG_TYPE"]),
        ]
        for path, value, codes in cells:
            with self.subTest(path=path, value=value):
                self.assert_codes(self.mutate(path, value), codes)

    def test_unexpected_keys_rejected(self):
        spec = make_spec()
        spec["gravity_m_s2"] = 9.81
        self.assert_codes(spec, ["E_UNEXPECTED_FIELD"])
        spec = make_spec()
        spec["time"]["fps"] = 30.0
        self.assert_codes(spec, ["E_UNEXPECTED_FIELD"])

    def test_range_rejections(self):
        cells = [
            (("amplitude_rad",), -0.5, ["E_OUT_OF_RANGE"]),
            (("angular_frequency_per_s",), 0.0, ["E_OUT_OF_RANGE"]),
            (("angular_frequency_per_s",), float("inf"),
             ["E_NON_FINITE"]),
            (("period_s",), float("nan"), ["E_NON_FINITE"]),
            (("length_px",), 0.0, ["E_OUT_OF_RANGE"]),
            (("phase_rad",), float("inf"), ["E_NON_FINITE"]),
            (("time", "dt_s"), 0.0, ["E_OUT_OF_RANGE"]),
            (("time", "n"), 0, ["E_OUT_OF_RANGE"]),
            (("time", "n"), 100_001, ["E_OUT_OF_RANGE"]),
            (("time", "n"), True, ["E_WRONG_TYPE"]),
            (("noise", "sigma_px"), -1.0, ["E_OUT_OF_RANGE"]),
        ]
        for path, value, codes in cells:
            with self.subTest(path=path, value=value):
                spec = self.mutate(path, value)
                if path[0] == "period_s":
                    spec["angular_frequency_per_s"] = None
                if path[:2] == ("noise", "sigma_px"):
                    spec["noise"] = {"mode": "gaussian", "sigma_px": value}
                self.assert_codes(spec, codes)

    def test_jitter_at_half_step_rejected(self):
        spec = make_spec(time={"mode": "jittered", "t0_s": 0.0,
                               "dt_s": 0.033, "n": 5,
                               "jitter_s": 0.033 / 2.0})
        self.assert_codes(spec, ["E_OUT_OF_RANGE"])

    def test_frequency_source_coherence(self):
        both = make_spec(period_s=2.0)
        self.assert_codes(both, ["E_INCOHERENT_VALUE"])
        neither = make_spec(angular_frequency_per_s=None)
        self.assert_codes(neither, ["E_INCOHERENT_VALUE"])

    def test_damping_coherence(self):
        ideal = make_spec(damping_per_s=0.1)
        self.assert_codes(ideal, ["E_INCOHERENT_VALUE"])
        damped = make_spec(model="damped")
        self.assert_codes(damped, ["E_INCOHERENT_VALUE"])
        damped_bad = make_spec(model="damped", damping_per_s=-0.1)
        self.assert_codes(damped_bad, ["E_OUT_OF_RANGE"])

    def test_explicit_time_rejections(self):
        spec = make_spec(time={"mode": "explicit",
                               "times_s": [0.0, 0.05, 0.05, 0.1]})
        self.assert_codes(spec, ["E_NON_MONOTONIC_PTS"])
        spec = make_spec(time={"mode": "explicit",
                               "times_s": [0.0, float("nan")]})
        self.assert_codes(spec, ["E_NON_FINITE"])
        spec = make_spec(time={"mode": "explicit", "times_s": []})
        self.assert_codes(spec, ["E_OUT_OF_RANGE"])

    def test_gap_rejections(self):
        cells = [
            ([[3, 2]], ["E_INCOHERENT_VALUE"]),  # inverted
            ([[0, 5]], ["E_INCOHERENT_VALUE"]),  # end outside grid
            ([[-1, 1]], ["E_INCOHERENT_VALUE"]),  # start outside grid
            ([[0, 1], [1, 2]], ["E_INCOHERENT_VALUE"]),  # overlapping
            ([[2, 3], [0, 1]], ["E_INCOHERENT_VALUE"]),  # unsorted
            ([[0, "x"]], ["E_WRONG_TYPE"]),  # bad pair shape
        ]
        for gaps, codes in cells:
            with self.subTest(gaps=gaps):
                self.assert_codes(make_spec(gaps=gaps), codes)

    def test_outlier_rejections(self):
        cells = [
            ([{"sample_index": 5, "dx_px": 1.0, "dy_px": 0.0}],
             ["E_INCOHERENT_VALUE"]),  # outside grid
            ([{"sample_index": 1, "dx_px": 1.0, "dy_px": 0.0},
              {"sample_index": 1, "dx_px": 2.0, "dy_px": 0.0}],
             ["E_INCOHERENT_VALUE"]),  # duplicated
            ([{"sample_index": 1, "dx_px": "x", "dy_px": 0.0}],
             ["E_WRONG_TYPE"]),  # bad offset type
            ([{"sample_index": 1, "dx_px": 1.0}],
             ["E_MISSING_FIELD"]),  # missing dy
        ]
        for outliers, codes in cells:
            with self.subTest(outliers=outliers):
                self.assert_codes(make_spec(outliers=outliers), codes)

    def test_outlier_inside_gap_rejected(self):
        spec = make_spec(
            gaps=[[2, 3]],
            outliers=[{"sample_index": 2, "dx_px": 1.0, "dy_px": 1.0}])
        self.assert_codes(spec, ["E_INCOHERENT_VALUE"])

    def test_export_failures(self):
        with self.assertRaises(ContractError) as raised:
            export_trajectory_json([])
        self.assertEqual(raised.exception.codes, ["E_WRONG_TYPE"])
        with self.assertRaises(ContractError) as raised:
            parse_trajectory_json(b"\xff\xfe not json")
        self.assertEqual(raised.exception.codes, ["E_MALFORMED_JSON"])
        with self.assertRaises(ContractError) as raised:
            parse_trajectory_json(b"[1, 2]")
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        with self.assertRaises(ContractError) as raised:
            parse_trajectory_json(b'{"generator": "x"}')
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])
        with self.assertRaises(ContractError) as raised:
            export_synthetic_csv({})
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])
        with self.assertRaises(ContractError) as raised:
            export_synthetic_csv({"samples": [{"sample_index": 0}]})
        self.assertEqual(raised.exception.codes, ["E_MISSING_FIELD"])


if __name__ == "__main__":
    unittest.main()
