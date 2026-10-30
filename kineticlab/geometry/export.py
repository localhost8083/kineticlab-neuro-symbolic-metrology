"""Canonical exports for geometry outputs (P-006).

JSON: UTF-8, LF, sorted keys, indent 2 — the KL-3.3 canonical form.
Overlays reuse ``kineticlab.result.overlay`` unchanged; this module
only files the bytes next to the geometry pins with provenance
filenames.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def report_bytes(report: dict[str, Any]) -> bytes:
    """Canonical JSON bytes for a geometry/calibration report dict."""
    if not isinstance(report, dict):
        raise TypeError(
            f"report must be a dict, got {type(report).__name__}")
    return (json.dumps(report, sort_keys=True, indent=2,
                       ensure_ascii=True) + "\n").encode("utf-8")


def save_report(path: str | Path, report: dict[str, Any]) -> Path:
    """Write canonical report bytes; return the path written."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(report_bytes(report))
    return target
