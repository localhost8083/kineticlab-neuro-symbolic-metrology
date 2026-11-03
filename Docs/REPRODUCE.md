# KineticLab reproduction guide

Steps to reproduce the verified offline checks and one live capture.
Source of truth for the live transcript: `Docs/Review_Log_Public.md`, entries (historical evidence — re-verify with the commands above)
"2026-10-29 - KL-8.4 - VERIFIED" and "2026-10-29 - KL-8.4 - LIVE VERIFIED".

## 1. Prerequisites

- Windows PowerShell, run from the repo root.
- Python 3.11 or newer (`pyproject.toml`: `requires-python = ">=3.11"`).
- No third-party runtime installs: the verified runtime uses the standard library only. Optional `pytest` and build tooling are separate development extras.
- `MODEL_API_KEY` set at user level (live capture only; offline checks need no key).
  Fetch it into the process environment at invocation:

```powershell
$env:MODEL_API_KEY = [Environment]::GetEnvironmentVariable('MODEL_API_KEY','User'); python -m kineticlab ...
```

The key is never logged, echoed, or stored by the app. It travels only in the
`Authorization` header of the live SAM request, is absent from every run
artifact, and the uploaded clip is deleted server-side after capture
(`delete_status 200` in the transcript).

## 2. Verified commands

Run from the repo root. Expected outcomes are from the Review_Log_Public ledger.

Full test suite (~17-20 minutes, blocking):

```powershell
python -m unittest
```

The latest full-suite run (2026-11-03, this tree) reported `877 tests, OK` (skipped=15, platform-gated byte pins), exit 0. An earlier run on the pre-swap tree reported `919 tests, OK`; 2026-11-02 reported `905 tests, OK`. Current discovery finds 921 test methods. On a fresh clone, tests backed by the raw SAM fixtures under `Smoke/results/` (which stay local) skip, and the suite reports fewer ran with `OK (skipped=...)` - expected, not a failure: the byte pins compare against outputs recorded on the machine that owns the media. The demo clip (`Smoke/demo_test.mp4`) ships, so media_check, the demo chains, and the UI module run everywhere. One environment-dependent live-bind skip is possible on some machines. The UI test module requires `node` on PATH.

Byte pins are same-platform determinism: on a different OS C library
(glibc vs UCRT) floats drift in the last ulp, so CI runs the suite with
`KL_CROSS_PLATFORM=1` (byte-pin tests skip, everything else strict) and
`PYTHONUTF8=1` (PEP 686 text mode). Run twice on one machine and every
pin hash matches.

Structural media check (fast):

```powershell
python scripts/media_check.py
```

Expected: the pinned fixture (Smoke/demo_test.mp4) PASSes, exit 0. This is a media structure check,
not a SAM replay.

CLI overview:

```powershell
python -m kineticlab --help
```

Expected: exit 0, usage for `config`, `demo`, `capture`, `serve`.

Non-secret configuration:

```powershell
python -m kineticlab config
```

Expected: exit 0, effective config JSON with `api_enabled: false`.

Pinned offline demo (no key, no network):

```powershell
python -m kineticlab demo
```

Expected: exit 0. Replays the pinned SAM + advisory artifacts, assembles one
chain, prints the written exports under `demo_out/`. Re-running replaces the existing demo_out/<chain> exports with byte-identical output — that replacement is itself the determinism proof, and demo_out/ is git-ignored scratch.

Local web UI (blocking; leave running):

```powershell
python -m kineticlab serve
```

Expected: serves on `http://127.0.0.1:8137` (127.0.0.1 only, default port
8137). Open that address in a browser.

Live motion-mode capture (needs the key prefix from section 1):

```powershell
$env:MODEL_API_KEY = [Environment]::GetEnvironmentVariable('MODEL_API_KEY','User'); python -m kineticlab capture --clip <your-own-side-view-clip.mp4> --mode motion
```

Expected: exit 0; `captured: bob N/N valid` for your clip's frame
count; one run directory under `live_out/` with `motion_report.json`
and `motion_angles.csv`.

Live full-mode capture (needs the key prefix; card width is typed by you):

```powershell
$env:MODEL_API_KEY = [Environment]::GetEnvironmentVariable('MODEL_API_KEY','User'); python -m kineticlab capture --clip <path-to-clip.mp4> --mode full --card-width-mm <measured-mm>
```

Substitute your clip path and your physically measured card width. There is no
default and no guessing; motion mode with `--card-width-mm` is rejected.

## 3. UI walk-through

1. Start the UI (`python -m kineticlab serve`) and open
   `http://127.0.0.1:8137`.
2. Drag an MP4 onto the live panel (side-view pendulum, fixed camera), or
   record in-browser (MP4 requested).
3. Choose Full (bob + card, needs your typed card width in mm) or Motion only
   (bob, scale-free).
4. Press Detect. Expect ~1-2 minutes of SAM detection plus ~5 minutes of local
   encoding with no progress bar; the run is working, not hung.
5. Confirm the first-frame boxes over the clip preview. Nothing is measured
   until you confirm; re-prompt or back out freely.
6. Press Measure. Full mode takes ~20 minutes; motion mode is fast.
7. Results render in the results column: verdict, evidence values, theta
   trajectory chart with fitted overlay, residual strip, centroid trail with
   start/end markers, scrubber/replay, provenance, and export links.

## 4. Honesty contract

- Every measurement/result number on screen comes from a run you started; a fresh
  page shows an idle empty state, never sample measurement values.
- Unknown renders as `null`, never a guess.
- Gravity stays `null` without a reference card plus an independent pivot
  length; unestimated uncertainty carries `W_UNCERTAINTY_UNAVAILABLE`.
  Type the optional pivot length you measured and the run reports `g`
  with its `user_supplied` provenance — no accuracy claim is made.
- Card width in mm is always human-typed (`user_supplied`), never derived
  from pixels or guessed.
- Model output is untrusted telemetry: detection boxes are confirmed by a
  human; advisory output can only add warnings or downgrade, never change a
  number; narrative text must echo the computed JSON exactly or it is
  discarded for a deterministic template.
- Failures are explicit: a locked taxonomy of 32 error codes plus 9 warning
  codes; rejection states never render as success.

## 5. What a real run produced (historical example)

Motion-mode live run `live-20261029T093519Z-3a9279f4` on a private
1920x1080 side-view clip (237 frames), from the Review_Log_Public
transcript. Historical example, not a guarantee; your run will produce
its own values.

- Frames: 237/237 valid, live SAM 3.1, prompt "red ball".
- Period: 1.1483600498 s; omega: 5.4714419126 1/s.
- g/L_eff: 29.9366766033 1/s^2 (scale-free, equals omega squared).
- Gravity: `null`; scale and pivot length `null`; reason
  "no reference card: no scale".
- Run artifacts (`live_out/`) were later deleted in a user-directed cleanup;
  the Review_Log_Public ledger text is the remaining record of this run.
