# KineticLab — auditable pendulum physics from a phone video

**TL;DR:** KineticLab measures a swinging pendulum from an ordinary MP4 and reports real physics numbers — with an architecture engineered so that *nothing in the result can be faked, guessed, or silently interpolated*. It is built for the Meta Global AI Developer Hackathon (Indie Developer track, theme "Push the Frontier").

## The problem it solves

"Measure gravity from a video" demos are easy to fake: an app pipes frames through an AI model, an LLM writes a plausible number, and nobody can audit where the number came from. KineticLab is the counter-example — a local-first metrology tool where every measurement is traceable to pixels you confirmed and measurements you supplied, and every unknown stays honestly `null`.

## What it does

1. **Upload** a side-view clip of a pendulum (fixed camera, e.g. a ball on a string with a paper card in frame).
2. **Detect** — the app sends the clip to Meta's SAM 3.1 segmentation model with your text prompts (e.g. "red ball", "white paper"). The model's raw per-frame output is saved *verbatim* as a one-bit fixture with source presentation timestamps — it is treated as **untrusted telemetry**, never as truth.
3. **Confirm** — you visually confirm the detected boxes. The model proposes pixels; you vouch for them.
4. **Measure** — angles are extracted from masks, fitted with a pre-registered model (M1: small-angle separable frequency-grid least squares; M2 runs as an independent diagnostic cross-check), and results are exported with artifact hashes and full provenance.

Two modes: **Full** (bob + reference card) and **Motion** (bob only — scale-free, no card needed).

## The honesty architecture (the differentiator)

- **No model supplies or changes measurement values.** Advisory text may echo exact JSON values only after audit and never feeds measurement assembly. All math is deterministic, inspectable Python.
- **Unknown = `null`.** Missing data renders as `null`, never interpolated, never guessed.
- **Millimeters are always human-typed.** The card's physical width is typed by the user from a ruler and stamped `user_supplied` in provenance. The app *never* suggests or infers physical size from pixels — a wrong guess would silently corrupt gravity, so it structurally cannot happen.
- **Gravity stays `null` without independent references** — the app reports the scale-free quantity g/L_eff (= ω²) instead of pretending to know g.
- **A locked error taxonomy** — exactly 32 error codes + 9 warning codes, zero new codes ever. If a situation fits no code, the pipeline stops rather than improvises.
- **Model output that violates the canonical format is rejected, not trimmed** — e.g. if the vision model returns two objects for one prompt in a frame, the run is rejected with a registered error and the raw evidence is preserved.
- **Four run exports are auditable**: `result.json`, `diagnostics.json`, `angles.csv`, and `summary.md`. Geometry reports, calibration records (with validity flags and warnings), and raw fixture references are supporting evidence artifacts, not part of those four exports. Hashes and provenance link the relevant artifacts; a `measure_reuse` record states what computation was cached and which bytes (by hash) it covered.
- **Provenance chain**: software version, model name, input hashes, and artifact metadata timestamps only where fields exist. Capture records artifact-save timestamps, not model-call timestamps; frame timing uses source PTS.

## Engineering shape

- **Backend/runtime: Python standard library only** — zero third-party runtime dependencies. Optional `pytest` and build tooling are separate development extras.
- **UI: one self-contained HTML file** (vanilla JS/CSS, no frameworks, no external references, no setInterval/setTimeout (one requestAnimationFrame ticker)) served by a stdlib HTTP server on `127.0.0.1:8137`.
- Test status is tracked honestly: current discovery finds 921 test methods; the latest full-suite run (2026-11-03) reported 877 tests, OK (skipped=15, platform-gated byte pins). An earlier run on the pre-swap tree reported 919 tests, OK; 2026-11-02 reported 905 tests, OK. Key hygiene remains covered (`python -m unittest` tests that the model API key is env-only, never logged or stored). Automated tests are mock-transport; real-API evidence is the recorded fixture run.
- Windows-first; live-verified end-to-end on real hardware.

## Honest status

- Works: upload → detect → confirm → measure, both modes, live-verified; results render with trajectory, residual, trail, and replay.
- Known limits: full-mode measurement is slow (~20 min of local compute for a 237-frame clip; motion mode is fast), single-user local tool, Windows-first.

## Roadmap

The pendulum is the first instrument, not the scope. The architecture — locked contracts, verbatim hash-pinned model telemetry, canonical codec, deterministic fit, loud verdicts — is experiment-agnostic. Designed next steps, stated as intent rather than claims, none built today: multi-object SAM 3.1 tracking with deterministic rigidity checks (stationary pivot, rigid rod), a DINOv2-class cross-model mask-agreement signal recorded in the diagnostics, a multimodal Experiment Inspector whose advisory notes stay in a visibly separate channel from the verdict, and further mechanical systems (spring-mass, projectile, collisions) on the same five-stage rail. Destination: a local physics experiment hub where Meta models do the seeing and every measurement/result number survives an audit, because no model supplies or changes measurement values.

---

*File owner: Fable (reviewer). Created 2026-10-29 at the user's request as a shareable project description; content is descriptive only — authoritative claims live in `Docs/Claims_Register_Public.md`.*
