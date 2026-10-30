# KineticLab — Master Project Plan

**Version:** 1.0
**Status:** Execution baseline
**Date:** 2026-10-27
**Repository:** `kineticlab-neuro-symbolic-metrology`
**Working mode:** Local-only development. No GitHub push until final submission decision.
**Primary reviewer:** Claude Fable 5

---

## 1. Executive decision

### 1.1 Build this first

KineticLab analyzes one short, fixed-camera, side-on pendulum video with one visible reference card. It returns:

- timestamped bob observations;
- reference-card geometry and calibration status;
- pendulum trajectory and fit diagnostics;
- an uncertainty-aware result when inputs support it;
- explicit failure or warning states when they do not;
- CSV/JSON/Markdown artifacts that another person can inspect.

### 1.2 Do not build first

Deferred until core measurement works:

- arbitrary object or experiment identification;
- multi-body scenes;
- live camera mode;
- cloud deployment;
- user accounts;
- symbolic model discovery;
- Muse Wonder escalation;
- generated ghost-overlay MP4;
- interactive digital twin;
- PDF reports;
- benchmark marketing claims;
- broad ID-card/object support.

### 1.3 Current go/no-go

**GO:** start implementation now.

**Not yet proven:** physical calibration, gravity measurement, uncertainty coverage, model validity, end-to-end result.

**No additional SAM smoke test required before implementation.** Existing fixtures prove media/API/response plumbing only.

### 1.4 First vertical slice

```text
local video
  -> ingest metadata + exact frame PTS
  -> replay saved SAM observations
  -> normalized bob/card records
  -> mask centroid + card geometry
  -> pixel-to-length calibration
  -> angle/time series
  -> ideal/damped fit
  -> residuals + uncertainty limits
  -> explicit result contract
  -> local report and exports
```

Build offline replay first. Live API use stays optional and replaceable.

---

## 2. Locked accuracy rules

These rules override speed, UI polish, agent preference, and demo pressure.

1. **No numeric result authored by language model.** Python/NumPy/SciPy code creates every numeric result.
2. **Actual timestamps only.** Use source frame PTS where available. Never replace VFR timing with nominal FPS silently.
3. **AI output is observation, not truth.** SAM masks, boxes, confidence, and IDs require validation.
4. **No fabricated output.** Missing, malformed, or weak data remains missing or causes rejection.
5. **No gravity claim without independent length or independently validated metric scale.** A circle fit from the same video cannot provide independent length.
6. **Known card dimensions require confirmed card type.** Standard ISO/IEC 7810 ID-1 dimensions are `85.60 mm × 53.98 mm` only when the object is confirmed as ID-1.
7. **AI-generated footage cannot prove physics accuracy.** It can test plumbing, parsing, and visualization.
8. **Every number gets a label:** measured, fixture assumption, target, estimate, or external fact.
9. **Warnings stay visible.** UI/report cannot turn warnings into a clean-looking pass.
10. **External API keys never enter source, fixtures, logs, reports, or Git history.** Revoke exposed key before any future API call.
11. **Model code cannot be changed by model output.** No runtime `eval`, `exec`, generated code, or unreviewed symbolic expressions.
12. **Small scope wins.** One reliable experiment beats broad unsupported automation.

---

## 3. Evidence already available

### 3.1 Existing local assets

- `Smoke/test_3.mp4`: strongest current real-capture fixture.
- `Smoke/results/test_3_processing.mp4`: audio-free processing copy.
- `Smoke/results/test_3_yellow_ball_raw.txt`: yellow-ball SAM response.
- `Smoke/results/test_3_white_card_raw.txt`: white-card SAM response.
- `Smoke/results/red_sphere_raw.txt`: synthetic/AI fixture response.
- `Smoke/results/card_raw.txt`: card response.
- `Smoke/results/real_white_paper_raw.txt`: limited real-capture card response.
- Empty negative response fixtures for failed prompts.
- Contact sheets, frame samples, ffprobe metadata, and SHA-256 records.

### 3.2 Existing smoke evidence

`test_3.mp4`:

- H.264, `1024×576`;
- `234` video frames;
- approximately `7.86` seconds;
- source timestamps monotonic;
- yellow ball: `234/234` frames;
- white card: `234/234` frames;
- yellow-ball confidence: `0.9532163739204407`;
- white-card confidence: `0.8947368264198303`;
- no observed SAM frame gaps;
- processing copy has no audio.

This evidence does **not** prove:

- decoded mask correctness;
- centroid accuracy;
- card dimensions;
- same-plane geometry;
- pendulum length;
- period or `g` accuracy;
- uncertainty coverage.

### 3.3 Repository reality

Current repository is planning/smoke-test skeleton. No application package, manifest, project test suite, CI, formatter, type checker, or verified application command exists yet. First implementation stage must establish these.

Existing `Docs/` and `Smoke/` files are user work. Preserve them. Do not broad-rename historical `PocketLab` or `KineticSim` references.

---

## 4. Scope lock

### 4.1 Supported v1 input

- One MP4 video.
- One fixed camera.
- One planar pendulum.
- One dominant bob.
- One visible reference card.
- Roughly 3–10 seconds.
- Bob and card fully visible for enough frames.
- Card and motion plane same or near-coplanar.
- User-confirmed card type/dimensions.
- Optional independently measured pivot-to-bob-center length.

### 4.2 v1 output

```text
status
input metadata
frame index -> source PTS mapping
bob observation coverage
card observation/calibration
trajectory data
fit model and parameters
residual diagnostics
uncertainty method and limitations
warnings/reject reasons
provenance
export paths
```

### 4.3 Result states

Use exact machine-readable states:

- `success`
- `success_with_warnings`
- `insufficient_data`
- `unsupported_input`
- `processing_error`

`success` requires all critical assumptions and quality gates. `success_with_warnings` permits non-critical documented limitations. No numeric gravity result when identifiability fails.

---

## 5. Architecture

Keep boundaries small. Each boundary must support deterministic offline tests.

```text
kineticlab/
  ingest/
  observation/
  geometry/
  fit/
  result/
  cli/

scripts/
tests/
fixtures/
Docs/
Smoke/
```

### 5.1 `ingest`

Responsibilities:

- validate file existence, extension/container, size, duration, resolution, stream count;
- preserve source media;
- extract stream metadata;
- extract per-frame source PTS;
- create processing copy only when needed;
- create explicit frame mapping;
- reject unsupported or ambiguous media.

Required mapping:

```text
processing_frame_index -> source_frame_index -> source_pts_seconds -> decoded_frame_reference
```

### 5.2 `observation`

Responsibilities:

- parse saved SAM responses;
- support live SAM adapter later;
- validate frame markers, object IDs, boxes, masks, dimensions, confidence;
- decode the verified mask encoding;
- compute mask centroid and area;
- preserve missing/duplicate/malformed records;
- emit normalized bob/card observations.

SAM adapter must be replaceable. Vendor response format must not leak through the rest of the application.

### 5.3 `geometry`

Responsibilities:

- derive card contour/corners from validated mask;
- use oriented geometry, not axis-aligned box alone;
- compare observed card proportions with confirmed dimensions;
- compute pixel-to-length scale or plane transform;
- estimate pendulum angle from calibrated coordinates;
- run fixed-camera, plane, trajectory, and conditioning checks.

Circle fit is diagnostic only unless independent length validation exists.

### 5.4 `fit`

Initial model library only:

- M1: ideal nonlinear pendulum, `theta'' + (g/L) sin(theta) = 0`;
- M2: linear damping, `theta'' + gamma theta' + (g/L) sin(theta) = 0`.

Use actual timestamps, bounded parameters, explicit observation weights, solver status, residuals, and convergence diagnostics.

Do not add M3, symbolic discovery, AICc claims, HAC covariance, or bootstrap claims until simpler fit and uncertainty tests pass.

### 5.5 `result`

Responsibilities:

- assemble result contract;
- enforce state transitions;
- reject critical failures;
- write JSON, CSV, Markdown, and provenance;
- prevent language-model numeric substitution.

### 5.6 `ui`

Minimal local UI or CLI report only after offline pipeline passes. UI shows computed values and status; it does not calculate physics.

---

## 6. Data contracts

Schemas must be versioned before parallel implementation. JSON is canonical; CSV is export.

