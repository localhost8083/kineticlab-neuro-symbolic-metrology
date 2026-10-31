# Demo Runbook (skeleton, M-4)

Ordered local demo: every step runs offline from pinned artifacts.
Every number shown cites its `Docs/Claims_Register.md` claim ID; no
other numbers are displayed. Items marked USER ACTION need a human
(card owner / submitter) and are not agent work.

Submission context (source:
`Docs/meta_ai_developer_hackathon_details.md`): deadline Nov 4, 9:00
PM EST; package = functional demo + public repo link + short video;
one track (Indie / Startup); scoring Impact 30 / Technical Execution
25 / Meta AI Tooling 25 / Demo & Presentation 20.

## 0. Prove the tree is green (1 command)

```powershell
python -m unittest
```

Say: "790 tests pass [C-003]." Say hygiene is enforced by 5 of them
(no key material in tree, fixtures, or history [C-017]).

## 1. Structural media check — NOT a SAM replay

```powershell
python scripts/media_check.py
```

Say exactly: "Both fixtures PASS structurally [C-002]. This is a
media structure check, not a model replay — the pinned SAM
responses replay to 234/234 valid records each through
`python -m kineticlab demo` [C-016]; nothing was tuned to
make anything pass; the 117 occlusion frames [C-026] and
blur-affected masks are reported as measured."

## 2. Advisory evidence (Meta tooling)

Show `fixtures/advisory/`: two `live` Spark entries
(`muse-spark-1.3-contributor`), hash-verified, replayable
offline [C-021]. The setup review adds exactly 3
`W_ASSUMPTION_UNVERIFIED` warnings and downgrades `success` to
`success_with_warnings`, nothing else [C-022]; the narrative
resolved with source `model` because every number echoed its
input JSON exactly (`30.007170633278655 1/s^2` [C-023] — that
input predates the KL-7 assembly value and is not re-claimed
against it). Replay runs through `python -m kineticlab demo`
(SAM -> advisory -> assemble). Say the hard rules:
flags can only add warnings or downgrade (240-case matrix
[C-018]); any hallucinated number discards the whole narrative
for a deterministic template [C-019].

## 3. Geometry and calibration (2 min)

Show `fixtures/geometry/calibration_live.json`: valid `calibration.v1`,
ID-1 85.60×53.98 mm caller-confirmed, scale 0.328633 mm/px over 117
clean frames, U-3 depth-offset bound 1.67% stated as an assumption,
scale uncertainty honestly null [C-024]. Show the arc-fit pivot at
(452.62, −523.75) px, r = 907.48 px, mean residual 5.158 px [C-025],
and clean-frame corner jitter mean 1.23 px / max 2.96 px as the
camera-stability evidence (occluded frames excluded with measured
cause [C-026]). Open `fixtures/geometry/overlay_live_ball.svg` in a
browser: the centroid path follows the swing. HUMAN INSPECTION DONE
2026-10-28: card owner confirmed "path looks right".

Say: "g stays null everywhere — U-2 length was never provided, so no
gravity is claimed [C-027]."

## 4. Fit honesty (1 min)

Say: bounded M1/M2 fits recover planted parameters inside a mapped
stall boundary on synthetic data only; the matrix reports where
recovery stalls instead of hiding it (gate finding in
`Docs/Review_Log.md`). No fit output in this demo is presented as a
physical gravity measurement [C-027].

## 5. USER ACTION — record the video

Script beats (compressed to fit 3:00 MAX): (0) green tree +
media structure check, (1) pinned SAM evidence files, (2)
advisory evidence + hard rules, (3) calibration + pivot +
overlay, (4) assembly result/summary + honesty close ("g is
null, warnings carried"). Timebox: 0:00-0:30 tree, 0:30-1:15
SAM, 1:15-2:00 advisory, 2:00-2:40 geometry, 2:40-3:00 honesty
close. Every on-screen number claim-cited as above. No new
numbers. Label all model evidence "live capture, offline
replay" - never a live network call in the video.

## 6. USER ACTION — portal + push

PORTAL RULES CONFIRMED 2026-10-28 (user logged in; official form
screenshots + `Docs/meta_ai_developer_hackathon_details.md` agree):
deadline Nov 4 9:00 PM EST; required = team name, track, theme,
project description, PUBLIC GitHub repo link, 3-MINUTE-MAX demo video
(YouTube link), "Describe your use of Meta products", "Why are Meta's
models important to your solution?"; optional = Most Viral Track X-post
link, product feedback, partner-technology feedback. User decisions:
solo builder -> INDIE DEVELOPER TRACK. Theme choice PENDING (Fable
recommends "Push the Frontier" — the theme names physical systems and
scientific experimentation verbatim; "Build for Your World" is the
personal-workflow theme). Team name DECIDED 2026-10-29:
"KineticLab" (brand unity with repo/package/README). Card-privacy
CONFIRMED
2026-10-28: the reference card is an old, expired, blank-purpose
hospital card used strictly as a size-reference prop — no active
identity, patient data, or sensitive info; safe for public-repo
publication. Push still needs explicit user approval; `*.mp4` is not
gitignored — stage deliberately, never `git add -A`. Nothing is pushed
by agents.

### 6a. DRAFT form answers (KL-10.3 will finalize; every number
claim-cited; user pastes, edits freely)

