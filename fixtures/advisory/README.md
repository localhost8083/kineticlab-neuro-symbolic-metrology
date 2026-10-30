# Advisory cache (`kineticlab/advisory/cache.py`, M-2)

This directory is the advisory response cache. Every file here is a
cache entry: request metadata + raw response text + SHA-256 over the
response bytes + an explicit provenance label.

Labels (locked, `CACHE_LABELS`):

- `synthetic-fixture`: hand-authored M-2 test data below. Never a live
  claim, never replayed as one. Request endpoints are null (no call
  happened) and the model id is the literal `synthetic-fixture`.
- `live`: bytes captured from a real API call, written only by
  `scripts/spark_live_cache.py` after a genuine call. TWO EXIST since
  2026-10-28 (Fable-operated, user-authorized key from env):
  `setup-review_20261028T081141Z.json` and
  `narrative_20261028T081237Z.json`, both model
  `muse-spark-1.3-contributor` at `https://api.meta.ai/v1/chat/completions`.
- `replay`: bytes copied from a `live` entry for the offline replay
  set; must name the live response hash in `replayed_from_sha256`.

Files:

- `setup_review_nominal.json`: all-nominal flags (maps to zero warnings).
- `setup_review_flagged.json`: every flag fired (maps to five warnings).
- `narrative_valid.json`: echo-clean narrative; pair with
  `narrative_valid_result.json`.
- `narrative_hallucinated.json`: invented 9.81 m/s^2 (must template).
- `narrative_valid_result.json`: a `result.v1` record that validates
  through `ResultContract.from_dict` (synthetic values, valid shape).

Request inputs (not cache entries) live in `inputs/`:
`setup_review_features.json` and `narrative_input_result.json`,
derived 2026-10-28 by Fable from the live M-1 artifacts (real
observations; pivot estimated by labeled deterministic methods; the
narrative result validates through `ResultContract`). Hash convention:
an entry's `request.input_sha256` is the SHA-256 of the UTF-8,
LF-normalized input text exactly as sent in the request; the on-disk
files use CRLF, so their raw-byte hashes differ by line endings only.

Replay path (`replay_entry`): hash re-verified, then the raw response
text parsed with the kind's strict parser. Tampered bytes fail with
`E_INCOHERENT_VALUE` before anything parses. No network code exists
on this path.
