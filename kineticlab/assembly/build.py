"""End-to-end offline result assembly (KL-7.1).

``assemble`` joins the frozen stages through their public surfaces
only: ingest (media + source-PTS table), observation (both live raw
files), geometry pins (calibration record + arc pivot, validated on
load), fit (M1 always; M2 by rule), and result (validated
``result.v1`` with canonical JSON + CSV exports).

Fit-default rationale (KL-4.2 style — bounds are search windows,
not claims): amplitude [0, 2] rad and omega [0.5, 8.0] rad/s are
the estimator's own tested defaults, wide for the observed ~0.29
rad / ~5.5 rad/s (omega spans periods 0.79 s–12.6 s, bracketing
what an ~8 s clip can resolve); grid/budget 200 match the verified
KL-5.2 behavior; gamma [0, 1.0]/s allows undamped at the edge while
1.0/s (63% decay per second) sits far above plausible pendulum
damping. Nothing here is tuned to the data.

Model-selection rule (pre-registered, no selection claim): the
reported fit is ALWAYS M1 (parsimony — one g/L number, no
model shopping). M2 runs as a diagnostic cross-check and is marked
included iff it converges with gamma strictly inside its bounds;
its omega/gamma/g_over_l ride the diagnostics either way with the
justification stated. No AIC/BIC-style verdict exists anywhere —
KL-5.4's no-unsupported-statistics rule binds this module too.

Angle zero: image +y about the arc-fit pivot (the fitter's own
convention); the M1 phase absorbs any fixed offset, so no
upright-camera assumption is needed. Scale enters ONLY the
descriptive pivot-radius-mm readout (with the U-3 bound stated);
angles are scale-free ratios. Gravity stays null (U-2): the
arc radius is same-data derived, flagged
``independent_length: false``, and can never feed a gravity path.

States: success_with_warnings for the identified chain
(uncertainty warning always present — plain success is
structurally unreachable while no uncertainty is estimated);
insufficient_data for
starved input (< 3 fittable points, ``E_OUT_OF_RANGE``) or
non-converged M1 (``E_INCOHERENT_VALUE`` + termination detail,
non-converged fit.v1 embedded for audit). Upstream critical
failures (KL-7.2) route to rejection states per
``REJECTION_STATE`` with all sections retained.

Severity follows the taxonomy's own fatal/non-fatal split
(``RejectReason`` is fatal, ``Warning`` is not): every ``E_*``
code is critical (its stage's result rejects), every ``W_*``
code is non-critical (carried verbatim inside the embedded
records, never a rejection). Routing principle:
``unsupported_input`` = the artifact is outside the stage's
accepted language (shape/vocabulary failures — the stage
cannot read it as the thing it claims to be);
``processing_error`` = a readable artifact failed during
processing (contradictions, references, order, state).
``insufficient_data`` is NOT a routing target: it stays
assembly's own verified scarcity verdict (KL-7.1), never an
upstream mapping. First collected code selects the state
(deterministic; the full list is preserved in
reject_reasons, stage-prefixed). Assembly-owned input gates
(KL-7.5): card usability at both seams (observation stage),
``n_usable_frames`` int/0..frame_count (geometry stage), and
strictly increasing valid PTS in source order via
``build_fit_points`` (observation stage) — never sorted.

Retention rule: rejection results keep warnings (the KL-7.1
verdict rule, unchanged), a failure-context assumption,
null-valued identifiable quantity, provenance, export refs
with written files, and every validated record collected
before the failure (partial counts stay explicit, unknown
stays null). Upstream warnings are retained verbatim in the
embedded records; they are never hoisted to the top-level
list (KL-7.1 success pin preserved byte-identically).

Still raised, never states (no honest result is
constructible): malformed requests (no ``out_dir`` known),
malformed ``assemble_parts`` inputs (caller errors), the
clip's direct byte read (raw ``OSError`` carries no
registered code, so none is forced), and
``ResultContract.from_dict`` failures inside ``_finish``
(assembly bugs, must stay loud).
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from kineticlab import __version__
from kineticlab.assembly.angles import angle_series, build_fit_points
from kineticlab.assembly.export import write_assembly_exports
from kineticlab.assembly.summary import (
    ARTIFACT_HASH_KEYS,
    HASHED_FILES,
    SUMMARY_FILENAME,
    render_summary_md,
)
from kineticlab.contracts import (
    CalibrationRecord,
    ContractError,
    FieldError,
    ResultContract,
)
from kineticlab.fit.m1 import fit_m1
from kineticlab.fit.m2 import fit_m2
from kineticlab.ingest import extract_frame_records, inspect_media
from kineticlab.observation import parse_raw_fixture

AMP_BOUNDS = (0.0, 2.0)
OMEGA_BOUNDS = (0.5, 8.0)
GRID_N_OMEGA = 200
MAX_REFINE = 200
GAMMA_BOUNDS = (0.0, 1.0)
GRID_N_GAMMA = 50
MIN_FIT_POINTS = 3

REQUEST_KEYS = frozenset({
    "clip_path",
    "raw_bob_path",
    "raw_card_path",
    "calibration_path",
    "geometry_report_path",
    "out_dir",
})

_HEX_DIGITS = frozenset("0123456789abcdef")


def _sha_or_none(path: Any) -> str | None:
    """SHA-256 hex of a file's bytes, or None when unreadable."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None

