"""Live measure orchestration: detect -> confirm -> measure (KL-8.4).

:func:`run_detect` saves the clip, runs the capture, parses both roles,
and writes a ``detect_summary.json`` confirm payload (counts + first-frame
boxes for the UI overlay). :func:`run_measure` reads that summary and runs
exactly one mode to completion. :func:`run_live_chain` is the one-shot
composition the CLI uses (the CLI user has already chosen; the UI splits
the two stages around human confirmation).

Full mode reuses :func:`kineticlab.assembly.build.assemble` unchanged: the
orchestrator only builds the two inputs a fresh clip cannot pin — a
``calibration.v1`` record and a geometry report — then hands the run dir
to the same assembly the demos use. Motion mode never touches assemble
(the card seam would reject a cardless chain); it builds a first-class
motion report from :func:`build_fit_points`, :func:`angle_series`, and
:func:`fit_m1` with scale/length/gravity null.

Fresh-clip honesty rules (U-1/U-2/U-3 were measurements of older
pinned clips and are NOT transferred to any fresh clip):

- Full mode requires BOTH card dimensions human-typed (``card_width_mm``
  and ``card_height_mm``; ``E_MISSING_FIELD`` without either): the
  record states ``reference_type: "unknown"`` (a cut card is no
  standard) with ``user_confirmed`` dimensions — both numbers from the
  user's ruler, never derived from pixel aspect. Motion mode builds no
  calibration.
- ``same_plane``/``camera_fixed`` stay null (unassessed) with one
  ``W_ASSUMPTION_UNVERIFIED`` warning each, so the record is honestly
  ``valid: false``. Assemble records that flag as data; it does not
  reject the chain for it.
- Scale is the isotropic fallback ``card_width_mm / median PCA long
  side`` over clean (fitted, non-occluded) card frames; the short side
  is reported but never enters the scale.
- Corners stay null: PCA corners are unlabeled and their order flips
  frame to frame, so no median corner set is honest.
- No depth-offset bound exists for a fresh clip; the report states that
  instead of borrowing U-3.
- ``card_width_mm``/``card_height_mm`` + their ``*_source:
  "user_supplied"`` stamps live in the geometry report's calibration
  section (the v1 record's strict keys forbid new fields, so the stamp
  sits with the calibration build's provenance, documented here).
- Motion + a supplied mm is REJECTED (``E_INCOHERENT_VALUE``), never
  silently ignored: a silently unused physical size would let the user
  believe the report used it. Same for a card prompt in motion mode.
- An optional human-typed ``pivot_length_mm`` threads from the measure
  request through ``run_measure`` / ``run_live_chain`` to ``assemble``
  (full mode only, KL-10.17). Motion mode has no gravity path, so it
  leaves the length unused with its pivot/gravity fields null — never
  claimed — and the UI only offers the field in full mode, so no user
  is misled. Absent or unusable values reproduce the length-less run
  byte for byte (never an error).
- Zero valid records for a required role is ``E_EMPTY_STRING`` (the
  detection set is empty), raised at detect so no empty run confirms.
- Non-monotonic valid PTS raises the observation code (time corruption
  has no honest report); scarcity (too few points, no pivot) files an
  ``incomplete`` motion report instead of raising.

Measure outputs are deterministic for a fixed run dir (no wall clock in
them); only detect writes timestamps, once. Every number is copied from
pipeline outputs, never authored here.

Stdlib only. No network except through :func:`run_capture`.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from kineticlab import __version__
from kineticlab.assembly.angles import angle_series, build_fit_points
from kineticlab.assembly.build import (
    AMP_BOUNDS,
    GRID_N_OMEGA,
    MAX_REFINE,
    OMEGA_BOUNDS,
    PIVOT_LENGTH_BOUNDS_MM,
    assemble,
)
from kineticlab.assembly.export import export_angles_csv
from kineticlab.capture import MODES, ROLE_FILENAMES, run_capture
from kineticlab.contracts import (
    CALIBRATION_VERSION,
    CalibrationRecord,
    ContractError,
    FieldError,
    ObservationRecord,
)
from kineticlab.demo import BOB_OBJECT_ID, CARD_OBJECT_ID
from kineticlab.fit.m1 import MIN_POINTS, fit_m1
from kineticlab.geometry import (
    decode_frame_masks,
    fit_arc,
    oriented_rectangle_from_raster,
    overlap_frames,
)
from kineticlab.ingest import extract_frame_records, inspect_media
from kineticlab.observation import parse_raw_fixture

__all__ = [
    "RUN_ID_PATTERN",
    "CLIP_FILENAME",
    "SUMMARY_FILENAME",
    "CALIBRATION_FILENAME",
    "GEOMETRY_REPORT_FILENAME",
    "MOTION_REPORT_FILENAME",
    "MOTION_CSV_FILENAME",
    "PARSE_CHECK_FILENAME",
    "MEASURE_REUSE_FILENAME",
    "MODE_ROLES",
    "OBJECT_IDS",
    "NO_SCALE_REASON",
    "MOTION_ASSUMPTIONS",
    "MODEL_LIMITATION_NOTE",
    "new_run_id",
    "validate_run_id",
    "validate_mode",
    "validate_prompts",
    "validate_card_width_mm",
    "live_status_line",
    "run_detect",
    "run_measure",
    "run_live_chain",
]

RUN_ID_PATTERN = re.compile(r"^live-\d{8}T\d{6}Z-[0-9a-f]{8}$")
"""Run ids are timestamped-unique; the GET route pattern-validates them."""

CLIP_FILENAME = "clip.mp4"
"""Exact captured bytes, copied into every run dir (runs self-contained)."""

SUMMARY_FILENAME = "detect_summary.json"
"""Confirm payload: counts + boxes + video dims + clip identity."""

PARSE_CHECK_FILENAME = "parse_check.json"
"""Detect-stage parse check record: per-role file SHA + record counts.

