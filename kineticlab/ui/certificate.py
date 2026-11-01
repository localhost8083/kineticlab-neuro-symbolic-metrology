"""Standalone HTML measurement certificate (KL-10.24).

``render_certificate`` renders a stored ``result.v1`` dict plus its
optional assembly diagnostics and provenance artifact digests as one
complete HTML document: inline CSS, no external resources, no
script. Copy rule (same law as ``assembly.summary``): every number
in the output is copied from the passed inputs (scalars via
``repr``, mappings via canonical JSON); the renderer emits zero
digits of its own — no statistics, no counts, no timestamps, no
recomputation. Missing pieces render as ``unknown`` — never a
placeholder number. No wall-clock, no randomness, no network:
identical inputs render byte-identical output.

Rejections render the fired ``E_*`` codes verbatim with no
explanations. ponytail: the human-readable code glossary lives in
index.html's JS map; upgrade path = a server-side shared dict both
renderers import.
"""

from __future__ import annotations

import html
import json
from typing import Any

ARTIFACT_HASH_KEYS = ("raw_bob_sha256", "raw_card_sha256",
                      "calibration_sha256", "geometry_report_sha256")
"""Provenance input-digest keys, in fixed render order."""

_FAILURE_STATES = ("insufficient_data", "unsupported_input",
                   "processing_error")
"""Result states that carry reject reasons and no value."""

_CSS = """body{font-family:system-ui,sans-serif;margin:24px;color:#17243A}
h1{font-size:20px;margin:0 0 4px}
h2{font-size:14px;margin:18px 0 6px;border-bottom:1px solid #ccc;padding-bottom:2px}
table{border-collapse:collapse;margin:4px 0}
th,td{border:1px solid #ccc;padding:2px 10px;text-align:left;font-size:13px}
th{font-weight:600}
code{font-family:ui-monospace,monospace}
.bad{color:#B91C1C}
ul{margin:4px 0}
"""


def _u(value: Any) -> str:
    """One copied value in JSON spelling; null/absent -> ``unknown``."""
    if value is None:
        return "unknown"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, sort_keys=True)


def _e(value: Any) -> str:
    """Escaped cell text: every interpolated string goes through here."""
    return html.escape(_u(value))


def _rows(pairs: list[tuple[str, Any]]) -> str:
    return "".join(f"<tr><th>{html.escape(key)}</th><td>{_e(value)}</td></tr>\n"
                   for key, value in pairs)


def _band(part: Any) -> str:
    """One {low, point, high} band rendered low/point/high, or unknown."""
    if not isinstance(part, dict):
        return "unknown"
    return (f"low {_e(part.get('low'))}, point {_e(part.get('point'))}, "
            f"high {_e(part.get('high'))}")


