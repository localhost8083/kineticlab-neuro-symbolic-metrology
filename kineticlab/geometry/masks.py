"""Per-frame mask rasters for geometry (P-006).

Observation records carry derived geometry (centroid, area, bbox) but
not the rasters themselves, and ``kineticlab/observation`` is frozen
for P-006 — so this module re-reads the same raw wire file and
re-decodes every mask through the SAME public codec chain the
adapter uses (``decode_mask_data`` framing laws, ``decode_raster``
range/context decode, ``check_canonical`` round-trip gate). The only
new parsing is a minimal strict split of each wire line into frame
marker, box numbers, and the ``data=`` value; its rules mirror the
adapter's, with one deliberate difference: non-finite box numbers
fail here (``E_NON_FINITE``) instead of deferring to contract
validation, because masks at infinite coordinates are meaningless
to geometry. Decoded rasters are placed at the wire box
origin: frame pixel ``(x1 + col, y1 + row)``.

Frame-set agreement with the caller-supplied records is enforced:
masks for exactly the record frames, no silent drops, no extras.

Stdlib only. No network. Deterministic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kineticlab.contracts import ContractError, FieldError
from kineticlab.observation.mask_codec import check_canonical, decode_raster
from kineticlab.observation.mask_framing import decode_mask_data

_LINE_HEAD = re.compile(r"^<(\d+)f>([^<]*)<\|")
"""Frame marker + track, mirroring the adapter's line head."""


@dataclass(frozen=True)
class FrameMask:
    """One decoded one-bit mask placed at its wire box origin."""

    frame_index: int
    width: int
    height: int
    x1: float
    y1: float
    raster: bytes

    def set_pixels(self) -> list[tuple[float, float]]:
        """Frame coordinates of every set bit, row-major (deterministic)."""
        pixels: list[tuple[float, float]] = []
        for row in range(self.height):
            base = row * self.width
            for col in range(self.width):
                if self.raster[base + col]:
                    pixels.append((self.x1 + col, self.y1 + row))
        return pixels


def _fail(code: str, field: str | None, detail: str) -> None:
    raise ContractError([FieldError(code, field, detail)])


def _parse_number(token: str, field: str, where: str) -> float:
    try:
        value = float(token)
    except ValueError:
        _fail("E_WRONG_TYPE", field,
              f"{where}: {field} is not numeric: {token!r}")
        raise AssertionError("unreachable")
    if not math.isfinite(value):
        _fail("E_NON_FINITE", field,
              f"{where}: {field} is not finite: {token!r}")
    return value


def _fields(segment: str, tag: str, where: str) -> dict[str, str]:
    # Same rule as the adapter's _segment_fields: skip the tag token,
    # fail malformed tokens, last duplicate wins. The mask payload
    # never reaches here (partitioned off by ";data=" first).
    fields: dict[str, str] = {}
    for token in segment.split(";")[1:]:
        key, separator, value = token.partition("=")
        if not separator or not key:
            _fail("E_NOT_AN_OBJECT", tag,
                  f"{where}: malformed {tag} token {token!r}")
        fields[key] = value
    return fields


def _parse_line(display: str, line_no: int,
                line: str) -> tuple[int, dict[str, float], str]:
    """Split one wire line into (frame, box numbers, mask data value)."""
    where = f"raw {display} line {line_no}"
    head = _LINE_HEAD.match(line)
    if head is None:
        _fail("E_MISSING_FIELD", "frame_index", f"{where}: no frame marker")
    assert head is not None
    frame = int(head.group(1))
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
    box = _fields(parts[0], "box", where)
    mask_head, data_sep, data_value = parts[1][:-2].partition(";data=")
    if not data_sep:
        _fail("E_MISSING_FIELD", "mask_reference",
              f"{where}: mask lacks `data`")
    mask = _fields(mask_head, "mask", where)
    for key in ("x1", "y1", "x2", "y2", "c"):
        if key not in box:
            _fail("E_MISSING_FIELD", "bbox", f"{where}: box lacks `{key}`")
    if "c" not in mask:
        _fail("E_MISSING_FIELD", "confidence", f"{where}: mask lacks `c`")
    if box["c"] != mask["c"]:
        _fail("E_INCOHERENT_VALUE", "confidence",
              f"{where}: box/mask confidence disagree")
    numbers = {key: _parse_number(box[key], "bbox", where)
               for key in ("x1", "y1", "x2", "y2")}
    _parse_number(box["c"], "confidence", where)
    return frame, numbers, data_value


def decode_frame_masks(raw_path: str | Path,
                       records: list[Any]) -> list[FrameMask]:
    """Decode every mask for exactly the given records' frames.

    ``records`` supplies the expected frame set (any objects with an
    int ``frame_index``; normally ``ObservationRecord``). Each wire
    line runs the full public codec chain; canonical mismatch,
    undecodable payloads, and confidence disagreement fail fast with
    registered codes naming file+line. Missing or extra frames fail
    with ``E_MISSING_MAPPING`` / ``E_INCOHERENT_VALUE``.
    """
    path = Path(raw_path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        _fail("E_MALFORMED_JSON", None,
              f"raw wire file is unreadable as UTF-8 text: {error}")
        raise AssertionError("unreachable")
    try:
        display = str(path.relative_to(Path.cwd()))
    except ValueError:
        display = path.name
    required: set[int] = set()
    for index, record in enumerate(records):
        frame_index = getattr(record, "frame_index", None)
        if isinstance(frame_index, bool) \
                or not isinstance(frame_index, int):
            _fail("E_WRONG_TYPE", f"records[{index}].frame_index",
                  "expected an int frame_index, got "
                  f"{type(frame_index).__name__}")
        required.add(frame_index)
    parsed: dict[int, tuple[dict[str, float], str, int]] = {}
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        frame, numbers, data_value = _parse_line(display, line_no, line)
        if frame in parsed:
            _fail("E_DUPLICATE_FRAME", "frame_index",
                  f"raw {display} line {line_no}: frame {frame} repeats")
        parsed[frame] = (numbers, data_value, line_no)
    missing = sorted(required - set(parsed))
    if missing:
        _fail("E_MISSING_MAPPING", "frame_index",
              f"raw {display}: no mask lines for frames {missing[:5]}")
    extra = sorted(set(parsed) - required)
    if extra:
        _fail("E_INCOHERENT_VALUE", "frame_index",
              f"raw {display}: mask lines without records {extra[:5]}")
    masks: list[FrameMask] = []
    for frame in sorted(required):
        numbers, data_value, line_no = parsed[frame]
        ref = f"{display}#L{line_no}"
        framing = decode_mask_data(data_value, ref=ref)
        raster = decode_raster(framing.opaque, framing.width,
                               framing.height, ref=ref)
        check_canonical(framing.payload, raster, framing.width,
                        framing.height, ref=ref)
        masks.append(FrameMask(frame_index=frame, width=framing.width,
                               height=framing.height, x1=numbers["x1"],
                               y1=numbers["y1"], raster=raster))
    return masks
