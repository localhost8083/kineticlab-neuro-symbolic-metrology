# PocketLab: Trustworthy Measurements from Phone Video

*Project document for the Meta Global AI Developer Hackathon, Indie Developer Track · Version 1.0 · October 27, 2026*

## 1. Summary

PocketLab turns a short phone video of a physical experiment into a measured, uncertainty-aware result. A student films a pendulum next to a credit card. PocketLab tracks the bob with SAM 3.1, converts pixels to meters, fits a library of physical models, and reports a measured quantity (for example gravitational acceleration, g) with error bars. It also renders a “ghost” of the fitted motion on top of the original video and writes a lab report.

**One-line pitch:** chatbots guess numbers from video; PocketLab measures them.

**Core thesis.** Language models are weak at precise geometry and numbers. SAM 3.1 is strong at geometry. SciPy is strong at fitting. PocketLab gives each job to the tool that does it best and uses the language model only for what it does well: proposing and explaining physics. No number in a result ever comes from a language model.

**Status.** Planning. PocketLab is the re-aimed version of the earlier KineticSim idea. A go/no-go smoke test on SAM 3.1 tracking is the first task (see section 13).

## 2. Hackathon context

- **Event:** Meta Global AI Developer Hackathon, hosted by Meta and Cerebral Valley. Virtual, October 26 to November 4, 2026.
- **Key dates:** submissions due November 4 at 9:00 PM ET; judging November 4 to 8; finals and winners announced November 9.
- **Indie Developer track:** for individual builders and students (teams of up to four per a third-party guide). Judged on creativity, technical ambition, and whether it works.
- **Problem statements** (from our research doc): *Build for Your World* and *Push the Frontier*. PocketLab is positioned under Push the Frontier (physical systems) with students and teachers as the beneficiary. Confirm the theme selection on the submission form.
- **Credits:** each selected participant gets $150 in Meta Model API credits.
- **Prize amounts:** a third-party guide reports $400,000 for the Indie track with $150,000 for first place. This is unverified against the official rules.

### How we are scored

The official rubric uses the same weights in Stage 2 and the final round. Each criterion is scored 0 to 10.

| Criterion | Weight | How PocketLab earns it | Evidence to show |
| :-- | :-- | :-- | :-- |
| Impact | 30% | A named user (physics students and teachers without lab equipment) and a concrete job: a trustworthy measurement and a report from one phone clip | Quotes and time-to-result from 3 to 5 real users; the measured accuracy table |
| Use of Meta AI tooling | 25% | SAM 3.1 does the measurement work (tracking and reference detection), Muse Spark does model proposals and explanations, Muse Code builds and tests the project | A pipeline diagram showing each Meta tool doing a job a single chat call cannot do |
| Technical depth | 20% | Calibration, weighted nonlinear fitting, model selection with AICc, uncertainty quantification, synthetic-clip parameter recovery tests | The residual and model-comparison view; the test suite results |
| Demo | 25% | Real clip in, ghost overlay locks on, number with error bars out, in under 15 seconds of video | A tight 110-second video and a live site with cached examples |

## 3. Problem and users

**Problem.** Measurement is the core of physics learning, but it needs equipment, time, and careful setup. Video-analysis tools exist (Tracker is the best known), but they typically require manual or semi-manual setup, and the student must choose the model. We have not benchmarked them, so we will not make claims about how long they take. We will measure that ourselves in a user test.

**Primary users.** High-school and university physics students and teachers, especially where lab kits are scarce. Also self-learners and makers.

**Job to be done.** “I filmed my experiment. Give me a trustworthy number and a report I can submit.”

**Validation plan.** Before November 3, have three to five real people (a teacher and two students, ideally) film and process a clip. Record time-to-result, whether they trusted the output, and one quote each. This is the strongest available evidence for the Impact score. Do not quote numbers we have not measured.

## 4. Why this is not a chatbot wrapper

Judges will ask whether Gemini or ChatGPT could do this. The honest answer is no, for these reasons:

| Capability | Chatbot with video upload | PocketLab |
| :-- | :-- | :-- |
| Frame-accurate positions | Approximate and not reproducible | SAM 3.1 tracks every frame with stable ids and confidence values |
| Metric scale | Guessed | Calibrated from a reference object of known size |
| Parameter estimation | Plausible-sounding numbers | Weighted nonlinear least squares with uncertainty |
| Model choice | Opinion | AICc comparison and residual tests; the language model only explains and proposes |
| Verification | None | Synthetic-clip parameter recovery tests plus a real-clip accuracy table |
| Output | Text | Dataset (CSV), ghost-overlay video, parameter table, lab report |