### 6.1 Media metadata

```json
{
  "schema_version": "media.v1",
  "source_path": "...",
  "source_sha256": "...",
  "container": "mp4",
  "video_stream_count": 1,
  "audio_stream_count": 0,
  "codec": "h264",
  "width": 1024,
  "height": 576,
  "pixel_format": "yuv420p",
  "duration_seconds": 7.86,
  "frame_count": 234,
  "nominal_frame_rate": null,
  "time_base": "1/90000",
  "warnings": []
}
```

Unknown values are `null`, not guessed.

### 6.2 Frame record

Required fields:

- `frame_index`;
- `source_frame_index`;
- `pts_seconds`;
- `duration_seconds` if available;
- `decoded_reference`;
- `valid`;
- `warnings`.

Rules:

- zero-based frame indexes;
- PTS strictly increasing for usable video;
- no silent frame deletion;
- missing mapping is explicit.

### 6.3 Observation record

Required fields:

- `frame_index`;
- `pts_seconds`;
- `object_role`: `bob` or `reference_card`;
- `object_id`;
- `confidence`;
- `bbox` if present;
- `mask_reference` or decoded mask record;
- `centroid_x_px`, `centroid_y_px`;
- `mask_area_px`;
- `valid`;
- `source`: `sam_fixture`, `sam_live`, `manual`, or `synthetic`;
- `warnings`.

### 6.4 Calibration record

Required fields:

- `reference_type`;
- `reference_dimensions_mm`;
- `dimension_source`;
- `observed_corners_px`;
- `observed_oriented_dimensions_px`;
- `scale_mm_per_px` or plane transform;
- `scale_uncertainty_mm_per_px` if known;
- `same_plane_assumption`;
- `camera_fixed_assumption`;
- `valid`;
- `warnings`.

### 6.5 Fit record

Required fields:

- `model_id`;
- `parameter_names`;
- `parameters`;
- `parameter_units`;
- `initial_conditions`;
- `solver`;
- `optimizer`;
- `converged`;
- `residual_summary`;
- `observation_count`;
- `rejected_count`;
- `fit_uncertainty_method`;
- `warnings`.

### 6.6 Final result contract

Required fields:

- `schema_version`;
- `status`;
- `measurement_name`;
- `value`;
- `unit`;
- `interval`;
- `interval_method`;
- `identifiable_quantity`;
- `calibration`;
- `fit`;
- `quality_metrics`;
- `assumptions`;
- `warnings`;
- `reject_reasons`;
- `provenance`;
- `exports`.

Numeric fields must be generated from computation. Reports may use templates around those fields.

---

## 7. Work method for swappable agents

Any coding agent may implement a stage. Agent identity does not matter; contract compliance does.

### 7.1 Agent roles

| Role | Work | Can be swapped? |
|---|---|---:|
| Builder | Implements assigned stage and tests | Yes |
| Specialist | Solves narrow parser/math/media/UI issue | Yes |
| Explorer | Maps repository, dependencies, API facts, or docs | Yes |
| Integrator | Applies reviewed work to main local branch | Yes |
| Fable reviewer | Reviews stage evidence, accuracy, scope, and claims | No; required gate |

### 7.2 Parallel lanes

Parallel work allowed only after shared contracts are locked:

- Lane A: ingest/media and PTS mapping;
- Lane B: observation parser and mask decoder;
- Lane C: synthetic trajectory and fit kernel;
- Lane D: result schemas and report assembly;
- Lane E: UI, blocked from inventing backend fields.

Do not parallelize conflicting schema design. One owner merges contract decisions.

### 7.3 Worktree rules

- Use separate local branches/worktrees when agents work in parallel.
- Never push during development.
- Never overwrite unreviewed user files.
- Integrator resolves conflicts against locked contracts, not by taking whichever code is larger.
- Local commits optional. GitHub push remains final release action.

### 7.4 Required handoff packet

Every completed stage returns:

```text
Stage ID:
Agent/model:
Files changed:
Contract changes:
Commands run:
Tests run and exact results:
Fixtures used:
Known limitations:
Scientific claims made:
Open risks:
Suggested next stage:
```

No handoff means no review.

### 7.5 Fable review gate

