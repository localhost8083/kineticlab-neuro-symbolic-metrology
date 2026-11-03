# KineticLab Claims Register (public redaction)

Public, tracked copy of the audit claims. Claim labels:
`verified_fact`, `measured`, `assumption`, `planned`, `target`,
`external_fact`.

No public claim enters README, UI, demo script, or submission text
without an evidence path and reviewer sign-off.

Redaction note: this file carries claim IDs, claim text, labels,
evidence references, and gate verdicts. Stripped from the private
ledgers: per-run process notes, machine-local paths and timings,
agent working chatter, and anything credentials-adjacent. The
private ledgers (`Docs/Claims_Register.md`, `Docs/Review_Log.md`)
stay gitignored and append-only; their owner re-points them, not
this file. New rows below the freeze line are marked explicitly.

| ID | Claim | Label | Evidence | Status |
|---|---|---|---|---|
| C-001 | Repository has P-001 package/config/smoke/test/CLI foundation. | `verified_fact` | `kineticlab/`, `scripts/media_check.py`, `python -m kineticlab --help` output; `README.md` quickstart | reviewed |
| C-002 | `python scripts/media_check.py` passes the pinned `demo_test` structural fixture. | `verified_fact` | command output; `fixtures/demo_test.json` | reviewed |
| C-003 | Latest full-suite run of `python -m unittest` (2026-11-03, this tree, post corpus-swap) reported 877 tests, OK (skipped=15, platform-gated byte pins), exit 0; discovery finds 921 test methods. Earlier runs recorded 919 tests, OK (2026-11-03, pre-swap tree) and 905 tests, OK (2026-11-02). | `verified_fact` | command output 2026-11-03 (full battery on the shipped tree); 2026-11-02 run recorded in review ledger; current discovery from `tests/`; `README.md`, `Docs/REPRODUCE.md` | reviewed |
| C-004 | `python -m kineticlab --help` exits 0. | `verified_fact` | command output; `kineticlab/cli/` | reviewed |
| C-005 | `demo_test.mp4` is 1024×576 with 591 frames and non-uniform MP4 `stts` timing (no nominal fps pinned). | `measured` | `fixtures/demo_test.json`; `scripts/media_check.py` output | structural only; not source PTS proof |
| C-006 | SAM response fixtures contain continuous bob/card frame records for `demo_test` (bob 591/591; card 392/392, frames 199..590). | `verified_fact` | `fixtures/demo_test.json` (structural); the tracked `fixtures/live/` raws decode in-suite via `tests/` | KL-3.2 decode DONE: 591/591 bob and 392/392 card records valid with mask-derived centroid/area |
| C-014 | SAM `one_bit` mask codec is fully specified by primary sources and decodes the real corpus. | `verified_fact` | `dev.meta.ai/docs/sam/` grammar; `github.com/meta-models/meta-sam` `protocol/sam3.md` + `python/src/meta_sam_parser/_mask_codec.py` (SAM License); independent transcription decoded 959/959 payloads with canonical round-trip | reviewed 2026-10-27; production decoder cross-verified 472/472 vs independent transcription |
| C-007 | KineticLab currently measures gravity accurately. | — | none | prohibited claim |
| C-008 | AI-generated footage proves physical or gravity accuracy. | — | none | prohibited claim |
| C-009 | Uncertainty on the reported quantity EXISTS as a seeded block-bootstrap resampling interval (method `block_bootstrap`, percentile [2.5,97.5], seed + n_boot + block recorded; captures measurement noise under M1, NOT the structured-residual model-adequacy bias — disclosed in assumptions). `W_UNCERTAINTY_UNAVAILABLE` fires only when the bootstrap genuinely cannot run; rejection and insufficient-frame paths stay `null` by design. | `verified_fact` | `kineticlab/fit/uncertainty.py`; `kineticlab/contracts.py` INTERVAL_METHODS + `block_bootstrap`; `kineticlab/assembly/build.py` wiring + honesty sentences; demo replay interval omega [5.375782102745884, 5.379355013477902, 5.38357668969718] 1/s | reviewed 2026-10-31 |
| C-010 | Planned v1 supports one fixed-camera planar pendulum plus confirmed reference card. | `planned` | project plan | scope lock |
| C-011 | Gravity requires independent length or independently validated metric scale; otherwise report identifiable `g/L_eff`. | `assumption` / design rule | project plan; locked app plan | implemented 2026-11-01 (KL-10.15/10.17; see C-031/C-032) |
| C-012 | P-001 used no network or API calls. | `verified_fact` | handoff record; command log | reviewed |
| C-013 | `pytest`, FFmpeg/bash harness, and lockfile resolution are verified locally. | — | unavailable in sandbox | do not claim |
| C-015 | Two live SAM 3.1 calls on `Smoke/demo_test.mp4` (prompts `ball`, `card`) were recorded 2026-11-03 via a user-run transport (run `live-20261103T044359Z-365dd3b5`); redacted raw artifacts + `run_metadata.json` are in `fixtures/live/` and are the live-run record. | `verified_fact` | console facts + SHA-256 hashes (clip `db5da89e…1d9945`, bob `23e4035e…315e8f`, card `ec6a62f7…a8d7df`); usage/cost null (transport does not capture it) | reviewed |
| C-016 | Both live SAM responses replay through the unchanged offline pipeline to 591/591 valid bob and 392/392 valid card `observation.v1` records, frames 0..590, zero missing PTS. | `verified_fact` | independent replay 2026-11-03 (records, validity, PTS joins recomputed); `fixtures/live/` | reviewed |
| C-017 | The live SAM artifacts contain no key material: committed hygiene patterns give 0 hits; the single case-insensitive `Sk-` substring is base85 mask-payload data, not a credential. | `verified_fact` | `tests/test_key_hygiene.py` 5/5 on tree incl. `fixtures/live/` | reviewed |
| C-018 | The M-2 advisory layer is built and tested offline: the five setup-review flags surface only as `W_ASSUMPTION_UNVERIFIED`, and advisory application is never-less-conservative (240-case matrix: 48 flag combinations x 5 result states; warnings only grow, states never upgrade). | `verified_fact` | `tests/test_advisory.py`; mapping in `kineticlab/advisory/setup_review.py` | reviewed |
| C-019 | The narrative number-echo audit discards any narrative containing a number that fails exact-value + vocabulary-word-also-in-JSON justification, substituting a byte-stable template; hostile-tested against hallucinated, rounded, unit-swapped, non-vocabulary, and injected numbers. | `verified_fact` | `kineticlab/advisory/narrative.py` (`audit_narrative`, `resolve_narrative`); hostile tests in `tests/test_advisory.py` | reviewed |
| C-020 | At M-2 closure no live Spark cache entries existed; every `fixtures/advisory/` entry was labeled `synthetic-fixture` with null endpoint and model id `synthetic-fixture`. (Historical statement, true at closure; two `live` entries were created later the same day — see C-021.) | `verified_fact` | `fixtures/advisory/README.md` label rules; `CACHE_LABELS` enforcement in `kineticlab/advisory/cache.py` | reviewed |
| C-021 | Both live Spark cache entries (`setup-review_20261028T081141Z.json`, `narrative_20261028T081237Z.json`) replay fully offline with hash re-verification through unchanged code (`load_entry` + `replay_entry`). | `verified_fact` | independent replays 2026-10-28; `kineticlab/advisory/cache.py` | reviewed |
| C-022 | The live setup-review advisory applied to the real computed result adds exactly 3 `W_ASSUMPTION_UNVERIFIED` warnings (card visibility, fixed camera, nominal scene) and downgrades `success` to `success_with_warnings`, changing nothing else. | `verified_fact` | independent `apply_setup_advisory` runs 2026-10-28 on `fixtures/advisory/inputs/narrative_input_result.json` | reviewed |
| C-023 | The live narrative advisory passes the number-echo audit against the real computed result — the audit fails closed on any digit token, spelled-out number word, or non-ASCII digit not justified by the result JSON (the narrative text itself stays display-only telemetry, never parsed as data) (source `model`, exact `30.007170633278655 1/s^2` echo); the narrative text is display-only telemetry, never parsed for numbers. | `verified_fact` | independent `resolve_narrative` runs 2026-10-28; audit gate in `kineticlab/advisory/narrative.py` | reviewed |
| C-024 | The live card geometry yields a `calibration.v1` record that stays honestly INVALID (`valid: false`): a cut card is no standard, so `reference_type: "unknown"` with BOTH dimensions human-typed (85.0×54.0 mm, `user_confirmed`), scale 0.406330 mm/px (width-based over median oriented geometry 209.189×128.346 px from 272 clean frames); two `W_ASSUMPTION_UNVERIFIED` warnings state same-plane and fixed-camera as unassessed, and scale uncertainty is honestly null. The record is carried but certifies neither coplanarity nor physical accuracy. | `measured` | `fixtures/geometry/calibration_live.json` (`b83ddf2d…2ce70`) | reviewed |
| C-025 | Arc-fit pivot at (467.309, −430.616) px, r = 800.966 px, mean radial residual 4.696 px (max 14.161 @frame 505, span 1.102 rad) from 591 live bob centroids by deterministic Kasa closed form. | `measured` | `fixtures/geometry/geometry_report_live.json` (`05ea0472…47816`; tracked pin swaps the run's U-3 wording for the fresh-clip statement, disclosed) | reviewed |
| C-026 | Clean-frame corner jitter mean 0.800 px / max 5.535 px (250 consecutive pairs within the 272 clean card frames) is the camera-stability evidence; the 120 card-occluded frames (23 bands; 97 consecutive pairs within that set) are excluded with measured cause (max 36.167 px @552→553, mean 13.848 px); both splits reported, neither hidden. | `measured` | jitter splits in `fixtures/geometry/geometry_report_live.json` | reviewed |
| C-027 | g stays null in length-less P-006/assembly outputs (U-2 pivot length null); no gravity is claimed there; metric use of scale/arc length is allowed only with the U-3 bound and the M-3e hollow-ball/string-mass limitation stated alongside. | `verified_fact` | byte scan of both geometry pins (no `m/s^2`, no gravity field); contract gravity-needs-independent-length rule | reviewed |
| C-028 | Current assembly pin: the real demo_test chain assembled offline to a validated `result.v1`, status `success`, g/L_eff = 28.93746036102984 1/s^2 (M1, 591/591 fit points), `gravity_m_s2` null, seeded block-bootstrap interval [28.899033216202955, 28.982897973850847] (omega [5.375782102745884, 5.38357668969718], seed 20261103, n_boot 800, block 36 — KL-10.11); M-3e limitation + arc-radius caveat carried in model_limitations; descriptive pivot radius 325.457 mm flagged `independent_length: false`. Pin SHA-256s: result `837a9b8a…abcb3`, diagnostics `0666b5fb…2069`, angles.csv `877b2b72…264e9`, summary.md `e54c5cc6…32ba6e`. | `measured` | `fixtures/assembly/result.json`, `diagnostics.json`, `angles.csv`, `summary.md`; `tests/test_demo.py::DemoChainTests::test_success_chain_matches_pin` | reviewed |
| C-029 | M2 runs as diagnostic cross-check with the pre-registered include rule: converged + gamma strictly inside [0.0, 1.0]/s; live outcome gamma 0.014296385985767188 included-interior, omega 5.37889084133999 rad/s cross-checks M1 omega 5.379355013477902 (delta ~0.01%); M1 stays the reported model in every outcome. | `measured` | `fixtures/assembly/diagnostics.json` `m2` section | reviewed |
| C-030 | The angle CSV carries SOURCE PTS (`pts_seconds`), never re-zeroed or synthesized (irregular VFR spacing preserved); a regeneration test caught the exporter writing an empty time column pre-handoff and the suite now asserts every PTS cell is non-empty and strictly increasing. | `verified_fact` | `tests/test_assembly.py::test_series_pts_are_real_and_increasing` | reviewed |
| C-031 | When the run carries a human-typed pivot length (10–2000 mm, `user_supplied`), assembly reports `gravity_m_s2 = g/L_eff × L/1000` through the existing fit.v1 fields with `pivot_length_source = independent_measurement`, plus a gravity band linearly rescaling the g/L_eff bootstrap band; the summary and assumptions label the provenance. No gravity-accuracy claim is made (C-007 still prohibited): the number is only as good as the user's ruler. | `measured` | `kineticlab/assembly/build.py::apply_pivot_length`; `kineticlab/contracts.py` gravity identity; `tests/test_assembly.py::PivotLengthGravityTests` covers identity, provenance, interval mapping, and fail-closed invalid lengths | reviewed in existing tests; pre-submit user signoff remains required |
| C-032 | Length-less runs produce byte-identical result records to before the gravity seam: same status, values, warnings, assumptions, and summary bytes. | `verified_fact` | `tests/test_assembly.py::PivotLengthGravityTests::test_explicit_none_matches_default` and related byte-identity assertions | reviewed in existing tests; pre-submit user signoff remains required |

## Update rule

Every future numeric claim records source command, input hash, date,
and whether value is measured, fixture assumption, target, estimate,
or external fact. Delete claim when evidence disappears; do not
silently downgrade it.

## Freeze note

The private register froze at KL-9.3 with C-001..C-030 reviewed; C-003
counts and C-009/C-027 wordings track the shipped tree (see the
private ledger for the per-run history). Rows C-031/C-032 above are
the KL-10.15 additions, supported by existing tests but still requiring
pre-submit user signoff; nothing else in this file changed meaning at
KL-10.15.
