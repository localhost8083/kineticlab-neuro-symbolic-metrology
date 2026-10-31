"""Versioned data contracts (KL-1.1 structures, KL-1.2 validation).

Single home for the six record schemas so parallel stages cannot invent
incompatible structures. JSON is canonical; CSV is export-only. Stdlib only.

CONVENTIONS LOCK (gate fix KL-0-G0 #5):

- Schema versions are exact strings: ``media.v1``, ``frame.v1``,
  ``observation.v1``, ``calibration.v1``, ``fit.v1``, ``result.v1``.
  Any other value is rejected (``E_BAD_VERSION``); new versions arrive
  only by explicit version bump, never by silent field drift.
- All record keys are REQUIRED. Nullability governs values, never key
  presence: a missing key is ``E_MISSING_FIELD`` (missing stays explicit),
  an unknown key is ``E_UNEXPECTED_FIELD``. Unknown values are ``null``.
- Units: time in seconds (float); image plane in pixels (``_px`` suffix);
  physical length in millimeters (``_mm`` suffix); angles in radians;
  gravity in m/s^2; the identifiable ``g/L`` in 1/s^2; confidence in
  0..1. Every numeric field states its unit; none is bare. Unit labels
  are locked: ``UNIT_VOCABULARY`` for fit parameters (plus forced
  bindings in ``KNOWN_PARAMETER_UNITS``), ``RESULT_UNITS``
  (``1/s^2``/``m/s^2``) for result and identifiable-quantity units,
  ``KNOWN_QUANTITY_UNITS`` for exact quantity names (``g/L_eff``,
  ``gravity``) and their forced units, and ``INTERVAL_METHODS`` for
  interval methods. Dimensionally false or out-of-vocabulary labels
  are rejected, and an interval must contain the reported value.
- Image coordinates: origin at the top-left pixel, +x right, +y down
  (OpenCV decoded-frame convention; the locked stack decodes with
  OpenCV/FFmpeg). Bounding boxes are
  ``[x_min, y_min, x_max, y_max]`` in float pixels with
  ``x_max > x_min`` and ``y_max > y_min``.
- Frame indexes are zero-based integers. ``frame_index`` is the
  processing/decode-order index; ``source_frame_index`` is the index in
  the source container. ``pts_seconds`` is actual source presentation
  time in seconds, never a nominal-FPS synthesis; finite negative
  values (media edit/preroll) are preserved, only non-finite values
  are rejected. A usable frame table has strictly increasing PTS.
- Validity: ``valid`` is an explicit boolean, never inferred. ``valid``
  records must carry their complete mapping (frame), source PTS plus
  confidence plus centroid (observation), explicit assumptions plus
  one scale form (calibration), and known identity plus structure
  (media).
- Cross-field identity: ``g_over_l_per_s2`` echoes
  ``parameters['g_over_l']`` exactly when present; gravity must equal
  ``g_over_l_per_s2 * pivot_length_mm / 1000`` within the documented
  tolerance; residual ``rmse`` cannot exceed ``max_abs``; quality
  counts obey part/whole bounds (nulls skip); dimensions are present
  iff their source is ``user_confirmed``.
- Result support: exact measurement names bind to exact quantities and
  units. The identifiable quantity agrees with the value and unit exactly,
  and success states require a present, converged, positive-observation fit
  whose matching summary and underlying ``g_over_l`` parameter equal the
  value. Failure states keep their rules (reasons required, no value or
  interval).
- Fit models: M1 uses exactly ``g_over_l``; M2 uses exactly ``g_over_l``
  and ``gamma``. Initial conditions remain separate state fields.
- Warnings are non-fatal ``{code, detail}`` entries with ``W_*`` codes;
  rejections are ``{code, field, detail}`` entries with ``E_*`` codes.
  Unknown codes are rejected: typos must fail loudly.
- Provenance is a ``{software_name, software_version, input_sha256,
  model_name, model_version, raw_refs}`` object. It is required on the
  result contract and nullable elsewhere (``null`` only when genuinely
  unknown, never as a default for known facts).
- Validation enforces structure, locked vocabularies, dimensional
  consistency, cross-field arithmetic identity, and provenance rules
  (such as gravity needing an independent length). Physical
  plausibility (signs, magnitudes, model adequacy) belongs to the
  pipeline stages, not to schema parsing.

Trust boundaries (KL-1.2): every ``from_dict``/``parse_*`` entry point
is strict, collects ALL field errors before raising ``ContractError``,
copies all input containers (caller mutation cannot corrupt records),
and rejects non-finite floats (JSON-canonical output cannot hold them).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ResultState(str, Enum):
    """Exact machine-readable result states (master plan section 4.3)."""

    SUCCESS = "success"
    SUCCESS_WITH_WARNINGS = "success_with_warnings"
    INSUFFICIENT_DATA = "insufficient_data"
    UNSUPPORTED_INPUT = "unsupported_input"
    PROCESSING_ERROR = "processing_error"


class ObjectRole(str, Enum):
    BOB = "bob"
    REFERENCE_CARD = "reference_card"


class ObservationSource(str, Enum):
    SAM_FIXTURE = "sam_fixture"
    SAM_LIVE = "sam_live"
    MANUAL = "manual"
    SYNTHETIC = "synthetic"


class ReferenceType(str, Enum):
    """Card identity. Only user-confirmed ID-1 unlocks standard dimensions."""

    ISO_ID1_CONFIRMED = "iso_id1_confirmed"
    UNKNOWN = "unknown"


class DimensionSource(str, Enum):
    USER_CONFIRMED = "user_confirmed"
    NOT_PROVIDED = "not_provided"


class ModelId(str, Enum):
    M1 = "M1"
    M2 = "M2"


class UncertaintyMethod(str, Enum):
    NONE = "none"
    ANALYTIC_LINEARIZED = "analytic_linearized"
    BLOCK_BOOTSTRAP = "block_bootstrap"


class LengthSource(str, Enum):
    INDEPENDENT_MEASUREMENT = "independent_measurement"
    NOT_PROVIDED = "not_provided"


UNIT_VOCABULARY = frozenset({"1/s^2", "m/s^2", "1/s", "rad", "rad/s", "s", "mm", "px"})
"""Locked unit labels. ``1/s`` covers the M2 damping rate ``gamma``."""

KNOWN_PARAMETER_UNITS = {
    "g_over_l": "1/s^2",
    "gamma": "1/s",
    "theta0": "rad",
    "omega0": "rad/s",
}
"""Dimensionally forced bindings for known M1/M2 parameter names."""

MODEL_PARAMETER_NAMES = {
    ModelId.M1: frozenset({"g_over_l"}),
    ModelId.M2: frozenset({"g_over_l", "gamma"}),
}
"""Exact fitted parameter sets; initial conditions are separate fields."""

MEASUREMENT_QUANTITIES = {
    "pendulum_g_over_l": "g/L_eff",
    "pendulum_gravity": "gravity",
}
"""Exact result measurement identities and their quantity names."""

MEASUREMENT_UNITS = {
    "pendulum_g_over_l": "1/s^2",
    "pendulum_gravity": "m/s^2",
}
"""Exact result measurement identities and their locked units."""

RESULT_UNITS = frozenset({"1/s^2", "m/s^2"})
"""v1 results report either ``g/L`` or gravity; nothing else."""

KNOWN_QUANTITY_UNITS = {"g/L_eff": "1/s^2", "gravity": "m/s^2"}
"""Exact accepted identifiable-quantity names and their forced units."""

INTERVAL_METHODS = frozenset({"analytic_linearized", "block_bootstrap"})
"""Locked uncertainty methods that can produce an interval."""

GRAVITY_REL_TOL = 1e-9
GRAVITY_ABS_TOL = 1e-12
"""Documented tolerance for the gravity derivation identity.