Written by :func:`run_detect` after the canonical check passes. Measure
verifies each SHA against the current raw bytes and, on match, rebuilds
the records from the stored dicts instead of re-running the expensive
re-encode — the skip is then recorded in ``measure_reuse.json``. A SHA
mismatch (or missing/unreadable check file) falls back to a full
re-parse; nothing is ever skipped silently.
"""

MEASURE_REUSE_FILENAME = "measure_reuse.json"
"""Measure-stage honesty record: what was skipped, what was checked.

``{"reused": bool, "checked": {role: sha}, "parsed_at_utc": ...,
"measured_at_utc": ...}`` — written on every measure run. ``reused``
is true only when every role's current raw bytes hash to the
detect-stage SHAs; on fallback (check file missing or SHA
mismatch) measure re-parses fully and records ``reused: false``
with the fresh SHAs, so the record always states what happened.
"""

CALIBRATION_FILENAME = "calibration.json"
"""Full mode only: the fresh-clip ``calibration.v1`` record."""

GEOMETRY_REPORT_FILENAME = "geometry_report.json"
"""Full mode only: pivot arc + calibration section assemble reads."""

MOTION_REPORT_FILENAME = "motion_report.json"
"""Motion mode only: the first-class scale-free motion report."""

MOTION_CSV_FILENAME = "motion_angles.csv"
"""Motion mode only: angle series (same columns as ``angles.csv``)."""

MODE_ROLES = {"full": ("bob", "card"), "motion": ("bob",)}
"""Required capture roles per mode."""

OBJECT_IDS = {"bob": BOB_OBJECT_ID, "card": CARD_OBJECT_ID}
"""Caller-declared SAM-live object ids (shared with the demo replay)."""

ROLE_NAMES = {"bob": "bob", "card": "reference_card"}
"""Short role -> ``observation.v1`` object_role."""

NO_SCALE_REASON = "no reference card: no scale"
"""Why motion reports carry null scale/length/gravity (verbatim)."""

MOTION_ASSUMPTIONS = (
    # KL-9.6 M2: same correction as the assemble assumption — the
    # arbitrary zero is absorbed only up to a constant offset the
    # M1 model does not represent.
    "Angles measured from image +y about the arc-fit pivot; the zero "
    "is arbitrary and absorbed by the fit phase only up to a "
    "constant offset the M1 model does not represent "
    "(A*cos(wt+phi) has no theta_eq term) - stated uncorrected (no "
    "upright-camera assumption).",
    "No reference card: scale, pivot length, and gravity are null; no "
    "calibration file exists for this run.",
    "M1 is the reported model (pre-registered parsimony); motion mode "
    "runs no M2 cross-check.",
    "M-3e hollow-ball/string-mass bias stated, uncorrected.",
)
"""Motion-report assumptions (fixed prose, same register as assemble's)."""

MODEL_LIMITATION_NOTE = (
    "M-3e hollow-ball/string-mass bias stated, uncorrected: the bob is "
    "a hollow ball on a massive string, not the point mass on a "
    "massless rigid rod M1 assumes."
)
"""Geometry-report model limitation (see the assemble assumption text)."""


def _arc_radius_caveat(arc: dict[str, Any], scale_mm_per_px: float) -> str:
    """Arc-fit radius caveat for the live geometry report (KL-9.6 M1).

    The radius is descriptive-only — confounded by plane offset,
    foreshortening, and bob-center estimation — while the measured
    g/L = omega^2 is frequency-based and unaffected. The millimeter
    value is this run's own fitted radius times this run's scale.
    """
    mapping = arc if isinstance(arc, dict) else {}
    radius_px = mapping.get("radius_px")
    if mapping.get("fitted") is True \
            and isinstance(radius_px, (int, float)) \
            and not isinstance(radius_px, bool):
        radius_mm = float(radius_px) * scale_mm_per_px
        lead = (f"Arc-fit radius ({radius_mm:.1f} mm on this run) is "
                "descriptive-only")
    else:
        lead = ("Arc-fit radius is descriptive-only "
                "(no fitted radius on this run)")
    return (lead + " and confounded by plane offset, foreshortening, "
            "and bob-center estimation; the measured g/L = omega^2 is "
            "frequency-based and unaffected. Stated uncorrected.")

U3_FRESH_CLIP_STATEMENT = (
    "No depth-offset scale bound: this clip provides no camera/card "
    "depth measurements (U-3 was a measurement of a retired pinned "
    "clip and is not borrowed here); "
    "scale assumes a coplanar card and a fixed camera, both unassessed "
    "(see the calibration warnings)."
)
"""Fresh-clip u3_bound statement (never borrows a retired clip's bound)."""


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, sort_keys=True, indent=2,
                       ensure_ascii=True) + "\n").encode("utf-8")