REJECTION_STATE = {
    # Shape/vocabulary failures: the artifact is outside the
    # stage's accepted language -> unsupported_input.
    "E_MALFORMED_JSON": "unsupported_input",
    "E_BAD_SCHEMA": "unsupported_input",
    "E_NOT_AN_OBJECT": "unsupported_input",
    "E_BAD_VERSION": "unsupported_input",
    "E_MISSING_FIELD": "unsupported_input",
    "E_UNEXPECTED_FIELD": "unsupported_input",
    "E_NULL_NOT_ALLOWED": "unsupported_input",
    "E_WRONG_TYPE": "unsupported_input",
    "E_BAD_ENUM": "unsupported_input",
    "E_EMPTY_STRING": "unsupported_input",
    "E_NON_FINITE": "unsupported_input",
    "E_OUT_OF_RANGE": "unsupported_input",
    "E_BAD_SHA256": "unsupported_input",
    "E_BAD_TIME_BASE": "unsupported_input",
    "E_BBOX_ORDER": "unsupported_input",
    "E_CENTROID_PAIR": "unsupported_input",
    "E_CORNERS_SHAPE": "unsupported_input",
    "E_TRANSFORM_SHAPE": "unsupported_input",
    "E_PARAMETER_MISMATCH": "unsupported_input",
    "E_VALUE_WITHOUT_UNIT": "unsupported_input",
    "E_INTERVAL_WITHOUT_METHOD": "unsupported_input",
    "E_INTERVAL_ORDER": "unsupported_input",
    "E_UNKNOWN_WARNING_CODE": "unsupported_input",
    "E_UNKNOWN_REASON_CODE": "unsupported_input",
    # Processing failures: a readable artifact failed during
    # processing (contradiction, reference, order, state).
    "E_INCOHERENT_VALUE": "processing_error",
    "E_MISSING_MAPPING": "processing_error",
    "E_NON_MONOTONIC_PTS": "processing_error",
    "E_DUPLICATE_FRAME": "processing_error",
    "E_UNCONFIRMED_DIMENSIONS": "processing_error",
    "E_SCALE_AMBIGUOUS": "processing_error",
    "E_GRAVITY_WITHOUT_LENGTH": "processing_error",
    "E_INCOHERENT_STATE": "processing_error",
}
"""Critical-error routing: every locked ``E_*`` code -> rejection state.

Covers exactly ``kineticlab.contracts.ERROR_CODES`` (asserted in
tests); ``insufficient_data`` is deliberately absent — it stays
assembly's own scarcity verdict, never an upstream routing.
"""

NON_CRITICAL_WARNINGS = frozenset({
    "W_VFR_TIMING",
    "W_MISSING_FRAMES_RETAINED",
    "W_LOW_CONFIDENCE",
    "W_PARTIAL_OBSERVATION",
    "W_ASSUMPTION_UNVERIFIED",
    "W_SHORT_TRACK",
    "W_UNCERTAINTY_UNAVAILABLE",
    "W_APPROXIMATE_GROUND_TRUTH",
    "W_DERIVED_COPY",
})
"""Warning codes are never critical: carried verbatim, never reject.

Covers exactly ``kineticlab.contracts.WARNING_CODES`` (asserted
in tests). Upstream warnings ride the embedded records; the
top-level warnings list keeps the KL-7.1 verdict rule.
"""

BOB_OBJECT_ID = "live-ball"
CARD_OBJECT_ID = "live-card"
"""Caller-declared track ids for this chain (documented, fixed)."""


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _display(path: Path) -> str:
    absolute = path if path.is_absolute() else Path.cwd() / path
    try:
        return absolute.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def _read_request(request: Any) -> dict[str, Path]:
    if not isinstance(request, dict):
        _fail("E_WRONG_TYPE", None,
              f"expected a request object, got {type(request).__name__}")
        raise AssertionError("unreachable")
    for key in sorted(set(request) - REQUEST_KEYS):
        _fail("E_UNEXPECTED_FIELD", key, f"unknown key {key!r}")
    for key in sorted(REQUEST_KEYS - set(request)):
        _fail("E_MISSING_FIELD", key, f"required key {key!r} is absent")
    paths: dict[str, Path] = {}
    for key in sorted(REQUEST_KEYS):
        value = request.get(key)
        if not isinstance(value, str) or not value:
            _fail("E_WRONG_TYPE" if not isinstance(value, str)
                  else "E_EMPTY_STRING", key,
                  "path must be a non-empty string")
        else:
            paths[key] = Path(value)
    if not paths:
        raise AssertionError("unreachable")
    return paths


