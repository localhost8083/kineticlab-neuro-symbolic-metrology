# Pinned live geometry (P-006)

Measured from the live M-1 artifacts (`fixtures/live/raw_*_one_bit.txt`,
bob 591 frames; card 392 frames) through `kineticlab/geometry/`.
Regeneration test in `tests/test_geometry.py` recomputes everything and
compares with tolerance (`math.isclose` per float; exact otherwise) —
sha pins would be libm-sensitive, so none are asserted; shas measured
on the pinning platform are recorded in the task handoff.

- `calibration_live.json`: KL-6.1 `calibration.v1` record that stays
  honestly invalid (valid false): a cut card is no standard, so
  reference_type is `"unknown"` with BOTH dimensions human-typed
  (85.0x54.0 mm, user_confirmed); median oriented geometry
  (209.189x128.346 px) over 272 clean card frames; width-based scale
  0.406330 mm/px; two W_ASSUMPTION_UNVERIFIED warnings (same-plane and
  fixed-camera unassessed); scale uncertainty null.
- `geometry_report_live.json`: assumptions table (tilt/blur/length
  null with reasons; truncation measured), fresh-clip U-3 statement
  (no depth-offset bound is borrowed from any retired clip), arc-fit
  pivot + residuals (center (467.309, -430.616) px, r 800.966 px,
  mean 4.696 px, max 14.161 px @frame 505, span 1.102 rad over 591
  centroids), jitter splits (391 all / 250 clean / 97 occluded
  pairs; 23 occlusion bands), blur-proxy summaries (geometric only),
  overlap frame list, M-3e limitation text + arc-radius caveat.
- `overlay_live_ball.svg`: KL-6.4 overlay evidence via the unchanged
  `result.overlay` path (live ball chain + threshold assessment).
  Byte-pinned (platform-bound: float repr). MANUAL INSPECTION:
  pending — open in a browser and confirm the centroid path follows
  the swing with flagged frames marked.

Provenance: clip `Smoke/demo_test.mp4`
(`db5da89e…1d9945`), model `sam-3.1`. Card dimensions are caller
inputs, not measurements — see the record's provenance block.
The tracked `geometry_report_live.json` differs from the captured run
file only in the U-3 statement (fresh-clip wording replaces the
retired-clip wording), which is why its sha differs from the
run-internal `geometry_report` digest.
