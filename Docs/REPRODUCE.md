# KineticLab reproduction guide

Judge-facing steps to reproduce the verified offline checks and one live capture.
Source of truth for the live transcript: `Docs/Review_Log.md`, entries
"2026-10-29 - KL-8.4 - VERIFIED" and "2026-10-29 - KL-8.4 - LIVE VERIFIED".

## 1. Prerequisites

- Windows PowerShell, run from the repo root.
- Python 3.11 or newer (`pyproject.toml`: `requires-python = ">=3.11"`).
- No third-party installs: the verified tree runs on the standard library only.
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

Run from the repo root. Expected outcomes are from the Review_Log ledger.

Full test suite (~17-20 minutes, blocking):

```powershell
python -m unittest
```

Expected: `838 tests, OK`, exit 0. One environment-dependent live-bind skip
is possible on some machines.

Byte pins are same-platform determinism: on a different OS C library
(glibc vs UCRT) floats drift in the last ulp, so CI runs the suite with
`KL_CROSS_PLATFORM=1` (byte-pin tests skip, everything else strict) and
`PYTHONUTF8=1` (PEP 686 text mode). Run twice on one machine and every
pin hash matches.

Structural media check (fast):

```powershell
python scripts/media_check.py
```

Expected: both pinned fixtures PASS, exit 0. This is a media structure check,
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
chain, prints the written exports under `demo_out/`.

Local web UI (blocking; leave running):

```powershell
python -m kineticlab serve
```

Expected: serves on `http://127.0.0.1:8137` (127.0.0.1 only, default port
8137). Open that address in a browser.

Live motion-mode capture (needs the key prefix from section 1):

```powershell
$env:MODEL_API_KEY = [Environment]::GetEnvironmentVariable('MODEL_API_KEY','User'); python -m kineticlab capture --clip Smoke/test_4.mp4 --mode motion
```

Expected: exit 0; `captured: bob 237/237 valid`; one run directory under
`live_out/` with `motion_report.json` and `motion_angles.csv`.

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

- Every number on screen comes from a run you started; a fresh page shows an
  idle empty state, never sample numbers.
- Unknown renders as `null`, never a guess.
- Gravity stays `null` without a reference card plus an independent pivot
  length; unestimated uncertainty carries `W_UNCERTAINTY_UNAVAILABLE`.
- Card width in mm is always human-typed (`user_supplied`), never derived
  from pixels or guessed.
- Model output is untrusted telemetry: detection boxes are confirmed by a
  human; advisory output can only add warnings or downgrade, never change a
  number; narrative text must echo the computed JSON exactly or it is
  discarded for a deterministic template.
- Failures are explicit: a locked taxonomy of 32 error codes plus 9 warning
  codes; rejection states never render as success.

## 5. What a real run produced (historical example)

Motion-mode live run `live-20261029T093519Z-3a9279f4` on `Smoke/test_4.mp4`
(1920x1080, 237 frames), from the Review_Log transcript. Historical example,
not a guarantee; your run will produce its own values.

- Frames: 237/237 valid, live SAM 3.1, prompt "red ball".
- Period: 1.1483600498 s; omega: 5.4714419126 1/s.
- g/L_eff: 29.9366766033 1/s^2 (scale-free, equals omega squared).
- Gravity: `null`; scale and pivot length `null`; reason
  "no reference card: no scale".
- Run artifacts (`live_out/`) were later deleted in a user-directed cleanup;
  the Review_Log ledger text is the remaining record of this run.