def _load_json(path: Path, field: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("E_MALFORMED_JSON", field,
              f"{_display(path)} is unreadable as JSON: {error}")
        raise AssertionError("unreachable")


def _read_pin(path: Path, field: str) -> dict[str, Any]:
    record = _load_json(path, field)
    if not isinstance(record, dict):
        _fail("E_NOT_AN_OBJECT", field,
              f"{_display(path)} must hold a JSON object")
        raise AssertionError("unreachable")
    return record


def _pivot_from_report(report: dict[str, Any],
                       display: str) -> tuple[float, float, float]:
    arc = report.get("pivot_arc")
    if not isinstance(arc, dict) or arc.get("fitted") is not True:
        _fail("E_INCOHERENT_VALUE", "geometry_report_path",
              f"{display}: pin carries no fitted arc pivot")
        raise AssertionError("unreachable")
    center = arc.get("center_px")
    radius = arc.get("radius_px")
    if (not isinstance(center, (list, tuple)) or len(center) != 2
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in center)
            or isinstance(radius, bool)
            or not isinstance(radius, (int, float))
            or not math.isfinite(radius) or radius <= 0.0):
        _fail("E_INCOHERENT_VALUE", "geometry_report_path",
              f"{display}: arc pivot is not finite/physical")
        raise AssertionError("unreachable")
    assert isinstance(center, (list, tuple))
    return float(center[0]), float(center[1]), float(radius)


def m2_section(m2: dict[str, Any]) -> dict[str, Any]:
    """Apply the M2 include/skip rule to a fit_m2 output (see module docstring)."""
    diagnostics = m2["diagnostics"]
    fitted = diagnostics.get("fitted") or {}
    gamma = fitted.get("gamma_per_s")
    converged = diagnostics.get("converged") is True
    interior = (isinstance(gamma, (int, float))
                and not isinstance(gamma, bool)
                and math.isfinite(gamma)
                and GAMMA_BOUNDS[0] < gamma < GAMMA_BOUNDS[1])
    included = converged and interior
    if included:
        justification = (
            f"included: converged ({diagnostics.get('termination_reason')}) "
            f"with gamma {gamma} strictly inside {list(GAMMA_BOUNDS)}; "
            "omega cross-checks M1; diagnostic only, M1 stays reported")
    elif not converged:
        justification = (
            f"excluded: M2 did not converge "
            f"({diagnostics.get('termination_reason')}); M1 reported")
    else:
        justification = (
            f"excluded: gamma {gamma} at/outside bounds "
            f"{list(GAMMA_BOUNDS)} (no interior damping identified); "
            "M1 reported")
    return {
        "included": included,
        "justification": justification,
        "converged": converged,
        "termination_reason": diagnostics.get("termination_reason"),
        "fitted": fitted,
        "bound_hits": diagnostics.get("bound_hits"),
        "g_over_l_per_s2": m2["fit"].get("g_over_l_per_s2"),
        "warnings": m2["fit"].get("warnings"),
    }