After every stage, invoke Fable with:

1. diff or changed-file list;
2. handoff packet;
3. test output;
4. fixture hashes if relevant;
5. result samples;
6. claim list;
7. known limitations.

Fable returns one decision:

- `PASS`: stage may merge;
- `PASS_WITH_FIXES`: listed fixes required before merge;
- `BLOCK`: do not continue; repair stage;
- `SCOPE_CUT`: remove unsafe feature and continue smaller path.

No next-stage work starts from a `BLOCK`.

---

## 8. Stages, tasks, and exit gates

## Stage 0 — Project freeze and local foundation

**Goal:** establish reproducible package and test commands without expanding scope.

### Tasks

- [ ] Confirm Python version available locally.
- [ ] Choose minimal package layout.
- [ ] Add package manifest and dependency lock strategy.
- [ ] Add test runner or stdlib-based test command.
- [ ] Add configuration for local paths and optional API use.
- [ ] Add secret exclusion rules.
- [ ] Generalize `Smoke/run_local_checks.sh`; remove hardcoded `1280×720`, `24 fps`, `240 frames` assumptions.
- [ ] Add `--help` and one offline smoke command.
- [ ] Document exact setup and test commands in `README.md`.
- [ ] Keep all existing smoke assets intact.

### Exit evidence

- Clean local setup from documented instructions.
- One executable offline command.
- One executable test command.
- No secrets in tracked/untracked test outputs.
- Existing assets still readable.

### Fable gate

Reject if manifest, commands, or dependency choices cannot be reproduced locally. Reject if implementation begins with UI or network-only behavior.

---

## Stage 1 — Schemas and result contract

**Goal:** stop agents from inventing incompatible data structures.

### Tasks

- [ ] Implement media metadata schema.
- [ ] Implement frame/PTS schema.
- [ ] Implement observation schema.
- [ ] Implement calibration schema.
- [ ] Implement fit schema.
- [ ] Implement warning/error taxonomy.
- [ ] Implement final result schema with all five states.
- [ ] Add schema validation at trust boundaries.
- [ ] Add fixtures for valid, missing, malformed, empty, and rejected records.

### Exit evidence

- Round-trip serialization tests pass.
- Unknown values use `null` or explicit invalid state.
- Missing frames remain represented.
- Numeric result fields cannot be supplied by prose generation.

### Fable gate

Review field meaning, units, defaults, failure states, and whether any field encourages fabricated precision.

---

## Stage 2 — Ingest and timestamp mapping

**Goal:** prove exact media-to-frame timing locally.

### Tasks

- [ ] Validate source file and video stream.
- [ ] Extract ffprobe metadata.
- [ ] Extract per-frame PTS.
- [ ] Preserve source and processing-copy hashes.
- [ ] Build explicit frame mapping.
- [ ] Detect non-monotonic, duplicate, missing, or unusable timestamps.
- [ ] Verify source and processing-copy frame identity mapping.
- [ ] Add CFR and VFR fixtures where available.
- [ ] Add media failure fixtures.

### Tests

- source files decode;
- one video stream required;
- unsupported codec rejected or explicitly supported;
- timestamps monotonic;
- processing copy has expected frame mapping;
- audio handling does not alter video timing;
- VFR timing reaches downstream code unchanged;
- malformed metadata fails safely.

### Exit evidence

`test_3` produces a stable frame table with `234` rows and real PTS. No code assumes `1/fps` timing.

### Fable gate

Block if any fit input uses synthetic uniform time where source PTS exists.

---

## Stage 3 — Offline observation parser and mask decoding

**Goal:** convert saved SAM fixtures into normalized observations without API calls.

### Tasks

- [ ] Parse explicit frame markers.
- [ ] Parse object IDs, boxes, dimensions, confidence, and mask payloads.
- [ ] Validate coordinate ranges and dimensions.
- [ ] Decode the actual fixture mask encoding, not a guessed format.
- [ ] Compute mask area and centroid.
- [ ] Detect malformed/truncated/empty masks.
- [ ] Detect missing, duplicate, reordered, or conflicting frame records.
- [ ] Keep raw response reference and parser version.
- [ ] Emit normalized JSON and CSV.
- [ ] Add parser replay command.

