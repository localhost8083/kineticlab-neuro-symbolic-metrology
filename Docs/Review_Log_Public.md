# Review Log (public redaction)

Public, tracked historical copy of gate decisions through KL-10.14.
Each entry keeps its date, gate, verdict, accepted evidence, and
blocking findings. Current verification belongs in
`Docs/Claims_Register_Public.md` and CI, not this historical log.
Stripped from the private ledger: machine-local paths and timings,
per-run process notes, agent working chatter, and anything
credentials-adjacent. The private ledger (`Docs/Review_Log.md`)
stays gitignored and append-only.

## 2026-10-27 — KL-0-G0 — PASS_WITH_FIXES

- Stage: P-001 foundation. Suite 6 OK; media check both PASS; CLI
  exits 0; no whitespace errors; no network/API use; no secret in
  bounded scan.
- Required fixes: destale task baseline and README product claims;
  add the claims register before public claims; keep
  pytest/FFmpeg/lockfile follow-ups recorded; define schema
  versioning, coordinates, timestamps, units, nullability, and
  error taxonomy before science.
- Accepted limitations: pytest unavailable offline (stdlib
  `unittest` valid); bash/FFmpeg harness unexecutable in sandbox;
  lockfile unresolved offline; FFprobe re-verification pending.

## 2026-10-27 — KL-1-G1 — BLOCK

- Stage: P-002 versioned contracts. 64 tests OK, but seven
  blocking semantic gaps: arbitrary unit labels; fit summaries
  contradicting parameters; results detached from supporting
  fits; impossible metric orderings; `valid` observations without
  PTS; contradictory calibration dimension/source pairs; rejected
  negative finite PTS.

## 2026-10-27 — KL-1-G1 re-review — PASS_WITH_FIXES

- Seven prior findings repaired and verified (99 tests OK).
- One follow-up required before gate completion: bind result
  semantics (quantity/unit/measurement identity and fit support).

## 2026-10-27 — KL-1-G1 audit addendum — BLOCK

- Independent re-audit found five more gaps: summary without
  underlying parameter; zero-observation success; orphan
  `interval_method`; free-form quantity/measurement names;
  underconstrained M1/M2 parameter sets.

## 2026-10-27 — KL-1-G1 re-review (addendum repair) — PASS

- 112 tests OK (5 addendum tests; exact code multisets).
  Measurement identities locked (`pendulum_g_over_l`,
  `pendulum_gravity`); model parameter sets locked (M1/M2);
  gravity results require independent length plus matching
  `gravity_m_s2` at both fit and result level. `KL-2.1`
  unblocked.

## 2026-10-27 — KL-2-G2 — PASS

- Stage: P-003 ingest and exact timing. 165 tests OK; validated
  `media.v1` from real bytes; per-frame PTS from sample tables
  (finite negatives preserved, no FPS synthesis); byte-identical
  regeneration pin over all 234 test_3 frame records.

## 2026-10-28 — KL-3-G3 — PASS

- Stage: P-004 observation core. 234 tests OK; 234/234 lines per
  real file; one_bit codec vs primary-source spec (959/959 corpus
  decode + canonical round-trip; production decoder cross-verified
  472/472 vs independent transcription); canonical lossless JSON
  exports with exact inverse parser.

## 2026-10-28 — KL-4-G4 — PASS

- Stage: P-004 quality judgment. 256 tests OK; five named
  thresholds with written rationales, fixed before constants
  (headroom verified: max jump/diagonal 0.4573, max area step
  ratio 1.3882); trajectory/overlay pins match independent runs
  exactly.

## 2026-10-28 — KL-5-G5 — PASS

- Stage: P-005 offline physics estimator. 358 tests OK;
  deterministic generator; bounded M1/M2 fits; 33-cell
  characterization matrix with tamper-audited verdicts; six
  banned statistical phrases byte-absent.
- Recorded finding: seeded recovery within tolerance is
  config-dependent (stall map is part of the estimator's
  contract); detectable via converged + out-of-tolerance, never
  silent.

## 2026-10-28 — KL-6-G6 — PASS

- Stage: P-006 geometry + calibration + M-3 diagnostics. 447
  tests OK. Gate criterion checked: dimensions caller-confirmed;
  plane assumptions explicit; g null everywhere (byte-verified);
  taxonomy 9+32 held; U-3 bound + M-3e limitation stated in
  record, report, and docstrings. P-006 and M-3 closed.

## 2026-10-28 — OG AUDIT — ACCEPTED