- Project Description (DRAFT): "KineticLab turns an ordinary phone
  video of a swinging pendulum into auditable physics measurements.
  Meta's SAM 3.1 segments the ball and a reference card in every frame
  (234/234 valid records [C-016]); the offline pipeline converts those
  masks into calibrated geometry (scale 0.328633 mm/px [C-024]) and a
  pivot localization, with honest failure states instead of invented
  numbers. Every displayed value traces to a reviewed claim; gravity
  is never claimed without an independently measured length [C-027]."
- Use of Meta products (DRAFT): "Two LIVE model calls on the real
  clip: SAM 3.1 segmented bob + card one-bit masks for all 234 frames
  (prompts 'ball' and 'card' [C-015]); raw responses are cached,
  hash-pinned, and replay through unchanged offline code [C-016].
  Muse Spark 1.3-contributor powers an advisory layer — a setup review
  plus a plain-language narrative — that can only ADD warnings or
  downgrade a result, never upgrade it or change a number [C-018,
  C-022]; its text passes a strict number-echo audit against the
  computed JSON or is discarded for a deterministic template [C-019,
  C-023]. All model output is treated as untrusted telemetry."
- Why Meta's models are important (DRAFT): "SAM 3.1 is the measurement
  instrument: only a video-segmentation model can turn raw pixels into
  per-frame object masks, which is where every measurement in the
  pipeline begins. Spark adds the human-readable layer: it reviews the
  recording setup and narrates results in plain language. The
  division of labor is the point — Meta models perceive, KineticLab
  computes and refuses to overclaim. That split is what makes the
  results auditable."
- Impact / problem statement (DRAFT — paste into Project Description
  or wherever impact is asked): "AI can see, but it can't be trusted
  to MEASURE — it answers confidently even when wrong. KineticLab is a
  working demonstration that AI measurement can be made auditable
  end-to-end: Meta's SAM 3.1 does the seeing, deterministic math does
  the computing, and the architecture physically prevents invented
  results — uncertainty shows as 'unknown,' failures are loud, every
  number traces to evidence [C-018], [C-019], [C-027]. Use case today:
  real physics experiments from a phone video — no lab equipment, no
  sensors attached (234/234 frames segmented from one phone clip
  [C-016], calibrated scale from a reference card [C-024]). The same
  pattern scales to vibration checks, swing analysis, and structural
  monitoring. Honest scope: the seeing-half is general; the math-half
  currently speaks 'pendulum' — ramp and collision experiments are the
  roadmap, because we add physics by reviewed contract, never by
  invention."

## 7. Live capture & measure (KL-8.4; the ONLY online step)

Everything above runs offline from pins. This step spends real API
calls against `https://api.meta.ai/v1` (model `sam-3.1`) with a
bring-your-own-key: `MODEL_API_KEY` lives in the process environment
only — never in files, logs, or the page. The live panel in the UI
stays hidden until the server sees the key. No new numeric claims
below: the mm value is a human-typed example, not a measurement.

CLI (one shot; the operator has already chosen):

```powershell
$env:MODEL_API_KEY = "<paste here, never commit>"
python -m kineticlab capture --clip <path-to-clip.mp4> --mode full --card-width-mm 85.6 --out-dir live_out
python -m kineticlab capture --clip <path-to-clip.mp4> --mode motion --out-dir live_out
```

Exit 0 means the run completed (a rejection result still exits 0 —
read the status line); exit 1 is a pipeline failure naming its
registered code; exit 2 is misuse (no key, bad flags). Full mode
needs the operator to TYPE the card width — the value `85.6` above
is an example placeholder, never a default and never guessed.
Motion mode takes no width and reports scale/length/gravity null
with the reason "no reference card: no scale".

UI (`python -m kineticlab serve`, panel 03): drop or record a clip,
pick full/motion, optionally edit the noun-phrase prompts, Detect,
CONFIRM the first-frame boxes over the clip preview (re-prompt or
back out freely — nothing is measured until Confirm), type the card
mm for full mode, then Measure. Full results reuse the demo stage
(result, trajectory, exports); motion reports render in-panel with
export links. Recordings request MP4 explicitly and wait unsent
until Detect; a browser that cannot record MP4 says so instead of
uploading something else.

Say: "Detection is one live round trip per role; the wire text is
saved verbatim and the pinned offline pipeline measures it
unchanged. Confirm-before-measure means the human sees what the
model saw before any number exists."