### Test matrix

- full `test_3` bob fixture;
- full `test_3` card fixture;
- missing first frame;
- missing middle frame;
- duplicate frame;
- duplicate object ID;
- malformed mask;
- empty response;
- confidence missing or outside `[0,1]`;
- invalid dimensions;
- unexpected characters;
- multiple object records;
- explicit negative fixtures.

### Exit evidence

- `test_3` produces `234/234` normalized records for bob and card.
- Missing frame handling is explicit.
- Centroids derive from decoded masks, not box centers except documented fallback.
- Parser never crashes on malformed external text.

### Fable gate

Block if mask decoding is inferred from payload appearance without tests against known dimensions or if parser silently drops records.

---

## Stage 4 — Observation quality and diagnostics

**Goal:** identify whether observations are fit-worthy before physics code sees them.

### Tasks

- [ ] Compute frame coverage.
- [ ] Compute gap spans.
- [ ] Detect centroid jumps.
- [ ] Detect area collapse and shape instability.
- [ ] Detect confidence degradation.
- [ ] Detect object-ID switches.
- [ ] Preserve rejected observations.
- [ ] Generate trajectory CSV.
- [ ] Generate overlay/contact-sheet diagnostics.
- [ ] Add deterministic quality thresholds with rationale.

### Exit evidence

- `test_3` has complete tracks but may still carry warnings.
- Failed real fixture gets `insufficient_data` or observation warning, not fabricated trajectory.
- Diagnostics let human inspect tracking.

### Fable gate

Review thresholds. No threshold may be tuned only to make `test_3` pass without a failure fixture.

---

## Stage 5 — Offline physics estimator

**Goal:** prove mathematics before coupling it to video or API.

### Tasks

- [ ] Generate deterministic ideal pendulum trajectories.
- [ ] Generate damped trajectories.
- [ ] Support nonuniform timestamps.
- [ ] Add seeded observation noise.
- [ ] Add short gaps and outliers.
- [ ] Fit M1.
- [ ] Fit M2 only after M1 passes.
- [ ] Record convergence and bounds.
- [ ] Compute residuals and basic diagnostics.
- [ ] Separate identifiable `g/L` from gravity requiring independent `L`.
- [ ] Add solver tolerance sensitivity check.
- [ ] Add failure states for short/weak/degenerate motion.

### Required tests

- noiseless recovery;
- noisy recovery;
- nonuniform PTS recovery;
- missing-frame recovery or honest rejection;
- poor-scale rejection;
- short-clip rejection;
- weak-amplitude rejection;
- non-convergent fit;
- parameter-bound hit;
- model mismatch warning;
- deterministic repeatability.

### Exit evidence

- Seeded tests recover known fixture parameters within documented tolerances.
- Tests report interval coverage or explicitly label uncertainty provisional.
- No gravity result appears when independent length is absent.

### Fable gate

Block unsupported statistical language such as “exact,” “global optimum,” “scientifically accurate,” or “validated uncertainty” without evidence.

---

## Stage 6 — Geometry and calibration

**Goal:** convert image observations into defensible physical coordinates.

### Tasks

- [ ] Confirm reference card type through user input or explicit fixture metadata.
- [ ] Extract card mask contour.
- [ ] Estimate oriented corners/rectangle.
- [ ] Compare observed proportions with expected dimensions.
- [ ] Compute scale in the reference plane.
- [ ] Record card and pendulum plane assumption.
- [ ] Add fixed-camera check.
- [ ] Add tilt, truncation, blur, and out-of-plane warnings.
- [ ] Add independent pendulum length input.
- [ ] Propagate declared scale/length uncertainty.
- [ ] Keep circle fit as diagnostic only.

### Geometry tests

- axis-aligned card;
- in-plane rotated card;
- partial card mask;
- perspective-distorted card;
- card too small;
- card out of frame;
- wrong aspect ratio;
- card and bob different depth;
- short pendulum arc;
- fixed-camera failure;
- known scale synthetic geometry.

### Exit evidence

- Confirmed card dimensions produce reproducible calibration.
- Invalid plane/card assumptions return warnings or rejection.
- No axis-aligned-box-only calibration claim.
- At least one manually inspected geometry overlay exists.