- Read-only zero-context audit, reviewer-gated. 11 findings
  accepted with dispositions (claims destaling, front-door doc
  truthfulness, submission-readiness verdict: not ready on
  visibility/packaging, not science).

## 2026-10-28 — M-4 — VERIFIED

- Visibility: README overhaul, Meta models table, runbook
  skeleton, destale sweep. 447 tests OK. Meta track M-0..M-4
  complete.

## 2026-10-28 — SCOPE AMENDMENT — KL-8 Web UI RESTORED

- Owner-ordered: KL-8.1–8.3 + KL-8-G8 back in scope after
  KL-7-G7, with hard honesty constraints (no faked progress,
  rejection never success-styled, UI adds no physics).

## 2026-10-28 — KL-7.1 — VERIFIED

- Historical KL-7.1 end-to-end offline result assembly. 472 tests OK x2.
  Independent clean-room `assemble()` recompute 15/15 PASS,
  g/L_eff 30.00563573707589 exact. Historical pin honesty chain:
  `success_with_warnings`, gravity null, interval null + method
  `none`; fit warning `W_UNCERTAINTY_UNAVAILABLE` (calibration also
  carries `W_ASSUMPTION_UNVERIFIED`). Superseded for current demo interval
  behavior by KL-10.11 seeded bootstrap.

## 2026-10-28 — KL-7.2 — VERIFIED

- Critical-failure result-state enforcement. 484 tests OK x2.
  Routing map proven exact programmatically (32/32 errors,
  9/9 warnings); independent probes confirm success-path
  invariance and honest rejection records.

## 2026-10-28 — KL-7.3 — VERIFIED

- Markdown summary + export hashes. 494 tests OK. Copy-only
  renderer verified by read (zero authored digits); rejection
  verdicts unmistakable; one environment-sensitive test fixed
  during verification (product invariant held in both
  environments).

## 2026-10-28 — KL-7.4 — VERIFIED

- Five states + human auditability. 500 tests OK x2. Pinned
  frame-0 audit walkthrough independently re-verified (16/16
  citations exact); `success` documented as structurally
  unreachable while warnings exist.

## 2026-10-28 — OG AUDIT P7 — ACCEPTED

- 8/8 findings verified TRUE against code; UI phase gated
  behind KL-7.5. Six release-blocking correctness items
  (contract success+warnings, observation validity, unwrap
  ordering, usable counts/card gate, M2 overflow, provenance
  identity) plus runbook truth and a truthful demo front door.

## 2026-10-29 — KL-7.5 — VERIFIED + KL-7-G7 RE-VERIFIED: PASSED

- 535 tests OK x2. All six release-blocking findings closed and
  code-confirmed; pins regenerated with parsed diff limited to
  the added digest block (g/L unchanged). Taxonomy still 32+9.

## 2026-10-29 — KL-8.1 — VERIFIED

- Demo CLI front door + localhost web UI. 574 tests OK.
  127.0.0.1-only bind; cheapest-first upload validation;
  allowlisted exports; digest-named uploads; real ingest entry
  points for the upload verdict; page uses text sinks only with
  verdicts keyed off `result.status`.

## 2026-10-29 — KL-8.2 — VERIFIED

- UI redesign (page-only). 580 tests OK. No model evaluation in
  JS (no trig/timers/markup sinks); observed-only charts;
  page CSV parser executed against real pins (234 points,
  frame-0 theta exact); keyboard + ARIA structure confirmed.

## 2026-10-29 — KL-8.3 — VERIFIED

- Presentation pass. 597 tests OK. Fitted curve
  derived as observed-minus-residual (period verbatim from
  pins); additive advisory payload (one-line server delta);
  zero timers/markup sinks; design-review items confirmed.

## 2026-10-29 — KL-8.4 — VERIFIED (mocked scope)

- Live capture & measure: injectable transport, key env-only
  (never persisted), upload-then-DELETE hygiene, registered
  codes only, verbatim raw saves; chain reuses `assemble()`
  unchanged (pin g/L reproduced exactly via mock wire); card mm
  `user_supplied`, never guessed. 682 tests OK. Open risk
  recorded: the upload part key was inferred from precedent and
  needed one real-wire confirmation.

## 2026-10-29 — KL-8.5 — VERIFIED

- UI readability pass (page-only). 682 tests OK. Warning glosses
  locked to the 9-code taxonomy; uncertainty words gated on
  payload truth; honesty greps zero.

