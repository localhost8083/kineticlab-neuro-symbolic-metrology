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

- frames_total: 234
- frames_usable: 234
- observations_total: 468
- observations_valid: 468
- calibrated_frames: null

## Assumptions

- Rejected at the geometry stage (E_MALFORMED_JSON); retained sections carry partial context collected before the failure, not a measurement.

## Warnings

- `W_UNCERTAINTY_UNAVAILABLE`: KL-7.1 estimates no uncertainty; method is none.

## Reject reasons

- `E_MALFORMED_JSON` (geometry.geometry_report): fixtures/assembly/corrupt_geometry_report.json is unreadable as JSON: Unterminated string starting at: line 10 column 14 (char 187)

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
  - geometry_report_sha256: f1020ff32c1a44fefcc25aab9c786ba235acd3528883f7cf0023beb09c0e7bf6

## Export files

SHA-256 over the exact written bytes, in write order:

- result.json: d72d38dfc6cd15a51be4bf8bc335aecec6d36a7f742f7cea4b862896e18ebb7f
- diagnostics.json: 97c97d4c4679af94644ccdc2e90c633ed36ba2ad42e335004197079014ff4b25
- angles.csv: ca2e507407c800918dc84d5d2021ad38091d957b20b3574ae7b038c16bef5e64
- summary.md: (this file — self-hash excluded by construction; verify by regenerating)