def new_run_id() -> str:
    """Mint a timestamped-unique run id (UTC + 8 hex digits)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"live-{stamp}-{secrets.token_hex(4)}"


def validate_run_id(run_id: Any) -> str:
    """Accept exactly the minted shape (malformed == missing, no oracle)."""
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.match(run_id):
        _fail("E_MISSING_FIELD", "run_id",
              f"unknown run: {run_id!r}")
        raise AssertionError("unreachable")
    return run_id


def validate_mode(mode: Any) -> str:
    """Accept exactly ``full``/``motion``."""
    if mode not in MODES:
        _fail("E_BAD_ENUM", "mode",
              f"mode must be 'full' or 'motion', got {mode!r}")
        raise AssertionError("unreachable")
    assert isinstance(mode, str)
    return mode


def validate_prompts(prompts: Any, mode: str) -> dict[str, str]:
    """Require exactly the mode's roles, each a non-blank noun phrase."""
    required = MODE_ROLES[mode]
    if not isinstance(prompts, dict):
        _fail("E_WRONG_TYPE", "prompts",
              f"prompts must be an object, got {type(prompts).__name__}")
        raise AssertionError("unreachable")
    for role in prompts:
        if role not in ROLE_FILENAMES:
            _fail("E_BAD_ENUM", "prompts",
                  f"unknown role {role!r} (expected 'bob'/'card')")
            raise AssertionError("unreachable")
    for role in required:
        if role not in prompts:
            _fail("E_MISSING_FIELD", f"prompt:{role}",
                  f"mode {mode!r} needs a {role!r} prompt")
            raise AssertionError("unreachable")
    for role in sorted(set(prompts) - set(required)):
        _fail("E_INCOHERENT_VALUE", f"prompt:{role}",
              f"mode {mode!r} captures no {role!r}; drop the prompt "
              "instead of letting it ride unused")
        raise AssertionError("unreachable")
    clean: dict[str, str] = {}
    for role in required:
        prompt = prompts[role]
        if not isinstance(prompt, str) or not prompt.strip():
            _fail("E_EMPTY_STRING", f"prompt:{role}",
                  f"role {role!r}: prompt must be a non-blank noun phrase")
            raise AssertionError("unreachable")
        clean[role] = prompt
    return clean


def validate_card_width_mm(value: Any, mode: str) -> float | None:
    """Validate the human-typed card width (full mode only)."""
    return _validate_card_dim_mm(value, mode, "card_width_mm")


def validate_card_height_mm(value: Any, mode: str) -> float | None:
    """Validate the human-typed card height (full mode only)."""
    return _validate_card_dim_mm(value, mode, "card_height_mm")


def _validate_card_dim_mm(value: Any, mode: str, field: str) -> float | None:
    """Validate one human-typed card dimension (full mode only).

    Full mode requires a positive finite number; motion mode rejects any
    supplied value (silently unused physical sizes are dishonest).
    Strings parse (multipart fields arrive as text); anything else must
    already be a number.
    """
    noun = "card width" if field == "card_width_mm" else "card height"
    if mode == "motion":
        if value is None:
            return None
        _fail("E_INCOHERENT_VALUE", field,
              f"motion mode uses no {noun}; drop the value instead "
              "of letting it ride unused")
        raise AssertionError("unreachable")
    if value is None:
        _fail("E_MISSING_FIELD", field,
              f"full mode needs the human-typed {noun} in mm")
        raise AssertionError("unreachable")
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            _fail("E_WRONG_TYPE", field,
                  f"{noun} must be a number, got {value!r}")
            raise AssertionError("unreachable")
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail("E_WRONG_TYPE", field,
              f"{noun} must be a number, got {type(value).__name__}")
        raise AssertionError("unreachable")
    else:
        number = float(value)
    if not math.isfinite(number):
        _fail("E_NON_FINITE", field,
              f"{noun} must be finite, got {value!r}")
        raise AssertionError("unreachable")
    if number <= 0.0:
        _fail("E_OUT_OF_RANGE", field,
              f"{noun} must be positive, got {value!r}")
        raise AssertionError("unreachable")
    return number