def _upstream_rejection(*, stage: str, error: ContractError,
                        table: Any = None, bob: Any = None,
                        card: Any = None,
                        calibration_dict: dict[str, Any] | None = None,
                        report_pin: dict[str, Any] | None = None,
                        pivot: tuple[float, float, float] | None = None,
                        series: list[dict[str, Any]] | None = None,
                        n_fit_points: int = 0,
                        excluded_frames: Any = (),
                        clip_sha256: str, out_dir: Any,
                        raw_bob_display: str, raw_card_display: str,
                        geometry_report_display: str | None = None,
                        artifact_hashes: dict[str, Any],
                        ) -> dict[str, Any]:
    """Build the rejection result for an upstream critical failure.

    ``calibration_dict`` must already be validated (only validated
    records are embedded); ``report_pin`` may be any loaded JSON
    object (only a guarded integer is read from it). Every
    collected error becomes a stage-prefixed reject reason; the
    first collected code selects the state via
    ``REJECTION_STATE``. Exports are written through ``_finish``
    exactly like every other path.
    """
    codes = error.codes
    state = REJECTION_STATE[codes[0]]
    reasons = [{
        "code": item.code,
        "field": f"{stage}.{item.field}" if item.field else stage,
        "detail": item.message,
    } for item in error.errors]
    seen: list[str] = []
    for code in codes:
        if code not in seen:
            seen.append(code)
    table_rows = list(table) if table is not None else None
    bob_rows = list(bob) if bob is not None else []
    card_rows = list(card) if card is not None else []
    observed = (bob_rows + card_rows
                if bob is not None or card is not None else None)
    calibration_section = report_pin.get("calibration") \
        if isinstance(report_pin, dict) else None
    calibrated_frames = calibration_section.get("n_usable_frames") \
        if isinstance(calibration_section, dict) else None
    if (not isinstance(calibrated_frames, int)
            or isinstance(calibrated_frames, bool)
            or calibrated_frames < 0):
        calibrated_frames = None
    usable_rows = (sum(1 for row in table_rows
                       if row.valid and row.pts_seconds is not None)
                   if table_rows is not None else None)
    if calibrated_frames is not None and usable_rows is not None \
            and calibrated_frames > usable_rows:
        # Failure-context guard: a report count above usable rows
        # cannot ride the metrics (contract bounds); the failure
        # section carries the true story. Success-path counts are
        # validated by the F4 gate instead of being normalized.
        calibrated_frames = None
    metrics = {
        "frames_total": len(table_rows) if table_rows is not None else None,
        "frames_usable": usable_rows,
        "observations_total": len(observed) if observed is not None else None,
        "observations_valid": (sum(1 for record in observed if record.valid)
                               if observed is not None else None),
        "calibrated_frames": calibrated_frames}
    scale = calibration_dict.get("scale_mm_per_px") \
        if calibration_dict is not None else None
    diagnostics: dict[str, Any] = {
        "n_table_frames": metrics["frames_total"],
        "n_bob_records": len(bob_rows) if bob is not None else None,
        "n_card_records": len(card_rows) if card is not None else None,
        "n_fit_points": n_fit_points,
        "excluded_frames": list(excluded_frames),
        "pivot_px": [pivot[0], pivot[1]] if pivot is not None else None,
        "pivot_source": geometry_report_display if pivot is not None else None,
        "calibration_valid": True if calibration_dict is not None else None,
        "radius": ({
            "radius_px": pivot[2],
            "scale_mm_per_px": scale,
            "radius_mm": (pivot[2] * scale
                          if isinstance(scale, (int, float)) else None),
            "u3_bound": "U-3 depth-offset scale bound stated "
                        "wherever scale is used",
            "independent_length": False,
            "descriptive_only": True,
        } if pivot is not None else None),
        "m1": None,
        "m2": None,
        "failure": {
            "stage": stage,
            "state": state,
            "codes": codes,
            "errors": [{"code": item.code, "field": item.field,
                        "message": item.message}
                       for item in error.errors],
        },
    }
    result_dict: dict[str, Any] = {
        "schema_version": "result.v1",
        "status": state,
        "measurement_name": "pendulum_g_over_l",
        "value": None,
        "unit": None,
        "interval": None,
        "interval_method": None,
        "identifiable_quantity": {"name": "g/L_eff", "value": None,
                                  "unit": "1/s^2"},
        "calibration": calibration_dict,
        "fit": None,
        "quality_metrics": metrics,
        "assumptions": [
            f"Rejected at the {stage} stage ({', '.join(seen)}); "
            "retained sections carry partial context collected "
            "before the failure, not a measurement.",
        ],
        "warnings": [{
            "code": "W_UNCERTAINTY_UNAVAILABLE",
            "detail": "KL-7.1 estimates no uncertainty; method is none.",
        }],
        "reject_reasons": reasons,
        "provenance": {
            "software_name": "kineticlab",
            "software_version": __version__,
            "input_sha256": clip_sha256,
            "model_name": "sam-3.1",
            "model_version": None,
            "raw_refs": [raw_bob_display, raw_card_display],
            "artifact_hashes": artifact_hashes,
        },
        "exports": [],
    }
    out_path = out_dir if isinstance(out_dir, Path) else Path(str(out_dir))
    return _finish(result_dict, diagnostics, series or [], out_path)


