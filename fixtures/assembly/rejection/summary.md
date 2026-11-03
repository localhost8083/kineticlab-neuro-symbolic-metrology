# KineticLab result: REJECTED (unsupported_input)

Human-auditable summary. Every number below is copied from
result.json and diagnostics.json in this directory — nothing is
recomputed or authored here. Null renders as `null` (unknown).

## Status and measurement

- status: unsupported_input
- measurement: pendulum_g_over_l
- value: null
- unit: null
- interval: null
- interval_method: null

## Identifiable quantity

- name: g/L_eff
- value: null
- unit: 1/s^2

## Fit

- fit: none (no fit output; see status)

## M2 diagnostic

- M2 diagnostic: not run (no M2 output)

## Quality metrics

- frames_total: 591
- frames_usable: 591
- observations_total: 983
- observations_valid: 983
- calibrated_frames: null

## Assumptions

- Rejected at the geometry stage (E_MALFORMED_JSON); retained sections carry partial context collected before the failure, not a measurement.

## Warnings

- `W_UNCERTAINTY_UNAVAILABLE`: KL-7.1 estimates no uncertainty; method is none.

## Reject reasons

- `E_MALFORMED_JSON` (geometry.geometry_report): fixtures/assembly/corrupt_geometry_report.json is unreadable as JSON: Unterminated string starting at: line 7 column 21 (char 187)

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
  - geometry_report_sha256: 31b6d28bab36377c916e2d500c2b276382a993d919f464a1f56c57796304f374

## Export files

SHA-256 over the exact written bytes, in write order:

- result.json: 2510bca66fbce1c7e59f84138f4763e1472b5e95641ec5557c43a404d948dac0
- diagnostics.json: 12bd702a4ac58462aaa77c44aadade1f93fed0c9c04aa3ebdd1861fcdf1fe24c
- angles.csv: ca2e507407c800918dc84d5d2021ad38091d957b20b3574ae7b038c16bef5e64
- summary.md: (this file — self-hash excluded by construction; verify by regenerating)
