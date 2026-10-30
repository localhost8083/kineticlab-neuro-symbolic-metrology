# Fixture expectations for `scripts/media_check.py`

Each `*.json` file pins the known-good structure of one media file. Fields:

- `video`: path relative to the repo root (the parent of this directory).
- `provenance`: per-fixture note saying which independent source each pinned
  value comes from. Values first measured by the stdlib probe say so and must
  be re-verified with `ffprobe` when it is available.
- `expect`: pinned structure. A `null` value means "not pinned, never compare"
  (`fps` for VFR-ish clips with no nominal rate; `pix_fmt`, which needs a
  decoder). Unknown keys fail the check so typos surface loudly.

`media_check.py` with no arguments checks every fixture in this directory.

Subdirectories hold other fixture kinds, not media_check pins:
`contracts/` (synthetic schema fixtures), `ingest/` (pinned
stdlib-parser measurements from real media), `live/` (redacted live
SAM 3.1 responses + run metadata), `advisory/` (cached Spark advisory
entries), `geometry/` (pinned calibration + geometry report), and
`assembly/` (pinned end-to-end result + diagnostics + angle series) —
each with its own README.