## 2026-10-29 — KL-8.4 — LIVE VERIFIED (real wire: motion mode)

- Operator ran `python -m kineticlab capture --clip
  <own-side-view-clip> --mode motion` with a user-supplied key
  (process env at invocation, never echoed/stored) on a
  1920x1080 237-frame clip. The inferred upload part key was
  confirmed correct on the real API.
- Transcript (values): `captured: bob 237/237 valid`;
  `live motion run live-20261029T093519Z-3a9279f4: complete —
  g/L_eff = 29.936676603339443 1/s^2 (2 files .../)`; exit 0;
  `motion_report.json` + `motion_angles.csv` written.
- Evidence: 237/237 frames segmented valid (prompt "red ball");
  period_s 1.1483600497832216, omega_per_s 5.471441912635045,
  g_over_l_per_s2 29.936676603339443 (= omega² exactly,
  scale-free); M1 converged, 0 bound hits, rmse 0.034119 rad.
- Honesty on real data: `gravity_m_s2` null,
  `scale_mm_per_px` null, `pivot_length_mm` null + source
  not_provided, reason "no reference card: no scale",
  W_UNCERTAINTY_UNAVAILABLE present. Upload deleted
  server-side after capture (`delete_status 200`); usage
  null (transport does not capture it; not invented); key
  absent from every artifact.
- Provenance: clip SHA-256 recorded in run metadata; model
  sam-3.1; raw one-bit records saved verbatim.
- Note: run artifacts later deleted in a user-directed
  cleanup; this entry is the remaining record.
- Recorded finding (deferred, not silent): a stale
  "synthetic fixture data" wording in an embedded fit note is
  factually wrong on live runs; fixing it needs pinned-byte
  regeneration and was deferred, not hidden.

## 2026-10-29 — KL-8.6 — VERIFIED

- UI structure pass (page-only): auto-start removed for an
  honest idle state; live motion promoted to the results
  column reusing the same painters; invariants re-checked.
  682 tests OK.

## 2026-10-29 — KL-8-G8 — USER REVIEW: NOT PASSED

- Live adversarial use held honesty (a frame-count-as-mm typo
  quarantined calibration while the mm-independent headline
  stayed intact; a multi-segment model response rejected
  outright) but failed usability: raw error strings, chaotic
  long layout, zero feedback on long stages, one silent
  post-capture death with open root cause. Follow-up KL-8.7
  opened.

## 2026-10-29 — KL-8.7 — VERIFIED

- Friendly error layer (41/41 taxonomy coverage), layout
  compression, honest duration copy, mask-codec perf with
  byte-identical output, detect-parse reuse with hash gates,
  console-independence guard. 699 tests OK. Root-cause
  conclusion honestly recorded as best-fit-open with a
  forensic protocol for recurrence.

## 2026-10-30 — KL-8-G8 visual passes — NOT PASSED, then PASS

- Pass #1 found a chart regression (CSV column fallback) and
  responsive defects; both fixed and node-proven.
- Pass #2: first full live end-to-end run on the redesigned
  page (own clip, 237 frames, Full mode, 85.0 mm
  human-typed) verified truthful against artifacts: gravity
  null, calibration invalid with registered warnings, L_eff
  "Not available", fit internally consistent, charts animated
  from served CSV.
- Final glance on the KL-8.12 tree returned PASS. Honesty
  architecture held through the redesign (taxonomy
  untouched, no fabricated values, rejection never green).

## 2026-10-30 — OG Audit #2 — triage

- Every finding verified against code before ledgering: five
  page/shape bugs confirmed (incl. a rejection-render
  TypeError and dict-vs-array payload drift), two doc
  dispositions, three server/ingest hardening items. Lesson
  recorded: string-pin tests cannot catch JS runtime type
  errors; executing-DOM tests required.

## 2026-10-30 — KL-9.4 — first content commit PUSHED

- User-approved push of the full tree (153 files). Pre-push:
  secret scan over all candidates (0 value hits), stale-sha
  sweep, claims freeze complete, 780-test battery green.
  Excluded per gitignore: user media, run scratch, evidence
  tees, templates.

## 2026-10-31 — Gate KL-10.6 — PASSED

- External blind-audit repairs: fresh-clone breakage fixed
  (two hash-pinned demo clips tracked with owner approval;
  CRLF fixture-inflation bug fixed beyond the audit);
  README gravity promise replaced with honest wording;
  upload DELETE in `finally`; mask dims capped pre-allocation;
  doc counts unified; UI length vocabulary fixed with node
  proof. 793 tests OK. Auditor's 9-failure set green on a
  fresh archive.