## 5. Scope

### 5.1 Supported experiments

- **Hero:** simple pendulum (a ball on a string).
- **Second, if time allows:** damped spring-mass oscillator.
- **Stretch:** ball drop or ramp roll.

### 5.2 Capture protocol

The app shows this checklist before recording, because tracking and calibration depend on it.

- Fixed camera on a tripod or a stack of books, perpendicular to the swing plane, with the whole motion in frame.
- A credit card (ISO ID-1, 85.6 mm long side) taped in the **same plane** as the bob. A card is available almost everywhere.
- A uniform, contrasting sphere. Steady lighting. Plain background.
- 30 to 60 fps (phone slow-motion is fine), 5 to 10 seconds, at least three full oscillations.
- Measure pivot-to-bob-center length with a ruler (target ±2 mm).
- Upload as MP4 (H.264 or H.265). The app transcodes anything else.

### 5.3 Out of scope

3D motion, handheld footage, multi-body collisions, robotic grippers. A MuJoCo or URDF export is a stretch goal only and is first on the cut list.

## 6. User flow

1. Upload or record a clip. The app transcodes it to H.264 MP4 with faststart.
2. Pick the experiment type (or let the app suggest one) and optionally enter the measured string length.
3. The pipeline runs with visible progress for each stage.
4. The result view shows the ghost-overlay video, the measured value with uncertainty, the model comparison, and the residual plot.
5. The user downloads a CSV, a lab report, and a reproducibility record (software versions, model ids, settings).

Target: a result in well under a minute for a 6-second clip. Log the real figure and report it, not the target.

## 7. System architecture

### 7.1 Pipeline stages

**Stage 0: Ingest.** Validate and transcode with ffmpeg to H.264 MP4 with the moov atom at the front. Keep the native frame rate. Cap the length (a few seconds is enough; the API accepts up to 15,000 frames per request, but we do not need that).

**Stage 1: Scene check (Muse Spark, optional).** Spark confirms the clip shows the expected experiment, names the object to track as a short noun phrase (for example “metal ball”), and flags capture problems such as a tilted camera, motion blur, or a missing reference object.

**Stage 2: Calibration (SAM 3.1, one image request).** Extract frame 0 as a PNG and send it with the concept “credit card”. Take the long side of the returned box in pixels. Scale (meters per pixel) is the known card length divided by that pixel length. Using a still image avoids the 50-frame minimum billed on video requests.

**Stage 3: Tracking (SAM 3.1, one video request).** Send the uploaded clip by file id with the concept for the bob. Request confidence values and compact masks. Parse the streamed lines into per-frame boxes and masks. Use the mask centroid for the position of a round object. Box centers are the fallback (note that the output box coordinates x2 and y2 are inclusive).

**Stage 4: Cleaning and geometry.** Reject outliers, interpolate short gaps, and flag long ones. Convert to meters. Estimate the pivot by a least-squares circle fit to the trajectory. The fitted radius times the scale gives an independent estimate of the string length, which cross-checks the ruler measurement. Compute the angle from vertical, θ(t).

**Stage 5: Model fitting (SciPy).** Fit each candidate model in the library (section 8) with weighted nonlinear least squares, integrating the ODE with an initial-value solver. Weights come from SAM confidence. Use multiple starting points to avoid local minima.

**Stage 6: Model selection and diagnosis.** Rank models by AICc. Run residual diagnostics: lag-1 autocorrelation, Durbin-Watson, and the spectrum of the residuals. If the best model still leaves structured residuals, send summary statistics (not raw numbers to be copied) to Muse Spark and ask for a candidate physical explanation and an extra model term. Validate the proposal (see 8.4), fit it, and accept it only if AICc improves meaningfully.

**Stage 7: Outputs.** Render the ghost overlay (fitted trajectory and body drawn over the original frames), the CSV, the parameter table with uncertainty, the model comparison chart, and the lab report. Muse Spark writes the report prose from the structured results. Every number in the report is inserted from the fit outputs by code, never generated.

### 7.2 Where each Meta tool is used

