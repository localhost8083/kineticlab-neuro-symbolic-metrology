# KineticLab result: SUCCESS (success)

Human-auditable summary. Every number below is copied from
result.json and diagnostics.json in this directory — nothing is
recomputed or authored here. Null renders as `null` (unknown).

## Status and measurement

- status: success
- measurement: pendulum_g_over_l
- value: 28.93746036102984
- unit: 1/s^2
- interval: {"lower": 28.899033216202955, "upper": 28.982897973850847}
- interval_method: block_bootstrap

## Identifiable quantity

- name: g/L_eff
- value: 28.93746036102984
- unit: 1/s^2

## Fit

- model_id: M1
- converged: true
- termination_reason: refine_tolerance_met
- optimizer: separable_omega_grid_linear_lsq_golden_refine_v1
- solver: closed_form_small_angle
- observation_count: 591
- rejected_count: 0
- g_over_l_per_s2: 28.93746036102984
- gravity_m_s2: null
- fitted (copied from diagnostics):
  - amplitude_rad: 0.4844222768378287
  - omega_per_s: 5.379355013477902
  - period_s: 1.1680183388969774
  - phase_rad: -2.730179137233871
- residual_summary (copied from fit.v1):
  - dof: 588
  - max_abs: 0.09307653918706144
  - rmse: 0.036873694317842085
- final_ssr: 0.8035645755935849
- bound_hits: []
- n_points: 591

## Uncertainty

- method: block_bootstrap
- seed: 20261103
- n_boot: 800
- block_frames: 36
- extended_to_contain_point: false
- omega_per_s (1/s): low 5.375782102745884, point 5.379355013477902, high 5.38357668969718
- g_over_l_eff_per_s2 (1/s^2): low 28.899033216202955, point 28.93746036102984, high 28.982897973850847

## M2 diagnostic

- included: true
- justification: included: converged (refine_tolerance_met) with gamma 0.014296385985767188 strictly inside [0.0, 1.0]; omega cross-checks M1; diagnostic only, M1 stays reported
- converged: true
- termination_reason: refine_tolerance_met
- fitted.amplitude_rad: 0.5560546475590737
- fitted.gamma_per_s: 0.014296385985767188
- fitted.omega_per_s: 5.37889084133999
- fitted.period_s: 1.168119133202993
- fitted.phase_rad: -2.72515511960891
- g_over_l_per_s2: 28.932466683051224
- bound_hits: []
- warnings:
  - `W_UNCERTAINTY_UNAVAILABLE`: KL-5.3 estimates no uncertainty; method is none (KL-5.4 owns uncertainty).

## Quality metrics

- frames_total: 591
- frames_usable: 591
- observations_total: 983
- observations_valid: 983
- calibrated_frames: 272

## Assumptions

- Angles measured from image +y about the arc-fit pivot; the zero is arbitrary and absorbed by the fit phase only up to a constant offset the M1 model does not represent (A*cos(wt+phi) has no theta_eq term) - stated uncorrected (no upright-camera assumption).
- No depth-offset scale bound: this clip provides no camera/card depth measurements (U-3 was a measurement of a retired pinned clip and is not borrowed here); scale assumes a coplanar card and a fixed camera, both unassessed (see the calibration warnings).
- M-3e hollow-ball/string-mass bias stated, uncorrected (see the geometry report model_limitations).
- Arc-fit radius is descriptive only, not an independent length; gravity stays null (U-2 not provided).
- M1 is the small-angle model: omega0 = omega*(1 - theta0^2/16 + O(theta0^4)), so the reported g/L_eff = omega^2 understates the small-angle g/L by about theta0^2/8 (order 1% at the observed amplitudes) - stated, uncorrected.
- M1 residuals are structured, not white noise (lag-1 autocorrelation ~0.88 on the replay; damping and the DC offset are omitted): M1 is a frequency estimator for omega, not a complete trajectory model. The reported value is a point estimate with a resampling-based interval under M1 (fit_uncertainty_method=block_bootstrap; see Uncertainty); the diagnostic damped fit M2 is a cross-check, not an error bar.
- M1 is the reported model (pre-registered parsimony); the M2 outcome rides the diagnostics as a cross-check.
- The omega and g/L_eff intervals come from a seeded block bootstrap over measured frames (method block_bootstrap): they capture measurement noise under the M1 model, not M1 model-adequacy bias - the structured-residual limitation above stands unchanged.
- Block resampling preserves short-range time dependence; the interval is resampling-based (percentiles of M1 refits), not an analytic derivation. Endpoints extend to contain the point estimate if a percentile excludes it (flagged as extended_to_contain_point in fit_uncertainty).

## Warnings

- none

## Reject reasons

- none

## Provenance

- software_name: kineticlab
- software_version: 0.1.0
- input_sha256: db5da89e06f74547f03a41a1ef2ff041c6b4b1948957538a8e4674f5ab1d9945
- model_name: sam-3.1
- model_version: null
- raw_refs:
  - fixtures/live/raw_bob_one_bit.txt
  - fixtures/live/raw_card_one_bit.txt
- artifact_hashes (input digests, copied):
  - raw_bob_sha256: 23e4035ef0e648383eff5c44e6e9511cb7d20254b9e3d82b4a7de57773315e8f
  - raw_card_sha256: ec6a62f76fdf2a2e58afea9eab83d2867737bb883ba675d88ded7c4040a8d7df
  - calibration_sha256: b83ddf2dcc17848cd3ca196cd1499027d756901424368fcea1449fc033a2ce70
  - geometry_report_sha256: 05ea04720ce0e785dff59798b7a94bd4bd7b19517e934c30b9c612eaeb147816

## Export files

SHA-256 over the exact written bytes, in write order:

- result.json: 837a9b8a8845ed4aafe32d026ec722cc1d2295b81ef117d4fed4f27cf73abcb3
- diagnostics.json: 0666b5fbfe7d1ffc11534942f40a8f29ae3c5fd4d7c33cf9ce0e05edb84e2069
- angles.csv: 877b2b7224b75e6258675a627d82ed18c4a9865f5951b1466a8a06a27f5264e9
- summary.md: (this file — self-hash excluded by construction; verify by regenerating)