def assemble(request: Any, _parsed: dict[str, Any] | None = None
             ) -> dict[str, Any]:
    """Assemble the end-to-end offline result (see module docstring).

    Returns ``{"result", "diagnostics", "angle_series",
    "export_refs"}`` with ``result`` a validated ``result.v1`` dict
    (success_with_warnings, insufficient_data, unsupported_input,
    or processing_error). Writes result.json + diagnostics.json +
    angles.csv under ``out_dir`` on every path and re-validates
    the result with its export refs attached. Upstream
    ``ContractError`` failures become rejection states; malformed
    requests still raise, and the clip's direct byte read still
    propagates raw ``OSError``.

    ``_parsed`` (KL-9.2 item 4) optionally carries already-parsed
    ``{"bob": [...], "card": [...]}`` observation records for the
    request's exact raw bytes, skipping assemble's own re-parse
    (range-decode + canonical check per mask — the dominant
    measure cost). Valid only when the caller proves the bytes
    are the parsed ones (chain proves it via the parse-check SHA
    pins or a fresh parse); outputs are then identical, field
    for field, to parsing again. All other callers omit it.
    """
    paths = _read_request(request)
    clip_bytes = paths["clip_path"].read_bytes()
    clip_sha = hashlib.sha256(clip_bytes).hexdigest()
    displays = {key: _display(path) for key, path in paths.items()
                if key != "out_dir"}
    out_path = paths["out_dir"]
    # F6: identities of the attempted inputs, hashed before any
    # stage runs (unreadable artifacts hash to None, never guessed).
    artifact_hashes = {
        "raw_bob_sha256": _sha_or_none(paths["raw_bob_path"]),
        "raw_card_sha256": _sha_or_none(paths["raw_card_path"]),
        "calibration_sha256": _sha_or_none(paths["calibration_path"]),
        "geometry_report_sha256": _sha_or_none(
            paths["geometry_report_path"]),
    }
    try:
        inspect_media(str(paths["clip_path"]))
        table = extract_frame_records(str(paths["clip_path"]))
    except ContractError as error:
        return _upstream_rejection(
            stage="ingest", error=error, clip_sha256=clip_sha,
            out_dir=out_path, raw_bob_display=displays["raw_bob_path"],
            raw_card_display=displays["raw_card_path"],
            artifact_hashes=artifact_hashes)
    if _parsed is not None:
        bob = _parsed["bob"]
    else:
        try:
            bob = parse_raw_fixture(
                str(paths["raw_bob_path"]), object_role="bob",
                object_id=BOB_OBJECT_ID, frame_table=table,
                model_name="sam-3.1")
        except ContractError as error:
            return _upstream_rejection(
                stage="observation", error=error, table=table,
                clip_sha256=clip_sha, out_dir=out_path,
                raw_bob_display=displays["raw_bob_path"],
                raw_card_display=displays["raw_card_path"],
                artifact_hashes=artifact_hashes)
    if _parsed is not None:
        card = _parsed["card"]
    else:
        try:
            card = parse_raw_fixture(
                str(paths["raw_card_path"]),
                object_role="reference_card",
                object_id=CARD_OBJECT_ID, frame_table=table,
                model_name="sam-3.1")
        except ContractError as error:
            return _upstream_rejection(
                stage="observation", error=error, table=table, bob=bob,
                clip_sha256=clip_sha, out_dir=out_path,
                raw_bob_display=displays["raw_bob_path"],
                raw_card_display=displays["raw_card_path"],
                artifact_hashes=artifact_hashes)
    if not card or not any(record.valid for record in card):
        # F4: the reference card is evidence, not decoration — a
        # chain without one usable card observation rejects here,
        # before any geometry or fit runs.
        return _upstream_rejection(
            stage="observation",
            error=ContractError([FieldError(
                "E_OUT_OF_RANGE", "reference_card",
                "reference-card parts contain no usable "
                "observations")]),
            table=table, bob=bob, card=card,
            clip_sha256=clip_sha, out_dir=out_path,
            raw_bob_display=displays["raw_bob_path"],
            raw_card_display=displays["raw_card_path"],
            geometry_report_display=displays["geometry_report_path"],
            artifact_hashes=artifact_hashes)
    try:
        calibration_dict = _read_pin(paths["calibration_path"],
                                     "calibration")
    except ContractError as error:
        return _upstream_rejection(
            stage="geometry", error=error, table=table, bob=bob,
            card=card, clip_sha256=clip_sha, out_dir=out_path,
            raw_bob_display=displays["raw_bob_path"],
            raw_card_display=displays["raw_card_path"],
            geometry_report_display=displays["geometry_report_path"],
            artifact_hashes=artifact_hashes)
    try:
        report_pin = _read_pin(paths["geometry_report_path"],
                               "geometry_report")
    except ContractError as error:
        try:
            CalibrationRecord.from_dict(calibration_dict)
        except ContractError:
            valid_calibration = None
        else:
            valid_calibration = calibration_dict
        return _upstream_rejection(
            stage="geometry", error=error, table=table, bob=bob,
            card=card, calibration_dict=valid_calibration,
            clip_sha256=clip_sha, out_dir=out_path,
            raw_bob_display=displays["raw_bob_path"],
            raw_card_display=displays["raw_card_path"],
            geometry_report_display=displays["geometry_report_path"],
            artifact_hashes=artifact_hashes)
    return assemble_parts(
        bob=bob, card=card, frame_table=table,
        calibration_dict=calibration_dict, report_pin=report_pin,
        clip_sha256=clip_sha, out_dir=paths["out_dir"],
        raw_bob_display=displays["raw_bob_path"],
        raw_card_display=displays["raw_card_path"],
        geometry_report_display=displays["geometry_report_path"],
        artifact_hashes=artifact_hashes)