### Fable gate

No `g` claim until card dimensions, plane assumption, and independent length status are explicit.

---

## Stage 7 — End-to-end local result

**Goal:** run one complete offline replay from `test_3` through result assembly.

### Tasks

- [ ] Join frame PTS and normalized observations.
- [ ] Apply geometry/calibration.
- [ ] Compute angle/time series.
- [ ] Run M1 fit.
- [ ] Run M2 only if justified by data.
- [ ] Produce residual diagnostics.
- [ ] Compute provisional uncertainty or clearly refuse it.
- [ ] Assemble final result state.
- [ ] Write CSV, JSON, Markdown, and visual diagnostics.
- [ ] Include provenance and input hashes.
- [ ] Test all failure states.

### Required output

```text
analysis_result.json
observations.csv
trajectory.csv
fit.csv or fit.json
warnings.json
provenance.json
trajectory_overlay.png or equivalent
analysis_report.md
```

### Exit evidence

A human can answer:

- Which frames were used?
- Which frames were missing/rejected?
- What card dimensions were assumed?
- Was independent length supplied?
- Which model fit?
- What quantity is identifiable?
- Why did result pass, warn, or fail?
- Which source files and code version produced it?

### Fable gate

This is primary review gate. A polished UI cannot proceed if this stage cannot produce honest output.

---

## Stage 8 — Minimal local UI or CLI report

**Goal:** make the proven pipeline demoable without adding scientific logic.

### Minimum features

- choose local video or cached fixture;
- show ingest status;
- show setup requirements;
- show progress/errors;
- show result state;
- show bob/card overlay;
- show trajectory and residuals;
- show measured value and uncertainty only when valid;
- show warnings and assumptions;
- export artifacts.

### UI rejection rules

- no fake progress percentage;
- no hardcoded result number;
- no success styling for rejected data;
- no hidden warnings;
- no AI-generated numeric prose;
- no claim that fixture parameters are measurements.

### Exit evidence

A new user can run cached example locally and understand both successful and rejected output.

### Fable gate

Review demo truthfulness, accessibility, error visibility, and whether visual polish hides measurement weakness.

---

## Stage 9 — Hardening and submission package

**Goal:** freeze a reproducible local demo and only then prepare GitHub submission.

### Tasks

- [ ] Run complete regression suite.
- [ ] Run clean-environment setup.
- [ ] Verify no secrets in files, logs, history, or generated artifacts.
- [ ] Revoke exposed API key.
- [ ] Confirm replacement key only if live API demo still required.
- [ ] Add timeouts, size limits, cleanup, and bounded resource use.
- [ ] Record dependency versions.
- [ ] Record measured local runtime, not target runtime.
- [ ] Verify all claims in README/demo script against evidence.
- [ ] Prepare demo video and submission notes.
- [ ] Freeze assets and hashes.
- [ ] Review Git diff and untracked files.
- [ ] Commit locally.
- [ ] Push GitHub only after final user approval and deadline confirmation.

### Exit evidence

- one clean local run;
- one clean failure run;
- test output saved;
- demo script works offline or clearly marks optional API dependency;
- no unverified claims;
- Fable final sign-off;
- user confirms push.

---

## 9. Verification plan

### 9.1 Test layers

| Layer | Purpose | Network? |
|---|---|---:|
| Unit | Parser, geometry, math, schema | No |
| Fixture replay | Saved SAM/media behavior | No |
| Synthetic physics | Parameter recovery and failures | No |
| Media contract | Decode, PTS, stream rules | No |
| Integration | Ingest → observation → fit → result | No |
| Live API smoke | Vendor adapter only | Optional |
| UI smoke | Local display/export | No |
| Manual review | Overlays, assumptions, warnings | No |

### 9.2 Minimum automated matrix

#### Media

- valid H.264 MP4;
- unsupported container/codec;
- no video stream;
- multiple video streams;
- corrupt file;
- audio present/absent;
- CFR timestamps;
- VFR timestamps;
- duplicate/non-monotonic PTS;
- frame count mismatch.

#### Parser

