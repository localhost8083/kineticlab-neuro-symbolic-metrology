"""Saved SAM fixture adapter (KL-3.1).

Parses raw SAM response fixtures (one vendor record per line) into
``observation.v1`` records. The vendor format stops at this adapter:
only contract-shaped ``ObservationRecord`` objects cross into the
package. Model output is untrusted telemetry — every record passes
through ``ObservationRecord.from_dict``, and malformed input raises
registered ``ContractError`` codes naming the raw file and line.

Observed vendor grammar (``Smoke/results/*_raw.txt``)::

    line     := "<" frame "f>" track "<|" boxseg "|><|" maskseg "|>"
    boxseg   := "box" (";" key "=" value)*
    maskseg  := "mask" (";" key "=" value)*

Required vendor keys are box ``x1``/``y1``/``x2``/``y2``/``c`` and mask
``c``/``data``; anything else (``w``/``h``/``x``/``y``, future keys) is
parsed structurally and ignored. Mask ``data`` runs to the end of its
segment as ``d0,d1,payload`` (row count, column count: ``H,W``
order per the bytes); its transport framing is validated by
``mask_framing.decode_mask_data`` (KL-3.2), the one_bit stream is
decoded to a box-relative raster by ``mask_codec`` (with a canonical
re-encode gate), and malformed payloads fail fast with registered
codes. Box and mask confidences must agree exactly (raw-string
comparison). Centroid/area come only from decoded mask bits (never
bbox centers); each record's ``mask_reference`` points at its raw
bytes as ``"<path>#L<line>"``.

Mapping (explicit and auditable): vendor frame marker -> processing
``frame_index``; ``pts_seconds`` joined from the caller's ingest frame
table (no nominal-FPS substitution ever); ``object_role``/``object_id``
and ``model_name``/``model_version`` are caller-declared — the raw bytes
carry no role, id, or version, and the adapter never parses identity
out of the filename. ``source`` is always ``sam_fixture`` (the
adapter's own nature, not a vendor claim). Provenance records the raw
file bytes' sha256 and the raw path; ``raw_refs`` carries the path as
given.

Validity: records are ``valid`` with no warnings once the mask
decodes (centroid pair + positive area from mask bits) and the
source row is valid with PTS present (full ``FrameRecord``
join). A record whose frame has no source PTS is retained
invalid with ``W_MISSING_FRAMES_RETAINED`` (geometry decoded but
unvalidatable); a record whose source row was withdrawn by the
ingest decision is likewise invalid, with its measured PTS
retained and the withdrawal named. Box, confidence, PTS, and raw
references are always retained. ``W_PARTIAL_OBSERVATION`` no
longer appears: partial geometry is failure, not a warning, on
this path.

Failure mapping (all explicit, all registered codes, never silent;
every detail names the raw file):

- missing/unreadable file -> ``E_MISSING_FIELD`` on ``raw_path``;
- undecodable bytes -> ``E_NOT_AN_OBJECT`` on ``raw_path``;
- line with no frame marker -> ``E_MISSING_FIELD`` on ``frame_index``;
- missing box/mask segment or required vendor key ->
  ``E_MISSING_FIELD`` on the contract destination (``bbox``/
  ``confidence``/``mask_reference``);
- malformed line structure or key=value token -> ``E_NOT_AN_OBJECT``
  on that line;
- malformed ``d0,d1,payload`` interior, bad magic/header/tail, or
  non-alphabet char -> ``E_NOT_AN_OBJECT``/``E_WRONG_TYPE``/
  ``E_OUT_OF_RANGE``/``E_EMPTY_STRING``/``E_BAD_ENUM`` on
  ``mask_reference`` (see ``mask_framing``);
- payload pieces that contradict each other (declared-length
  mismatch, group/tail >= u32, re-pack mismatch) ->
  ``E_INCOHERENT_VALUE`` on ``mask_reference``;
- range stream too short, exhausted mid-raster, invalid coding
  state, non-canonical re-encode, or zero-bit mask ->
  ``E_INCOHERENT_VALUE`` on ``mask_reference`` (content
  contradicts its framing; centroid never fabricated);
- non-numeric vendor number -> ``E_WRONG_TYPE`` on its contract field;
- box/mask confidence disagreement -> ``E_INCOHERENT_VALUE`` on
  ``confidence``;
- mixed track ids in one file -> ``E_INCOHERENT_VALUE`` on
  ``object_id`` (one id cannot cover mixed tracks);
- frame with no matching source frame -> ``E_OUT_OF_RANGE`` on
  ``frame_index``;
- duplicate processing index in the frame table -> ``E_DUPLICATE_FRAME``
  (join would be ambiguous);
- repeated raw frame marker -> ``E_DUPLICATE_FRAME`` on
  ``frame_index`` (the offending line number is in the detail);
- value rejections (bad role/id/version, confidence range, bbox
  order, finiteness) propagate from ``ObservationRecord.from_dict``
  with codes preserved and the raw file+line appended.

An empty file (or one with only blank lines) parses to ``[]``: zero
vendor records in, zero observation records out. Blank lines carry no
record and are skipped, never failed.

This adapter decodes masks and derives geometry (KL-3.2) but does
NOT judge quality or anomalies (KL-4), calibrate (KL-6), or fit
physics (KL-5).
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from kineticlab import __version__
from kineticlab.contracts import (
    ContractError,
    FieldError,
    FrameRecord,
    ObservationRecord,
)
from kineticlab.observation.mask_codec import (
    check_canonical,
    decode_raster,
    raster_geometry,
)
from kineticlab.observation.mask_framing import DecodedMaskFraming, decode_mask_data

_LINE_HEAD = re.compile(r"<(\d+)f>(\d+)<\|")
_BOX_KEYS = ("x1", "y1", "x2", "y2")
_REQUIRED_BOX_KEYS = _BOX_KEYS + ("c",)


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _read_raw_text(path: str | Path) -> tuple[str, str, str]:
    """Return (display path, text, sha256) or raise a coded ``ContractError``."""
    display = str(path)
    try:
        data = Path(path).read_bytes()
    except FileNotFoundError as error:
        _fail("E_MISSING_FIELD", "raw_path",
              f"raw fixture not found: {display}")
    except OSError as error:
        _fail("E_MISSING_FIELD", "raw_path",
              f"raw fixture unreadable: {display}: {error}")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail("E_NOT_AN_OBJECT", "raw_path",
              f"raw fixture is not UTF-8 text: {display}: {error}")
    return display, text, hashlib.sha256(data).hexdigest()


def _parse_number(token: str, field: str, where: str) -> float:
    try:
        return float(token)
    except ValueError:
        _fail("E_WRONG_TYPE", field, f"{where} is not a number: {token!r}")
    raise AssertionError("unreachable")  # _fail always raises


def _segment_fields(segment: str, tag: str, display: str, line_no: int) -> dict:
    """Split a ``tag;k=v;...`` segment into its value dict."""
    tokens = segment.split(";")
    fields: dict[str, str] = {}
    for token in tokens[1:]:
        key, separator, value = token.partition("=")
        if not separator or not key:
            _fail("E_NOT_AN_OBJECT", f"line {line_no}",
                  f"raw {display} line {line_no}: malformed {tag} token {token!r}")
        fields[key] = value
    return fields


def _parse_line(display: str, line_no: int, line: str
                ) -> tuple[int, str, list, float, DecodedMaskFraming]:
    """Parse one vendor line into (frame, track, bbox, confidence, framing)."""
    where = f"raw {display} line {line_no}"
    head = _LINE_HEAD.match(line)
    if head is None:
        _fail("E_MISSING_FIELD", "frame_index",
              f"{where}: no frame marker `<Nf>`")
    assert head is not None
    frame = int(head.group(1))
    track = head.group(2)
    rest = line[head.end():]
    if not rest.startswith("box;"):
        _fail("E_MISSING_FIELD", "bbox", f"{where}: no box segment")
    parts = rest.split("|><|")
    if len(parts) < 2:
        _fail("E_MISSING_FIELD", "mask_reference", f"{where}: no mask segment")
    if len(parts) > 2:
        _fail("E_NOT_AN_OBJECT", f"line {line_no}",
              f"{where}: extra segment delimiters")
    if not parts[1].startswith("mask;") or not parts[1].endswith("|>"):
        _fail("E_MISSING_FIELD", "mask_reference", f"{where}: no mask segment")
    box = _segment_fields(parts[0], "box", display, line_no)
    mask_head, data_sep, data_value = parts[1][:-2].partition(";data=")
    if not data_sep:
        _fail("E_MISSING_FIELD", "mask_reference", f"{where}: mask lacks `data`")
    mask = _segment_fields(mask_head, "mask", display, line_no)
    mask["data"] = data_value
    for key in _REQUIRED_BOX_KEYS:
        if key not in box:
            field = "confidence" if key == "c" else "bbox"
            _fail("E_MISSING_FIELD", field, f"{where}: box lacks `{key}`")
    if "c" not in mask:
        _fail("E_MISSING_FIELD", "confidence", f"{where}: mask lacks `c`")
    if box["c"] != mask["c"]:
        _fail("E_INCOHERENT_VALUE", "confidence",
              f"{where}: box confidence {box['c']!r} disagrees with "
              f"mask confidence {mask['c']!r}")
    # KL-3.2: malformed payloads fail fast here with registered codes.
    framing = decode_mask_data(mask["data"], ref=f"{display}#L{line_no}")
    bbox = [_parse_number(box[key], "bbox", f"{where} box `{key}`")
            for key in _BOX_KEYS]
    confidence = _parse_number(box["c"], "confidence", f"{where} confidence")
    return frame, track, bbox, confidence, framing


def find_multisegment_lines(text: str) -> list[int]:
    """Return 1-based numbers of lines carrying extra wire segments.

    KL-9.2 item 2: detect-stage pre-validation. Mirrors the
    delimiter rule in :func:`_parse_line` exactly (same head
    pattern, same ``box;`` guard, same ``|><|`` split): any line
    number returned here would fail canonical parsing with
    ``E_NOT_AN_OBJECT`` "extra segment delimiters" — a second
    model segment for one prompt. Lines failing for other
    reasons are NOT flagged; the canonical parser reports those
    with its own codes. Never raises.
    """
    bad: list[int] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        head = _LINE_HEAD.match(line)
        if head is None:
            continue
        rest = line[head.end():]
        if not rest.startswith("box;"):
            continue
        if len(rest.split("|><|")) > 2:
            bad.append(line_no)
    return bad


def parse_raw_fixture(path: str | Path, *, object_role: str, object_id: str,
                      frame_table: list[FrameRecord],
                      model_name: str | None = None,
                      model_version: str | None = None) -> list[ObservationRecord]:
    """Parse a saved SAM raw fixture into ``observation.v1`` records (KL-3.1).

    ``frame_table`` is the ingest frame table (e.g. from
    ``extract_frame_records``) that supplies real source PTS per
    processing frame. ``object_role``/``object_id`` and
    ``model_name``/``model_version`` are caller-declared identity: the
    raw bytes carry none of them, so absent version info stays null.
    Fails fast with a registered code on the first bad line; never
    returns a partial list, never drops a record silently.
    """
    display, text, digest = _read_raw_text(path)
    frame_by_index: dict[int, FrameRecord] = {}
    for record in frame_table:
        if record.frame_index in frame_by_index:
            _fail("E_DUPLICATE_FRAME", f"frame_index={record.frame_index}",
                  f"frame table has duplicate processing index "
                  f"{record.frame_index}; PTS join for raw {display} "
                  f"would be ambiguous")
        frame_by_index[record.frame_index] = record
    records: list[ObservationRecord] = []
    expected_track: str | None = None
    seen_frames: set[int] = set()
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        frame, track, bbox, confidence, framing = _parse_line(
            display, line_no, line)
        if expected_track is None:
            expected_track = track
        elif track != expected_track:
            _fail("E_INCOHERENT_VALUE", "object_id",
                  f"raw {display} line {line_no}: track {track} differs from "
                  f"track {expected_track}; one object_id cannot cover mixed tracks")
        if frame not in frame_by_index:
            _fail("E_OUT_OF_RANGE", "frame_index",
                  f"raw {display} line {line_no}: frame {frame} has no "
                  f"matching source frame")
        if frame in seen_frames:
            _fail("E_DUPLICATE_FRAME", "frame_index",
                  f"raw {display} line {line_no}: frame marker {frame} "
                  "repeats an earlier line")
        seen_frames.add(frame)
        mask_ref = f"{display}#L{line_no}"
        raster = decode_raster(framing.opaque, framing.width, framing.height,
                               ref=mask_ref)
        check_canonical(framing.payload, raster, framing.width, framing.height,
                        ref=mask_ref)
        area, centroid_x, centroid_y = raster_geometry(
            raster, framing.width, framing.height,
            x1=bbox[0], y1=bbox[1], ref=mask_ref)
        frame_record = frame_by_index[frame]
        pts_seconds = frame_record.pts_seconds
        record_valid = frame_record.valid and pts_seconds is not None
        if record_valid:
            warnings = []
        elif pts_seconds is None:
            warnings = [{
                "code": "W_MISSING_FRAMES_RETAINED",
                "detail": ("source PTS unavailable; mask geometry decoded but "
                           "the record cannot validate without PTS"),
            }]
        else:
            warnings = [{
                "code": "W_MISSING_FRAMES_RETAINED",
                "detail": ("source frame withdrawn by ingest decision "
                           "(valid=False); mask geometry decoded but the "
                           "record stays invalid"),
            }]
        try:
            records.append(ObservationRecord.from_dict({
                "schema_version": "observation.v1",
                "frame_index": frame,
                "pts_seconds": pts_seconds,
                "object_role": object_role,
                "object_id": object_id,
                "confidence": confidence,
                "bbox": bbox,
                "centroid_x_px": centroid_x,
                "centroid_y_px": centroid_y,
                "mask_area_px": float(area),
                "mask_reference": mask_ref,
                "valid": record_valid,
                "source": "sam_fixture",
                "warnings": warnings,
                "provenance": {
                    "software_name": "kineticlab",
                    "software_version": __version__,
                    "input_sha256": digest,
                    "model_name": model_name,
                    "model_version": model_version,
                    "raw_refs": [display],
                },
            }))
        except ContractError as error:
            raise ContractError([
                FieldError(item.code, item.field,
                           f"{item.message} (raw {display} line {line_no})")
                for item in error.errors
            ]) from error
    return records