| Tool | Role | Required? |
| :-- | :-- | :-- |
| SAM 3.1 | Reference detection (image) and bob tracking (video); the measurement backbone | Required |
| Muse Spark (1.3; the cheaper contributor tier for high-volume loops) | Scene check, residual diagnosis, candidate model proposals, report prose | Required |
| Muse Code | Builds the project with parallel work trees; optionally runs headless regression checks | Used in the build; verify the headless commands in the docs before relying on them |
| Muse Wonder | Heavier reasoning if Spark’s proposals are weak | Optional |
| Muse Voice Transcribe | Hands-free “start” and annotations | Optional; cut first if time is short |
| Muse Image | Not needed | Do not force it |

A tool is included only if it does real work. Forcing optional tools in would look like the “basic integration” the rubric penalizes.

### 7.3 SAM 3.1 API facts (verified in Meta’s docs on October 27)

- Base URL is https://api.meta.ai/v1 and the model id is sam-3.1, called through the Responses API with streaming. The API is OpenAI-SDK compatible. The key goes in MODEL\_API\_KEY.
- **One concept per request,** written as a short noun phrase such as “metal ball”. Comma lists return nothing; commands and questions are unreliable. Send one request per concept.
- Upload a video once with the Files API (purpose user\_data). The upload is synchronous, and the returned file id is reused across requests.
- Video output is one line per frame; read the frame marker rather than relying on line order. Video tracks up to 16 objects per frame.
- Accepted video: MP4 or MOV with H.264, H.265, or MPEG-4. VP9 and WebM are rejected, so browser recordings must be transcoded.
- Video is billed per frame with a 50-frame minimum per request.
- Results can vary slightly between runs of the same request. This drives the three-run protocol in section 10.
- Setting include\_confidence to the string “true” adds a confidence value (0 to 1) to each box and mask.
- Mask encoding is selectable; the compact one-bit encoding is smaller and faster to stream.
- A Python parser (meta\_sam\_parser) and TypeScript packages exist. The Python entry points are not documented in detail, so the project’s smoke-test script parses box lines directly with a regular expression instead of depending on them.

## 8. Physics and mathematics

### 8.1 Model library

Let θ be the angle from vertical, L the string length to the bob’s center, and g the gravitational acceleration.

- **M1, ideal pendulum:** θ'' + (g/L) sin θ = 0.
- **M2, linear damping:** θ'' + γ θ' + (g/L) sin θ = 0.
- **M3, quadratic drag:** θ'' + c |θ'| θ' + (g/L) sin θ = 0.
- **M4, extended bob:** replaces g/L with g·L / (L² + (2/5) r²) for a solid sphere of radius r on a light string, because the moment of inertia about the pivot is I = (2/5) m r² + m L².
- **M5, pivot friction:** adds a constant-magnitude friction term that opposes the motion.

For large amplitudes the period grows roughly as T ≈ T0 (1 + θ0²/16), where T0 = 2π √(L/g). The nonlinear ODE captures this automatically, which is why we do not rely on the small-angle formula.

### 8.2 Identifiability: you cannot fit g without an independent L

In the pendulum equations only the ratio g/L appears. The dynamics alone give g/L, not g. PocketLab therefore has two modes:

- **Measure g:** take L from the ruler (or from the circle-fit radius times the card scale), fit g/L from the dynamics, and compute g = (g/L) × L.
- **Identify the model:** assume a nominal g and fit an effective length and the damping terms, to compare model structures.

### 8.3 Uncertainty

Combine three sources and report the total with its breakdown:

1. **Fit uncertainty** from the parameter covariance (the Jacobian-based estimate scaled by the residual variance).
2. **Tracking variability** from three independent SAM runs on the same clip, each re-fitted.
3. **Scale and length uncertainty** from the card’s pixel length and the ruler reading. Because g = (g/L) × L, the relative uncertainty in g combines the relative uncertainty in g/L and in L in quadrature.

Use a block bootstrap on residuals, since residuals from oscillating signals are autocorrelated. Observe at least three full periods.

### 8.4 Model selection rules and language-model guardrails

- Rank by AICc, which penalizes extra parameters and corrects for small samples. A drop of more than about 2 is the usual rule of thumb for a meaningful improvement.
- The language model may propose an additional term, but only as a structured expression using a fixed whitelist of symbols and operators. The expression is parsed with a symbolic library, never executed as code.
- A proposed model is accepted only if it improves AICc and leaves unstructured residuals. Otherwise the report states that no tested model fits well.
- The language model never supplies numeric results.

