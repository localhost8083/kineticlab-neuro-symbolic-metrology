# Ingest measurement fixtures (KL-2.4)

Unlike `fixtures/contracts/` (synthetic, hand-authored), files here are
**pinned structural measurements** produced by the kineticlab stdlib MP4
parser from real `Smoke/` bytes. They are regression pins: identical
bytes plus an unchanged parser must reproduce them byte-identically.
They are NOT ffprobe ground truth; FFprobe re-verification stays a
recorded follow-up wherever a pin is first measured.

- `test_3_frame_table.json`: all 234 `frame.v1` records from
  `Smoke/test_3.mp4` via `extract_frame_records`, wrapped in an
  envelope (`artifact`, `source`, `source_sha256`, `measured_utc`,
  `generator`, `provenance_note`, `frames`). Canonical form is
  `json.dumps(envelope, indent=2, sort_keys=True) + "\n"` encoded as
  UTF-8 with LF newlines (write bytes: Windows text mode would emit
  CRLF and break the pin).
  Regeneration is guarded by `tests/test_media_matrix.py`
  (`StableArtifactTest`): any parser drift in PTS values, mapping,
  warnings, or record shape breaks the byte-equality pin loudly.

Pin policy: never hand-edit a measurement artifact to match new code.
If the parser changes deliberately, re-derive the artifact from the
same source bytes with the documented generator, review the diff as
the actual behavioral claim, and record the re-pin in the task
handoff.