``gravity_m_s2`` must equal ``g_over_l_per_s2 * pivot_length_mm / 1000``
within ``math.isclose`` under these tolerances. The band covers decimal
serialization round-trips, not measurement uncertainty.
"""


MEDIA_VERSION = "media.v1"
FRAME_VERSION = "frame.v1"
OBSERVATION_VERSION = "observation.v1"
CALIBRATION_VERSION = "calibration.v1"
FIT_VERSION = "fit.v1"
RESULT_VERSION = "result.v1"

WARNING_CODES = {
    "W_VFR_TIMING": "frame timing is non-uniform; no nominal frame rate applies",
    "W_MISSING_FRAMES_RETAINED": "frames without usable data are retained as invalid records",
    "W_LOW_CONFIDENCE": "observation confidence below the stage threshold but retained",
    "W_PARTIAL_OBSERVATION": "observation lacks optional geometric detail (box, area, or mask)",
    "W_ASSUMPTION_UNVERIFIED": "a required assumption is stated but not independently verified",
    "W_SHORT_TRACK": "usable observation span is short for the requested analysis",
    "W_UNCERTAINTY_UNAVAILABLE": "no uncertainty estimate is available for a reported value",
    "W_APPROXIMATE_GROUND_TRUTH": "fixture or reference data is approximate, not certified truth",
    "W_DERIVED_COPY": "measurement ran on a derived processing copy, not the source bytes",
}

ERROR_CODES = {
    "E_MALFORMED_JSON": "input bytes are not parseable JSON",
    "E_BAD_SCHEMA": "unknown schema name in parse dispatcher",
    "E_NOT_AN_OBJECT": "record input is not a JSON object",
    "E_BAD_VERSION": "schema_version does not match this record type",
    "E_MISSING_FIELD": "a required key is absent",
    "E_UNEXPECTED_FIELD": "an unknown key is present",
    "E_NULL_NOT_ALLOWED": "field value is null where a value is required",
    "E_WRONG_TYPE": "field value has the wrong JSON type",
    "E_BAD_ENUM": "string value is outside the locked vocabulary",
    "E_EMPTY_STRING": "string value is empty where content is required",
    "E_NON_FINITE": "numeric value is NaN or infinite",
    "E_OUT_OF_RANGE": "numeric value is outside its locked range",
    "E_BAD_SHA256": "hash is not 64 lowercase hex characters",
    "E_BAD_TIME_BASE": "time base is not an 'int/int' rational string",
    "E_BBOX_ORDER": "bounding box corners are not ordered minima/maxima",
    "E_CENTROID_PAIR": "centroid x/y must both be set or both be null",
    "E_CORNERS_SHAPE": "corners are not exactly 4 finite [x, y] pairs",
    "E_TRANSFORM_SHAPE": "plane transform is not a 3x3 finite matrix",
    "E_PARAMETER_MISMATCH": "parameter names, values, and units disagree",
    "E_INCOHERENT_VALUE": " individually valid fields contradict each other",
    "E_MISSING_MAPPING": "valid frame lacks source index, PTS, or decoded reference",
    "E_NON_MONOTONIC_PTS": "valid frame PTS is not strictly increasing",
    "E_DUPLICATE_FRAME": "frame index appears more than once in a frame table",
    "E_UNCONFIRMED_DIMENSIONS": "confirmed card type lacks user-confirmed dimensions",
    "E_SCALE_AMBIGUOUS": "calibration needs exactly one of scale or plane transform",
    "E_GRAVITY_WITHOUT_LENGTH": "gravity value lacks independent pivot length",
    "E_VALUE_WITHOUT_UNIT": "numeric value lacks its unit",
    "E_INTERVAL_WITHOUT_METHOD": "interval lacks its method label",
    "E_INTERVAL_ORDER": "interval lower bound exceeds the upper bound",
    "E_INCOHERENT_STATE": "result state contradicts values, warnings, or reasons",
    "E_UNKNOWN_WARNING_CODE": "warning code is outside the locked taxonomy",
    "E_UNKNOWN_REASON_CODE": "reject reason code is outside the locked taxonomy",
}


@dataclass(frozen=True)
class FieldError:
    """One machine-readable validation failure."""

    code: str
    field: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "field": self.field, "message": self.message}


class ContractError(Exception):
    """Raised when record input fails validation. Never partial objects."""

    def __init__(self, errors: list[FieldError]) -> None:
        self.errors = list(errors)
        summary = "; ".join(
            f"[{error.code}] {error.field or '<record>'}: {error.message}"
            for error in self.errors
        )
        super().__init__(f"{len(self.errors)} contract error(s): {summary}")

    @property
    def codes(self) -> list[str]:
        return [error.code for error in self.errors]

    def to_dict(self) -> dict[str, Any]:
        return {"errors": [error.to_dict() for error in self.errors]}


class _Collector:
    """Gathers every field error so one parse reports all failures."""

    def __init__(self) -> None:
        self.errors: list[FieldError] = []

    def add(self, code: str, field: str | None, message: str) -> None:
        self.errors.append(FieldError(code, field, message))

    def raise_if_errors(self) -> None:
        if self.errors:
            raise ContractError(self.errors)


_MISSING = object()


def _check_keys(data: dict, expected: set[str], collector: _Collector, where: str) -> None:
    for key in sorted(set(data) - expected):
        collector.add("E_UNEXPECTED_FIELD", f"{where}.{key}" if where else key,
                      f"unknown key {key!r}")
    for key in sorted(expected - set(data)):
        collector.add("E_MISSING_FIELD", f"{where}.{key}" if where else key,
                      f"required key {key!r} is absent")


def _read(data: dict, key: str, collector: _Collector, where: str) -> Any:
    field = f"{where}.{key}" if where else key
    if key not in data:
        return _MISSING
    value = data[key]
    if value is None:
        collector.add("E_NULL_NOT_ALLOWED", field, "value is null where a value is required")
        return _MISSING
    return value


def _read_nullable(data: dict, key: str) -> Any:
    if key not in data:
        return _MISSING
    return data[key]


def _read_str(data: dict, key: str, collector: _Collector, where: str,
              *, allow_null: bool) -> str | None:
    field = f"{where}.{key}" if where else key
    value = _read_nullable(data, key)
    if value is _MISSING or value is None:
        if value is None and not allow_null:
            collector.add("E_NULL_NOT_ALLOWED", field, "value is null where a value is required")
        return None
    if not isinstance(value, str):
        collector.add("E_WRONG_TYPE", field, f"expected string, got {type(value).__name__}")
        return None
    if not value:
        collector.add("E_EMPTY_STRING", field, "string must not be empty")
        return None
    return value


def _read_bool(data: dict, key: str, collector: _Collector, where: str,
               *, allow_null: bool) -> bool | None:
    field = f"{where}.{key}" if where else key
    value = _read_nullable(data, key)
    if value is _MISSING or value is None:
        if value is None and not allow_null:
            collector.add("E_NULL_NOT_ALLOWED", field, "value is null where a value is required")
        return None
    if type(value) is not bool:
        collector.add("E_WRONG_TYPE", field, f"expected boolean, got {type(value).__name__}")
        return None
    return value


def _read_int(data: dict, key: str, collector: _Collector, where: str,
              *, allow_null: bool, minimum: int | None = None,
              maximum: int | None = None) -> int | None:
    field = f"{where}.{key}" if where else key
    value = _read_nullable(data, key)
    if value is _MISSING or value is None:
        if value is None and not allow_null:
            collector.add("E_NULL_NOT_ALLOWED", field, "value is null where a value is required")
        return None
    if type(value) is not int:
        collector.add("E_WRONG_TYPE", field, f"expected integer, got {type(value).__name__}")
        return None
    if (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        collector.add("E_OUT_OF_RANGE", field, f"value {value} outside [{minimum}, {maximum}]")
        return None
    return value


def _read_float(data: dict, key: str, collector: _Collector, where: str,
                *, allow_null: bool, minimum: float | None = None,
                maximum: float | None = None,
                minimum_exclusive: bool = False) -> float | None:
    field = f"{where}.{key}" if where else key
    value = _read_nullable(data, key)
    if value is _MISSING or value is None:
        if value is None and not allow_null:
            collector.add("E_NULL_NOT_ALLOWED", field, "value is null where a value is required")
        return None
    if type(value) is bool or not isinstance(value, (int, float)):
        collector.add("E_WRONG_TYPE", field, f"expected number, got {type(value).__name__}")
        return None
    number = float(value)
    if not math.isfinite(number):
        collector.add("E_NON_FINITE", field, "value must be finite for JSON-canonical output")
        return None
    too_low = number < minimum if minimum is not None else False
    if minimum_exclusive and minimum is not None and number == minimum:
        too_low = True
    if too_low or (maximum is not None and number > maximum):
        bound = f">{minimum}" if minimum_exclusive else f">={minimum}"
        collector.add("E_OUT_OF_RANGE", field, f"value {number} outside {bound}..{maximum}")
        return None
    return number


def _read_enum(data: dict, key: str, collector: _Collector, where: str,
               enum_type: type[Enum]) -> Enum | None:
    field = f"{where}.{key}" if where else key
    value = _read(data, key, collector, where)
    if value is _MISSING:
        return None
    if not isinstance(value, str):
        collector.add("E_WRONG_TYPE", field, f"expected string, got {type(value).__name__}")
        return None
    try:
        return enum_type(value)
    except ValueError:
        allowed = sorted(item.value for item in enum_type)
        collector.add("E_BAD_ENUM", field, f"value {value!r} outside {allowed}")
        return None


def _read_list(data: dict, key: str, collector: _Collector, where: str) -> list | None:
    field = f"{where}.{key}" if where else key
    value = _read(data, key, collector, where)
    if value is _MISSING:
        return None
    if not isinstance(value, list):
        collector.add("E_WRONG_TYPE", field, f"expected list, got {type(value).__name__}")
        return None
    return value


def _read_dict(data: dict, key: str, collector: _Collector, where: str,
               *, allow_null: bool) -> dict | None:
    field = f"{where}.{key}" if where else key
    value = _read_nullable(data, key)
    if value is _MISSING or value is None:
        if value is None and not allow_null:
            collector.add("E_NULL_NOT_ALLOWED", field, "value is null where a value is required")
        return None
    if not isinstance(value, dict):
        collector.add("E_WRONG_TYPE", field, f"expected object, got {type(value).__name__}")
        return None
    return value


def _read_sha256(data: dict, key: str, collector: _Collector, where: str,
                 *, allow_null: bool) -> str | None:
    value = _read_str(data, key, collector, where, allow_null=allow_null)
    if value is None:
        return None
    field = f"{where}.{key}" if where else key
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        collector.add("E_BAD_SHA256", field, "hash must be 64 lowercase hex characters")
        return None
    return value


@dataclass(frozen=True)
class Warning:
    """Non-fatal coded warning. ``code`` must be a locked ``W_*`` code."""

    code: str
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}


def _parse_warnings(value: list, collector: _Collector, where: str) -> list[Warning] | None:
    warnings: list[Warning] = []
    for index, item in enumerate(value):
        field = f"{where}[{index}]"
        if not isinstance(item, dict):
            collector.add("E_WRONG_TYPE", field, f"expected object, got {type(item).__name__}")
            continue
        _check_keys(item, {"code", "detail"}, collector, field)
        code = _read_str(item, "code", collector, field, allow_null=False)
        detail = _read_str(item, "detail", collector, field, allow_null=False)
        if code is None or detail is None:
            continue
        if code not in WARNING_CODES:
            collector.add("E_UNKNOWN_WARNING_CODE", f"{field}.code",
                          f"code {code!r} is outside the locked taxonomy")
            continue
        warnings.append(Warning(code=code, detail=detail))
    return warnings


@dataclass(frozen=True)
class RejectReason:
    """Fatal coded reason. ``code`` must be a locked ``E_*`` code."""

    code: str
    field: str | None
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "field": self.field, "detail": self.detail}


def _parse_reject_reasons(value: list, collector: _Collector, where: str) -> list[RejectReason] | None:
    reasons: list[RejectReason] = []
    for index, item in enumerate(value):
        field = f"{where}[{index}]"
        if not isinstance(item, dict):
            collector.add("E_WRONG_TYPE", field, f"expected object, got {type(item).__name__}")
            continue
        _check_keys(item, {"code", "field", "detail"}, collector, field)
        code = _read_str(item, "code", collector, field, allow_null=False)
        reason_field = _read_str(item, "field", collector, field, allow_null=True)
        detail = _read_str(item, "detail", collector, field, allow_null=False)
        if code is None or detail is None:
            continue
        if code not in ERROR_CODES:
            collector.add("E_UNKNOWN_REASON_CODE", f"{field}.code",
                          f"code {code!r} is outside the locked taxonomy")
            continue
        reasons.append(RejectReason(code=code, field=reason_field, detail=detail))
    return reasons


@dataclass(frozen=True)
class ArtifactHashes:
    """Identities of the upstream artifacts behind a result (KL-7.5).

    Strict SHA-256 digests (64 lowercase hex) of the exact input
    bytes, or null when an artifact was unreadable (unknown stays
    null). Paths stay in ``raw_refs``; identities live here.
    """

    raw_bob_sha256: str | None
    raw_card_sha256: str | None
    calibration_sha256: str | None
    geometry_report_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_bob_sha256": self.raw_bob_sha256,
            "raw_card_sha256": self.raw_card_sha256,
            "calibration_sha256": self.calibration_sha256,
            "geometry_report_sha256": self.geometry_report_sha256,
        }


@dataclass(frozen=True)
class Provenance:
    """Origin record. Software identity required; the rest nullable-if-unknown.

    - ``input_sha256``: 64 lowercase hex chars or null.
    - ``model_name``/``model_version``: external model identity or null.
    - ``raw_refs``: artifact references (fixture paths, response files).
    - ``artifact_hashes``: upstream artifact digests (result
      provenance carries them; other records omit the key).
    """

    software_name: str
    software_version: str
    input_sha256: str | None
    model_name: str | None
    model_version: str | None
    raw_refs: tuple[str, ...]
    artifact_hashes: ArtifactHashes | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "software_name": self.software_name,
            "software_version": self.software_version,
            "input_sha256": self.input_sha256,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "raw_refs": list(self.raw_refs),
            # Additive-compat: provenances without artifact
            # identities omit the key, so legacy fixtures
            # round-trip byte-identically.
            **({"artifact_hashes": self.artifact_hashes.to_dict()}
               if self.artifact_hashes is not None else {}),
        }


def _parse_artifact_hashes(value: dict, collector: _Collector,
                           where: str) -> ArtifactHashes | None:
    _check_keys(value, {"raw_bob_sha256", "raw_card_sha256",
                        "calibration_sha256", "geometry_report_sha256"},
                collector, where)
    error_count_before = len(collector.errors)
    digests = {key: _read_sha256(value, key, collector, where,
                                 allow_null=True)
               for key in ("raw_bob_sha256", "raw_card_sha256",
                           "calibration_sha256", "geometry_report_sha256")}
    if len(collector.errors) != error_count_before:
        return None
    return ArtifactHashes(**digests)


def _parse_provenance(value: dict, collector: _Collector, where: str) -> Provenance | None:
    expected = {"software_name", "software_version", "input_sha256",
                        "model_name", "model_version", "raw_refs"}
    if "artifact_hashes" in value:
        expected = expected | {"artifact_hashes"}
    _check_keys(value, expected, collector, where)
    error_count_before = len(collector.errors)
    software_name = _read_str(value, "software_name", collector, where, allow_null=False)
    software_version = _read_str(value, "software_version", collector, where, allow_null=False)
    input_sha256 = _read_sha256(value, "input_sha256", collector, where, allow_null=True)
    model_name = _read_str(value, "model_name", collector, where, allow_null=True)
    model_version = _read_str(value, "model_version", collector, where, allow_null=True)
    raw_refs_value = _read_list(value, "raw_refs", collector, where)
    raw_refs: list[str] = []
    if raw_refs_value is not None:
        for index, item in enumerate(raw_refs_value):
            if not isinstance(item, str) or not item:
                collector.add("E_WRONG_TYPE" if not isinstance(item, str) else "E_EMPTY_STRING",
                              f"{where}.raw_refs[{index}]", "reference must be a non-empty string")
            else:
                raw_refs.append(item)
    hashes_path = f"{where}.artifact_hashes" if where else "artifact_hashes"
    artifact_hashes: ArtifactHashes | None = None
    if "artifact_hashes" in value:
        hashes_value = value["artifact_hashes"]
        if hashes_value is None:
            artifact_hashes = None
        elif isinstance(hashes_value, dict):
            artifact_hashes = _parse_artifact_hashes(hashes_value, collector,
                                                     hashes_path)
        else:
            collector.add("E_WRONG_TYPE", hashes_path,
                          f"expected an object, got {type(hashes_value).__name__}")
    if len(collector.errors) != error_count_before or software_name is None \
            or software_version is None:
        return None
    return Provenance(software_name=software_name, software_version=software_version,
                      input_sha256=input_sha256, model_name=model_name,
                      model_version=model_version, raw_refs=tuple(raw_refs),
                      artifact_hashes=artifact_hashes)


@dataclass(frozen=True)
class MediaMetadata:
    """Validated source-media description (``media.v1``).

    Mirrors master plan section 6.1 plus ``valid`` and ``provenance``.
    v1 scope admits MP4/H.264 only; anything else fails at this trust
    boundary so the pipeline can report ``unsupported_input``.
    Nullable unknowns: ``source_sha256``, ``pixel_format``,
    ``duration_seconds``, ``frame_count``, ``nominal_frame_rate``
    (null for VFR/unknown; never synthesized), ``time_base``,
    processing-copy fields, ``provenance``.
    ``valid`` requires known identity and structure (hash, geometry,
    duration, frame count).
    """

    schema_version: str
    source_path: str
    source_sha256: str | None
    container: str
    video_stream_count: int
    audio_stream_count: int
    codec: str
    width: int
    height: int
    pixel_format: str | None
    duration_seconds: float | None
    frame_count: int | None
    nominal_frame_rate: float | None
    time_base: str | None
    processing_copy_path: str | None
    processing_copy_sha256: str | None
    valid: bool
    warnings: tuple[Warning, ...]
    provenance: Provenance | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "container": self.container,
            "video_stream_count": self.video_stream_count,
            "audio_stream_count": self.audio_stream_count,
            "codec": self.codec,
            "width": self.width,
            "height": self.height,
            "pixel_format": self.pixel_format,
            "duration_seconds": self.duration_seconds,
            "frame_count": self.frame_count,
            "nominal_frame_rate": self.nominal_frame_rate,
            "time_base": self.time_base,
            "processing_copy_path": self.processing_copy_path,
            "processing_copy_sha256": self.processing_copy_sha256,
            "valid": self.valid,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> MediaMetadata:
        collector = _Collector()
        if not isinstance(data, dict):
            collector.add("E_NOT_AN_OBJECT", None, "media record must be a JSON object")
            collector.raise_if_errors()
        assert isinstance(data, dict)
        _check_keys(data, {"schema_version", "source_path", "source_sha256", "container",
                           "video_stream_count", "audio_stream_count", "codec", "width",
                           "height", "pixel_format", "duration_seconds", "frame_count",
                           "nominal_frame_rate", "time_base", "processing_copy_path",
                           "processing_copy_sha256", "valid", "warnings", "provenance"},
                    collector, "")
        version = _read_str(data, "schema_version", collector, "", allow_null=False)
        if version is not None and version != MEDIA_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {MEDIA_VERSION!r}, got {version!r}")
        source_path = _read_str(data, "source_path", collector, "", allow_null=False)
        source_sha256 = _read_sha256(data, "source_sha256", collector, "", allow_null=True)
        container = _read_str(data, "container", collector, "", allow_null=False)
        if container is not None and container != "mp4":
            collector.add("E_BAD_ENUM", "container",
                          f"v1 scope admits 'mp4' only, got {container!r}")
        video_stream_count = _read_int(data, "video_stream_count", collector, "",
                                       allow_null=False, minimum=1, maximum=1)
        audio_stream_count = _read_int(data, "audio_stream_count", collector, "",
                                       allow_null=False, minimum=0)
        codec = _read_str(data, "codec", collector, "", allow_null=False)
        if codec is not None and codec != "h264":
            collector.add("E_BAD_ENUM", "codec", f"v1 scope admits 'h264' only, got {codec!r}")
        width = _read_int(data, "width", collector, "", allow_null=False, minimum=1)
        height = _read_int(data, "height", collector, "", allow_null=False, minimum=1)
        pixel_format = _read_str(data, "pixel_format", collector, "", allow_null=True)
        duration_seconds = _read_float(data, "duration_seconds", collector, "",
                                       allow_null=True, minimum=0.0)
        frame_count = _read_int(data, "frame_count", collector, "", allow_null=True, minimum=1)
        nominal_frame_rate = _read_float(data, "nominal_frame_rate", collector, "",
                                         allow_null=True, minimum=0.0, minimum_exclusive=True)
        time_base = _read_str(data, "time_base", collector, "", allow_null=True)
        if time_base is not None:
            parts = time_base.split("/")
            if len(parts) != 2 or not all(part.isdigit() and int(part) > 0 for part in parts):
                collector.add("E_BAD_TIME_BASE", "time_base",
                              f"value {time_base!r} is not an 'int/int' rational")
                time_base = None
        processing_copy_path = _read_str(data, "processing_copy_path", collector, "",
                                         allow_null=True)
        processing_copy_sha256 = _read_sha256(data, "processing_copy_sha256", collector, "",
                                              allow_null=True)
        valid = _read_bool(data, "valid", collector, "", allow_null=False)
        warnings_value = _read_list(data, "warnings", collector, "")
        warnings = _parse_warnings(warnings_value, collector, "warnings") \
            if warnings_value is not None else None
        provenance_value = _read_dict(data, "provenance", collector, "", allow_null=True)
        provenance = _parse_provenance(provenance_value, collector, "provenance") \
            if provenance_value is not None else None
        if valid and any(value is None for value in
                         (source_sha256, width, height, duration_seconds, frame_count)):
            collector.add("E_INCOHERENT_VALUE", "valid",
                          "valid media requires hash, geometry, duration, and frame count")
        collector.raise_if_errors()
        assert source_path is not None and container is not None
        assert video_stream_count is not None and audio_stream_count is not None
        assert codec is not None and width is not None and height is not None
        assert valid is not None and warnings is not None
        return cls(schema_version=MEDIA_VERSION, source_path=source_path,
                   source_sha256=source_sha256, container=container,
                   video_stream_count=video_stream_count,
                   audio_stream_count=audio_stream_count, codec=codec, width=width,
                   height=height, pixel_format=pixel_format,
                   duration_seconds=duration_seconds, frame_count=frame_count,
                   nominal_frame_rate=nominal_frame_rate, time_base=time_base,
                   processing_copy_path=processing_copy_path,
                   processing_copy_sha256=processing_copy_sha256, valid=valid,
                   warnings=tuple(warnings), provenance=provenance)


@dataclass(frozen=True)
class FrameRecord:
    """One processing-frame mapping (``frame.v1``).

    Zero-based ``frame_index`` (processing order) maps to
    ``source_frame_index`` (source container order), ``pts_seconds``
    (actual source presentation time), and ``decoded_reference``
    (opaque decode handle). Finite negative PTS is preserved as-is
    (media edit/preroll); only non-finite PTS is rejected. Missing
    mappings stay explicit: the nullable fields are null and ``valid``
    is false. No silent deletion: every processing index appears
    exactly once per table.
    """

    schema_version: str
    frame_index: int
    source_frame_index: int | None
    pts_seconds: float | None
    duration_seconds: float | None
    decoded_reference: str | None
    valid: bool
    warnings: tuple[Warning, ...]
    provenance: Provenance | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "frame_index": self.frame_index,
            "source_frame_index": self.source_frame_index,
            "pts_seconds": self.pts_seconds,
            "duration_seconds": self.duration_seconds,
            "decoded_reference": self.decoded_reference,
            "valid": self.valid,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> FrameRecord:
        collector = _Collector()
        if not isinstance(data, dict):
            collector.add("E_NOT_AN_OBJECT", None, "frame record must be a JSON object")
            collector.raise_if_errors()
        assert isinstance(data, dict)
        _check_keys(data, {"schema_version", "frame_index", "source_frame_index",
                           "pts_seconds", "duration_seconds", "decoded_reference",
                           "valid", "warnings", "provenance"}, collector, "")
        version = _read_str(data, "schema_version", collector, "", allow_null=False)
        if version is not None and version != FRAME_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {FRAME_VERSION!r}, got {version!r}")
        frame_index = _read_int(data, "frame_index", collector, "", allow_null=False, minimum=0)
        source_frame_index = _read_int(data, "source_frame_index", collector, "",
                                       allow_null=True, minimum=0)
        pts_seconds = _read_float(data, "pts_seconds", collector, "", allow_null=True)
        duration_seconds = _read_float(data, "duration_seconds", collector, "",
                                       allow_null=True, minimum=0.0)
        decoded_reference = _read_str(data, "decoded_reference", collector, "", allow_null=True)
        valid = _read_bool(data, "valid", collector, "", allow_null=False)
        warnings_value = _read_list(data, "warnings", collector, "")
        warnings = _parse_warnings(warnings_value, collector, "warnings") \
            if warnings_value is not None else None
        provenance_value = _read_dict(data, "provenance", collector, "", allow_null=True)
        provenance = _parse_provenance(provenance_value, collector, "provenance") \
            if provenance_value is not None else None
        if valid and any(value is None for value in
                         (source_frame_index, pts_seconds, decoded_reference)):
            collector.add("E_MISSING_MAPPING", "valid",
                          "valid frame requires source index, PTS, and decoded reference")
        collector.raise_if_errors()
        assert frame_index is not None and valid is not None and warnings is not None
        return cls(schema_version=FRAME_VERSION, frame_index=frame_index,
                   source_frame_index=source_frame_index, pts_seconds=pts_seconds,
                   duration_seconds=duration_seconds, decoded_reference=decoded_reference,
                   valid=valid, warnings=tuple(warnings), provenance=provenance)


def validate_frame_table(records: list[FrameRecord]) -> None:
    """Collection rules for a frame table (KL-1.2 trust boundary).

    Every processing index appears at most once; valid records carry
    unique source indexes and strictly increasing PTS in processing
    order. Raises ``ContractError`` on the first violated rule class
    with all offending indexes collected.
    """
    collector = _Collector()
    seen_processing: set[int] = set()
    for record in records:
        if record.frame_index in seen_processing:
            collector.add("E_DUPLICATE_FRAME", f"frame_index={record.frame_index}",
                          "processing frame index appears more than once")
        seen_processing.add(record.frame_index)
    ordered = sorted((record for record in records if record.valid),
                     key=lambda record: record.frame_index)
    seen_source: set[int] = set()
    previous_pts: float | None = None
    for record in ordered:
        assert record.source_frame_index is not None and record.pts_seconds is not None
        if record.source_frame_index in seen_source:
            collector.add("E_DUPLICATE_FRAME",
                          f"frame_index={record.frame_index}.source_frame_index",
                          "source frame index appears more than once among valid frames")
        seen_source.add(record.source_frame_index)
        if previous_pts is not None and record.pts_seconds <= previous_pts:
            collector.add("E_NON_MONOTONIC_PTS",
                          f"frame_index={record.frame_index}.pts_seconds",
                          f"PTS {record.pts_seconds} is not strictly after {previous_pts}")
        previous_pts = record.pts_seconds
    collector.raise_if_errors()


def _parse_bbox(value: list, collector: _Collector, where: str) -> tuple[float, ...] | None:
    if len(value) != 4 or any(type(item) is bool or not isinstance(item, (int, float))
                              for item in value):
        collector.add("E_WRONG_TYPE", where, "bbox must be 4 JSON numbers")
        return None
    numbers = [float(item) for item in value]
    if any(not math.isfinite(item) for item in numbers):
        collector.add("E_NON_FINITE", where, "bbox corners must be finite")
        return None
    x_min, y_min, x_max, y_max = numbers
    if not (x_max > x_min and y_max > y_min):
        collector.add("E_BBOX_ORDER", where,
                      f"box {numbers} is not ordered [x_min, y_min, x_max, y_max]")
        return None
    return tuple(numbers)


@dataclass(frozen=True)
class ObservationRecord:
    """One normalized object observation (``observation.v1``).

    Coordinates use the locked image system (top-left origin, +x right,
    +y down, float pixels). ``bbox`` is ``[x_min, y_min, x_max, y_max]``.
    ``mask_area_px`` is in square pixels despite its plan-fixed name.
    Decoded masks live behind ``mask_reference`` (artifact path or id);
    vendor payloads never inline here. ``pts_seconds`` keeps finite
    negative source timestamps; only non-finite PTS is rejected.
    ``valid`` requires source PTS plus confidence plus a complete
    centroid pair; box, area, and mask refine but do not gate validity.
    """

    schema_version: str
    frame_index: int
    pts_seconds: float | None
    object_role: ObjectRole
    object_id: str
    confidence: float | None
    bbox: tuple[float, ...] | None
    centroid_x_px: float | None
    centroid_y_px: float | None
    mask_area_px: float | None
    mask_reference: str | None
    valid: bool
    source: ObservationSource
    warnings: tuple[Warning, ...]
    provenance: Provenance | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "frame_index": self.frame_index,
            "pts_seconds": self.pts_seconds,
            "object_role": self.object_role.value,
            "object_id": self.object_id,
            "confidence": self.confidence,
            "bbox": list(self.bbox) if self.bbox is not None else None,
            "centroid_x_px": self.centroid_x_px,
            "centroid_y_px": self.centroid_y_px,
            "mask_area_px": self.mask_area_px,
            "mask_reference": self.mask_reference,
            "valid": self.valid,
            "source": self.source.value,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> ObservationRecord:
        collector = _Collector()
        if not isinstance(data, dict):
            collector.add("E_NOT_AN_OBJECT", None, "observation record must be a JSON object")
            collector.raise_if_errors()
        assert isinstance(data, dict)
        _check_keys(data, {"schema_version", "frame_index", "pts_seconds", "object_role",
                           "object_id", "confidence", "bbox", "centroid_x_px",
                           "centroid_y_px", "mask_area_px", "mask_reference", "valid",
                           "source", "warnings", "provenance"}, collector, "")
        version = _read_str(data, "schema_version", collector, "", allow_null=False)
        if version is not None and version != OBSERVATION_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {OBSERVATION_VERSION!r}, got {version!r}")
        frame_index = _read_int(data, "frame_index", collector, "", allow_null=False, minimum=0)
        pts_seconds = _read_float(data, "pts_seconds", collector, "", allow_null=True)
        object_role = _read_enum(data, "object_role", collector, "", ObjectRole)
        object_id = _read_str(data, "object_id", collector, "", allow_null=False)
        confidence = _read_float(data, "confidence", collector, "", allow_null=True,
                                 minimum=0.0, maximum=1.0)
        bbox_value = _read_nullable(data, "bbox")
        bbox: tuple[float, ...] | None = None
        if bbox_value is not _MISSING:
            if bbox_value is None:
                bbox = None
            elif isinstance(bbox_value, list):
                bbox = _parse_bbox(bbox_value, collector, "bbox")
            else:
                collector.add("E_WRONG_TYPE", "bbox",
                              f"expected list or null, got {type(bbox_value).__name__}")
        centroid_x_px = _read_float(data, "centroid_x_px", collector, "", allow_null=True)
        centroid_y_px = _read_float(data, "centroid_y_px", collector, "", allow_null=True)
        if (centroid_x_px is None) != (centroid_y_px is None):
            collector.add("E_CENTROID_PAIR", "centroid_x_px",
                          "centroid x and y must both be set or both be null")
        mask_area_px = _read_float(data, "mask_area_px", collector, "", allow_null=True, minimum=0.0)
        mask_reference = _read_str(data, "mask_reference", collector, "", allow_null=True)
        valid = _read_bool(data, "valid", collector, "", allow_null=False)
        source = _read_enum(data, "source", collector, "", ObservationSource)
        warnings_value = _read_list(data, "warnings", collector, "")
        warnings = _parse_warnings(warnings_value, collector, "warnings") \
            if warnings_value is not None else None
        provenance_value = _read_dict(data, "provenance", collector, "", allow_null=True)
        provenance = _parse_provenance(provenance_value, collector, "provenance") \
            if provenance_value is not None else None
        if valid and any(value is None for value in
                         (pts_seconds, confidence, centroid_x_px, centroid_y_px)):
            collector.add("E_INCOHERENT_VALUE", "valid",
                          "valid observation requires PTS, confidence, and a centroid pair")
        collector.raise_if_errors()
        assert frame_index is not None and object_role is not None and object_id is not None
        assert valid is not None and source is not None and warnings is not None
        return cls(schema_version=OBSERVATION_VERSION, frame_index=frame_index,
                   pts_seconds=pts_seconds, object_role=object_role, object_id=object_id,
                   confidence=confidence, bbox=bbox, centroid_x_px=centroid_x_px,
                   centroid_y_px=centroid_y_px, mask_area_px=mask_area_px,
                   mask_reference=mask_reference, valid=valid, source=source,
                   warnings=tuple(warnings), provenance=provenance)


@dataclass(frozen=True)
class ReferenceDimensions:
    """Physical card size in millimeters. Values come from U-1 user input."""

    width_mm: float
    height_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {"width_mm": self.width_mm, "height_mm": self.height_mm}


def _parse_reference_dimensions(value: dict, collector: _Collector,
                                where: str) -> ReferenceDimensions | None:
    _check_keys(value, {"width_mm", "height_mm"}, collector, where)
    width = _read_float(value, "width_mm", collector, where, allow_null=False,
                        minimum=0.0, minimum_exclusive=True)
    height = _read_float(value, "height_mm", collector, where, allow_null=False,
                         minimum=0.0, minimum_exclusive=True)
    if width is None or height is None:
        return None
    return ReferenceDimensions(width_mm=width, height_mm=height)


@dataclass(frozen=True)
class OrientedDimensions:
    """Observed card extent in pixels: long side first."""

    long_side_px: float
    short_side_px: float

    def to_dict(self) -> dict[str, Any]:
        return {"long_side_px": self.long_side_px, "short_side_px": self.short_side_px}


def _parse_oriented_dimensions(value: dict, collector: _Collector,
                               where: str) -> OrientedDimensions | None:
    _check_keys(value, {"long_side_px", "short_side_px"}, collector, where)
    long_side = _read_float(value, "long_side_px", collector, where, allow_null=False,
                            minimum=0.0, minimum_exclusive=True)
    short_side = _read_float(value, "short_side_px", collector, where, allow_null=False,
                             minimum=0.0, minimum_exclusive=True)
    if long_side is None or short_side is None:
        return None
    if short_side > long_side:
        collector.add("E_INCOHERENT_VALUE", where,
                      "short_side_px exceeds long_side_px")
        return None
    return OrientedDimensions(long_side_px=long_side, short_side_px=short_side)


def _parse_corners(value: list, collector: _Collector, where: str) -> tuple[tuple[float, ...], ...] | None:
    corners: list[tuple[float, ...]] = []
    if len(value) != 4:
        collector.add("E_CORNERS_SHAPE", where, f"expected 4 corners, got {len(value)}")
        return None
    for index, item in enumerate(value):
        if (not isinstance(item, list) or len(item) != 2
                or any(type(number) is bool or not isinstance(number, (int, float))
                       for number in item)):
            collector.add("E_CORNERS_SHAPE", f"{where}[{index}]",
                          "corner must be 2 JSON numbers")
            return None
        point = (float(item[0]), float(item[1]))
        if not all(math.isfinite(number) for number in point):
            collector.add("E_NON_FINITE", f"{where}[{index}]", "corner must be finite")
            return None
        corners.append(point)
    return tuple(corners)


def _parse_transform(value: list, collector: _Collector,
                     where: str) -> tuple[tuple[float, ...], ...] | None:
    if len(value) != 3 or any(not isinstance(row, list) or len(row) != 3 for row in value):
        collector.add("E_TRANSFORM_SHAPE", where, "transform must be a 3x3 nested list")
        return None
    rows: list[tuple[float, ...]] = []
    for row_index, row in enumerate(value):
        numbers: list[float] = []
        for item in row:
            if type(item) is bool or not isinstance(item, (int, float)):
                collector.add("E_WRONG_TYPE", f"{where}[{row_index}]",
                              "transform entries must be JSON numbers")
                return None
            numbers.append(float(item))
        if not all(math.isfinite(item) for item in numbers):
            collector.add("E_NON_FINITE", f"{where}[{row_index}]", "transform must be finite")
            return None
        rows.append(tuple(numbers))
    return tuple(rows)


@dataclass(frozen=True)
class CalibrationRecord:
    """Reference-card calibration (``calibration.v1``).

    Corners are 4 ``[x, y]`` float-pixel pairs in clockwise order as seen
    in the image, starting at the corner nearest the image origin
    (top-left). ``scale_mm_per_px`` is the isotropic fallback;
    ``plane_transform`` is the row-major 3x3 homography mapping pixel
    ``[x, y, 1]`` to plane ``[X_mm, Y_mm, 1]``. Exactly one scale form
    is allowed on a valid record. Standard ID-1 dimensions enter only
    through U-1 user input: this module hardcodes no card size, and a
    confirmed type without user-confirmed dimensions is rejected.
    Dimensions and source must agree in both directions for every
    reference type: present iff ``user_confirmed``, null iff
    ``not_provided``. Assumption flags are nullable booleans: ``null``
    means unassessed, never a silent default; a valid record states
    both explicitly.
    """

    schema_version: str
    reference_type: ReferenceType
    reference_dimensions_mm: ReferenceDimensions | None
    dimension_source: DimensionSource
    observed_corners_px: tuple[tuple[float, ...], ...] | None
    observed_oriented_dimensions_px: OrientedDimensions | None
    scale_mm_per_px: float | None
    plane_transform: tuple[tuple[float, ...], ...] | None
    scale_uncertainty_mm_per_px: float | None
    same_plane_assumption: bool | None
    camera_fixed_assumption: bool | None
    valid: bool
    warnings: tuple[Warning, ...]
    provenance: Provenance | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "reference_type": self.reference_type.value,
            "reference_dimensions_mm": self.reference_dimensions_mm.to_dict()
            if self.reference_dimensions_mm else None,
            "dimension_source": self.dimension_source.value,
            "observed_corners_px": [list(point) for point in self.observed_corners_px]
            if self.observed_corners_px is not None else None,
            "observed_oriented_dimensions_px": self.observed_oriented_dimensions_px.to_dict()
            if self.observed_oriented_dimensions_px else None,
            "scale_mm_per_px": self.scale_mm_per_px,
            "plane_transform": [list(row) for row in self.plane_transform]
            if self.plane_transform is not None else None,
            "scale_uncertainty_mm_per_px": self.scale_uncertainty_mm_per_px,
            "same_plane_assumption": self.same_plane_assumption,
            "camera_fixed_assumption": self.camera_fixed_assumption,
            "valid": self.valid,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> CalibrationRecord:
        collector = _Collector()
        if not isinstance(data, dict):
            collector.add("E_NOT_AN_OBJECT", None, "calibration record must be a JSON object")
            collector.raise_if_errors()
        assert isinstance(data, dict)
        _check_keys(data, {"schema_version", "reference_type", "reference_dimensions_mm",
                           "dimension_source", "observed_corners_px",
                           "observed_oriented_dimensions_px", "scale_mm_per_px",
                           "plane_transform", "scale_uncertainty_mm_per_px",
                           "same_plane_assumption", "camera_fixed_assumption", "valid",
                           "warnings", "provenance"}, collector, "")
        version = _read_str(data, "schema_version", collector, "", allow_null=False)
        if version is not None and version != CALIBRATION_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {CALIBRATION_VERSION!r}, got {version!r}")
        reference_type = _read_enum(data, "reference_type", collector, "", ReferenceType)
        dimensions_value = _read_dict(data, "reference_dimensions_mm", collector, "",
                                      allow_null=True)
        dimensions = _parse_reference_dimensions(dimensions_value, collector,
                                                 "reference_dimensions_mm") \
            if dimensions_value is not None else None
        dimension_source = _read_enum(data, "dimension_source", collector, "", DimensionSource)
        corners_value = _read_nullable(data, "observed_corners_px")
        corners: tuple[tuple[float, ...], ...] | None = None
        if corners_value is not _MISSING:
            if corners_value is None:
                corners = None
            elif isinstance(corners_value, list):
                corners = _parse_corners(corners_value, collector, "observed_corners_px")
            else:
                collector.add("E_WRONG_TYPE", "observed_corners_px",
                              f"expected list or null, got {type(corners_value).__name__}")
        oriented_value = _read_dict(data, "observed_oriented_dimensions_px", collector, "",
                                    allow_null=True)
        oriented = _parse_oriented_dimensions(oriented_value, collector,
                                              "observed_oriented_dimensions_px") \
            if oriented_value is not None else None
        scale = _read_float(data, "scale_mm_per_px", collector, "", allow_null=True,
                            minimum=0.0, minimum_exclusive=True)
        transform_value = _read_nullable(data, "plane_transform")
        transform: tuple[tuple[float, ...], ...] | None = None
        if transform_value is not _MISSING:
            if transform_value is None:
                transform = None
            elif isinstance(transform_value, list):
                transform = _parse_transform(transform_value, collector, "plane_transform")
            else:
                collector.add("E_WRONG_TYPE", "plane_transform",
                              f"expected list or null, got {type(transform_value).__name__}")
        scale_uncertainty = _read_float(data, "scale_uncertainty_mm_per_px", collector, "",
                                        allow_null=True, minimum=0.0)
        same_plane = _read_bool(data, "same_plane_assumption", collector, "", allow_null=True)
        camera_fixed = _read_bool(data, "camera_fixed_assumption", collector, "", allow_null=True)
        valid = _read_bool(data, "valid", collector, "", allow_null=False)
        warnings_value = _read_list(data, "warnings", collector, "")
        warnings = _parse_warnings(warnings_value, collector, "warnings") \
            if warnings_value is not None else None
        provenance_value = _read_dict(data, "provenance", collector, "", allow_null=True)
        provenance = _parse_provenance(provenance_value, collector, "provenance") \
            if provenance_value is not None else None
        if reference_type is ReferenceType.ISO_ID1_CONFIRMED and (
                dimension_source is not DimensionSource.USER_CONFIRMED or dimensions is None):
            collector.add("E_UNCONFIRMED_DIMENSIONS", "reference_type",
                          "confirmed ID-1 requires user-confirmed dimensions (U-1)")
        if dimension_source is not None and (dimensions_value is None) == (
                dimension_source is DimensionSource.USER_CONFIRMED):
            collector.add("E_INCOHERENT_VALUE", "dimension_source",
                          "dimensions must be present iff the source is user_confirmed")
        if valid and (scale is None) == (transform is None):
            collector.add("E_SCALE_AMBIGUOUS", "valid",
                          "valid calibration needs exactly one of scale or plane transform")
        if valid and (same_plane is None or camera_fixed is None):
            collector.add("E_INCOHERENT_VALUE", "valid",
                          "valid calibration must state both plane assumptions explicitly")
        collector.raise_if_errors()
        assert reference_type is not None and dimension_source is not None
        assert valid is not None and warnings is not None
        return cls(schema_version=CALIBRATION_VERSION, reference_type=reference_type,
                   reference_dimensions_mm=dimensions, dimension_source=dimension_source,
                   observed_corners_px=corners, observed_oriented_dimensions_px=oriented,
                   scale_mm_per_px=scale, plane_transform=transform,
                   scale_uncertainty_mm_per_px=scale_uncertainty, same_plane_assumption=same_plane,
                   camera_fixed_assumption=camera_fixed, valid=valid,
                   warnings=tuple(warnings), provenance=provenance)


@dataclass(frozen=True)
class InitialConditions:
    """Pendulum release state: angle (rad) and angular velocity (rad/s)."""

    theta0_rad: float | None
    omega0_rad_s: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"theta0_rad": self.theta0_rad, "omega0_rad_s": self.omega0_rad_s}


def _parse_initial_conditions(value: dict, collector: _Collector,
                              where: str) -> InitialConditions | None:
    _check_keys(value, {"theta0_rad", "omega0_rad_s"}, collector, where)
    theta0 = _read_float(value, "theta0_rad", collector, where, allow_null=True)
    omega0 = _read_float(value, "omega0_rad_s", collector, where, allow_null=True)
    if theta0 is None and omega0 is None:
        pass
    elif theta0 is None or omega0 is None:
        collector.add("E_INCOHERENT_VALUE", where,
                      "initial conditions must both be set or both be null")
        return None
    return InitialConditions(theta0_rad=theta0, omega0_rad_s=omega0)


@dataclass(frozen=True)
class ResidualSummary:
    """Fit residuals in radians over ``dof`` degrees of freedom."""

    rmse: float | None
    max_abs: float | None
    dof: int | None

    def to_dict(self) -> dict[str, Any]:
        return {"rmse": self.rmse, "max_abs": self.max_abs, "dof": self.dof}


def _parse_residual_summary(value: dict, collector: _Collector,
                            where: str) -> ResidualSummary | None:
    _check_keys(value, {"rmse", "max_abs", "dof"}, collector, where)
    rmse = _read_float(value, "rmse", collector, where, allow_null=True, minimum=0.0)
    max_abs = _read_float(value, "max_abs", collector, where, allow_null=True, minimum=0.0)
    dof = _read_int(value, "dof", collector, where, allow_null=True, minimum=0)
    if rmse is not None and max_abs is not None and rmse > max_abs:
        collector.add("E_INCOHERENT_VALUE", where,
                      f"rmse {rmse} exceeds max_abs {max_abs}")
        return None
    return ResidualSummary(rmse=rmse, max_abs=max_abs, dof=dof)


@dataclass(frozen=True)
class FitRecord:
    """Bounded pendulum fit (``fit.v1``).

    ``model_id`` is M1 (ideal nonlinear pendulum) or M2 (linear
    damping); ``parameter_names``/``parameters``/``parameter_units``
    must agree key-for-key. Every unit label must belong to
    ``UNIT_VOCABULARY``, and known names must carry their forced unit
    (``KNOWN_PARAMETER_UNITS``): dimensionally false labels are
    rejected. ``g_over_l_per_s2`` must equal
    ``parameters['g_over_l']`` exactly when that parameter is present.
    ``gravity_m_s2`` is null unless an independent pivot length is
    supplied (``E_GRAVITY_WITHOUT_LENGTH`` otherwise), and a supplied
    gravity must equal ``g_over_l_per_s2 * pivot_length_mm / 1000``
    within the documented tolerance (it is unverifiable without
    ``g_over_l_per_s2``). Residual ``rmse`` cannot exceed ``max_abs``.
    No sign or plausibility rules here: physical gates belong to the
    fitting stage, while the schema enforces structure, units,
    arithmetic identity, and provenance.
    """

    schema_version: str
    model_id: ModelId
    parameter_names: tuple[str, ...]
    parameters: dict[str, float]
    parameter_units: dict[str, str]
    initial_conditions: InitialConditions
    solver: str
    optimizer: str
    converged: bool
    residual_summary: ResidualSummary | None
    observation_count: int
    rejected_count: int
    fit_uncertainty_method: UncertaintyMethod
    pivot_length_mm: float | None
    pivot_length_source: LengthSource
    g_over_l_per_s2: float | None
    gravity_m_s2: float | None
    warnings: tuple[Warning, ...]
    provenance: Provenance | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "model_id": self.model_id.value,
            "parameter_names": list(self.parameter_names),
            "parameters": dict(self.parameters),
            "parameter_units": dict(self.parameter_units),
            "initial_conditions": self.initial_conditions.to_dict(),
            "solver": self.solver,
            "optimizer": self.optimizer,
            "converged": self.converged,
            "residual_summary": self.residual_summary.to_dict()
            if self.residual_summary else None,
            "observation_count": self.observation_count,
            "rejected_count": self.rejected_count,
            "fit_uncertainty_method": self.fit_uncertainty_method.value,
            "pivot_length_mm": self.pivot_length_mm,
            "pivot_length_source": self.pivot_length_source.value,
            "g_over_l_per_s2": self.g_over_l_per_s2,
            "gravity_m_s2": self.gravity_m_s2,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: Any) -> FitRecord:
        collector = _Collector()
        if not isinstance(data, dict):
            collector.add("E_NOT_AN_OBJECT", None, "fit record must be a JSON object")
            collector.raise_if_errors()
        assert isinstance(data, dict)
        _check_keys(data, {"schema_version", "model_id", "parameter_names", "parameters",
                           "parameter_units", "initial_conditions", "solver", "optimizer",
                           "converged", "residual_summary", "observation_count",
                           "rejected_count", "fit_uncertainty_method", "pivot_length_mm",
                           "pivot_length_source", "g_over_l_per_s2", "gravity_m_s2",
                           "warnings", "provenance"}, collector, "")
        version = _read_str(data, "schema_version", collector, "", allow_null=False)
        if version is not None and version != FIT_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {FIT_VERSION!r}, got {version!r}")
        model_id = _read_enum(data, "model_id", collector, "", ModelId)
        names_value = _read_list(data, "parameter_names", collector, "")
        names: list[str] = []
        if names_value is not None:
            for index, item in enumerate(names_value):
                if not isinstance(item, str) or not item:
                    collector.add("E_WRONG_TYPE" if not isinstance(item, str)
                                  else "E_EMPTY_STRING",
                                  f"parameter_names[{index}]",
                                  "parameter name must be a non-empty string")
                else:
                    names.append(item)
            if not names_value:
                collector.add("E_INCOHERENT_VALUE", "parameter_names",
                              "at least one parameter name is required")
            if len(set(names)) != len(names):
                collector.add("E_PARAMETER_MISMATCH", "parameter_names",
                              "parameter names must be unique")
        parameters_value = _read_dict(data, "parameters", collector, "", allow_null=False)
        parameters: dict[str, float] = {}
        if parameters_value is not None:
            for name, item in parameters_value.items():
                if type(item) is bool or not isinstance(item, (int, float)):
                    collector.add("E_WRONG_TYPE", f"parameters.{name}",
                                  "parameter value must be a JSON number")
                elif not math.isfinite(float(item)):
                    collector.add("E_NON_FINITE", f"parameters.{name}",
                                  "parameter value must be finite")
                else:
                    parameters[name] = float(item)
        units_value = _read_dict(data, "parameter_units", collector, "", allow_null=False)
        units: dict[str, str] = {}
        if units_value is not None:
            for name, item in units_value.items():
                if not isinstance(item, str) or not item:
                    collector.add("E_WRONG_TYPE" if not isinstance(item, str)
                                  else "E_EMPTY_STRING",
                                  f"parameter_units.{name}",
                                  "parameter unit must be a non-empty string")
                else:
                    units[name] = item
        if names_value is not None and parameters_value is not None and units_value is not None:
            if set(names) != set(parameters) or set(names) != set(units):
                collector.add("E_PARAMETER_MISMATCH", "parameters",
                              "names, values, and units must agree key-for-key")
        if (model_id is not None and names_value is not None
                and parameters_value is not None and units_value is not None
                and set(names) == set(parameters) == set(units)):
            expected_names = MODEL_PARAMETER_NAMES[model_id]
            if set(names) != expected_names:
                collector.add("E_PARAMETER_MISMATCH", "parameter_names",
                              f"{model_id.value} requires exactly "
                              f"{sorted(expected_names)}")
        for name, label in units.items():
            if label not in UNIT_VOCABULARY:
                collector.add("E_BAD_ENUM", f"parameter_units.{name}",
                              f"unit {label!r} is outside the locked vocabulary "
                              f"{sorted(UNIT_VOCABULARY)}")
            elif name in KNOWN_PARAMETER_UNITS and label != KNOWN_PARAMETER_UNITS[name]:
                collector.add("E_INCOHERENT_VALUE", f"parameter_units.{name}",
                              f"unit {label!r} is dimensionally false for {name!r}; "
                              f"expected {KNOWN_PARAMETER_UNITS[name]!r}")
        initial_value = _read_dict(data, "initial_conditions", collector, "", allow_null=False)
        initial = _parse_initial_conditions(initial_value, collector, "initial_conditions") \
            if initial_value is not None else None
        solver = _read_str(data, "solver", collector, "", allow_null=False)
        optimizer = _read_str(data, "optimizer", collector, "", allow_null=False)
        converged = _read_bool(data, "converged", collector, "", allow_null=False)
        residual_value = _read_dict(data, "residual_summary", collector, "", allow_null=True)
        residual = _parse_residual_summary(residual_value, collector, "residual_summary") \
            if residual_value is not None else None
        observation_count = _read_int(data, "observation_count", collector, "",
                                      allow_null=False, minimum=0)
        rejected_count = _read_int(data, "rejected_count", collector, "",
                                   allow_null=False, minimum=0)
        if (observation_count is not None and rejected_count is not None
                and rejected_count > observation_count):
            collector.add("E_INCOHERENT_VALUE", "rejected_count",
                          "rejected observations cannot exceed total observations")
        uncertainty = _read_enum(data, "fit_uncertainty_method", collector, "",
                                 UncertaintyMethod)
        pivot_length = _read_float(data, "pivot_length_mm", collector, "", allow_null=True,
                                   minimum=0.0, minimum_exclusive=True)
        pivot_source = _read_enum(data, "pivot_length_source", collector, "", LengthSource)
        g_over_l = _read_float(data, "g_over_l_per_s2", collector, "", allow_null=True)
        gravity = _read_float(data, "gravity_m_s2", collector, "", allow_null=True)
        if g_over_l is not None and "g_over_l" not in parameters:
            collector.add("E_INCOHERENT_VALUE", "g_over_l_per_s2",
                          "g_over_l_per_s2 requires parameters['g_over_l']")
        if "g_over_l" in parameters and (g_over_l is None
                                         or g_over_l != parameters["g_over_l"]):
            collector.add("E_INCOHERENT_VALUE", "g_over_l_per_s2",
                          "g_over_l_per_s2 must equal parameters['g_over_l'] when present")
        if gravity is not None and (pivot_length is None
                                    or pivot_source is not LengthSource.INDEPENDENT_MEASUREMENT):
            collector.add("E_GRAVITY_WITHOUT_LENGTH", "gravity_m_s2",
                          "gravity requires an independently measured pivot length")
        if gravity is not None and pivot_length is not None:
            if g_over_l is None:
                collector.add("E_INCOHERENT_VALUE", "gravity_m_s2",
                              "gravity is unverifiable without g_over_l_per_s2")
            elif not math.isclose(gravity, g_over_l * pivot_length / 1000.0,
                                  rel_tol=GRAVITY_REL_TOL, abs_tol=GRAVITY_ABS_TOL):
                collector.add("E_INCOHERENT_VALUE", "gravity_m_s2",
                              f"gravity {gravity} disagrees with "
                              f"g_over_l_per_s2 * pivot_length_mm / 1000")
        if converged and initial is not None and (
                initial.theta0_rad is None or initial.omega0_rad_s is None):
            collector.add("E_INCOHERENT_VALUE", "converged",
                          "converged fit requires stated initial conditions")
        warnings_value = _read_list(data, "warnings", collector, "")
        warnings = _parse_warnings(warnings_value, collector, "warnings") \
            if warnings_value is not None else None
        provenance_value = _read_dict(data, "provenance", collector, "", allow_null=True)
        provenance = _parse_provenance(provenance_value, collector, "provenance") \
            if provenance_value is not None else None
        collector.raise_if_errors()
        assert model_id is not None and initial is not None and solver is not None
        assert optimizer is not None and converged is not None
        assert observation_count is not None and rejected_count is not None
        assert uncertainty is not None and pivot_source is not None
        assert warnings is not None
        return cls(schema_version=FIT_VERSION, model_id=model_id,
                   parameter_names=tuple(names), parameters=parameters,
                   parameter_units=units, initial_conditions=initial, solver=solver,
                   optimizer=optimizer, converged=converged, residual_summary=residual,
                   observation_count=observation_count, rejected_count=rejected_count,
                   fit_uncertainty_method=uncertainty, pivot_length_mm=pivot_length,
                   pivot_length_source=pivot_source, g_over_l_per_s2=g_over_l,
                   gravity_m_s2=gravity, warnings=tuple(warnings), provenance=provenance)


@dataclass(frozen=True)
class IdentifiableQuantity:
    """The quantity the data actually identifies (name, value, unit).

    Names are locked by ``KNOWN_QUANTITY_UNITS``: ``g/L_eff`` pairs
    with ``1/s^2`` and ``gravity`` with ``m/s^2``. Unknown names and
    mismatched pairs are rejected so a record cannot mislabel ``g/L``
    as gravity.
    """

    name: str
    value: float | None
    unit: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "unit": self.unit}


def _parse_identifiable_quantity(value: dict, collector: _Collector,
                                 where: str) -> IdentifiableQuantity | None:
    _check_keys(value, {"name", "value", "unit"}, collector, where)
    name = _read_str(value, "name", collector, where, allow_null=False)
    quantity_value = _read_float(value, "value", collector, where, allow_null=True)
    unit = _read_str(value, "unit", collector, where, allow_null=False)
    if unit is not None and unit not in RESULT_UNITS:
        collector.add("E_BAD_ENUM", f"{where}.unit",
                      f"unit {unit!r} is outside the locked result units "
                      f"{sorted(RESULT_UNITS)}")
        return None
    if name is not None:
        if name not in KNOWN_QUANTITY_UNITS:
            collector.add("E_BAD_ENUM", f"{where}.name",
                          f"name {name!r} is outside the locked quantity names "
                          f"{sorted(KNOWN_QUANTITY_UNITS)}")
            return None
        if unit is not None and KNOWN_QUANTITY_UNITS[name] != unit:
            collector.add("E_INCOHERENT_VALUE", f"{where}.unit",
                          f"unit {unit!r} is dimensionally false for {name!r}; "
                          f"expected {KNOWN_QUANTITY_UNITS[name]!r}")
            return None
    if name is None or unit is None:
        return None
    return IdentifiableQuantity(name=name, value=quantity_value, unit=unit)


@dataclass(frozen=True)
class Interval:
    """Closed [lower, upper] interval in the measurement unit."""

    lower: float
    upper: float

    def to_dict(self) -> dict[str, Any]:
        return {"lower": self.lower, "upper": self.upper}


def _parse_interval(value: dict, collector: _Collector, where: str) -> Interval | None:
    _check_keys(value, {"lower", "upper"}, collector, where)
    lower = _read_float(value, "lower", collector, where, allow_null=False)
    upper = _read_float(value, "upper", collector, where, allow_null=False)
    if lower is None or upper is None:
        return None
    if lower > upper:
        collector.add("E_INTERVAL_ORDER", where, f"lower {lower} exceeds upper {upper}")
        return None
    return Interval(lower=lower, upper=upper)


@dataclass(frozen=True)
class QualityMetrics:
    """Pipeline coverage counts. All nullable: unknown stays null.

    Part/whole bounds apply whenever both sides are known:
    ``frames_usable <= frames_total``,
    ``observations_valid <= observations_total``, and
    ``calibrated_frames <= frames_usable``.
    """

    frames_total: int | None
    frames_usable: int | None
    observations_total: int | None
    observations_valid: int | None
    calibrated_frames: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "frames_total": self.frames_total,
            "frames_usable": self.frames_usable,
            "observations_total": self.observations_total,
            "observations_valid": self.observations_valid,
            "calibrated_frames": self.calibrated_frames,
        }


def _parse_quality_metrics(value: dict, collector: _Collector,
                           where: str) -> QualityMetrics | None:
    _check_keys(value, {"frames_total", "frames_usable", "observations_total",
                        "observations_valid", "calibrated_frames"}, collector, where)
    counts = {key: _read_int(value, key, collector, where, allow_null=True, minimum=0)
              for key in ("frames_total", "frames_usable", "observations_total",
                          "observations_valid", "calibrated_frames")}
    bounds = (("frames_usable", "frames_total"), ("observations_valid", "observations_total"),
              ("calibrated_frames", "frames_usable"))
    for part, whole in bounds:
        if counts[part] is not None and counts[whole] is not None and counts[part] > counts[whole]:
            collector.add("E_INCOHERENT_VALUE", f"{where}.{part}",
                          f"{part} {counts[part]} exceeds {whole} {counts[whole]}")
    return QualityMetrics(**counts)


@dataclass(frozen=True)
class ExportRef:
    """One written artifact: format label plus repo-relative path."""

    format: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {"format": self.format, "path": self.path}


def _parse_exports(value: list, collector: _Collector, where: str) -> list[ExportRef] | None:
    exports: list[ExportRef] = []
    for index, item in enumerate(value):
        field = f"{where}[{index}]"
        if not isinstance(item, dict):
            collector.add("E_WRONG_TYPE", field, f"expected object, got {type(item).__name__}")
            continue
        _check_keys(item, {"format", "path"}, collector, field)
        format_label = _read_str(item, "format", collector, field, allow_null=False)
        path = _read_str(item, "path", collector, field, allow_null=False)
        if format_label is None or path is None:
            continue
        exports.append(ExportRef(format=format_label, path=path))
    return exports


@dataclass(frozen=True)
class ResultContract:
    """Final auditable result (``result.v1``).

    State coherence is machine-checked: ``success`` carries a value
    with no reject reasons; ``success_with_warnings`` additionally
    requires at least one warning; the three failure states carry
    reject reasons and no value or interval. A value always needs its
    unit (``RESULT_UNITS``); an interval always needs a locked method
    (``INTERVAL_METHODS``) and must contain the value. The
    identifiable quantity must agree with the value and unit exactly.
    Success states require a present, converged supporting fit whose
    ``g_over_l_per_s2`` (for ``1/s^2``) or ``gravity_m_s2`` (for
    ``m/s^2``) equals the result value, and the fit must carry the
    underlying ``parameters['g_over_l']`` in both cases: a numeric
    result cannot detach from its evidence. Embedded calibration and
    fit records are validated recursively with prefixed fields.
    """

    schema_version: str
    status: ResultState
    measurement_name: str
    value: float | None
    unit: str | None
    interval: Interval | None
    interval_method: str | None
    identifiable_quantity: IdentifiableQuantity
    calibration: CalibrationRecord | None
    fit: FitRecord | None
    quality_metrics: QualityMetrics | None
    assumptions: tuple[str, ...]
    warnings: tuple[Warning, ...]
    reject_reasons: tuple[RejectReason, ...]
    provenance: Provenance
    exports: tuple[ExportRef, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status.value,
            "measurement_name": self.measurement_name,
            "value": self.value,
            "unit": self.unit,
            "interval": self.interval.to_dict() if self.interval else None,
            "interval_method": self.interval_method,
            "identifiable_quantity": self.identifiable_quantity.to_dict(),
            "calibration": self.calibration.to_dict() if self.calibration else None,
            "fit": self.fit.to_dict() if self.fit else None,
            "quality_metrics": self.quality_metrics.to_dict()
            if self.quality_metrics else None,
            "assumptions": list(self.assumptions),
            "warnings": [warning.to_dict() for warning in self.warnings],
            "reject_reasons": [reason.to_dict() for reason in self.reject_reasons],
            "provenance": self.provenance.to_dict(),
            "exports": [export.to_dict() for export in self.exports],
        }

    @classmethod
    def from_dict(cls, data: Any) -> ResultContract:
        collector = _Collector()
        if not isinstance(data, dict):
            collector.add("E_NOT_AN_OBJECT", None, "result contract must be a JSON object")
            collector.raise_if_errors()
        assert isinstance(data, dict)
        _check_keys(data, {"schema_version", "status", "measurement_name", "value",
                           "unit", "interval", "interval_method", "identifiable_quantity",
                           "calibration", "fit", "quality_metrics", "assumptions",
                           "warnings", "reject_reasons", "provenance", "exports"},
                    collector, "")
        version = _read_str(data, "schema_version", collector, "", allow_null=False)
        if version is not None and version != RESULT_VERSION:
            collector.add("E_BAD_VERSION", "schema_version",
                          f"expected {RESULT_VERSION!r}, got {version!r}")
        status = _read_enum(data, "status", collector, "", ResultState)
        measurement_name = _read_str(data, "measurement_name", collector, "", allow_null=False)
        value = _read_float(data, "value", collector, "", allow_null=True)
        unit = _read_str(data, "unit", collector, "", allow_null=True)
        if value is not None and unit is None:
            collector.add("E_VALUE_WITHOUT_UNIT", "unit",
                          "a reported value requires its unit")
        if unit is not None and unit not in RESULT_UNITS:
            collector.add("E_BAD_ENUM", "unit",
                          f"unit {unit!r} is outside the locked result units "
                          f"{sorted(RESULT_UNITS)}")
        if measurement_name is not None:
            quantity_name = MEASUREMENT_QUANTITIES.get(measurement_name)
            if quantity_name is None:
                collector.add("E_BAD_ENUM", "measurement_name",
                              f"name {measurement_name!r} is outside the locked measurement names "
                              f"{sorted(MEASUREMENT_QUANTITIES)}")
            elif unit is not None and MEASUREMENT_UNITS[measurement_name] != unit:
                collector.add("E_INCOHERENT_VALUE", "unit",
                              f"unit {unit!r} is dimensionally false for {measurement_name!r}; "
                              f"expected {MEASUREMENT_UNITS[measurement_name]!r}")
        interval_value = _read_dict(data, "interval", collector, "", allow_null=True)
        interval = _parse_interval(interval_value, collector, "interval") \
            if interval_value is not None else None
        interval_method = _read_str(data, "interval_method", collector, "", allow_null=True)
        if interval is not None and interval_method is None:
            collector.add("E_INTERVAL_WITHOUT_METHOD", "interval_method",
                          "an interval requires its method label")
        if interval_method is not None and interval is None:
            collector.add("E_INCOHERENT_VALUE", "interval_method",
                          "interval_method requires an interval")
        if interval_method is not None and interval_method not in INTERVAL_METHODS:
            collector.add("E_BAD_ENUM", "interval_method",
                          f"method {interval_method!r} is outside the locked methods "
                          f"{sorted(INTERVAL_METHODS)}")
        if (value is not None and interval is not None and interval.lower <= interval.upper
                and not (interval.lower <= value <= interval.upper)):
            collector.add("E_INCOHERENT_VALUE", "interval",
                          f"value {value} lies outside "
                          f"[{interval.lower}, {interval.upper}]")
        quantity_value = _read_dict(data, "identifiable_quantity", collector, "",
                                    allow_null=False)
        quantity = _parse_identifiable_quantity(quantity_value, collector,
                                                "identifiable_quantity") \
            if quantity_value is not None else None
        if quantity is not None:
            expected_measurement_quantity = MEASUREMENT_QUANTITIES.get(measurement_name)
            if (expected_measurement_quantity is not None
                    and quantity.name != expected_measurement_quantity):
                collector.add("E_INCOHERENT_VALUE", "measurement_name",
                              "measurement_name must identify identifiable_quantity")
            if quantity.value != value:
                collector.add("E_INCOHERENT_VALUE", "identifiable_quantity.value",
                              "identifiable quantity value must equal the result value")
            if unit is not None and quantity.unit != unit:
                collector.add("E_INCOHERENT_VALUE", "identifiable_quantity.unit",
                              "identifiable quantity unit must equal the result unit")
        calibration_value = _read_dict(data, "calibration", collector, "", allow_null=True)
        calibration: CalibrationRecord | None = None
        if calibration_value is not None:
            try:
                calibration = CalibrationRecord.from_dict(calibration_value)
            except ContractError as error:
                for item in error.errors:
                    nested = f"calibration.{item.field}" if item.field else "calibration"
                    collector.add(item.code, nested, item.message)
        fit_value = _read_dict(data, "fit", collector, "", allow_null=True)
        fit: FitRecord | None = None
        if fit_value is not None:
            try:
                fit = FitRecord.from_dict(fit_value)
            except ContractError as error:
                for item in error.errors:
                    nested = f"fit.{item.field}" if item.field else "fit"
                    collector.add(item.code, nested, item.message)
        metrics_value = _read_dict(data, "quality_metrics", collector, "", allow_null=True)
        metrics = _parse_quality_metrics(metrics_value, collector, "quality_metrics") \
            if metrics_value is not None else None
        assumptions_value = _read_list(data, "assumptions", collector, "")
        assumptions: list[str] = []
        if assumptions_value is not None:
            for index, item in enumerate(assumptions_value):
                if not isinstance(item, str) or not item:
                    collector.add("E_WRONG_TYPE" if not isinstance(item, str)
                                  else "E_EMPTY_STRING",
                                  f"assumptions[{index}]",
                                  "assumption must be a non-empty string")
                else:
                    assumptions.append(item)
        warnings_value = _read_list(data, "warnings", collector, "")
        warnings = _parse_warnings(warnings_value, collector, "warnings") \
            if warnings_value is not None else None
        reasons_value = _read_list(data, "reject_reasons", collector, "")
        reasons = _parse_reject_reasons(reasons_value, collector, "reject_reasons") \
            if reasons_value is not None else None
        provenance_value = _read_dict(data, "provenance", collector, "", allow_null=False)
        provenance = _parse_provenance(provenance_value, collector, "provenance") \
            if provenance_value is not None else None
        if provenance_value is not None:
            if "artifact_hashes" not in provenance_value:
                collector.add("E_MISSING_FIELD", "provenance.artifact_hashes",
                              "result provenance requires artifact_hashes")
            elif provenance_value["artifact_hashes"] is None:
                collector.add("E_NULL_NOT_ALLOWED", "provenance.artifact_hashes",
                              "result provenance requires artifact_hashes")
        exports_value = _read_list(data, "exports", collector, "")
        exports = _parse_exports(exports_value, collector, "exports") \
            if exports_value is not None else None
        if status is not None and warnings is not None and reasons is not None:
            if status is ResultState.SUCCESS:
                if reasons or warnings or value is None or unit is None:
                    collector.add("E_INCOHERENT_STATE", "status",
                                  "success needs a valued unit, no warnings, "
                                  "and no reject reasons")
            elif status is ResultState.SUCCESS_WITH_WARNINGS:
                if reasons or not warnings or value is None or unit is None:
                    collector.add("E_INCOHERENT_STATE", "status",
                                  "success_with_warnings needs a value, warnings, no reasons")
            else:
                if not reasons or value is not None or interval is not None:
                    collector.add("E_INCOHERENT_STATE", "status",
                                  f"{status.value} needs reasons and no value or interval")
        is_success = status in (ResultState.SUCCESS, ResultState.SUCCESS_WITH_WARNINGS)
        if is_success and fit_value is None:
            collector.add("E_INCOHERENT_STATE", "fit",
                          f"{status.value} requires a supporting fit record")
        if is_success and fit is not None and not fit.converged:
            collector.add("E_INCOHERENT_STATE", "fit",
                          f"{status.value} requires a converged supporting fit")
        if is_success and fit is not None and fit.observation_count <= 0:
            collector.add("E_INCOHERENT_STATE", "fit.observation_count",
                          f"{status.value} requires positive observation_count")
        if value is not None and fit is not None and unit in RESULT_UNITS:
            if "g_over_l" not in fit.parameters:
                collector.add("E_INCOHERENT_STATE", "fit",
                              f"{unit} result requires fit.parameters['g_over_l']")
            if unit == "m/s^2" and (
                    fit.pivot_length_mm is None
                    or fit.pivot_length_source is not LengthSource.INDEPENDENT_MEASUREMENT
                    or fit.gravity_m_s2 is None):
                collector.add("E_INCOHERENT_STATE", "fit",
                              "m/s^2 result requires independent pivot length and gravity_m_s2")
            expected = fit.g_over_l_per_s2 if unit == "1/s^2" else fit.gravity_m_s2
            if expected is None or value != expected:
                collector.add("E_INCOHERENT_STATE", "value",
                              "result value disagrees with its supporting fit quantity")
        collector.raise_if_errors()
        assert status is not None and measurement_name is not None and quantity is not None
        assert warnings is not None and reasons is not None and provenance is not None
        assert exports is not None
        return cls(schema_version=RESULT_VERSION, status=status,
                   measurement_name=measurement_name, value=value, unit=unit,
                   interval=interval, interval_method=interval_method,
                   identifiable_quantity=quantity, calibration=calibration, fit=fit,
                   quality_metrics=metrics, assumptions=tuple(assumptions),
                   warnings=tuple(warnings), reject_reasons=tuple(reasons),
                   provenance=provenance, exports=tuple(exports))


SCHEMAS = {
    "media": MediaMetadata,
    "frame": FrameRecord,
    "observation": ObservationRecord,
    "calibration": CalibrationRecord,
    "fit": FitRecord,
    "result": ResultContract,
}


def parse_record(schema: str, data: Any) -> Any:
    """Parse ``data`` with the named schema. Raises ``ContractError``."""
    if not isinstance(schema, str) or schema not in SCHEMAS:
        raise ContractError([FieldError("E_BAD_SCHEMA", "schema",
                                        f"unknown schema {schema!r}; "
                                        f"expected one of {sorted(SCHEMAS)}")])
    return SCHEMAS[schema].from_dict(data)


def parse_json(schema: str, text: str) -> Any:
    """Parse a JSON document with the named schema. Raises ``ContractError``."""
    if not isinstance(text, str):
        raise ContractError([FieldError("E_MALFORMED_JSON", None,
                                        f"input must be a JSON string, "
                                        f"got {type(text).__name__}")])
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ContractError([FieldError("E_MALFORMED_JSON", None,
                                        f"invalid JSON: {error}")]) from None
    return parse_record(schema, data)