def validate_pivot_length_mm(value: Any) -> float | None:
    """Parse the optional human-typed pivot length (KL-10.17).

    Returns the length as a float when it is a finite number inside
    ``PIVOT_LENGTH_BOUNDS_MM``, else None. Strings parse (multipart
    fields arrive as text); booleans are not numbers here. Never
    raises: an absent or unusable length leaves gravity null, exactly
    the length-less run (byte-identical records).
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            number = float(value.strip())
        except ValueError:
            return None
    elif isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    else:
        number = float(value)
    if not math.isfinite(number):
        return None
    low, high = PIVOT_LENGTH_BOUNDS_MM
    if not low <= number <= high:
        return None
    return number


def _parse_roles(run_dir: Path, table: Any,
                 roles: tuple[str, ...]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for role in roles:
        parsed[role] = parse_raw_fixture(
            str(run_dir / ROLE_FILENAMES[role]),
            object_role=ROLE_NAMES[role], object_id=OBJECT_IDS[role],
            frame_table=table, model_name="sam-3.1")
    return parsed


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_parse_check(run_dir: Path,
                       parsed: dict[str, Any]) -> dict[str, Any]:
    """Persist the detect-stage parse check record (KL-8.7 item 4).

    Stores per-role raw-file SHA-256 plus record counts and the full
    record dicts. The SHA pins the exact bytes the canonical check
    covered; the dicts let measure rebuild without re-running the
    expensive decode/re-encode when the bytes still match.
    """
    check: dict[str, Any] = {"roles": {}}
    for role in sorted(parsed):
        raw_path = run_dir / ROLE_FILENAMES[role]
        check["roles"][role] = {
            "raw_sha256": _sha256_file(raw_path),
            "n_records": len(parsed[role]),
            "n_valid": sum(1 for record in parsed[role]
                           if record.valid),
            "records": [record.to_dict() for record in parsed[role]],
        }
    check["parsed_at_utc"] = _utc_now()
    (run_dir / PARSE_CHECK_FILENAME).write_bytes(_canonical(check))
    return check


def _read_parse_check(run_dir: Path) -> dict[str, Any]:
    """Read the parse check record; raise coded errors when unusable."""
    path = run_dir / PARSE_CHECK_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        _fail("E_MISSING_FIELD", PARSE_CHECK_FILENAME,
              f"no parse check in {run_dir.name!r}; re-parse required")
        raise AssertionError("unreachable")
    try:
        check = json.loads(text)
    except json.JSONDecodeError as error:
        _fail("E_MALFORMED_JSON", PARSE_CHECK_FILENAME,
              f"parse check is not parseable JSON: {error}")
        raise AssertionError("unreachable")
    if not isinstance(check, dict) or not isinstance(
            check.get("roles"), dict):
        _fail("E_WRONG_TYPE", PARSE_CHECK_FILENAME,
              "parse check must be an object with a roles object")
        raise AssertionError("unreachable")
    return check


def _reuse_or_reparse(run_dir: Path, table: Any,
                      roles: tuple[str, ...]) -> tuple[dict[str, Any], bool]:
    """Rebuild detect's records when raw SHAs verify, else re-parse.

    Returns ``(parsed, reused)``. Reuse rebuilds
    ``ObservationRecord`` objects from the check file's stored dicts
    after verifying each role's current raw bytes hash to the stored
    SHA — so the covered bytes are proven identical, and the records
    are proven valid by ``from_dict`` on the way back in. Any failure
    (missing file, bad JSON, SHA mismatch, shape mismatch, or a
    record that no longer validates) raises a registered
    ``ContractError`` naming ``parse_check.json`` — the caller falls
    back to a full re-parse. Never partial: either every role
    verifies or none is reused.
    """
    check = _read_parse_check(run_dir)
    stored = check["roles"]
    if set(stored) != set(roles):
        _fail("E_INCOHERENT_VALUE", PARSE_CHECK_FILENAME,
              f"parse check covers roles {sorted(stored)}; "
              f"measure needs {sorted(roles)}")
        raise AssertionError("unreachable")
    parsed: dict[str, Any] = {}
    for role in roles:
        entry = stored[role]
        if not isinstance(entry, dict) \
                or not isinstance(entry.get("records"), list) \
                or not isinstance(entry.get("raw_sha256"), str):
            _fail("E_WRONG_TYPE", f"{PARSE_CHECK_FILENAME}.{role}",
                  f"parse check entry for {role!r} is malformed")
            raise AssertionError("unreachable")
        try:
            current = _sha256_file(run_dir / ROLE_FILENAMES[role])
        except OSError:
            _fail("E_MISSING_FIELD", f"{PARSE_CHECK_FILENAME}.{role}",
                  f"raw file for {role!r} is unreadable; re-parse required")
            raise AssertionError("unreachable")
        if current != entry["raw_sha256"]:
            _fail("E_INCOHERENT_VALUE", f"{PARSE_CHECK_FILENAME}.{role}",
                  f"raw bytes for {role!r} changed since detect "
                  f"(sha {current[:12]}… != {entry['raw_sha256'][:12]}…); "
                  "re-parse required")
            raise AssertionError("unreachable")
        try:
            records = [ObservationRecord.from_dict(item)
                       for item in entry["records"]]
        except ContractError as error:
            first = error.errors[0]
            _fail(first.code, f"{PARSE_CHECK_FILENAME}.{role}",
                  f"stored record for {role!r} no longer validates: "
                  f"{first.message}")
            raise AssertionError("unreachable")
        if [record.to_dict() for record in records] != entry["records"]:
            _fail("E_INCOHERENT_VALUE", f"{PARSE_CHECK_FILENAME}.{role}",
                  f"stored records for {role!r} do not round-trip; "
                  "re-parse required")
            raise AssertionError("unreachable")
        parsed[role] = records
    return parsed, True


def _write_measure_reuse(run_dir: Path, check: dict[str, Any],
                         reused: bool) -> dict[str, Any]:
    """Record what measure skipped and what it checked (KL-8.7 item 4)."""
    reuse = {
        "reused": reused,
        "checked": {role: entry["raw_sha256"]
                    for role, entry in check["roles"].items()},
        "parsed_at_utc": check.get("parsed_at_utc"),
        "measured_at_utc": _utc_now(),
    }
    (run_dir / MEASURE_REUSE_FILENAME).write_bytes(_canonical(reuse))
    return reuse


def _gate_valid(records: Any, role: str) -> list[Any]:
    valid = [record for record in records if record.valid]
    if not valid:
        _fail("E_EMPTY_STRING", f"detections:{role}",
              f"role {role!r}: {len(records)} records parsed, 0 valid "
              "(nothing detected well enough to measure)")
        raise AssertionError("unreachable")
    return valid


def run_detect(clip_path: str | Path, run_dir: str | Path, mode: str,
               prompts: dict[str, str], api_key: str,
               transport: Callable[[dict[str, Any]],
                                   dict[str, Any]] | None = None
               ) -> dict[str, Any]:
    """Detect: save the clip, capture, parse, write the confirm payload.

    Returns ``{"run_id", "summary", "summary_path", "raw_paths",
    "metadata", "clip_sha256"}``. Raises registered ``ContractError``
    (ingest, capture, parse, or empty-detection failures) — never a
    partial run dir without its summary.
    """
    clean_mode = validate_mode(mode)
    clean_prompts = validate_prompts(prompts, clean_mode)
    source = Path(clip_path)
    try:
        clip_bytes = source.read_bytes()
    except OSError:
        _fail("E_MISSING_FIELD", "clip_path",
              f"clip is unreadable: {source.name!r}")
        raise AssertionError("unreachable")
    if not clip_bytes:
        _fail("E_EMPTY_STRING", "clip_path",
              f"clip is empty: {source.name!r}")
        raise AssertionError("unreachable")
    target = Path(run_dir)
    target.mkdir(parents=True, exist_ok=True)
    saved_clip = target / CLIP_FILENAME
    saved_clip.write_bytes(clip_bytes)
    media = inspect_media(str(saved_clip))
    table = extract_frame_records(str(saved_clip))
    captured = run_capture(saved_clip, clean_prompts, target, api_key,
                           transport=transport, mode=clean_mode)
    parsed = _parse_roles(target, table, MODE_ROLES[clean_mode])
    _write_parse_check(target, parsed)
    roles: dict[str, Any] = {}
    for role in MODE_ROLES[clean_mode]:
        records = parsed[role]
        valid = _gate_valid(records, role)
        first = valid[0]
        box = list(first.bbox) if first.bbox is not None else None
        roles[role] = {"records": len(records), "valid": len(valid),
                       "first_frame_index": first.frame_index,
                       "first_box": box}
    summary = {
        "run_id": target.name,
        "mode": clean_mode,
        "prompts": clean_prompts,
        "clip_sha256": captured["clip_sha256"],
        "video": {"width": media.width, "height": media.height,
                  "frames": len(table)},
        "roles": roles,
        "created_utc": _utc_now(),
    }
    summary_path = target / SUMMARY_FILENAME
    summary_path.write_bytes(_canonical(summary))
    return {"run_id": target.name, "summary": summary,
            "summary_path": str(summary_path),
            "raw_paths": captured["raw_paths"],
            "metadata": captured["metadata"],
            "clip_sha256": captured["clip_sha256"]}


def _read_summary(run_dir: Path) -> dict[str, Any]:
    path = run_dir / SUMMARY_FILENAME
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        _fail("E_MISSING_FIELD", "run_id",
              f"no confirmed detection in {run_dir.name!r}")
        raise AssertionError("unreachable")
    try:
        summary = json.loads(text)
    except json.JSONDecodeError as error:
        _fail("E_MALFORMED_JSON", SUMMARY_FILENAME,
              f"detect summary is not parseable JSON: {error}")
        raise AssertionError("unreachable")
    if not isinstance(summary, dict):
        _fail("E_WRONG_TYPE", SUMMARY_FILENAME,
              "detect summary must be a JSON object")
        raise AssertionError("unreachable")
    for key in ("run_id", "mode", "prompts", "clip_sha256", "video",
                "roles"):
        if key not in summary:
            _fail("E_MISSING_FIELD", f"{SUMMARY_FILENAME}.{key}",
                  f"detect summary lacks {key!r}")
            raise AssertionError("unreachable")
    validate_mode(summary["mode"])
    if summary["run_id"] != run_dir.name:
        _fail("E_INCOHERENT_VALUE", f"{SUMMARY_FILENAME}.run_id",
              "detect summary names a different run than its directory")
        raise AssertionError("unreachable")
    return summary


def _clean_card_frames(run_dir: Path, card: list[Any],
                       bob: list[Any]) -> tuple[dict[int, Any], list[int]]:
    """Oriented card rects per frame + the clean (fitted, unoccluded) set."""
    masks = decode_frame_masks(str(run_dir / ROLE_FILENAMES["card"]),
                               card)
    rects: dict[int, Any] = {}
    for mask in masks:
        # KL-9.2 item 4: fused raster PCA — bit-identical to
        # oriented_rectangle(mask.set_pixels()), verified by
        # test_fused_pca_matches_classic_on_live_masks.
        rect = oriented_rectangle_from_raster(
            mask.raster, mask.width, mask.height, mask.x1, mask.y1)
        if rect.get("fitted") is True:
            rects[mask.frame_index] = rect
    occluded = set(overlap_frames(bob, card))
    clean = sorted(frame for frame in rects if frame not in occluded)
    return rects, clean


def _fresh_calibration(clip_sha256: str, long_med: float,
                       short_med: float, card_width_mm: float,
                       card_height_mm: float) -> dict[str, Any]:
    """Build the confirmed fresh-clip ``calibration.v1`` dict (validated).

    Both card dimensions are human-typed by the user (the confirm
    gesture), so the record states ``unknown`` reference type (a cut
    card is no standard) with ``user_confirmed`` dimensions — both from
    the user's ruler, never derived from pixel aspect, which would make
    the aspect check vacuous. Assumptions stay unassessed (null) with
    their warnings, so the record stays honestly ``valid: false``; the
    scale is stamped by the caller below.
    """
    record = CalibrationRecord.from_dict({
        "schema_version": CALIBRATION_VERSION,
        "reference_type": "unknown",
        "reference_dimensions_mm": {"width_mm": card_width_mm,
                                    "height_mm": card_height_mm},
        "dimension_source": "user_confirmed",
        "observed_corners_px": None,
        "observed_oriented_dimensions_px": {
            "long_side_px": long_med, "short_side_px": short_med},
        "scale_mm_per_px": None,  # stamped by the caller below
        "plane_transform": None,
        "scale_uncertainty_mm_per_px": None,
        "same_plane_assumption": None,
        "camera_fixed_assumption": None,
        "valid": False,
        "warnings": [
            {"code": "W_ASSUMPTION_UNVERIFIED",
             "detail": "same-plane card/swing geometry unassessed for "
                       "this clip (no depth measurements provided)"},
            {"code": "W_ASSUMPTION_UNVERIFIED",
             "detail": "fixed-camera geometry unassessed for this clip "
                       "(no stability check provided)"},
        ],
        "provenance": {
            "software_name": "kineticlab",
            "software_version": __version__,
            "input_sha256": clip_sha256,
            "model_name": "sam-3.1",
            "model_version": None,
            "raw_refs": [ROLE_FILENAMES["card"]],
        },
    })
    return record.to_dict()


def _measure_full(run_dir: Path, summary: dict[str, Any],
                  card_width_mm: float, card_height_mm: float,
                  pivot_length_mm: float | None = None
                  ) -> dict[str, Any]:
    clip = run_dir / CLIP_FILENAME
    table = extract_frame_records(str(clip))
    try:
        parsed, reused = _reuse_or_reparse(run_dir, table, ("bob", "card"))
        check = _read_parse_check(run_dir)
    except ContractError:
        parsed = _parse_roles(run_dir, table, ("bob", "card"))
        check = _write_parse_check(run_dir, parsed)
        reused = False
    _write_measure_reuse(run_dir, check, reused)
    _gate_valid(parsed["bob"], "bob")
    _gate_valid(parsed["card"], "card")
    rects, clean = _clean_card_frames(run_dir, parsed["card"],
                                         parsed["bob"])
    if not clean:
        _fail("E_OUT_OF_RANGE", "clean_frames",
              "0 clean card frames (minimum 1): the card is never both "
              "detected and unoccluded")
        raise AssertionError("unreachable")
    longs = [rects[frame]["long_side"] for frame in clean]
    shorts = [rects[frame]["short_side"] for frame in clean]
    long_med = float(statistics.median(longs))
    short_med = float(statistics.median(shorts))
    scale = card_width_mm / long_med
    calibration = _fresh_calibration(summary["clip_sha256"], long_med,
                                     short_med, card_width_mm,
                                     card_height_mm)
    calibration["scale_mm_per_px"] = scale
    # Re-validate with the scale stamped: the written bytes are proven.
    CalibrationRecord.from_dict(calibration)
    calibration_path = run_dir / CALIBRATION_FILENAME
    calibration_path.write_bytes(_canonical(calibration))
    bob_valid = [record for record in parsed["bob"] if record.valid]
    centers = [(record.centroid_x_px, record.centroid_y_px)
               for record in bob_valid]
    areas = [record.mask_area_px for record in bob_valid]
    arc = fit_arc(centers, areas
                  if all(isinstance(area, (int, float))
                         and not isinstance(area, bool)
                         for area in areas) else None)
    report = {
        "pivot_arc": arc,
        "calibration": {
            "n_usable_frames": len(clean),
            "card_width_mm": card_width_mm,
            "card_width_mm_source": "user_supplied",
            "card_height_mm": card_height_mm,
            "card_height_mm_source": "user_supplied",
            "scale_mm_per_px": scale,
            "median_long_side_px": long_med,
            "median_short_side_px": short_med,
            "scale_note": ("Isotropic scale = user-supplied card width "
                           "/ median PCA long side over "
                           f"{len(clean)} clean (fitted, non-occluded) "
                           "card frames; the short side is reported but "
                           "never enters the scale."),
            "corners_note": ("observed_corners_px is null: PCA corners "
                             "are unlabeled and their order flips frame "
                             "to frame, so no median corner set is "
                             "honest."),
            "u3_bound": {"statement": U3_FRESH_CLIP_STATEMENT},
        },
        # KL-9.6 M1: the arc-fit radius caveat joins the M-3e
        # note (a list, matching the offline calibration report's
        # model_limitations shape). The radius value is this run's
        # own fitted radius times this run's scale — descriptive,
        # never a reference length.
        "model_limitations": [MODEL_LIMITATION_NOTE,
                              _arc_radius_caveat(arc, scale)],
    }
    report_path = run_dir / GEOMETRY_REPORT_FILENAME
    report_path.write_bytes(_canonical(report))
    # KL-9.2 item 4: hand assemble the records parsed (or
    # SHA-verified) above instead of re-parsing the same bytes —
    # identical records, field for field, at zero re-decode cost.
    assembled = assemble({
        "clip_path": str(clip),
        "raw_bob_path": str(run_dir / ROLE_FILENAMES["bob"]),
        "raw_card_path": str(run_dir / ROLE_FILENAMES["card"]),
        "calibration_path": str(calibration_path),
        "geometry_report_path": str(report_path),
        "out_dir": str(run_dir),
    }, _parsed={"bob": parsed["bob"], "card": parsed["card"]},
        pivot_length_mm=pivot_length_mm)
    written = [str(run_dir / name) for name in
               ("result.json", "diagnostics.json", "angles.csv",
                "summary.md")]
    for path in written:
        if not Path(path).is_file():
            _fail("E_MISSING_FIELD", "exports",
                  f"assemble did not write {Path(path).name!r}")
            raise AssertionError("unreachable")
    return {"mode": "full", "result": assembled["result"],
            "diagnostics": assembled["diagnostics"],
            "angle_series": assembled["angle_series"],
            "export_refs": assembled["export_refs"],
            "written": written,
            "status_line": live_status_line(
                "full", run_dir.name, assembled["result"],
                len(written))}


def _motion_provenance(clip_sha256: str) -> dict[str, Any]:
    return {"software_name": "kineticlab",
            "software_version": __version__,
            "input_sha256": clip_sha256,
            "model_name": "sam-3.1",
            "model_version": None,
            "raw_refs": [ROLE_FILENAMES["bob"]]}


def _measure_motion(run_dir: Path,
                    summary: dict[str, Any]) -> dict[str, Any]:
    clip = run_dir / CLIP_FILENAME
    table = extract_frame_records(str(clip))
    try:
        parsed, reused = _reuse_or_reparse(run_dir, table, ("bob",))
        check = _read_parse_check(run_dir)
    except ContractError:
        parsed = _parse_roles(run_dir, table, ("bob",))
        check = _write_parse_check(run_dir, parsed)
        reused = False
    _write_measure_reuse(run_dir, check, reused)
    bob = parsed["bob"]
    _gate_valid(bob, "bob")
    fitted = build_fit_points(bob)
    points = fitted["points"]
    excluded = fitted["excluded_frames"]
    areas_by_frame = {record.frame_index: record.mask_area_px
                      for record in bob if record.valid}
    areas: list[float] | None = []
    for point in points:
        area = areas_by_frame.get(point["frame_index"])
        if not isinstance(area, (int, float)) \
                or isinstance(area, bool):
            areas = None
            break
        areas.append(float(area))
    arc = fit_arc([(point["x_px"], point["y_px"]) for point in points],
                  areas)
    pivot: list[float] | None = None
    radius_px: float | None = None
    pivot_source: str | None = None
    series: list[dict[str, Any]] = []
    m1: dict[str, Any] | None = None
    status = "incomplete"
    reason: str | None = None
    if arc.get("fitted") is not True:
        reason = (f"arc fit failed ({arc.get('reason')}; "
                  f"n={arc.get('n')}): no pivot, no angles, no fit")
    elif len(points) < MIN_POINTS:
        center = arc.get("center_px")
        pivot = [float(center[0]), float(center[1])] \
            if isinstance(center, (list, tuple)) else None
        radius = arc.get("radius_px")
        radius_px = float(radius) \
            if isinstance(radius, (int, float)) else None
        pivot_source = "arc fit of bob centroids (scale-free)"
        reason = (f"{len(points)} usable points below the M1 minimum "
                  f"{MIN_POINTS}: no fit attempted")
    else:
        center = arc["center_px"]
        pivot = [float(center[0]), float(center[1])]
        radius_px = float(arc["radius_px"])
        pivot_source = "arc fit of bob centroids (scale-free)"
        series = angle_series(points, pivot[0], pivot[1])
        m1 = fit_m1({
            "points": [{"t_seconds": point["t_seconds"],
                        "x_px": point["x_px"], "y_px": point["y_px"]}
                       for point in points],
            "pivot_x_px": pivot[0], "pivot_y_px": pivot[1],
            "bounds": {"amplitude_rad": list(AMP_BOUNDS),
                       "omega_per_s": list(OMEGA_BOUNDS)},
            "grid_n_omega": GRID_N_OMEGA,
            "max_refine_iterations": MAX_REFINE, "truth": None})
        # KL-9.6 B4: a ran-but-unconverged fit (e.g. the flat-objective
        # path, which returns grid-edge values) is NOT a publishable
        # result. Gate "complete" on diagnostics.converged.
        diagnostics = m1.get("diagnostics", {}) \
            if isinstance(m1, dict) else {}
        if diagnostics.get("converged") is True:
            status = "complete"
        else:
            term = diagnostics.get("termination_reason")
            reason = ("M1 fit did not converge" +
                      (f" ({term})" if term else "") +
                      ": no publishable result")
    published = status == "complete"
    fitted_params = ((m1["diagnostics"].get("fitted") or {})
                     if m1 is not None and published else {})
    report = {
        "format": "motion-report.v1",
        "status": status,
        "run_id": run_dir.name,
        "mode": "motion",
        "clip_sha256": summary["clip_sha256"],
        "prompts": {"bob": summary["prompts"]["bob"]},
        "capture_ref": ROLE_FILENAMES["bob"],
        "n_table_frames": len(table),
        "n_bob_records": len(bob),
        "n_fit_points": len(points),
        "excluded_frames": excluded,
        "pivot_px": pivot,
        "pivot_source": pivot_source,
        "radius_px": radius_px,
        "arc": arc,
        # KL-9.6 B4: strip the synthetic-fixture test-convention note
        # from the published report (shallow copy; nested fit and
        # diagnostics dicts are preserved verbatim).
        "m1": ({key: value for key, value in m1.items()
                if key != "test_convention_note"}
               if m1 is not None else None),
        "amplitude_rad": fitted_params.get("amplitude_rad"),
        "omega_per_s": fitted_params.get("omega_per_s"),
        "period_s": fitted_params.get("period_s"),
        "g_over_l_per_s2": (m1["fit"].get("g_over_l_per_s2")
                            if m1 is not None and published else None),
        "scale_mm_per_px": None,
        "pivot_length_mm": None,
        "gravity_m_s2": None,
        "reason": NO_SCALE_REASON if status == "complete" else reason,
        "assumptions": list(MOTION_ASSUMPTIONS),
        "warnings": [{
            "code": "W_UNCERTAINTY_UNAVAILABLE",
            "detail": "motion mode estimates no uncertainty; "
                      "method is none.",
        }],
        "provenance": _motion_provenance(summary["clip_sha256"]),
        "exports": [MOTION_REPORT_FILENAME, MOTION_CSV_FILENAME],
    }
    report_path = run_dir / MOTION_REPORT_FILENAME
    report_path.write_bytes(_canonical(report))
    csv_path = run_dir / MOTION_CSV_FILENAME
    csv_path.write_bytes(export_angles_csv(series))
    written = [str(report_path), str(csv_path)]
    return {"mode": "motion", "report": report, "written": written,
            "status_line": live_status_line(
                "motion", run_dir.name, report, len(written))}


def run_measure(run_dir: str | Path,
                card_width_mm: Any = None,
                pivot_length_mm: Any = None,
                card_height_mm: Any = None) -> dict[str, Any]:
    """Measure a confirmed run dir to completion (full or motion).

    Full mode needs the human-typed ``card_width_mm`` AND
    ``card_height_mm``; motion mode rejects both. Returns the mode
    output (``result``- or ``report``-shaped) plus ``written`` paths
    and a ``status_line``.

    ``pivot_length_mm`` (KL-10.17) optionally carries the human-typed
    independent pivot length; full mode forwards it to
    :func:`kineticlab.assembly.build.assemble` so gravity computes.
    Absent or unusable values behave exactly like the length-less
    run. Motion mode has no gravity path, so it leaves the length
    unused and its pivot/gravity fields null (never claimed).
    """
    target = Path(run_dir)
    validate_run_id(target.name)
    summary = _read_summary(target)
    mode = summary["mode"]
    width = validate_card_width_mm(card_width_mm, mode)
    height = validate_card_height_mm(card_height_mm, mode)
    if mode == "full":
        assert width is not None and height is not None
        pivot = validate_pivot_length_mm(pivot_length_mm)
        return _measure_full(target, summary, width, height,
                             pivot_length_mm=pivot)
    return _measure_motion(target, summary)


def live_status_line(mode: str, run_id: str, outcome: dict[str, Any],
                     n_written: int) -> str:
    """One honest status line for a live run (relative dir only)."""
    status = outcome.get("status")
    if mode == "full":
        quantity = outcome.get("identifiable_quantity") or {}
        name = quantity.get("name")
        value = quantity.get("value")
        unit = quantity.get("unit")
        measurement = "value null" if value is None else \
            f"{name} = {value!r} {unit}"
    else:
        value = outcome.get("g_over_l_per_s2")
        measurement = "value null" if value is None else \
            f"g/L_eff = {value!r} 1/s^2"
    return (f"live {mode} run {run_id}: {status} — {measurement} "
            f"({n_written} files in {run_id}/)")


def run_live_chain(clip: str | Path, mode: str,
                   prompts: dict[str, str], card_width_mm: Any,
                   run_dir: str | Path, api_key: str,
                   transport: Callable[[dict[str, Any]],
                                       dict[str, Any]] | None = None,
                   pivot_length_mm: Any = None,
                   card_height_mm: Any = None) -> dict[str, Any]:
    """One-shot live chain: detect then measure (the CLI composition).

    ``run_dir`` must already be the run's directory (callers mint the id
    with :func:`new_run_id`). Returns the measure output plus ``run_id``,
    ``summary``, and ``clip_sha256``. ``pivot_length_mm`` (KL-10.17)
    forwards to :func:`run_measure` so recorded runs carry the length
    identically to served runs.
    """
    target = Path(run_dir)
    validate_run_id(target.name)
    detected = run_detect(clip, target, mode, prompts, api_key,
                          transport=transport)
    measured = run_measure(target, card_width_mm,
                           pivot_length_mm=pivot_length_mm,
                           card_height_mm=card_height_mm)
    return {**measured, "run_id": detected["run_id"],
            "summary": detected["summary"],
            "clip_sha256": detected["clip_sha256"]}