## 2026-10-31 — Gate KL-10.7 — PASSED

- Hostile second pass: all 9 KL-10.6 repair claims PASS;
  structured-residual finding confirmed by independent
  compute and disclosed in assumptions (zero new codes).
  793 tests OK.

## 2026-10-31 — Gates KL-10.10 + KL-10.9-A — PASSED

- CI portability: byte pins scoped to same-platform
  determinism; UTF-8 text mode fixed. Measured-arm replay
  verified page-only (node proofs, zero trig/timers/
  markup sinks). 804 tests OK.

## 2026-10-31 — Gate KL-10.10 close — CI GREEN

- Quickstart proven verbatim on fresh checkouts of both
  OSes with zero installs; badge publicly passing.

## 2026-10-31 — Gate KL-10.11 — PASSED

- Seeded block bootstrap over measured frames; demo
  interval bit-exact cross-checked; resampling-under-M1
  honesty kept (noise, not bias); rejection paths
  byte-identical nulls. 820 tests OK.

## 2026-10-31 — Gate KL-10.9-B close — PASSED

- Simulation playground shipped: seeded RK4, measured
  trail underlay, sentinel-scoped trig, isolation
  node-proven byte-identical, honest labels,
  reduced-motion park. 829 tests OK. Queue empty.

## 2026-10-31 — Gate KL-10.12 — PASSED

- Simulation tab visual restyle (template grammar);
  physics/strings/isolation frozen. 832 tests OK.

## 2026-10-31 — Gate KL-10.13 — PASSED

- UI polish pass, zero physics: spacing tokens, honest
  indeterminate progress, inline validation, four-kind
  toast system (rAF-only, rejections never green).
  838 tests OK.

## 2026-10-31 — Gate KL-10.14 — VERIFY (historical snapshot)

- Layout restructure to the 3-column instrument
  dashboard (structure moves; components, physics,
  honesty frozen). 844 tests OK at the time of this entry.
  Verdict was pending reviewer sign-off when this historical
  snapshot was recorded; current verification is tracked in
  `Docs/Claims_Register_Public.md` and CI.

## 2026-11-03 - KL-10.24 - fixture corpus swap onto demo_test

- Corpus swap: every tracked pin, test, and public doc moved from
  the retired `Smoke/test_3.mp4` clip to the shipped
  `Smoke/demo_test.mp4` (sha256 db5da89e...d9945, h264 1024x576,
  591 frames, 19.73 s). Evidence source: verified live run
  `live-20261103T044359Z-365dd3b5` (two SAM 3.1 calls, prompts
  ball/card; bob 591/591, card 392/392 records, frames 199..590).
- New pins: `fixtures/live/` raws + run_metadata (bob
  23e4035e...15e8f, card ec6a62f7...a8d7df), ingest frame table,
  `fixtures/demo_test.json` media pin, geometry trio
  (calibration b83ddf2d...2ce70, report pin 05ea0472...47816,
  overlay 8667cd51...a1345), assembly quartet (result
  837a9b8a...abcb3, diagnostics 0666b5fb...2069, angles.csv
  877b2b72...264e9, summary e54c5cc6...32ba6e) + rejection quartet
  + corrupt pin 31b6d28b...f374.
- Honest-calibration change landed with the swap: full mode now
  needs BOTH card dimensions human-typed (85.0x54.0 typed for the
  new card); the calibration record stays invalid with
  reference_type "unknown" (a cut card is no standard) and two
  W_ASSUMPTION_UNVERIFIED warnings; no new E_*/W_* codes, no
  contracts.py schema edits. The fresh-clip U-3 statement replaces
  the retired-clip bound wording; assembly result is plain
  `success` with the seeded block-bootstrap interval
  (g/L_eff 28.93746036102984 1/s^2, omega band
  [5.375782102745884, 5.38357668969718], seed 20261103, n_boot 800,
  block 36).
- Docs updated with stable claim IDs (C-002/005/006/009/015/016/
  024/025/026/028/029); historical entries above kept verbatim.
  Advisory fixtures untouched (C-020..C-023 keep their recorded
  evidence). `Docs/img/` screenshots still show the retired run;
  regenerating them stays user action.
- Full stdlib battery green on the swapped tree (module battery:
  contracts 114, geometry 33, assembly 77, live_chain 40, ui 193,
  guards battery 65 OK / 15 expected skips).
