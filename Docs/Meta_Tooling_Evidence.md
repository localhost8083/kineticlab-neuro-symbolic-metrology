# Meta Tooling Evidence — M-1 live SAM 3.1 run

Label: LIVE-RUN (real API responses, recorded 2026-10-28).

Facts only. No quality verdicts; replay data lives in the WHITEBOARD handoff.

## What ran

- Two live `responses.stream` calls, model `sam-3.1`, endpoint
  `https://api.meta.ai/v1` (responses resource), from WSL via
  `Smoke/sam_smoke_test.py --output` (M-1 option b: user-operated
  transport; no agent-held key, no agent-side network).
- Access check first: `model access check passed: sam-3.1`.
- Prompts: `ball` (call 1) and `card` (call 2), one noun phrase each.
- Mask encoding: `one_bit`. Confidence requested: true.
- Input clip: `Smoke/test_3.mp4`, SHA-256
  `a98a532410a4af2d70921d5adaf1298f151dab8f0e92348f6920cce0be5875ce`
  (matches the `fixtures/test_3.json` pin).
- Uploads `file-1108610508729425` (call 1) and `file-1703049044676928`
  (call 2), purpose `user_data`, deleted after each call by the transport.

## When (mtime-labeled)

The transport did not capture call timestamps. Times below are the saved
artifacts' filesystem mtimes, measured in UTC:

- `raw_bob_one_bit.txt`: 2026-10-28T06:45:32Z, 51348 bytes.
- `raw_card_one_bit.txt`: 2026-10-28T06:46:09Z, 54635 bytes.

Byte sizes match the transport-reported `response_chars` exactly
(51348 / 54635). The task brief stated 12:45:32Z / 12:46:09Z; that is
local machine time (UTC+6) mislabeled with Z — the UTC values above win.

## Artifact layout (`fixtures/live/`)

- `raw_bob_one_bit.txt` — call-1 raw wire text, unmodified bytes.
  SHA-256: `b216815fd6ca5e15718fed2dd8947a9972e00b1f27f71881e5d39401a4fb3ad7`
- `raw_card_one_bit.txt` — call-2 raw wire text, unmodified bytes.
  SHA-256: `d3fe9a7ecde3f48c6ef2753bd66f7d93f86783613d50bb2ebbf566deb57473d1`
- `run_metadata.json` — request metadata (endpoint, model, prompts,
  clip hash, artifact hashes/sizes, transport, mtime-labeled
  timestamps, upload ids, usage null). Sorted keys, indent 2, LF.

Wire shape (observed, both files): 234 newline-terminated records, one
per frame, `<Nf>` markers 0..233, `<|box;...|><|mask;...;data=W,H,payload|>`.
Same grammar the offline adapter already parses; replay ran unchanged.

## Redaction

The transport writes streamed model text only; the key is passed via
environment to the client and never enters the response stream. Keyscan
with the committed `test_key_hygiene` patterns over both artifacts:
0 hits. A case-insensitive probe reproduces Fable's single `Sk-`
substring (card file, line 11, after `data=` inside a mask payload):
base85 payload soup, not a delimited credential — false positive,
same disposition as Fable. Hygiene suite stays 5/5.

## Usage / cost

Not captured by the transport. Recorded as `"usage": null` in
`run_metadata.json` with the note "transport does not capture usage;
not invented". No estimate exists anywhere in this file.

## Provenance chain

User console (upload ids, response_chars 51348/54635, frames_returned
234/234, deletion lines) -> raw files (byte sizes match) -> hashes above
-> offline replay in the M-1 WHITEBOARD handoff. Every number in this
document comes from a file, command output, or the wire text itself.