def assemble_parts(*, bob: Any, card: Any, frame_table: Any,
                   calibration_dict: Any, report_pin: Any,
                   clip_sha256: Any, out_dir: Any,
                   raw_bob_display: str, raw_card_display: str,
                   geometry_report_display: str,
                   artifact_hashes: dict[str, Any]) -> dict[str, Any]:
    """Join loaded parts into the validated result (testable seam).

    Same contract as ``assemble`` minus file loading: records/table
    arrive parsed, pins arrive as dicts, ``clip_sha256``/display
    paths arrive computed. ``artifact_hashes`` is the four-key
    digest object landing in provenance ``artifact_hashes``
    unchanged (validated strictly: each value null or 64-char
    lowercase hex). Powers the rejection-state tests with
    synthetic parts (labeled in-test, never pinned as evidence).
    """
    if not isinstance(bob, (list, tuple)) \
            or not isinstance(card, (list, tuple)) \
            or not isinstance(frame_table, (list, tuple)):
        _fail("E_WRONG_TYPE", "parts",
              "bob/card/frame_table must be record lists")
    if not isinstance(calibration_dict, dict) \
            or not isinstance(report_pin, dict):
        _fail("E_WRONG_TYPE", "parts",
              "calibration/report pins must be objects")
    if not isinstance(clip_sha256, str) \
            or len(clip_sha256) != 64:
        _fail("E_BAD_SHA256", "clip_sha256",
              "clip hash must be 64 hex characters")
    # F6: the seam takes digests as data, never computes them —
    # strict shape, nulls allowed, hex enforced here too.
    if not isinstance(artifact_hashes, dict) or set(
            artifact_hashes) != set(ARTIFACT_HASH_KEYS):
        raise TypeError("artifact_hashes must be a dict with exactly "
                        "the keys " + ", ".join(ARTIFACT_HASH_KEYS))
    for _key in ARTIFACT_HASH_KEYS:
        _value = artifact_hashes[_key]
        if _value is not None and (
                not isinstance(_value, str) or len(_value) != 64
                or any(char not in _HEX_DIGITS for char in _value)):
            raise TypeError(
                f"artifact_hashes[{_key!r}] must be null or "
                "64-char lowercase hex")
    out_path = out_dir if isinstance(out_dir, Path) else Path(str(out_dir))
    if not card or not any(record.valid for record in card):
        # F4 parts seam: same gate as the file seam — pipeline
        # order puts observation evidence before geometry, so the
        # calibration is not yet validated (and not embedded).
        return _upstream_rejection(
            stage="observation",
            error=ContractError([FieldError(
                "E_OUT_OF_RANGE", "reference_card",
                "reference-card parts contain no usable "
                "observations")]),
            table=frame_table, bob=bob, card=card,
            report_pin=report_pin, clip_sha256=clip_sha256,
            out_dir=out_path, raw_bob_display=raw_bob_display,
            raw_card_display=raw_card_display,
            geometry_report_display=geometry_report_display,
            artifact_hashes=artifact_hashes)
    try:
        calibration = CalibrationRecord.from_dict(calibration_dict)
    except ContractError as error:
        return _upstream_rejection(
            stage="geometry", error=error, table=frame_table,
            bob=bob, card=card, report_pin=report_pin,
            clip_sha256=clip_sha256, out_dir=out_path,
            raw_bob_display=raw_bob_display,
            raw_card_display=raw_card_display,
            geometry_report_display=geometry_report_display,
            artifact_hashes=artifact_hashes)
    try:
        pivot_x, pivot_y, radius_px = _pivot_from_report(
            report_pin, geometry_report_display)
    except ContractError as error:
        return _upstream_rejection(
            stage="geometry", error=error, table=frame_table,
            bob=bob, card=card, calibration_dict=calibration_dict,
            report_pin=report_pin, clip_sha256=clip_sha256,
            out_dir=out_path, raw_bob_display=raw_bob_display,
            raw_card_display=raw_card_display,
            geometry_report_display=geometry_report_display,
            artifact_hashes=artifact_hashes)
    # F4: the geometry count is validated before any fit-point
    # construction — int, not bool, inside 0..frame_count.
    calibration_section = report_pin.get("calibration")
    n_usable = calibration_section.get("n_usable_frames") \
        if isinstance(calibration_section, dict) else None
    if (not isinstance(n_usable, int) or isinstance(n_usable, bool)
            or not 0 <= n_usable <= len(frame_table)):
        return _upstream_rejection(
            stage="geometry",
            error=ContractError([FieldError(
                "E_INCOHERENT_VALUE", "geometry_report.n_usable_frames",
                "calibration.n_usable_frames must be an int in "
                f"0..{len(frame_table)}, got {n_usable!r}")]),
            table=frame_table, bob=bob, card=card,
            calibration_dict=calibration_dict, report_pin=report_pin,
            pivot=(pivot_x, pivot_y, radius_px),
            clip_sha256=clip_sha256, out_dir=out_path,
            raw_bob_display=raw_bob_display,
            raw_card_display=raw_card_display,
            geometry_report_display=geometry_report_display,
            artifact_hashes=artifact_hashes)
    # F3 gate: non-monotonic valid PTS rejects (observation
    # stage) instead of fitting scrambled time. Pivot and
    # calibration are already validated, so they are retained.
    try:
        fitted = build_fit_points(bob)
        points = fitted["points"]
        series = angle_series(points, pivot_x, pivot_y)
    except ContractError as error:
        return _upstream_rejection(
            stage="observation", error=error, table=frame_table,
            bob=bob, card=card, calibration_dict=calibration_dict,
            report_pin=report_pin,
            pivot=(pivot_x, pivot_y, radius_px),
            clip_sha256=clip_sha256, out_dir=out_path,
            raw_bob_display=raw_bob_display,
            raw_card_display=raw_card_display,
            geometry_report_display=geometry_report_display,
            artifact_hashes=artifact_hashes)
    calibration_section = report_pin.get("calibration")
    u3 = calibration_section.get("u3_bound") \
        if isinstance(calibration_section, dict) else None
    bound_text = (u3.get("statement")
                  if isinstance(u3, dict) else None) or (
        "U-3 depth-offset scale bound stated wherever scale is used")
    frame_count = len(frame_table)
    usable_count = sum(1 for row in frame_table
                       if row.valid and row.pts_seconds is not None)
    observations_total = len(bob) + len(card)
    observations_valid = sum(1 for record in list(bob) + list(card)
                             if record.valid)
    calibrated_frames = report_pin.get("calibration", {}).get(
        "n_usable_frames") if isinstance(
            report_pin.get("calibration"), dict) else None
    metrics = {"frames_total": frame_count,
               "frames_usable": usable_count,
               "observations_total": observations_total,
               "observations_valid": observations_valid,
               "calibrated_frames": calibrated_frames}
    assumptions = [
        # KL-9.6 M2: the old text claimed the arbitrary zero is
        # "absorbed by the fit phase" — wrong for a DC offset, which
        # the M1 model (A*cos(wt+phi), no theta_eq term) cannot
        # represent. Stated honestly now, and uncorrected.
        "Angles measured from image +y about the arc-fit pivot; the "
        "zero is arbitrary and absorbed by the fit phase only up to "
        "a constant offset the M1 model does not represent "
        "(A*cos(wt+phi) has no theta_eq term) - stated uncorrected "
        "(no upright-camera assumption).",
        bound_text,
        "M-3e hollow-ball/string-mass bias stated, uncorrected (see "
        "the geometry report model_limitations).",
        "Arc-fit radius is descriptive only, not an independent "
        "length; gravity stays null (U-2 not provided).",
        "M1 is the reported model (pre-registered parsimony); the M2 "
        "outcome rides the diagnostics as a cross-check.",
    ]
    provenance = {"software_name": "kineticlab",
                  "software_version": __version__,
                  "input_sha256": clip_sha256,
                  "model_name": "sam-3.1",
                  "model_version": None,
                  "raw_refs": [raw_bob_display,
                               raw_card_display],
                  "artifact_hashes": artifact_hashes}
    uncertainty_warning = {
        "code": "W_UNCERTAINTY_UNAVAILABLE",
        "detail": "KL-7.1 estimates no uncertainty; method is none.",
    }
    scale = calibration_dict.get("scale_mm_per_px")
    diagnostics_base: dict[str, Any] = {
        "n_table_frames": frame_count,
        "n_bob_records": len(bob),
        "n_card_records": len(card),
        "n_fit_points": len(points),
        "excluded_frames": fitted["excluded_frames"],
        "pivot_px": [pivot_x, pivot_y],
        "pivot_source": geometry_report_display,
        "calibration_valid": calibration.valid,
        "radius": {
            "radius_px": radius_px,
            "scale_mm_per_px": scale,
            "radius_mm": (radius_px * scale
                          if isinstance(scale, (int, float)) else None),
            "u3_bound": bound_text,
            "independent_length": False,
            "descriptive_only": True,
        },
    }
    if len(points) < MIN_FIT_POINTS:
        diagnostics_base["m1"] = None
        diagnostics_base["m2"] = None
        result_dict: dict[str, Any] = {
            "schema_version": "result.v1",
            "status": "insufficient_data",
            "measurement_name": "pendulum_g_over_l",
            "value": None,
            "unit": None,
            "interval": None,
            "interval_method": None,
            "identifiable_quantity": {"name": "g/L_eff", "value": None,
                                      "unit": "1/s^2"},
            "calibration": calibration_dict,
            "fit": None,
            "quality_metrics": metrics,
            "assumptions": assumptions,
            "warnings": [uncertainty_warning],
            "reject_reasons": [{
                "code": "E_OUT_OF_RANGE",
                "field": "points",
                "detail": f"{len(points)} fittable points below the "
                          f"fitter minimum {MIN_FIT_POINTS}",
            }],
            "provenance": provenance,
            "exports": [],
        }
        return _finish(result_dict, diagnostics_base, series, out_path)

    fit_points = [{"t_seconds": point["t_seconds"], "x_px": point["x_px"],
                   "y_px": point["y_px"]} for point in points]
    m1_request = {"points": fit_points, "pivot_x_px": pivot_x,
                  "pivot_y_px": pivot_y,
                  "bounds": {"amplitude_rad": list(AMP_BOUNDS),
                             "omega_per_s": list(OMEGA_BOUNDS)},
                  "grid_n_omega": GRID_N_OMEGA,
                  "max_refine_iterations": MAX_REFINE, "truth": None}
    try:
        m1 = fit_m1(m1_request)
    except ContractError as error:
        return _upstream_rejection(
            stage="fit", error=error, table=frame_table, bob=bob,
            card=card, calibration_dict=calibration_dict,
            report_pin=report_pin,
            pivot=(pivot_x, pivot_y, radius_px), series=series,
            n_fit_points=len(points),
            excluded_frames=fitted["excluded_frames"],
            clip_sha256=clip_sha256, out_dir=out_path,
            raw_bob_display=raw_bob_display,
            raw_card_display=raw_card_display,
            geometry_report_display=geometry_report_display,
            artifact_hashes=artifact_hashes)
    m1_diagnostics = m1["diagnostics"]
    m1_fitted = m1_diagnostics.get("fitted") or {}
    diagnostics_base["m1"] = {
        "converged": m1_diagnostics.get("converged"),
        "termination_reason": m1_diagnostics.get("termination_reason"),
        "fitted": m1_fitted,
        "bound_hits": m1_diagnostics.get("bound_hits"),
        "objectives": m1_diagnostics.get("objectives"),
        "n_points": m1_diagnostics.get("n_points"),
        "residuals": m1_diagnostics.get("residuals"),
    }
    # NOTE (test-convention label): fit_m1's outer
    # "test_convention_note" asserts synthetic inputs, which is false
    # for this real chain — it is dropped here and never stored. The
    # embedded fit.v1 + diagnostics carry no synthetic wording
    # (asserted in tests/test_assembly.py).
    if m1_diagnostics.get("converged") is not True:
        diagnostics_base["m2"] = None
        result_dict = {
            "schema_version": "result.v1",
            "status": "insufficient_data",
            "measurement_name": "pendulum_g_over_l",
            "value": None,
            "unit": None,
            "interval": None,
            "interval_method": None,
            "identifiable_quantity": {"name": "g/L_eff", "value": None,
                                      "unit": "1/s^2"},
            "calibration": calibration_dict,
            "fit": m1["fit"],
            "quality_metrics": metrics,
            "assumptions": assumptions,
            "warnings": [uncertainty_warning],
            "reject_reasons": [{
                "code": "E_INCOHERENT_VALUE",
                "field": "fit",
                "detail": f"M1 did not converge "
                          f"({m1_diagnostics.get('termination_reason')}); "
                          f"g/L unidentifiable from {len(points)} points",
            }],
            "provenance": provenance,
            "exports": [],
        }
        return _finish(result_dict, diagnostics_base, series, out_path)

    m2_request = dict(m1_request)
    m2_request["bounds"] = {"amplitude_rad": list(AMP_BOUNDS),
                            "omega_per_s": list(OMEGA_BOUNDS),
                            "gamma_per_s": list(GAMMA_BOUNDS)}
    m2_request["grid_n_gamma"] = GRID_N_GAMMA
    # M2 errors reject strictly like any upstream critical
    # failure: M2 shares M1's validated request, so a raise here
    # means something is deeply off — never silently dropped.
    try:
        m2 = fit_m2(m2_request)
    except ContractError as error:
        return _upstream_rejection(
            stage="fit", error=error, table=frame_table, bob=bob,
            card=card, calibration_dict=calibration_dict,
            report_pin=report_pin,
            pivot=(pivot_x, pivot_y, radius_px), series=series,
            n_fit_points=len(points),
            excluded_frames=fitted["excluded_frames"],
            clip_sha256=clip_sha256, out_dir=out_path,
            raw_bob_display=raw_bob_display,
            raw_card_display=raw_card_display,
            geometry_report_display=geometry_report_display,
            artifact_hashes=artifact_hashes)
    diagnostics_base["m2"] = m2_section(m2)
    fit_record = m1["fit"]
    g_over_l = fit_record["g_over_l_per_s2"]
    seen_codes = {uncertainty_warning["code"]}
    warnings = [uncertainty_warning]
    dropped_details: list[str] = []
    for warning in fit_record.get("warnings") or []:
        if warning.get("code") in seen_codes:
            dropped_details.append(str(warning))
        else:
            seen_codes.add(warning.get("code"))
            warnings.append(warning)
    diagnostics_base["dropped_fit_warning_details"] = dropped_details
    result_dict = {
        "schema_version": "result.v1",
        "status": "success_with_warnings",
        "measurement_name": "pendulum_g_over_l",
        "value": g_over_l,
        "unit": "1/s^2",
        "interval": None,
        "interval_method": None,
        "identifiable_quantity": {"name": "g/L_eff", "value": g_over_l,
                                  "unit": "1/s^2"},
        "calibration": calibration_dict,
        "fit": fit_record,
        "quality_metrics": metrics,
        "assumptions": assumptions,
        "warnings": warnings,
        "reject_reasons": [],
        "provenance": provenance,
        "exports": [],
    }
    return _finish(result_dict, diagnostics_base, series, out_path)


