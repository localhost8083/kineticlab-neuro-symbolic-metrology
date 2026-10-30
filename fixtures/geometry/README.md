# Pinned live geometry (P-006)

Measured from the live M-1 artifacts (`fixtures/live/raw_*_one_bit.txt`,
234 frames each) through `kineticlab/geometry/`. Regeneration test in
`tests/test_geometry.py` recomputes everything and compares with
tolerance (`math.isclose` per float; exact otherwise) — sha pins would
be libm-sensitive, so none are asserted; shas measured on the pinning
platform are recorded in the WHITEBOARD handoff.

- `calibration_live.json`: KL-6.1 `calibration.v1` record (ID-1
  85.60x53.98 mm user-confirmed; median oriented geometry over 117
  clean frames; isotropic scale; U-3 bound in warnings; valid true).
- `geometry_report_live.json`: assumptions table (tilt/blur/length
  null with reasons; truncation measured), U-3 bound, anisotropy,
  aspect data, arc-fit pivot + residuals, jitter splits
  (all/clean/occluded), blur-proxy summaries (geometric only),
  overlap frame list, M-3e limitation text.
- `overlay_live_ball.svg`: KL-6.4 overlay evidence via the unchanged
  `result.overlay` path (live ball chain + threshold assessment).
  Byte-pinned (platform-bound: float repr). MANUAL INSPECTION:
  pending — open in a browser and confirm the centroid path follows
  the swing with flagged frames marked.

Provenance: clip `Smoke/test_3.mp4`
(`a98a53…be5875ce`), model `sam-3.1`. U-1/U-3 values are caller
inputs, not measurements — see the report's provenance block.