## 9. Tech stack and repository layout

- **Backend:** Python 3.11 or later, FastAPI, ffmpeg, OpenCV (overlay rendering), NumPy, SciPy, SymPy, pandas.
- **Frontend:** a small React and Vite app (or plain HTML) with Plotly for charts and a video element for the ghost overlay. Server-side rendering of the overlay into an MP4 is the reliable choice, because frame-accurate client-side sync is a common time sink.
- **Jobs:** background tasks with progress polling; stream SAM events to report progress.
- **Hosting:** any host with ffmpeg and enough request time. Partner credits (Modal, Baseten, Fireworks) may be offered to selected participants; confirm before relying on them.

Suggested layout: an app folder for the API and pipeline, with modules for ingest, calibration, tracking, geometry, fitting, selection, and report; a tests folder with synthetic-clip generators; a data folder for real clips and their ground truth; a scripts folder holding smoke\_test\_sam.py; and a README mapped to the rubric.

## 10. Evaluation plan

The accuracy table is the single most persuasive artifact for Technical depth and Impact, so we build it deliberately.

**Test matrix (real clips, at least 10):** three string lengths, two lighting conditions, two ball colors, 30 and 60 fps, at least one clip with a deliberate flaw (slight tilt or partial occlusion) kept as an honest failure case.

**Ground truth:** the local value of g is about 9.8 m/s² (it varies slightly by location and altitude), plus an independent stopwatch period count over many swings.

**Metrics per clip:** error in g (percent), period error, fraction of frames with a stable track, tracking jitter, run-to-run spread over three SAM runs, end-to-end latency, and cost per run.

**Targets (not results):** g within a few percent on most clips. Replace this with the measured outcome and publish failures too. Judges trust honest numbers.

**User test:** three people, time-to-result and one quote each. If we compare to Tracker, do it with a real person on the same clip and report what we saw.

## 11. Automated verification

**Level 1, trajectory tests (offline, free, fast).** Generate synthetic trajectories from the model library with known parameters and added noise, then check that the fitter recovers them and that model selection picks the right structure (including when quadratic drag is the truth). Run thousands of cases.

**Level 2, synthetic video tests (uses SAM).** Render pendulum clips with known parameters, a card, and noise, encode as H.264, and run the full pipeline on about 20 of them. Inject faults: occlusion, blur, a scale error, a tilted camera. Note that SAM may behave differently on synthetic shapes than on real footage, so real clips remain the primary evidence.

**Level 3, real-clip regression.** A saved set of real clips with ground truth, re-run before every deploy.

Muse Code can be used to generate the test harness and run it in CI. Verify its headless commands in the Muse Code docs first.

## 12. Budget and limits

- Credits: $150 in Meta Model API credits.
- Third-party price summaries list SAM 3.1 at about $0.20 per 1,000 video frames and $2.50 per 1,000 images, and the Spark contributor tier at $0.10 per million input tokens and $0.20 per million output tokens. Confirm on Meta’s pricing page.
- A 6-second clip at 30 fps is 180 frames, roughly $0.04 for the tracking request, plus a tiny image request and a few thousand Spark tokens. Treat this as an estimate and log the real cost per run from day one.
- Rate limits are generous for SAM (a third-party source lists 3,000 requests per minute), but confirm before a live demo.

## 13. Build schedule (submit by noon ET on November 4)

| Date | Goal | Exit criteria |
| :-- | :-- | :-- |
| Tue Oct 27 | Smoke test, capture protocol, repo skeleton | Go/no-go gates below pass |
| Wed Oct 28 | Calibration, tracking extraction, CSV; offline fitter on synthetic trajectories | Synthetic parameters recovered; real clip produces a clean trajectory |
| Thu Oct 29 | End-to-end on real pendulum clips; circle-fit pivot and length; both modes | First real g with uncertainty |
| Fri Oct 30 | Model library, AICc, residual diagnostics, language-model proposals with whitelist | Correct model chosen on a damped clip |
| Sat Oct 31 | UI: upload, progress, results; overlay renderer | Full flow works in a browser |
| Sun Nov 1 | Evaluation: 10 or more real clips, three-run variance, latency and cost logs, user tests | Accuracy table complete |
| Mon Nov 2 | Lab report generator, hardening, cached demo examples, fallback paths | Demo survives a flaky network |
| Tue Nov 3 | Record and edit the video, README, deploy, final regression | Video and live site ready |
| Wed Nov 4 | Buffer and submission | Submitted by noon ET, nine hours before the deadline |