- complete response;
- empty response;
- malformed response;
- missing frame;
- duplicate frame;
- reordered frame;
- invalid confidence;
- invalid box;
- malformed mask;
- object-ID switch;
- multiple objects.

#### Geometry

- known card scale;
- rotated card;
- partial card;
- wrong dimensions;
- out-of-plane card;
- short arc;
- fixed-camera violation;
- bob/card depth mismatch.

#### Physics

- ideal trajectory;
- damped trajectory;
- nonuniform PTS;
- noise;
- outliers;
- gaps;
- weak amplitude;
- short duration;
- non-convergence;
- parameter-bound hit;
- independent length missing.

#### Result states

Every state must have one fixture and one assertion:

- `success`;
- `success_with_warnings`;
- `insufficient_data`;
- `unsupported_input`;
- `processing_error`.

### 9.3 One runnable check per non-trivial stage

Each stage leaves at least one executable check. Use small assert-based tests or one small test file. Avoid test infrastructure bigger than product code.

---

## 10. Review protocol

### 10.1 Fable review checklist

For every stage:

- [ ] Scope matches locked v1.
- [ ] Diff is minimal.
- [ ] Contracts remain compatible.
- [ ] Input validation exists at trust boundaries.
- [ ] Error handling prevents false output.
- [ ] Tests include negative cases.
- [ ] Actual PTS are preserved.
- [ ] Units and coordinate conventions are explicit.
- [ ] AI output remains untrusted.
- [ ] No numeric result comes from prose/model.
- [ ] Scientific claim is supported by evidence.
- [ ] Uncertainty claim matches implementation.
- [ ] User files are preserved.
- [ ] No unnecessary dependency or abstraction added.

### 10.2 Review response format

```text
Decision: PASS | PASS_WITH_FIXES | BLOCK | SCOPE_CUT
Evidence accepted:
Critical defects:
Accuracy risks:
Security risks:
Scope risks:
Required fixes:
Next allowed stage:
```

### 10.3 Re-review triggers

Re-run Fable review when:

- schema changes;
- timestamp handling changes;
- mask decoding changes;
- calibration assumptions change;
- fit equations/solver change;
- uncertainty method changes;
- UI changes result interpretation;
- external API/model changes;
- a new agent replaces prior implementation;
- a merge conflict changes behavior.

---

## 11. Provisional hackathon timeline

Current date: **2026-10-27**. Existing audit documents cite a Meta/Cerebral Valley event around **2026-10-26 to 2026-11-04**, but official portal rules and submission deadline remain authority. Verify before final freeze. Do not rely on search snippets or planning-document claims.

| Date | Target | Must exist by end of day |
|---|---|---|
| Oct 27 | Freeze scope and contracts | This plan, stage assignments, package decision, no more smoke-test expansion |
| Oct 28 | Stages 0–2 | Manifest, runnable local check, schemas, media/PTS pipeline |
| Oct 29 | Stages 3–4 | Offline SAM parser, decoded masks, normalized observations, diagnostics |
| Oct 30 | Stage 5 | Synthetic ideal fit, basic damped fit, failure tests |
| Oct 31 | Stage 6 | Card geometry, calibration, independent-length input, geometry rejection |
| Nov 1 | Stage 7 | End-to-end offline `test_3` result and exports |
| Nov 2 | Stage 8 | Minimal local UI/CLI demo, cached fixture, failure path |
| Nov 3 | Stage 9 | Regression, security, claims audit, demo recording, docs freeze |
| Nov 4 | Final review | Fable sign-off, user acceptance, local commit, submission package |
| Nov 5 if applicable | Submission buffer | Push only after official deadline/rules confirmation |

### Time-cut order

If schedule slips, cut in this order:

1. interactive twin;
2. generated overlay video;
3. extra models;
4. live API reruns;
5. web UI;
6. broad object/card support.

Never cut:

- timestamp preservation;
- validation;
- failure states;
- tests;
- provenance;
- security;
- manual inspectability.

### Minimum hackathon demo

```text
local video fixture
  -> validated media
  -> timestamped observations
  -> card/bob overlay
  -> trajectory plot
  -> deterministic fit
  -> warning-aware result
  -> downloadable CSV/JSON
```

A CLI or static local report is acceptable if UI threatens the measurement path.