def _finish(result_dict: dict[str, Any], diagnostics: dict[str, Any],
            series: list[dict[str, Any]],
            out_path: Path) -> dict[str, Any]:
    ResultContract.from_dict(result_dict)
    refs = write_assembly_exports(out_path, result_dict,
                                  diagnostics, series)
    result_dict["exports"] = [
        {"format": "result-json", "path": refs["result_json"]},
        {"format": "diagnostics-json", "path": refs["diagnostics_json"]},
        {"format": "angles-csv", "path": refs["angles_csv"]},
    ]
    ResultContract.from_dict(result_dict)
    write_assembly_exports(out_path, result_dict, diagnostics,
                           series)
    # KL-7.3: the summary is rendered over the FINAL bytes
    # (result.json changed above when the export refs were
    # attached). This step only adds summary.md — the three
    # pinned files are byte-identical with or without it.
    file_hashes = {
        name: hashlib.sha256(
            (out_path / name).read_bytes()).hexdigest()
        for name in HASHED_FILES
    }
    summary_path = out_path / SUMMARY_FILENAME
    summary_path.write_bytes(
        render_summary_md(result_dict, diagnostics,
                          file_hashes).encode("utf-8"))
    refs["summary_md"] = _display(summary_path)
    return {"result": result_dict, "diagnostics": diagnostics,
            "angle_series": series, "export_refs": refs}
