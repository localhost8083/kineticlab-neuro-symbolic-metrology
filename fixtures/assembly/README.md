# Pinned end-to-end assembly (KL-7.1)

The live test_3 chain assembled by `kineticlab/assembly/assemble`:
media/PTS -> live SAM observations (234 bob + 234 card records) ->
arc-fit pivot -> M1 fit -> validated `result.v1`, plus exports.
Regeneration test in `tests/test_assembly.py` reassembles into a
scratch dir and compares parsed (isclose per float; export paths
compared by basename since the scratch dir differs) — no asserted
shas (libm-sensitive floats); shas measured on the pinning platform
are recorded in the WHITEBOARD handoff.

- `result.json`: the validated `result.v1`
  (success_with_warnings, g/L_eff in 1/s^2, gravity null,
  uncertainty null, U-3/M-3e assumptions, export refs).
- `diagnostics.json`: chain counts, excluded frames, M1 termination
  + fitted params + per-point residuals, M2 include/skip rule
  outcome with justification, descriptive pivot radius (U-3 bound
  stated, `independent_length: false`).
- `angles.csv`: presentation-grade angle series
  (`frame_index,pts_seconds,theta_rad,centroid_x_px,centroid_y_px`;
  header always; JSON is the lossless form; no parser by design).
- `summary.md` (KL-7.3): human-auditable Markdown rendered from
  the validated result + diagnostics — every number copied,
  never recomputed; export file list carries SHA-256 over the
  exact written bytes (basenames only). Same request re-run is
  byte-identical; across out dirs at most the `result.json` hash
  line differs (it embeds out-dir refs; identical when refs
  fall back to basenames outside the working directory —
  honest boundary, tested with its cause). The summary lists
  itself without a self-hash
  (uncomputable — verify by regenerating).

KL-7.2 rejection pins (deterministic; same isclose convention):

- `corrupt_geometry_report.json`: CORRUPT-INPUT, not evidence —
  the first 200 bytes of `geometry_report_live.json`,
  JSON-truncated on purpose. Drives the pinned rejection.
- `rejection/`: the `unsupported_input` (`E_MALFORMED_JSON`)
  set for live inputs + the corrupt report pin
  (`result.json`, `diagnostics.json`, header-only
  `angles.csv`, `summary.md` reading unmistakably as a
  rejection). Rejection evidence: the valid calibration
  (warnings intact) and full frame/observation counts are
  retained; only `calibrated_frames` is null. Regen-tested
  like the success triple. Caveat: the reject detail embeds
  the stdlib JSON error message, which is interpreter-version
  sensitive like the libm floats — drift fails loudly.

Provenance: clip `Smoke/test_3.mp4`
(`a98a53…be5875ce`), model `sam-3.1`. The angle zero (image +y
about the pivot) is arbitrary and absorbed by the fit phase —
stated in the result assumptions, not an upright-camera claim.

Plain `success` is structurally unreachable in P-007: every
assembled result carries `W_UNCERTAINTY_UNAVAILABLE` (no
uncertainty is ever estimated here; KL-5.4 owns uncertainty),
and the contract requires `success_with_warnings` whenever
warnings are present. Documented, not forced — see
`AuditWalkthroughTests::test_plain_success_unreachable_note`
for the pinned statement.

## Human audit walkthrough (KL-7.4 — pinned)

Follow frame 0 of the live test_3 chain from source PTS to
summary line. Every citation below is asserted by
`tests/test_assembly.py::AuditWalkthroughTests`, so this
section cannot rot silently.

1. Source PTS — `fixtures/ingest/test_3_frame_table.json`:
   frame 0 (`"frame_index": 0`, line 7) carries
   `"pts_seconds": 0.0` (line 16), `"source_frame_index": 0`
   (line 18), `"decoded_reference": "sample:0"` (line 5).
   Measured by the stdlib MP4 parser; never synthesized.
2. Observation + angle — the live SAM ball mask for frame 0
   decodes (KL-3.2, covered by its own tests) to centroid
   (565.7244623655914, 366.5494210090984) px; the assembly
   measures its angle about the arc-fit pivot:
   `fixtures/assembly/angles.csv` line 2:
   `0,0.0,0.12636167830883652,565.7244623655914,366.5494210090984`
   (frame_index, pts_seconds, theta_rad, cx, cy).
   The PTS is preserved verbatim from step 1.
3. Fit input — the point (t = 0.0 s,
   theta = 0.12636167830883652 rad) enters the M1 fit;
   `fixtures/assembly/diagnostics.json` records its residual
   `"residual_rad": -0.07864719822009777` (line 26;
   `"point_index": 0` line 25, `"t_seconds": 0.0` line 27).
4. Fit output — M1 converges (`refine_tolerance_met`) to
   `"omega_per_s": 5.47774002094622` (diagnostics line 12),
   `"amplitude_rad": 0.29309715273018166` (line 11),
   `"period_s": 1.1470397067318712` (line 13),
   `"phase_rad": 0.7961587971827984` (line 14).
5. Result — `fixtures/assembly/result.json` line 155 reports
   `"value": 30.00563573707589` with `"unit": "1/s^2"`,
   equal to the embedded fit's
   `"g_over_l_per_s2": 30.00563573707589` (line 83);
   `gravity_m_s2` is null (U-2 length never provided).
6. Summary — `fixtures/assembly/summary.md` line 11 copies
   the value (`- value: 30.00563573707589`) and line 35 copies
   omega (`- omega_per_s: 5.47774002094622`); both copied,
   never recomputed (KL-7.3).
