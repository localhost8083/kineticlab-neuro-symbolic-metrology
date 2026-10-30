"""Assembly exports: canonical JSON + presentation CSV (KL-7.1).

JSON follows the KL-3.3 canonical form (UTF-8, LF, sorted keys,
indent 2): ``export_result_json`` serializes the validated
``result.v1`` dict, ``export_diagnostics_json`` the assembly
diagnostics dict. Both round-trip byte-identically through
``json.loads`` + re-export.

CSV is presentation-grade (KL-3.3/KL-4.2 precedent): ``export_angles_csv``
writes the angle series with a fixed documented column contract and
no parser by design —

``frame_index,pts_seconds,theta_rad,centroid_x_px,centroid_y_px``

header always, one row per fitted point in assembly order, JSON is
the lossless form. Deterministic bytes for identical input.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ANGLE_CSV_COLUMNS = ("frame_index", "pts_seconds", "theta_rad",
                     "centroid_x_px", "centroid_y_px")
"""Fixed column contract for the angle-series CSV."""


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    if not isinstance(payload, dict):
        raise TypeError(
            f"payload must be a dict, got {type(payload).__name__}")
    return (json.dumps(payload, sort_keys=True, indent=2,
                       ensure_ascii=True) + "\n").encode("utf-8")


def export_result_json(result: dict[str, Any]) -> bytes:
    """Canonical bytes for a validated ``result.v1`` dict."""
    return _canonical_bytes(result)


def export_diagnostics_json(diagnostics: dict[str, Any]) -> bytes:
    """Canonical bytes for the assembly diagnostics dict."""
    return _canonical_bytes(diagnostics)


def export_angles_csv(rows: Any) -> bytes:
    """Presentation CSV for angle-series rows (see module docstring)."""
    if not isinstance(rows, (list, tuple)):
        raise TypeError(
            f"rows must be a list, got {type(rows).__name__}")
    lines = [",".join(ANGLE_CSV_COLUMNS)]
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TypeError(f"rows[{index}] must be a dict")
        cells: list[str] = []
        for column in ANGLE_CSV_COLUMNS:
            value = row.get(column)
            if value is None:
                cells.append("")
            elif isinstance(value, bool):
                raise TypeError(f"rows[{index}].{column} is a boolean")
            elif isinstance(value, (int, float)):
                cells.append(repr(float(value)) if column != "frame_index"
                             else str(value))
            else:
                raise TypeError(
                    f"rows[{index}].{column} must be numeric or null")
        lines.append(",".join(cells))
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_assembly_exports(out_dir: str | Path, result: dict[str, Any],
                           diagnostics: dict[str, Any],
                           angles: Any) -> dict[str, str]:
    """Write result.json + diagnostics.json + angles.csv; return display refs.

    Returns ``{"result_json": path, "diagnostics_json": path,
    "angles_csv": path}`` with repo-relative display paths for the
    result's ``exports`` refs. Never writes outside ``out_dir``.
    """
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    written = {
        "result_json": target / "result.json",
        "diagnostics_json": target / "diagnostics.json",
        "angles_csv": target / "angles.csv",
    }
    written["result_json"].write_bytes(export_result_json(result))
    written["diagnostics_json"].write_bytes(
        export_diagnostics_json(diagnostics))
    written["angles_csv"].write_bytes(export_angles_csv(angles))
    refs: dict[str, str] = {}
    for key, path in written.items():
        # Absolute-ize first: relative_to fails when exactly one
        # side is relative, which would silently degrade every
        # relative out_dir to bare filenames.
        absolute = path if path.is_absolute() else Path.cwd() / path
        try:
            refs[key] = absolute.relative_to(Path.cwd()).as_posix()
        except ValueError:
            refs[key] = path.name
    return refs