**Day 1 go/no-go gates.** Run the smoke test on a clip of your own pendulum. Continue only if all hold: the ball is found on at least 95% of frames with a stable id; the tracking jitter is small relative to the swing amplitude; the reference card is found in one image request; and a 6-second clip completes in about 30 seconds or less. Fallback if tracking is flaky: seed the ball with a box prompt on frame 0 so SAM tracks that specific object. If that also fails, switch to the MixedTraffic idea.

**Cut list, in order:** MuJoCo export, spring-mass experiment, voice input, PDF report (keep Markdown).

## 14. Risks and mitigations

| Risk | Impact | Mitigation |
| :-- | :-- | :-- |
| Track flicker or id switches | Bad fits | Confidence weighting, outlier rejection, box-prompt seeding, consistent contrast and lighting |
| Reference not in the motion plane | Scale error | Capture checklist; cross-check with the circle-fit length and the ruler |
| Lens distortion and tilted camera | Systematic error | Keep motion near the frame center; flag tilt in the scene check; report as an uncertainty term |
| Run-to-run variation | Unstable numbers | Three runs, report spread |
| Live demo latency or API failure | Demo fails | Pre-cached examples, recorded video as a fallback, retries |
| “Tracker already exists” | Lower Impact | Lead with zero-click tracking, automatic model comparison with explanation, and the user test |
| “It is a toy” | Lower Impact | Real users, real accuracy table, honest failure case |
| Overfitting with more parameters | Wrong conclusions | AICc and residual tests; language model cannot override them |
| Browser clips in WebM | Upload errors | Transcode in ingest |
| Preview API changes | Breakage | Pin the SDK version; keep the smoke test as a health check |
| Solo capacity | Missed deadline | Cut list above; protect days 6 to 8 for evaluation and the video |

## 15. Demo and submission plan

### 15.1 Demo video (about 110 seconds)

- **0:00 to 0:15:** phone clip of the pendulum; the ghost overlay locks on; the headline measurement appears with its error bar. Use only numbers measured on the real run.
- **0:15 to 0:45:** the ideal model fails; residuals show decay; the AICc table selects the damped model; the language model explains why.
- **0:45 to 1:15:** the credit card sets the scale; show the generated lab report.
- **1:15 to 1:40:** the accuracy table across real clips, including the failure case.
- **1:40 to 1:50:** the pipeline diagram with each Meta tool’s job, and the cost per run.

Open with the transformation itself. No title slides.

### 15.2 Live demo

Three pre-loaded clips with cached results, plus an upload box. Keep the site live through at least November 9 (finals), and confirm the exact requirement in the rules.

### 15.3 Submission checklist

- Public demo video link
- Live site URL
- Repository (with README mapped to the four rubric criteria)
- Project description that names the user and the measured results
- Track and theme selection
- Team members listed
- Submitted early, with a screenshot of the confirmation

Confirm the exact fields and any video-length limit on the submission form.

## 16. Open items to verify

1. Smoke test results (latency, track stability, reference detection) on real clips.
2. Python parser entry points, if we choose to use it instead of the regular-expression parser.
3. Muse Code headless and CI commands.
4. Official prize structure, theme selection, and submission requirements.
5. Pricing page figures and the rate limits that apply to our account.
6. Whether partner credits (Modal, Baseten, Fireworks) apply to us.
7. Hosting choice and the maximum request duration.

## 17. Sources

- Cerebral Valley event page: https://cerebralvalley.ai/e/meta-ai-developer-hackathon
- Meta Model API, segmenting with prompts: https://dev.meta.ai/docs/sam/segmenting
- Meta Model API, SAM client libraries: https://dev.meta.ai/docs/sam/client-libraries
- Meta for Developers announcement ($150 credits): https://x.com/MetaforDevs/status/2110045152601633114
- Third-party guide (prize figures, unverified): https://reconscribe.com/meta-global-ai-developer-hackathon-2026/
- Third-party pricing summary (to be confirmed): https://www.orcarouter.ai/blog/muse-api
