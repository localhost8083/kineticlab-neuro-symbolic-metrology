# Meta AI usage in KineticLab

Factual inventory of where Meta models participate, what they are allowed to
touch, and where the verifiable evidence lives. No quality verdicts — the
measured numbers are in the pipeline's own exports.

## Models and roles

| Model | Role | Boundary |
|---|---|---|
| **Meta SAM 3.1** (`sam-3.1`) | Perception core: text-prompted segmentation of the pendulum bob and the reference card, per frame, mask encoding `one_bit` | Masks are stored **verbatim** (byte-pinned), decoded by a canonical codec, and treated as **untrusted telemetry**. Every downstream number is computed by deterministic stdlib-Python from decoded masks and source PTS timestamps. |
| **Spark** (advisory layer) | Offline-cached setup-review and narrative advisories | The narrative layer passes a **number-echo audit**: any narrative number not exactly justified by the run's own JSON is discarded and replaced. Advisories surface only as registered `W_ASSUMPTION_UNVERIFIED` warnings. |

Spark is an optional cached sidecar: it never participates in measurement assembly. Narrative advisories are replayed from hash-checked offline cache and audited so any number not justified by the run's JSON is discarded.

The measurement itself is deterministic. Meta AI does the seeing and the
explaining; no language model ever authors a number.

## Live run vs offline replay — labeled evidence

**LIVE-RUN** (real API responses, recorded 2026-10-28, user-operated
transport, no agent-held key): [`fixtures/live/`](live)

- `run_metadata.json` pins everything: model `sam-3.1`, endpoint
  `https://api.meta.ai/v1`, prompts `ball` and `card`, mask encoding
  `one_bit`, confidence requested, and SHA-256 hashes of both raw response
  artifacts plus the input clip (matching the `fixtures/test_3.json` pin).
- `raw_bob_one_bit.txt` / `raw_card_one_bit.txt` — the verbatim response
  payloads (50–53 KB each), redacted of any request scaffolding.
- Uploaded working files were **deleted after each call** by the transport
  (`uploads_deleted_after: true`). No key material is present in any
  artifact; the API key lives in the environment only and is never logged
  or stored.
- Usage/cost telemetry was not captured by the transport — recorded as
  `null` with an explanatory note, **not invented**.

**OFFLINE REPLAY** (deterministic, no network): the demo chains
(`python -m kineticlab demo --chain success|rejection`) and the whole test
suite replay recorded mask payloads through the identical pipeline. The
live SAM responses above replay through the unchanged offline pipeline to
234/234 valid observations — the live and offline paths share one codec,
one contract layer, one taxonomy.

## What this buys you

- **Reproducibility:** every artifact hash in `fixtures/live/` can be
  re-verified; every demo export is byte-stable across runs.
- **Honesty under audit:** vision output is never trusted directly; the
  pipeline fails loudly (registered codes, `null` results) when evidence
  is missing rather than guessing.
- **No network at runtime:** measurement, UI, and exports run fully
  offline; live capture is opt-in via an environment key.
