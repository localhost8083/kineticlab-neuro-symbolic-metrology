"""Media validation, stream metadata (KL-2.1), frame timing (KL-2.2), run gates (KL-2.3).

``inspect_media`` produces validated ``media.v1`` records from local video
files using the shared stdlib MP4 parser in ``kineticlab.ingest.mp4``.
``extract_frame_times`` returns the raw decode-order timing entries and
``extract_frame_records`` the validated ``frame.v1`` table; ffprobe-based
decode arrives in later work. ``verify_copy_identity`` adds an optional
byte-identity check for a claimed processing copy, and
``check_frame_table`` gates a frame table for run readiness.

Timing mapping (explicit and auditable): processing ``frame_index``
(0-based, decode order) -> ``source_frame_index`` (0-based source sample
number) -> ``pts_seconds`` (PTS units / ``mdhd`` timescale, exact integer
ratio) -> ``decoded_reference`` (opaque ``sample:N`` source-sample handle;
no pixel decode is performed). PTS = DTS + ``ctts`` offset when ``ctts``
exists, else PTS = DTS. Edit lists (``elst``) are not applied: times are
track-timeline values, never shifted, clamped, or re-zeroed, so finite
negative PTS (preroll) is preserved as-is.

Validity is judged on exact integer PTS units, before float conversion: a
frame is valid only when its PTS is strictly after the previous valid
frame's PTS. Out-of-order frames (B-frame reorder in decode order) are
withdrawn from the monotonic run but retained in the table with their
measured values and ``W_MISSING_FRAMES_RETAINED``; nulls are reserved for
genuinely missing data. ``duration_seconds`` stays null: a decode delta
is not a presentation duration. No timestamp is ever synthesized from
any frame rate.

Copy identity (KL-2.3): a claimed processing copy is confirmed only by
sha256 equality with the source bytes — byte-identical, never
"close enough". Confirmed copies are recorded in
``processing_copy_path``/``processing_copy_sha256`` with no warning
(identical bytes need no ``W_DERIVED_COPY``); an absent copy keeps both
null, exactly as ``inspect_media`` alone; differing bytes fail
explicitly, never a silent fallback to the source.

Timing gates (KL-2.3): ``check_frame_table`` audits a ``frame.v1``
table in one deterministic pass — contract table rules first
(``validate_frame_table`` is wrapped, never bypassed or re-implemented),
then missing timing (any null ``pts_seconds`` fails), then the usable
floor (fewer than ``MINIMUM_USABLE_FRAMES`` valid frames fails). One
timed frame defines no interval, so the floor is 2. Withdrawn frames
(invalid but measured, e.g. B-frame reorder) pass with their counts
acknowledged in the returned report; only genuinely missing timing
fails the missing gate.

Failure mapping (all explicit, all registered codes, never silent):

- missing/unreadable file -> ``E_MISSING_FIELD`` on ``source_path``
  (or ``processing_copy_path`` for the claimed copy);
- unparseable bytes or unreadable/contradictory sample table
  (``ProbeError``) -> ``E_NOT_AN_OBJECT`` on ``source_path`` with the
  probe detail;
- claimed copy bytes differ from source bytes ->
  ``E_INCOHERENT_VALUE`` on ``processing_copy_path``;
- frame-table gates: duplicates/non-monotonic propagate from
  ``validate_frame_table`` (``E_DUPLICATE_FRAME``/
  ``E_NON_MONOTONIC_PTS``); null PTS -> ``E_NULL_NOT_ALLOWED``;
  usable frames below the floor -> ``E_OUT_OF_RANGE``;
- container/codec/stream-count/geometry/scope violations and missing
  structural essentials -> raised by ``MediaMetadata.from_dict``
  (``E_BAD_ENUM``/``E_OUT_OF_RANGE``/``E_NULL_NOT_ALLOWED``/
  ``E_INCOHERENT_VALUE``). Ingest never re-validates by hand what the
  contract enforces.

Container identification maps ISO BMFF brands (``isom``, ``iso2``,
``mp41``, ``mp42``) to ``mp4``; anything else passes through raw so the
v1 scope check rejects it explicitly. ``time_base`` is the video track
``mdhd`` timescale (``1/N``), the unit of per-frame timing in KL-2.2.
``nominal_frame_rate`` and ``pixel_format`` stay null without ffprobe:
a measured ratio is not a nominal rate, and pixel format needs a
decoder. Processing copies are never made here; a claimed copy is only
recorded after byte-identity verification (KL-2.3).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from kineticlab import __version__
from kineticlab.contracts import (
    ContractError,
    FieldError,
    FrameRecord,
    MediaMetadata,
    validate_frame_table,
)
from kineticlab.ingest.mp4 import ProbeError, extract_sample_timing, probe_bytes

MP4_BRANDS = frozenset({"isom", "iso2", "mp41", "mp42"})
"""ISO BMFF major brands identified as the ``mp4`` container."""

MINIMUM_USABLE_FRAMES = 2
"""Fewest valid timed frames that make a table usable for a run (KL-2.3).

