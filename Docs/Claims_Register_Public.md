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
| C-001 | Repository has P-001 package/config/smoke/test/CLI foundation. | `verified_fact` | `TASKS.md`, `WHITEBOARD.md`, `README.md` | reviewed |
| C-002 | `python scripts/media_check.py` passes pinned `gemini_clean` and `test_3` structural fixtures. | `verified_fact` | command output; `fixtures/*.json` | reviewed |
| C-003 | `python -m unittest` passes 871 tests. | `verified_fact` | command output 2026-11-01 (KL-10.18 dashboard restructure; one environment-dependent live-bind skip possible; the UI test module requires `node` on PATH); `tests/` | reviewed |
| C-004 | `python -m kineticlab --help` exits 0. | `verified_fact` | command output; `kineticlab/cli/` | reviewed |
| C-005 | `test_3.mp4` is 1024×576 with 234 frames and non-uniform MP4 `stts` timing. | `measured` | `fixtures/test_3.json`; `scripts/media_check.py` output | structural only; not source PTS proof |
| C-006 | SAM response fixtures contain continuous bob/card frame records for `test_3`. | `verified_fact` | `Smoke/results/test_3_*_raw.txt`; KL-3.1 adapter parses 234/234 lines per file | KL-3.2 decode DONE: 234/234 records valid per file with mask-derived centroid/area |
| C-014 | SAM `one_bit` mask codec is fully specified by primary sources and decodes the real corpus. | `verified_fact` | `dev.meta.ai/docs/sam/` grammar; `github.com/meta-models/meta-sam` `protocol/sam3.md` + `python/src/meta_sam_parser/_mask_codec.py` (SAM License); independent transcription decoded 959/959 payloads with canonical round-trip | reviewed 2026-10-27; production decoder cross-verified 472/472 vs independent transcription |
| C-007 | KineticLab currently measures gravity accurately. | — | none | prohibited claim |
| C-008 | AI-generated footage proves physical or gravity accuracy. | — | none | prohibited claim |
| C-009 | Uncertainty on the reported quantity EXISTS as a seeded block-bootstrap resampling interval (method `block_bootstrap`, percentile [2.5,97.5], seed + n_boot + block recorded; captures measurement noise under M1, NOT the structured-residual model-adequacy bias — disclosed in assumptions). `W_UNCERTAINTY_UNAVAILABLE` fires only when the bootstrap genuinely cannot run; rejection and insufficient-frame paths stay `null` by design. | `verified_fact` | `kineticlab/fit/uncertainty.py`; `kineticlab/contracts.py` INTERVAL_METHODS + `block_bootstrap`; `kineticlab/assembly/build.py` wiring + honesty sentences; demo replay interval omega [5.46797987265865, 5.47774002094622, 5.488711558451474] 1/s | reviewed 2026-10-31 |
| C-010 | Planned v1 supports one fixed-camera planar pendulum plus confirmed reference card. | `planned` | project plan | scope lock |
| C-011 | Gravity requires independent length or independently validated metric scale; otherwise report identifiable `g/L_eff`. | `assumption` / design rule | project plan; locked app plan | implementation gate pending |
| C-012 | P-001 used no network or API calls. | `verified_fact` | handoff record; command log | reviewed |
| C-013 | `pytest`, FFmpeg/bash harness, and lockfile resolution are verified locally. | — | unavailable in sandbox | do not claim |
| C-015 | Two live SAM 3.1 calls on `Smoke/test_3.mp4` (prompts `ball`, `card`) were recorded 2026-10-28 via a user-run transport; redacted raw artifacts + `run_metadata.json` are in `fixtures/live/`; `Docs/Meta_Tooling_Evidence.md` carries the LIVE-RUN label. | `verified_fact` | console facts + SHA-256 hashes (clip `a98a5324…be5875ce`, bob `b216815f…fb3ad7`, card `d3fe9a7e…57473d1`); usage/cost null (transport does not capture it) | reviewed |
| C-016 | Both live SAM responses replay through the unchanged offline pipeline to 234/234 valid `observation.v1` records each, frames 0..233, zero missing PTS. | `verified_fact` | independent replay 2026-10-28 (records, validity, PTS joins recomputed); `fixtures/live/` | reviewed |
| C-017 | The live SAM artifacts contain no key material: committed hygiene patterns give 0 hits; the single case-insensitive `Sk-` substring is base85 mask-payload data, not a credential. | `verified_fact` | `tests/test_key_hygiene.py` 5/5 on tree incl. `fixtures/live/` | reviewed |
| C-018 | The M-2 advisory layer is built and tested offline: the five setup-review flags surface only as `W_ASSUMPTION_UNVERIFIED`, and advisory application is never-less-conservative (240-case matrix: 48 flag combinations x 5 result states; warnings only grow, states never upgrade). | `verified_fact` | `tests/test_advisory.py`; mapping in `kineticlab/advisory/setup_review.py` | reviewed |
| C-019 | The narrative number-echo audit discards any narrative containing a number that fails exact-value + vocabulary-word-also-in-JSON justification, substituting a byte-stable template; hostile-tested against hallucinated, rounded, unit-swapped, non-vocabulary, and injected numbers. | `verified_fact` | `kineticlab/advisory/narrative.py` (`audit_narrative`, `resolve_narrative`); hostile tests in `tests/test_advisory.py` | reviewed |
| C-020 | At M-2 closure no live Spark cache entries existed; every `fixtures/advisory/` entry was labeled `synthetic-fixture` with null endpoint and model id `synthetic-fixture`. (Historical statement, true at closure; two `live` entries were created later the same day — see C-021.) | `verified_fact` | `fixtures/advisory/README.md` label rules; `CACHE_LABELS` enforcement in `kineticlab/advisory/cache.py` | reviewed |
| C-021 | Both live Spark cache entries (`setup-review_20261028T081141Z.json`, `narrative_20261028T081237Z.json`) replay fully offline with hash re-verification through unchanged code (`load_entry` + `replay_entry`). | `verified_fact` | independent replays 2026-10-28; `kineticlab/advisory/cache.py` | reviewed |
| C-022 | The live setup-review advisory applied to the real computed result adds exactly 3 `W_ASSUMPTION_UNVERIFIED` warnings (card visibility, fixed camera, nominal scene) and downgrades `success` to `success_with_warnings`, changing nothing else. | `verified_fact` | independent `apply_setup_advisory` runs 2026-10-28 on `fixtures/advisory/inputs/narrative_input_result.json` | reviewed |
| C-023 | The live narrative advisory passes the number-echo audit against the real computed result (source `model`, exact `30.007170633278655 1/s^2` echo); the narrative text is display-only telemetry, never parsed for numbers. | `verified_fact` | independent `resolve_narrative` runs 2026-10-28; audit gate in `kineticlab/advisory/narrative.py` | reviewed |
| C-024 | The live card geometry yields a valid `calibration.v1`: ID-1 85.60×53.98 mm caller-confirmed, scale 0.328633 mm/px (isotropic, medians over 117 clean frames, anisotropy 1.35%, aspect 1.5646 vs 1.5858 nominal), U-3 depth-offset bound stated in record warnings + report (25/1500 = 1.67%, rendered as "1.7%" in the record's formatted text — same value); scale uncertainty honestly null with `W_UNCERTAINTY_UNAVAILABLE`. | `measured` | `fixtures/geometry/calibration_live.json` (`09e3e852…fa3aa`) | reviewed |
| C-025 | Arc-fit pivot at (452.62, −523.75) px, r = 907.48 px, mean radial residual 5.158 px (max 17.70 @frame 227, span 0.652 rad) from 234 live bob centroids by deterministic Kasa closed form. | `measured` | `fixtures/geometry/geometry_report_live.json` (`39540e56…a89a41`) | reviewed |
| C-026 | Clean-frame corner jitter mean 1.23 px / max 2.96 px (109 consecutive pairs) is the camera-stability evidence; the 117 occluded FRAMES (7 bands; 110 consecutive pairs within that set) are excluded with measured cause (max 70.6 px @79→80, mean 8.24 px); both splits reported, neither hidden. | `measured` | jitter splits in `fixtures/geometry/geometry_report_live.json` | reviewed |
| C-027 | g stays null in length-less P-006/assembly outputs (U-2 pivot length null); no gravity is claimed there; metric use of scale/arc length is allowed only with the U-3 bound and the M-3e hollow-ball/string-mass limitation stated alongside. | `verified_fact` | byte scan of both geometry pins (no `m/s^2`, no gravity field); contract gravity-needs-independent-length rule | reviewed |
| C-028 | The real test_3 chain assembles end-to-end offline (`kineticlab/assembly/`) to a validated `result.v1`, status `success_with_warnings`, g/L_eff = 30.00563573707589 1/s^2 (M1, 234/234 fit points), `gravity_m_s2` null, interval from the seeded block bootstrap; U-3 bound + M-3e limitation carried in assumptions; descriptive pivot radius 298.228 mm flagged `independent_length: false`. | `measured` | `fixtures/assembly/result.json` (`88d1ec2a…61263c`), `diagnostics.json` (`c58d2715…4c594`), `angles.csv` (`d44e33c9…c55b3e`) | reviewed |
| C-029 | M2 runs as diagnostic cross-check with the pre-registered include rule: converged + gamma strictly inside [0.0, 1.0]/s; live outcome gamma 0.029794544246787853 included-interior, omega 5.478960 rad/s cross-checks M1 omega (delta ~0.02%); M1 stays the reported model in every outcome. | `measured` | `fixtures/assembly/diagnostics.json` `m2` section | reviewed |
| C-030 | The angle CSV carries SOURCE PTS (`pts_seconds`), never re-zeroed or synthesized (irregular VFR spacing preserved); a regeneration test caught the exporter writing an empty time column pre-handoff and the suite now asserts every PTS cell is non-empty and strictly increasing. | `verified_fact` | `tests/test_assembly.py::test_series_pts_are_real_and_increasing` | reviewed |
| C-031 | When the run carries a human-typed pivot length (10–2000 mm, `user_supplied`), assembly reports `gravity_m_s2 = g/L_eff × L/1000` through the existing fit.v1 fields with `pivot_length_source = independent_measurement`, plus a gravity band linearly rescaling the g/L_eff bootstrap band; the summary and assumptions label the provenance. No gravity-accuracy claim is made (C-007 still prohibited): the number is only as good as the user's ruler. | `measured` | `kineticlab/assembly/build.py::apply_pivot_length`; `kineticlab/contracts.py` gravity identity; assembly tests incl. byte-identical length-less pins | pending reviewer sign-off (KL-10.15) |
| C-032 | Length-less runs produce byte-identical result records to before the gravity seam: same status, values, warnings, assumptions, and summary bytes. | `verified_fact` | assembly byte-identity tests vs pinned fixtures | pending reviewer sign-off (KL-10.15) |

## Update rule

Every future numeric claim records source command, input hash, date,
and whether value is measured, fixture assumption, target, estimate,
or external fact. Delete claim when evidence disappears; do not
silently downgrade it.

## Freeze note

The private register froze at KL-9.3 with C-001..C-030 reviewed; C-003
counts and C-009/C-027 wordings track the shipped tree (see the
private ledger for the per-run history). Rows C-031/C-032 above are
the KL-10.15 additions and await reviewer sign-off; nothing else in
this file changed meaning at KL-10.15.
