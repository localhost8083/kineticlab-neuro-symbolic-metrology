# Contract fixtures for `kineticlab/contracts.py` (KL-1.3)

All records here are synthetic, hand-authored for schema tests — not
measurements. Real media pins stay in `fixtures/*.json` (see the parent
`fixtures/` dir). Provenance blocks inside these files say
`kineticlab-test` so fixture origin is never mistaken for evidence.

- `valid_<schema>.json`: one fully valid record per schema; each must
  parse and JSON-round-trip byte-identically through `to_dict`.
- `valid_frame_negative_pts.json`: a valid frame with finite negative
  source PTS (media preroll preserved as-is, never clamped).
- `frame_table.json`: a 5-frame table with one invalid frame retained
  (null mapping + `W_MISSING_FRAMES_RETAINED`); valid PTS strictly
  increases, so `validate_frame_table` passes.
- `invalid_cases.json`: `[{name, schema, record, expect_codes}]`. Each
  record must raise `ContractError` whose sorted code multiset equals
  `expect_codes` exactly, and every raised code must be registered in
  `ERROR_CODES`. Missing keys, wrong types, empty objects, bad
  versions/enums/hashes/units, incoherent values, cross-field
  arithmetic contradictions (summary echo, gravity derivation,
  rmse/max_abs, value/quantity/fit agreement, metric bounds),
  quantity name/unit mislabeling, detached success results, missing
  underlying fit parameters, and fabricated numerics (gravity without
  independent length) are all covered.