One timed frame defines no interval, so a run needs at least two
usable frames; anything less is unusable timing (``E_OUT_OF_RANGE``).
"""


def _read_source_bytes(path: str | Path, *, field: str = "source_path",
                       what: str = "media file") -> tuple[str, bytes, str]:
    """Return (display path, file bytes, sha256) or raise a coded ``ContractError``."""
    display = str(path)
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError as error:
        raise ContractError([FieldError(
            "E_MISSING_FIELD", field,
            f"{what} not found: {display}")]) from error
    except OSError as error:
        raise ContractError([FieldError(
            "E_MISSING_FIELD", field,
            f"{what} unreadable: {display}: {error}")]) from error
    return display, data, hashlib.sha256(data).hexdigest()


def _read_sample_timing(display: str, data: bytes) -> dict:
    """Return the parsed video sample timing or raise a coded ``ContractError``."""
    try:
        return extract_sample_timing(data)
    except ProbeError as error:
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", "source_path",
            f"file has no readable video sample table: {error}")]) from error


def _frame_provenance(digest: str) -> dict:
    return {
        "software_name": "kineticlab",
        "software_version": __version__,
        "input_sha256": digest,
        "model_name": None,
        "model_version": None,
        "raw_refs": [],
    }


def verify_copy_identity(source_path: str | Path,
                         copy_path: str | Path | None = None) -> MediaMetadata:
    """Build a validated ``media.v1`` record, verifying a claimed copy (KL-2.3).

    With no ``copy_path`` this is exactly ``inspect_media``: copy fields
    stay null. With a claimed copy, the copy bytes must be sha256-equal
    to the source bytes, and the confirmed path and hash are recorded;
    differing bytes raise ``E_INCOHERENT_VALUE`` — never a silent
    fallback to the source. Raises ``ContractError`` with a registered
    code on any failure.
    """
    display, data, digest = _read_source_bytes(source_path)
    copy_display: str | None = None
    copy_digest: str | None = None
    if copy_path is not None:
        copy_display, _, copy_digest = _read_source_bytes(
            copy_path, field="processing_copy_path", what="processing copy")
        if copy_digest != digest:
            raise ContractError([FieldError(
                "E_INCOHERENT_VALUE", "processing_copy_path",
                f"processing copy bytes differ from source bytes: "
                f"{copy_digest} != {digest}")])
    try:
        report = probe_bytes(data, display)
    except ProbeError as error:
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", "source_path",
            f"file is not a parseable MP4 structure: {error}")]) from error
    major_brand = report["major_brand"]
    container = "mp4" if major_brand in MP4_BRANDS else major_brand
    codec = report["codec"] if report["codec"] is not None else report["codec_tag"]
    timescale = report["timescale"]
    warnings = []
    if report["timing_uniform"] is False:
        warnings.append({"code": "W_VFR_TIMING",
                         "detail": "video stts timing is non-uniform; no nominal rate"})
    return MediaMetadata.from_dict({
        "schema_version": "media.v1",
        "source_path": display,
        "source_sha256": digest,
        "container": container,
        "video_stream_count": report["video_track_count"],
        "audio_stream_count": report["audio_track_count"],
        "codec": codec,
        "width": report["width"],
        "height": report["height"],
        "pixel_format": None,
        "duration_seconds": report["duration_s"],
        "frame_count": report["frames"],
        "nominal_frame_rate": None,
        "time_base": f"1/{timescale}" if timescale else None,
        "processing_copy_path": copy_display,
        "processing_copy_sha256": copy_digest,
        "valid": True,
        "warnings": warnings,
        "provenance": _frame_provenance(digest),
    })


def inspect_media(path: str | Path) -> MediaMetadata:
    """Build a validated ``media.v1`` record for a local video file.

    Reads the file bytes once: the same bytes are hashed for
    ``source_sha256`` and structurally parsed. Copy fields stay null
    (see ``verify_copy_identity``). Raises ``ContractError`` with a
    registered code on any failure; never returns a partial or guessed
    record.
    """
    return verify_copy_identity(path, None)


def check_frame_table(records: list[FrameRecord],
                      *, minimum_usable_frames: int = MINIMUM_USABLE_FRAMES) -> dict:
    """Audit a ``frame.v1`` table for run readiness (KL-2.3).

    Gates run in one deterministic pass; the first failure raises
    ``ContractError`` with its registered code:

    1. contract table rules via ``validate_frame_table`` (duplicates ->
       ``E_DUPLICATE_FRAME``, non-monotonic PTS ->
       ``E_NON_MONOTONIC_PTS``; wrapped, never bypassed or re-implemented);
    2. missing timing: any null ``pts_seconds`` ->
       ``E_NULL_NOT_ALLOWED``;
    3. usable floor: fewer than ``minimum_usable_frames`` valid frames ->
       ``E_OUT_OF_RANGE``.

    Withdrawn frames (invalid but measured) pass; their counts are
    acknowledged in the returned report: ``total_frames``,
    ``usable_frames``, ``withdrawn_frames``, ``missing_frames`` (always
    0 here — any missing frame fails gate 2), ``minimum_usable_frames``.
    """
    validate_frame_table(records)
    for record in records:
        if record.pts_seconds is None:
            raise ContractError([FieldError(
                "E_NULL_NOT_ALLOWED",
                f"frame_index={record.frame_index}.pts_seconds",
                "frame has no PTS; missing timing cannot run")])
    usable = sum(1 for record in records if record.valid)
    if usable < minimum_usable_frames:
        raise ContractError([FieldError(
            "E_OUT_OF_RANGE", "usable_frame_count",
            f"{usable} usable frames below minimum {minimum_usable_frames}")])
    return {
        "total_frames": len(records),
        "usable_frames": usable,
        "withdrawn_frames": sum(1 for record in records if not record.valid),
        "missing_frames": 0,
        "minimum_usable_frames": minimum_usable_frames,
    }


def extract_frame_times(path: str | Path) -> list[dict]:
    """Return one timing entry per video sample in decode order (KL-2.2).

    Each entry maps processing ``frame_index`` (0-based) to
    ``source_frame_index``, ``pts_seconds`` (exact PTS units over the
    ``mdhd`` timescale), and the ``valid`` monotonic-run flag. Validity
    is judged on integer PTS units before float conversion. Raises
    ``ContractError`` with a registered code on any failure.
    """
    display, data, _digest = _read_source_bytes(path)
    timing = _read_sample_timing(display, data)
    timescale = timing["timescale"]
    entries = []
    previous_pts: int | None = None
    for processing_index, sample in enumerate(timing["samples"]):
        pts_units = sample["pts"]
        valid = previous_pts is None or pts_units > previous_pts
        if valid:
            previous_pts = pts_units
        entries.append({
            "frame_index": processing_index,
            "source_frame_index": processing_index,
            "pts_seconds": pts_units / timescale,
            "valid": valid,
        })
    return entries


def extract_frame_records(path: str | Path) -> list[FrameRecord]:
    """Return the validated ``frame.v1`` table for a local video file.

    Every processing index appears exactly once. Frames withdrawn from
    the monotonic run stay in the table with their measured values,
    ``valid`` false, and ``W_MISSING_FRAMES_RETAINED``. The table passes
    ``validate_frame_table`` before it is returned. Raises
    ``ContractError`` with a registered code on any failure.
    """
    display, data, digest = _read_source_bytes(path)
    timing = _read_sample_timing(display, data)
    timescale = timing["timescale"]
    records = []
    previous_pts: int | None = None
    for processing_index, sample in enumerate(timing["samples"]):
        pts_units = sample["pts"]
        pts_seconds = pts_units / timescale
        valid = previous_pts is None or pts_units > previous_pts
        warnings = []
        if valid:
            previous_pts = pts_units
        else:
            warnings.append({
                "code": "W_MISSING_FRAMES_RETAINED",
                "detail": (f"PTS {pts_seconds} is not strictly after the previous "
                           "valid PTS; withdrawn from the monotonic run, "
                           "measured values retained"),
            })
        records.append(FrameRecord.from_dict({
            "schema_version": "frame.v1",
            "frame_index": processing_index,
            "source_frame_index": processing_index,
            "pts_seconds": pts_seconds,
            "duration_seconds": None,
            "decoded_reference": f"sample:{processing_index}",
            "valid": valid,
            "warnings": warnings,
            "provenance": _frame_provenance(digest),
        }))
    validate_frame_table(records)
    return records