---

## 12. User inputs required later

Implementation starts without these. Physical result does not.

### Required before calibration

```text
Reference object type:
Reference object confirmed as ISO/IEC 7810 ID-1: yes/no
Reference width in mm:
Reference height in mm:
Card and pendulum motion plane same or near-coplanar: yes/no
Camera fixed: yes/no
Pivot fixed: yes/no
```

If confirmed ID-1, dimensions may be:

```text
width: 85.60 mm
height: 53.98 mm
```

Do not use those values for an unknown paper rectangle.

### Required before gravity claim

```text
Pivot-to-bob-center length in mm:
Length measurement method:
Length uncertainty in mm:
```

If absent, report the identifiable dynamic quantity, such as `g/L_eff`, or return insufficient data for a gravity claim.

### Optional validation input

```text
Expected local g:
Independent ruler/calibration evidence:
Additional real clips:
```

Expected `g` is validation context, never an input used to force fit output.

---

## 13. Documentation plan

### Keep and use

- `Docs/KineticLab_Locked_App_Plan.md`: locked product boundary and architecture.
- `Docs/Smoke_Test_Asset_Generation_Plan.md`: fixture rules.
- `Docs/KineticSim Theory and Project Audit.md`: hypothesis/risk catalogue; not authoritative where it conflicts with this plan.
- `Smoke/README.md`: smoke fixture notes.
- `README.md`: current setup and verified commands after implementation.

### Add

- `Docs/KineticLab_Master_Project_Plan.md`: this execution plan.
- `Docs/Decision_Log.md`: short dated decisions and reversals.
- `Docs/Review_Log.md`: Fable gate results.
- `Docs/Accuracy_Rules.md`: copied concise rules for every agent.
- `Docs/Demo_Runbook.md`: exact local demo sequence.
- `Docs/Claims_Register.md`: claim, label, evidence path, review date.

### Claims register fields

```text
claim_id
claim_text
label: measured | target | assumption | estimate | external_fact
source/evidence path
date checked
review status
```

No invented accuracy table, latency, API cost, user quote, or benchmark number.

---

## 14. Security and provenance

- Revoke API key previously exposed in chat.
- Check Windows and WSL environment variables before live API use.
- Store replacement key only in environment/secret store.
- Never save key in Markdown, shell history, raw output, test fixture, or provenance.
- Scrub logs for authorization headers and environment dumps.
- Hash source and derived media.
- Record software/dependency/model identifiers without credentials.
- Set local temporary-file cleanup rules.
- Preserve original media separately from processing copies.
- Do not upload user media unless explicitly required and consented.

---

## 15. Final release definition

KineticLab is ready for local demo when all are true:

- [ ] One supported clip runs end-to-end locally.
- [ ] Media and PTS validation passes.
- [ ] SAM fixture replay works offline.
- [ ] Mask centroid extraction works and is tested.
- [ ] Card geometry/calibration is inspectable.
- [ ] Independent-length requirement is enforced.
- [ ] M1 fit passes deterministic synthetic tests.
- [ ] M2 is either tested or excluded from demo.
- [ ] Residuals and warnings are visible.
- [ ] Every result has explicit state.
- [ ] CSV, JSON, and provenance export work.
- [ ] Failure fixture returns failure, not fake success.
- [ ] No unsupported scientific claim appears in UI, README, or demo narration.
- [ ] No secrets appear in repository or artifacts.
- [ ] Fable passes final review.

KineticLab is ready for GitHub push only when all above pass and user confirms final submission timing.

---

## 16. Immediate next actions

1. Treat this document as execution baseline.
2. Assign Stage 0 to one builder agent.
3. Assign Stage 1 schema work to one agent or same builder.
4. Keep fit work in a separate local lane after contracts are agreed.
5. Do not start UI yet.
6. After Stage 0/1 completion, invoke Fable for review.
7. Then build Stage 2 and Stage 3 offline replay.
8. Collect card/setup/length inputs before Stage 6 physical calibration.
9. Revoke exposed API key before any new API request.
10. Push GitHub only after final review and explicit user approval.

**First implementation target:** offline, inspectable, timestamp-preserving pipeline. Not broad AI automation. Not polished speculation.