def render_certificate(result: dict, diagnostics: dict | None,
                       artifact_hashes: dict | None) -> str:
    """Render the standalone certificate (see module docstring).

    ``result`` is a ``result.v1`` dict as stored in ``result.json``;
    ``diagnostics`` is the run's ``diagnostics.json`` doc or None;
    ``artifact_hashes`` is the provenance digest map or None.
    """
    if not isinstance(result, dict):
        raise TypeError(
            f"result must be a dict, got {type(result).__name__}")
    provenance = result.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    quantity = result.get("identifiable_quantity")
    quantity = quantity if isinstance(quantity, dict) else {}
    fit = result.get("fit")
    fit = fit if isinstance(fit, dict) else {}
    metrics = result.get("quality_metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    calibration = result.get("calibration")
    calibration = calibration if isinstance(calibration, dict) else {}
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    status = result.get("status")
    interval = result.get("interval")
    interval = interval if isinstance(interval, dict) else None

    title = f"REJECTED ({_u(status)})" if status in _FAILURE_STATES \
        else f"Measurement certificate — status: {_u(status)}"
    head = (f"<h1>{html.escape(title)}</h1>\n"
            f"<p>Every value below is copied from the run's stored "
            f"exports; nothing is recomputed. Missing pieces read "
            f"unknown, never a guess.</p>\n")

    measurement = _rows([
        ("status", status),
        ("measurement", result.get("measurement_name")),
        ("value", result.get("value")),
        ("unit", result.get("unit")),
        ("identifiable quantity",
         None if not quantity else
         f"{quantity.get('name')} = {_u(quantity.get('value'))} "
         f"{_u(quantity.get('unit'))}"),
    ])
    if interval is not None:
        measurement += _rows([
            ("interval method", result.get("interval_method")),
            ("interval low", interval.get("lower")),
            ("interval point", result.get("value")),
            ("interval high", interval.get("upper")),
        ])
    else:
        measurement += _rows([("interval", None)])

    provenance_rows = _rows([
        ("software_version", provenance.get("software_version")),
        ("input_sha256", provenance.get("input_sha256")),
        ("model_name", provenance.get("model_name")),
    ])

    calibration_rows = _rows([
        ("calibration valid", calibration.get("valid")),
        ("dimension_source", calibration.get("dimension_source")),
    ])

    counts_rows = _rows([
        ("frames_total", metrics.get("frames_total")),
        ("frames_usable", metrics.get("frames_usable")),
        ("observations_total", metrics.get("observations_total")),
        ("observations_valid", metrics.get("observations_valid")),
        ("calibrated_frames", metrics.get("calibrated_frames")),
    ])

    m1 = diagnostics.get("m1")
    m1 = m1 if isinstance(m1, dict) else {}
    fitted = m1.get("fitted")
    fitted_rows = _rows([(key, fitted.get(key))
                         for key in sorted(fitted)]
                        if isinstance(fitted, dict) else
                        [("fitted", None)])

    uncertainty_rows = _rows([("fit_uncertainty", None)])
    fu = diagnostics.get("fit_uncertainty")
    if isinstance(fu, dict):
        uncertainty_rows = _rows([
            ("method", fu.get("method")),
            ("seed", fu.get("seed")),
            ("n_boot", fu.get("n_boot")),
            ("block_frames", fu.get("block_frames")),
            ("omega_per_s (1/s)", _band(fu.get("omega_per_s"))),
            ("g_over_l_eff_per_s2 (1/s^2)",
             _band(fu.get("g_over_l_eff_per_s2"))),
        ])

    m2 = diagnostics.get("m2")
    m2 = m2 if isinstance(m2, dict) else None
    if m2 is not None:
        m2_fitted = m2.get("fitted")
        m2_fitted = m2_fitted if isinstance(m2_fitted, dict) else {}
        m2_g = m2.get("g_over_l_per_s2")
        m1_g = fit.get("g_over_l_per_s2")
        delta = m2_g - m1_g if isinstance(m2_g, (int, float)) \
            and isinstance(m1_g, (int, float)) else None
        m2_rows = _rows([
            ("included", m2.get("included")),
            ("m2 omega (1/s)", m2_fitted.get("omega_per_s")),
            ("m2 g_over_l_per_s2", m2_g),
            ("delta (m2 - m1 g_over_l_per_s2)", delta),
            ("justification", m2.get("justification")),
        ])
    else:
        m2_rows = _rows([("M2 cross-check", None)])

    hash_map = artifact_hashes if isinstance(artifact_hashes, dict) else {}
    hash_names = [key for key in ARTIFACT_HASH_KEYS if key in hash_map] + \
        sorted(set(hash_map) - set(ARTIFACT_HASH_KEYS))
    if hash_names:
        exports_rows = _rows([(key, hash_map[key]) for key in hash_names])
    else:
        exports_rows = _rows([("artifact digests", None)])

    reject_codes = ""
    reasons = result.get("reject_reasons")
    if status in _FAILURE_STATES and isinstance(reasons, list) and reasons:
        items = "".join(
            "<li><code>"
            + _e(reason.get('code') if isinstance(reason, dict)
                 else reason)
            + "</code></li>\n"
            for reason in reasons)
        reject_codes = (f"<h2>Reject reasons (fired codes, verbatim)</h2>\n"
                        f"<ul>\n{items}</ul>\n")

    return ("<!DOCTYPE html>\n"
            '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            "<title>KineticLab measurement certificate</title>\n"
            f"<style>{_CSS}</style>\n</head>\n<body>\n"
            f"{head}"
            "<h2>Measurement</h2>\n<table>\n" + measurement + "</table>\n"
            "<h2>Provenance</h2>\n<table>\n" + provenance_rows + "</table>\n"
            "<h2>Calibration</h2>\n<table>\n" + calibration_rows + "</table>\n"
            "<h2>Observation counts</h2>\n<table>\n" + counts_rows
            + "</table>\n"
            "<h2>M1 fitted parameters</h2>\n<table>\n" + fitted_rows
            + "</table>\n"
            "<h2>Uncertainty (from diagnostics.json when provided)</h2>\n"
            "<table>\n" + uncertainty_rows + "</table>\n"
            "<h2>M2 cross-check</h2>\n<table>\n" + m2_rows + "</table>\n"
            "<h2>Input artifact digests</h2>\n<table>\n" + exports_rows
            + "</table>\n"
            + reject_codes
            + "</body>\n</html>\n")
