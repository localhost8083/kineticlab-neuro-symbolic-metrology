# KineticLab — Locked Application Plan

**Version:** 1.0  
**Status:** Implementation baseline for smoke tests  
**Date:** October 27, 2026  
**Project name:** KineticLab  
**Repository:** `kineticlab-neuro-symbolic-metrology`

---

## 1. Executive Decision

### 1.1 One-sentence product definition

**KineticLab turns a short phone video of a single-plane pendulum experiment into an uncertainty-aware physical measurement—most notably gravitational acceleration \(g\)—using vision-based object tracking, a known reference object, timestamped frames, nonlinear ODE fitting, and explicit quality gates.**

### 1.2 Product thesis

Language models are not the measurement engine. KineticLab uses models only where they add capability that deterministic software cannot provide safely:

- **SAM 3.1** performs visual detection/tracking and produces frame-level object observations.
- **Muse Spark** may support scene validation and explanation, but **it never authors numeric results**.
- **SciPy/NumPy** perform geometry, ODE integration, parameter estimation, and residual diagnostics.
- **SymPy** may later validate bounded symbolic proposals, but only after the core estimator is proven.

### 1.3 Locked core result

The first product must reliably answer:

> “Given a properly filmed pendulum clip plus an independent physical scale reference, what quantity can we measure, with what uncertainty, and can we trust the fit?”

The app must also safely answer:

> “This clip/setup is not sufficient for a defensible measurement; here is what failed and why.”

### 1.4 What this document locks

This document locks the **product boundary, architecture, scientific assumptions, interfaces, verification strategy, smoke-test gates, and minimum viable release** for the first implementation.

It does **not** lock marketing claims, benchmark numbers, model/vendor specifics beyond the current best plan, or optional “wow” features.

---

## 2. Naming and Scope

### 2.1 Naming

- **Current name:** **KineticLab**
- Deprecated/historical names in older docs: **PocketLab**, **KineticSim**
- Do not reuse those old names in UI, docs, filenames, or code unless explicitly describing historical design iterations.

### 2.2 In scope for the first release

The first release focuses on **one experiment type only**:

- **Simple planar pendulum** filmed side-on from a fixed camera.
- One visible **reference card** (ISO/IEC 7810 ID-1 format) placed as close as possible to the swing plane.
- A single dominant moving object: the **pendulum bob**.
- One user-uploaded clip of roughly **3–10 seconds**.
- One analysis result per clip, with uncertainty and quality status.

### 2.3 Explicitly out of scope for v1

These are intentionally deferred:

- Multi-body experiments.
- Collisions, springs, double pendulums, rolling balls, ramps.
- Handheld video.
- 3D reconstruction.
- Generic physical-scene auto-detection beyond a limited scene sanity check.
- Full symbolic model discovery loop.
- Interactive digital twin.
- Multi-user collaboration.
- Cloud deployment.
- Accounts, auth, or stored user libraries.
- Generated PDF reports.
- Muse Wonder escalation.
- Voice input.
- Live camera processing.
- Browser-upload transcoding pipeline for arbitrary codecs beyond a narrow safe ingest path.

### 2.4 Product promise boundary

KineticLab should promise:

- **Measured trajectory and fit**
- **Traceable uncertainty**
- **Clear reject/insufficient-data states**
- **Inspectable diagnostics**

It should **not** promise:

- Guaranteed gravity accuracy without independent scale/length.
- “Exact” physics.
- Fully automatic physics discovery.
- Judge-ready benchmark claims before data exists.

---

## 3. Target Users and Jobs

### 3.1 Primary users

- High-school and university physics students.
- Physics teachers and lab instructors.
- Self-learners and makers without dedicated lab hardware.

### 3.2 Primary job-to-be-done

> “I recorded my experiment. Give me a defensible measurement and explain whether the video quality is good enough to trust it.”

### 3.3 Secondary jobs

- Compare ideal vs damped pendulum behavior on the same footage.
- Export observations and fit results for further analysis or submission.
- Understand why a clip was rejected or flagged.

### 3.4 Non-goals

- Do not replace a full video-analysis suite.
- Do not support arbitrary experiments at launch.
- Do not hide bad data behind a polished report.

