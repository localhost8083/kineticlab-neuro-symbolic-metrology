# KineticLab result: SUCCESS (success_with_warnings)

Human-auditable summary. Every number below is copied from
result.json and diagnostics.json in this directory — nothing is
recomputed or authored here. Null renders as `null` (unknown).

## Status and measurement

- status: success_with_warnings
- measurement: pendulum_g_over_l
- value: 30.00563573707589
- unit: 1/s^2
- interval: null
- interval_method: null

## Identifiable quantity

- name: g/L_eff
- value: 30.00563573707589
- unit: 1/s^2

## Fit

- model_id: M1
- converged: true
- termination_reason: refine_tolerance_met
- optimizer: separable_omega_grid_linear_lsq_golden_refine_v1
- solver: closed_form_small_angle
- observation_count: 234
- rejected_count: 0
- g_over_l_per_s2: 30.00563573707589
- gravity_m_s2: null
- fitted (copied from diagnostics):
  - amplitude_rad: 0.29309715273018166
  - omega_per_s: 5.47774002094622
  - period_s: 1.1470397067318712
  - phase_rad: 0.7961587971827984
- residual_summary (copied from fit.v1):
  - dof: 231
  - max_abs: 0.07864719822009777
  - rmse: 0.02275752015969389
- final_ssr: 0.12118970537361647
- bound_hits: []
- n_points: 234

## M2 diagnostic

- included: true
- justification: included: converged (refine_tolerance_met) with gamma 0.029794544246787853 strictly inside [0.0, 1.0]; omega cross-checks M1; diagnostic only, M1 stays reported
- converged: true
- termination_reason: refine_tolerance_met
- fitted.amplitude_rad: 0.3290844298262253
- fitted.gamma_per_s: 0.029794544246787853
- fitted.omega_per_s: 5.478960430266463
- fitted.period_s: 1.14678420973265
- fitted.phase_rad: 0.7921461825884377
- g_over_l_per_s2: 30.019007396425668
- bound_hits: []
- warnings:
  - `W_UNCERTAINTY_UNAVAILABLE`: KL-5.3 estimates no uncertainty; method is none (KL-5.4 owns uncertainty).

## Quality metrics

- frames_total: 234
- frames_usable: 234
- observations_total: 468
- observations_valid: 468
- calibrated_frames: 117

## Assumptions

- Angles measured from image +y about the arc-fit pivot; the zero is arbitrary and absorbed by the fit phase (no upright-camera assumption).
- U-3 depth-offset scale bound 1.7% (25.0 mm offset over 1500.0 mm camera distance, tape estimate) stated as an assumption wherever this scale is used
- M-3e hollow-ball/string-mass bias stated, uncorrected (see the geometry report model_limitations).
- Arc-fit radius is descriptive only, not an independent length; gravity stays null (U-2 not provided).
- M1 is the reported model (pre-registered parsimony); the M2 outcome rides the diagnostics as a cross-check.

## Warnings

- `W_UNCERTAINTY_UNAVAILABLE`: KL-7.1 estimates no uncertainty; method is none.

## Reject reasons

- none

## Provenance

- software_name: kineticlab
- software_version: 0.1.0
- input_sha256: a98a532410a4af2d70921d5adaf1298f151dab8f0e92348f6920cce0be5875ce
- model_name: sam-3.1
- model_version: null
- raw_refs:
  - fixtures/live/raw_bob_one_bit.txt
  - fixtures/live/raw_card_one_bit.txt
- artifact_hashes (input digests, copied):
  - raw_bob_sha256: b216815fd6ca5e15718fed2dd8947a9972e00b1f27f71881e5d39401a4fb3ad7
  - raw_card_sha256: d3fe9a7ecde3f48c6ef2753bd66f7d93f86783613d50bb2ebbf566deb57473d1
  - calibration_sha256: 09e3e852efe6a7d74f67f642ef9710558c898d65bd6c55a9d67a033bba3fa3aa
  - geometry_report_sha256: 39540e565b557fc98d8b507f36a617a2117bb064f0f8b55fcd7352a237a89a41

## Export files

SHA-256 over the exact written bytes, in write order:

- result.json: d6ca023107edbc4ac2fd91069ddcf11f28708003c0498d9e42c984ea7084f9c2
- diagnostics.json: c58d27156671881e884916abf204e89c2b230ab15799164b897d0d91c4d4c594
- angles.csv: d44e33c95e614047f12ef9d9b66bae0fcb881f30c420bae5621a4c5c2dc55b3e
- summary.md: (this file — self-hash excluded by construction; verify by regenerating)
