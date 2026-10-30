"""Inspectable chain overlay as deterministic SVG bytes (KL-4.2).

One artifact per chain for human inspection: bbox rectangles plus
centroid dots in frame order over the given video dimensions, with
a centroid path polyline, a chain-verdict caption, and a fixed
legend. Flagged frames render red, the rest steelblue; verdict and
legend text use a monospace face so the file stays readable in any
SVG viewer. Pure stdlib (string building only), offline, no UI code.

Determinism: element order follows input order, numbers render via
repr (exact, no locale dependence), and nothing embeds timestamps
or paths — output is byte-stable for identical inputs and
pin-friendly. Records lacking bbox/centroid simply skip those
shapes (never a crash); an empty chain still yields a valid SVG
with verdict and legend.

Malformed inputs reuse registered codes: non-record items ->
``E_WRONG_TYPE``; non-dict assessment -> ``E_NOT_AN_OBJECT``;
non-integer or non-positive video dimensions -> ``E_WRONG_TYPE`` /
``E_OUT_OF_RANGE``; non-string label -> ``E_WRONG_TYPE``.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from kineticlab.contracts import (
    ContractError,
    FieldError,
    ObservationRecord,
)

_OK_COLOR = "#4682b4"
_FLAG_COLOR = "#cc0000"
_PATH_COLOR = "#888888"
_TEXT_COLOR = "#eeeeee"
_BACKGROUND = "#111111"
_FONT = "monospace"


def _number(value: Any) -> str:
    if isinstance(value, bool):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None, "overlay coordinate must be numeric")])
    if not isinstance(value, (int, float)):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None, "overlay coordinate must be numeric")])
    return repr(value)


def export_overlay_svg(records: list[ObservationRecord],
                       video_width: int, video_height: int,
                       assessment: dict[str, Any],
                       *, label: str = "") -> bytes:
    """Draw one chain as deterministic SVG bytes over video dimensions."""
    for index, record in enumerate(records):
        if not isinstance(record, ObservationRecord):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", None,
                f"overlay item [{index}] is not an ObservationRecord: "
                f"{type(record).__name__}")])
    for name, size in (("video_width", video_width),
                       ("video_height", video_height)):
        if isinstance(size, bool) or not isinstance(size, int):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", None,
                f"overlay {name} must be an int, got {type(size).__name__}")])
        if size <= 0:
            raise ContractError([FieldError(
                "E_OUT_OF_RANGE", None,
                f"overlay {name} must be positive, got {size}")])
    if not isinstance(assessment, dict):
        raise ContractError([FieldError(
            "E_NOT_AN_OBJECT", None,
            f"overlay assessment must be a dict, got "
            f"{type(assessment).__name__}")])
    if not isinstance(label, str):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", None,
            f"overlay label must be a string, got {type(label).__name__}")])
    entries = assessment.get("frames", [])
    if not isinstance(entries, list):
        raise ContractError([FieldError(
            "E_WRONG_TYPE", "frames",
            f"expected a list, got {type(entries).__name__}")])
    flagged: dict[int, bool] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", f"frames[{index}]",
                f"expected a dict, got {type(entry).__name__}")])
        frame = entry.get("frame_index")
        if isinstance(frame, bool) or not isinstance(frame, int):
            raise ContractError([FieldError(
                "E_WRONG_TYPE", f"frames[{index}].frame_index",
                f"expected a frame index int, got {type(frame).__name__}")])
        flagged.setdefault(frame, entry.get("flagged_any") is True)
    if assessment.get("assessable") is None and "fit_worthy" not in assessment:
        verdict = "unassessed"
    else:
        verdict = ("fit_worthy" if assessment.get("fit_worthy") is True
                   else "not fit-worthy")
        reasons = assessment.get("reasons", [])
        count = len(reasons) if isinstance(reasons, list) else 0
        verdict += f" ({count} reason(s))"
    flagged_count = sum(1 for record in records
                        if flagged.get(record.frame_index, False))
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{video_width}" height="{video_height}" '
        f'viewBox="0 0 {video_width} {video_height}">',
        f"<title>{escape(label if label else 'observation overlay')}</title>",
        f'<rect x="0" y="0" width="{video_width}" height="{video_height}" '
        f'fill="{_BACKGROUND}"/>',
    ]
    for record in records:
        color = (_FLAG_COLOR if flagged.get(record.frame_index, False)
                 else _OK_COLOR)
        if record.bbox is not None:
            x1, y1, x2, y2 = (_number(v) for v in record.bbox)
            parts.append(
                f'<rect x="{x1}" y="{y1}" width="{_number(record.bbox[2] - record.bbox[0])}" '
                f'height="{_number(record.bbox[3] - record.bbox[1])}" fill="none" '
                f'stroke="{color}" stroke-width="2"/>')
        if record.centroid_x_px is not None and record.centroid_y_px is not None:
            parts.append(
                f'<circle cx="{_number(record.centroid_x_px)}" '
                f'cy="{_number(record.centroid_y_px)}" r="4" fill="{color}"/>')
    dots = [(record.centroid_x_px, record.centroid_y_px) for record in records
            if record.centroid_x_px is not None
            and record.centroid_y_px is not None]
    if len(dots) >= 2:
        points = " ".join(f"{_number(x)},{_number(y)}" for x, y in dots)
        parts.append(f'<polyline points="{points}" fill="none" '
                     f'stroke="{_PATH_COLOR}" stroke-width="1.5"/>')
    parts.append(
        f'<text x="10" y="20" fill="{_TEXT_COLOR}" font-family="{_FONT}" '
        f'font-size="14">chain: {escape(verdict)}; {len(records)} record(s); '
        f'{flagged_count} flagged</text>')
    parts.append(
        f'<rect x="10" y="{video_height - 44}" width="12" height="12" '
        f'fill="{_OK_COLOR}"/>'
        f'<text x="28" y="{video_height - 33}" fill="{_TEXT_COLOR}" '
        f'font-family="{_FONT}" font-size="12">ok</text>'
        f'<rect x="70" y="{video_height - 44}" width="12" height="12" '
        f'fill="{_FLAG_COLOR}"/>'
        f'<text x="88" y="{video_height - 33}" fill="{_TEXT_COLOR}" '
        f'font-family="{_FONT}" font-size="12">flagged</text>')
    parts.append("</svg>")
    return ("\n".join(parts) + "\n").encode("utf-8")