---

## 4. End-to-End User Flow

### 4.1 Intended happy path

1. User reads a short capture checklist.
2. User uploads or records a small clip of a pendulum with a visible reference card.
3. App validates the file and extracts metadata.
4. App obtains bob observations and a card observation.
5. App computes scale, trajectory, quality flags, and fit.
6. App displays:
   - measured quantity or identifiable quantity,
   - uncertainty,
   - fit quality,
   - trajectory overlay or equivalent visual verification,
   - assumptions and warnings,
   - CSV/provenance export.

### 4.2 Failure path

If a clip is unsupported or insufficiently trustworthy, the app must return one of:

- `unsupported_input`
- `insufficient_data`
- `processing_error`
- `success` with warnings only when appropriate

The app must **not** fabricate a precise answer when the measurement chain fails.

---

## 5. Locked System Architecture

## 5.1 Architectural philosophy

- Keep each stage small, testable, and independently replaceable.
- Keep the measurement path deterministic and auditable.
- Treat all external model output as **untrusted telemetry**, not ground truth.
- Prefer a local/offline core first; add UI and cloud layers only after the estimator is proven.

## 5.2 High-level pipeline

```text
Uploaded clip
  -> Ingest & validation
  -> Frame/timestamp mapping
  -> Observation stage (bob tracking + card detection)
  -> Geometry & calibration
  -> Model fitting & residual diagnostics
  -> Result assembly & export
  -> UI/review layer
```

## 5.3 Module boundaries

### 5.3.1 `ingest`

Responsibilities:

- Validate media type, size, duration, resolution, and frame count.
- Preserve original upload.
- Extract media metadata.
- Extract presentation timestamps when available.
- Normalize the processing copy only if required by downstream stages.

Outputs:

- `input_metadata`
- `frame_index_to_pts`
- normalized processing media
- ingest warnings/errors

Hard rule:

- Never silently discard timestamp information.

### 5.3.2 `observation`

Responsibilities:

- Detect/track the bob.
- Detect the reference card.
- Return per-frame object IDs, confidence, masks/boxes/centroids, and provenance.
- Allow a mock/offline implementation for tests.

Outputs:

- `bob_observations`
- `card_observations`
- tracking quality flags

Hard rules:

- Model output must be schema-validated.
- Missing or malformed frames must remain explicit, not silently reordered.
- A stable track must not be inferred merely because a noun phrase was sent.

### 5.3.3 `geometry`

Responsibilities:

- Convert image coordinates to physical units using a known reference.
- Estimate or validate bob trajectory geometry.
- Provide setup-quality checks and coordinate transforms.

Outputs:

- pixel-to-meter scale or plane mapping
- bob trajectory in physical coordinates
- pivot/center diagnostics
- geometry warnings/reject reasons

Hard rules:

- A card in the background is not automatically valid calibration for the bob plane.
- Circle fit is a diagnostic, not proof of scale or length.

### 5.3.4 `fit`

Responsibilities:

- Fit a small locked model library to the observed angle/time series.
- Use actual timestamps and explicit observation weights.
- Return parameter estimates, convergence status, residual summaries, and uncertainty components.

Outputs:

- fitted parameters
- model ranking/diagnostics
- uncertainty summary
- warnings/reject reasons

Hard rules:

- `solve_ivp` is a numerical solver, not “exact physics.”
- No model-specific magic numbers may leak into the final result without assumptions being recorded.

### 5.3.5 `result`

Responsibilities:

- Assemble the final result contract.
- Enforce quality gates and explicit state transitions.
- Generate CSV/provenance/report artifacts.

Outputs:

- final `AnalysisResult`
- downloadable CSV
- provenance record
- optional Markdown report

Hard rule:

- Numeric values in exports and reports must be inserted by code, never authored by a language model.

### 5.3.6 `ui` / `review`

Responsibilities:

- Present capture guidance, upload flow, quality flags, and result views.
- Show trajectory and residuals clearly enough for manual inspection.
- Avoid pretending the result is better than it is.

Hard rules:

- UI must expose assumptions and warnings.
- UI must distinguish measured values from model predictions.

---

## 6. Scientific Model and Measurement Contract

## 6.1 Physical experiment

A planar pendulum with bob center distance \(L\) from pivot, angular displacement \(\theta(t)\) from vertical, and possibly damping.

## 6.2 Locked initial model library

Start with a small, explicit set only:

- **M1 — Ideal pendulum:**
  \(\theta'' + (g/L)\sin\theta = 0\)

- **M2 — Linear damping:**
  \(\theta'' + \gamma \theta' + (g/L)\sin\theta = 0\)

- **M3 — Quadratic drag:** optional only after M2 works reliably:
  \(\theta'' + c|\theta'|\theta' + (g/L)\sin\theta = 0\)

Everything else is out of scope until the baseline is proven.

## 6.3 Identifiability rule

For the angular dynamics alone, the identifiable quantity is approximately:

\[
\Omega_0^2 = g/L_{\mathrm{eff}}
\]

Therefore:

- To report \(g\), the app requires an independent length \(L\) or an independently validated scale in the bob’s motion plane.
- If independent length is unavailable, report \(g/L_{\mathrm{eff}}\) or a fit on angular dynamics only.
- A video circle fit cannot be treated as an independent length measurement when it is derived from the same video and same scale chain.

## 6.4 Calibration contract

The initial calibration contract is deliberately conservative:

- The card is a **same-plane or near-coplanar** reference.
- The camera is fixed.
- The clip is a side-on, near-planar view.
- Perspective distortion is small enough for the intended uncertainty budget.

If this assumption fails, the app should flag or reject the clip rather than invent a correction.

## 6.5 Uncertainty policy

The first release must report uncertainty with a transparent decomposition:

- fit uncertainty,
- tracking variability,
- scale/length uncertainty,
- model/geometry warnings where relevant.

If the full statistical framework is not yet validated, the app must state that uncertainty is provisional and describe the method used.

### Uncertainty guardrail

- Do not double-count a video-derived scale error and a circle-fit radius error as independent corrections.
- Do not present narrow error bars from a Jacobian covariance alone as if they include all systematic optical and tracking biases.

## 6.6 Result contract

Every result must include:

- `status`: `success | insufficient_data | unsupported_input | processing_error`
- measurement name and value
- units
- uncertainty interval and method
- fitted model name
- parameter list and fit/convergence status
- track completeness and rejected/interpolated samples
- assumptions and warnings
- provenance metadata
- export files

If any critical assumption fails, the result must fail honestly.

---

## 7. Data Contracts

## 7.1 Internal frame mapping

Canonical mapping:

```text
output_frame_index -> source_pts_seconds -> decoded/transcoded frame_reference
```

This mapping is the source of truth for fitting and any overlay sync.

## 7.2 Bob observation record

Each tracked frame should store at minimum:

- frame index
- timestamp
- object id
- confidence
- centroid or equivalent position
- mask/box reference if available
- validity flag

## 7.3 Calibration record

Store:

- reference object type
- observed pixel dimensions
- estimated scale or plane transform
- uncertainty inputs
- assumptions and warnings

## 7.4 Fit record

Store:

- model name
- parameters
- solver/optimizer settings
- convergence flags
- residual statistics
- residual autocorrelation summary
- parameter uncertainty or confidence method

## 7.5 Provenance record

Each result should record:

- input hash
- timestamp of run
- software/dependency versions
- model/API identifiers
- request settings
- input metadata
- calibration inputs
- fit configuration
- output schema version

Do **not** store API keys or unnecessary identifying user media metadata.

---

## 8. External Services and Dependency Boundaries

## 8.1 Meta Model API / SAM 3.1 boundary

The project may use **SAM 3.1** for visual tracking and reference detection, but the interface must be replaceable.

Required adapter behavior:

- Accept a prepared clip/frame.
- Return normalized observation records.
- Expose raw vendor response for debugging/inspection.
- Allow offline replay from saved fixtures.

### Current implementation rule

Before implementation, verify:

- current API endpoint and SDK contract,
- request schema,
- image vs video modes,
- response framing,
- mask encoding,
- confidence representation,
- object ID semantics,
- accepted media types and limits.

Do **not** code against undocumented assumptions.

## 8.2 Muse Spark boundary

Muse Spark may be used for:

- scene sanity checks,
- naming the tracked object,
- optional narrative/report prose.

It must not:

- decide numeric results,
- bypass validation,
- modify model code at runtime,
- override quality gates.

## 8.3 Numerical stack

Preferred initial stack:

- Python 3.11+
- FastAPI or equivalent HTTP backend when needed
- ffmpeg/ffprobe for media metadata and processing
- NumPy, SciPy, pandas
- OpenCV for contours/overlays
- SymPy only if later needed for constrained symbolic proposals

---

## 9. Minimum Implementation Plan

## 9.1 Phase order

The project should be implemented in strict order:

### Phase A — Repository and smoke-test foundation

- Create package/module skeleton.
- Add dependency manifest and minimal config.
- Add a small CLI or script for smoke tests.
- Add saved fixtures directory.
- Add a tiny integration test for media metadata and API request/response parsing.

### Phase B — Offline estimator

- Generate synthetic trajectories.
- Fit M1 and M2.
- Validate parameter recovery.
- Implement residual diagnostics and failure states.

### Phase C — Observation pipeline

- Implement card detection.
- Implement bob tracking.
- Normalize observations.
- Save inspection overlays and fixtures.

### Phase D — Calibration and measurement

- Combine scale + independent length.
- Compute physical coordinates.
- Fit real clip(s).
- Report uncertainty and failure states.

### Phase E — Minimal app shell

- Upload file.
- Run analysis.
- Show result, warnings, exports.
- Keep UI simple and inspectable.

### Phase F — Optional extensions

Only after a stable real-clip benchmark exists:

- AICc/model comparison refinement
- symbolic proposal loop
- ghost overlay video export
- interactive twin
- report prose via model
- deployment work

## 9.2 Recommended file structure

```text
app/
  ingest/
  observation/
  geometry/
  fit/
  result/
  ui/
scripts/
tests/
data/
  fixtures/
  samples/
Docs/
```

---

## 10. Smoke Test Plan — Day One

The first smoke test is the go/no-go gate for the entire project.

## 10.1 Inputs needed

- One consented, controlled H.264 MP4 clip of a pendulum.
- One visible ISO ID-1 card in the same or near plane.
- A measured physical pendulum length via ruler.
- Local access to ffmpeg/ffprobe.
- API credentials in environment only.
- A saved fixture path for offline parser testing.

## 10.2 Smoke-test objectives

Verify all of the following before proceeding:

- Can we extract meaningful frame timestamps?
- Can we detect the card and bob reliably enough?
- Can we normalize observations into a stable schema?
- Can we map frame indices to timestamps correctly?
- Can we generate a useful trajectory for fitting?

## 10.3 Smoke-test gates

The smoke test should verify, at minimum:

- **Track completeness:** bob found on a large fraction of frames.
- **Track stability:** no obvious object ID switching or centroid spikes.
- **Card detection:** card found on frame 0 or equivalent reference frame.
- **Timestamp mapping:** extracted PTS values align with decoded frame order.
- **End-to-end latency:** clip processes in a practical amount of time.
- **Parser robustness:** malformed or missing frames are detected, not silently absorbed.

## 10.4 Smoke-test outputs

The smoke test should save:

- input metadata summary
- frame index ↔ PTS table
- normalized observation table
- card detection summary
- trajectory CSV
- one or more inspection overlays or frames
- any warnings and errors

## 10.5 Smoke-test success criteria

Proceed only if the smoke test produces:

- a usable timestamped trajectory,
- a credible card observation,
- no silent timestamp corruption,
- stable object association,
- a repeatable normalized schema,
- and a clear path to a first fit.

If any gate fails, fix the lowest-level cause first.

---

## 11. Quality Gates and Failure Rules

## 11.1 Input rejection rules

Reject or flag a clip if:

- file type/container is unsupported,
- duration is outside limits,
- camera moves during the clip,
- reference card is absent or ambiguous,
- bob track coverage is too low,
- timestamps are missing or inconsistent,
- frame indices cannot be mapped reliably,
- perspective/setup violates the locked assumptions.

## 11.2 Fit rejection rules

Fail or downgrade result if:

- the trajectory has too few usable oscillations,
- the fit does not converge,
- parameters hit bounds in a way that invalidates interpretation,
- residuals show severe unexplained structure,
- independent length is missing for a gravity result.

## 11.3 Warning rules

Warn but continue when:

- a short dropout is interpolated,
- confidence is borderline but still usable,
- card plane is only approximately coplanar,
- fit uncertainty is large but interpretable.

---

## 12. Metrics to Measure

The app should record and later report:

- fraction of frames with valid bob observations
- missing-frame spans
- track jitter
- fit residual statistics
- parameter estimates and confidence methods
- latency by stage
- API/request cost when measured
- failure reasons by clip

Never present targets as results.

---

## 13. Minimum Release Definition

A v1 release is complete only when:

- a user can upload one supported clip,
- the app validates input and timestamps,
- card and bob observations are produced,
- at least one supported model fit runs,
- a result or explicit failure state is returned,
- uncertainty and warnings are shown,
- CSV and provenance are exported,
- and a small regression suite exists.

If this is not true, the app is not release-ready.

---

## 14. Risks and Mitigations

| Risk | Impact | Mitigation |
| :-- | :-- | :-- |
| Vendor API changes | Break tracking | Adapter layer + saved fixtures + smoke test |
| Variable frame-rate timing | Corrupts fit | Preserve exact PTS and frame mapping |
| Card/bob depth mismatch | Scale error | Require coplanarity or reject/flag |
| Short-arc circle fit | Bad geometry | Use only as diagnostic, not independent length |
| Tracking flicker | Bad fit | Confidence weighting, outlier rejection, missing-frame flags |
| Overstated uncertainty | False confidence | Transparent uncertainty budget and coverage tests |
| Overcomplex model search | Selection bias | Start with tiny fixed model set only |
| UI polish before proof | Wasted effort | Build the offline pipeline first |
| Unsupported performance claims | Reputational risk | Label all values as measured/target/estimate |
| Secret leakage | Security risk | Environment-only credentials; no secret logs |

---

## 15. Locked Design Rules

1. **No numeric result may come from a language model.**
2. **A result must be inspectable, not merely impressive.**
3. **Independent scale/length is required for a gravity claim.**
4. **Timestamps are sacred.** Do not infer uniform timing when actual timing is available.
5. **Circle fit is a diagnostic, not proof of calibration.**
6. **Reject bad input early; never guess silently.**
7. **Keep the first model library small and explicit.**
8. **Treat every external model output as untrusted telemetry.**
9. **No benchmark claims without benchmark data.**
10. **Prefer a small working pipeline over a large speculative one.**

---

## 16. Deferred Features

These are explicitly deferred until the core pipeline is proven:

- closed-loop symbolic discovery,
- model-selection ranking improvements beyond a basic comparison,
- interactive RK4 digital twin,
- server-rendered ghost-overlay MP4 export,
- advanced residual whitening pipeline,
- multi-run uncertainty benchmarking,
- user accounts,
- cloud deployment,
- automated benchmark suites,
- real-time camera mode,
- PDF report generation.

---

## 17. Acceptance Checklist for Implementation Start

Before coding the full app, confirm:

- [ ] The repo has a minimal dependency manifest.
- [ ] ffmpeg/ffprobe are available locally.
- [ ] A test clip and measured length exist.
- [ ] API credentials are available locally and not committed.
- [ ] A fixture capture path exists.
- [ ] The smoke test has been defined in a script or CLI entry point.
- [ ] The app has a locked result contract.
- [ ] The app has a locked list of supported models.
- [ ] The app has a clear rejection/failure policy.

---

## 18. Final Lock

This plan locks the **minimum useful KineticLab**: a defensible, uncertainty-aware pendulum measurement pipeline with explicit failure handling and a small set of supported physics models.

Everything beyond that is optional, staged, and subordinate to proof that the measurement chain works.

---

## 19. Open verification items

These must be verified against primary sources before public claims:

- current Meta Model API endpoint and SDK contract,
- SAM 3.1 request/response schema and supported media limits,
- confidence/mask/object-ID semantics,
- current pricing and rate limits,
- hackathon submission rules and allowed tooling claims.
