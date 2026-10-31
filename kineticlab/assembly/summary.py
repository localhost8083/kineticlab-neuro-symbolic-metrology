"""Human-auditable Markdown summary (KL-7.3).

``render_summary_md`` renders a validated ``result.v1`` dict plus
its assembly diagnostics dict as ``summary.md``. Copy rule: every
number in the output is copied from those two inputs (scalars via
``repr``, mappings/sequences via canonical JSON); the renderer
emits zero digits of its own — no statistics, no counts, no
timestamps, no recomputation. Bullets everywhere (never numbered
lists) so even presentation numbering contributes no digits.
Missing sections render as ``null``/``none`` notes, never guesses.

Determinism: fixed section order, fixed row order, sorted mapping
keys, LF newlines. The export file list uses basenames only
(files sit beside the summary). Same request (including
``out_dir``) re-run yields byte-identical ``summary.md``.
Across different output directories summaries differ in AT MOST
one line — the ``result.json`` hash — because ``result.json``
honestly embeds its own out-dir export refs. They may be
identical when export refs fall back to basenames outside the
working directory (documented ``export.py`` fallback). The
``diagnostics.json`` and ``angles.csv`` hashes are stable
everywhere. SHA-256 values
arrive precomputed over the exact written bytes (see
``build._finish``); the summary lists itself without a
self-hash (a self-embedded hash is uncomputable — verify it
by regenerating).

Rejections render through the same function: the title reads
``REJECTED (<state>)`` and every section states what is absent,
so a rejection summary is unmistakable.
"""

from __future__ import annotations

import json
from typing import Any

SUMMARY_FILENAME = "summary.md"
"""On-disk name of the rendered summary (sibling of the JSON/CSV)."""

HASHED_FILES = ("result.json", "diagnostics.json", "angles.csv")
"""Exports hashed over exact written bytes, in fixed list order."""

ARTIFACT_HASH_KEYS = ("raw_bob_sha256", "raw_card_sha256",
                      "calibration_sha256", "geometry_report_sha256")
"""Provenance input-digest keys, in fixed render order (F6)."""

_HEX_DIGITS = frozenset("0123456789abcdef")


def _v(value: Any) -> str:
    """Render one copied value in JSON spelling (null/true/false/repr)."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value, sort_keys=True)


def _rows(mapping: Any) -> list[tuple[str, Any]]:
    """Sorted key rows of a mapping, or [] for anything else."""
    if not isinstance(mapping, dict):
        return []
    return [(key, mapping[key]) for key in sorted(mapping)]


def render_summary_md(result: dict[str, Any], diagnostics: dict[str, Any],
                      file_hashes: dict[str, str]) -> str:
    """Render the Markdown summary (see module docstring).

    ``file_hashes`` must map exactly ``HASHED_FILES`` to their
    SHA-256 hex digests over the written bytes.
    """
    if not isinstance(result, dict):
        raise TypeError(
            f"result must be a dict, got {type(result).__name__}")
    if not isinstance(diagnostics, dict):
        raise TypeError(
            f"diagnostics must be a dict, got {type(diagnostics).__name__}")
    if not isinstance(file_hashes, dict) \
            or set(file_hashes) != set(HASHED_FILES):
        raise TypeError(
            f"file_hashes must map exactly {list(HASHED_FILES)}")
    for name, digest in file_hashes.items():
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise TypeError(
                f"file_hashes[{name!r}] must be a 64-character "
                "lowercase SHA-256 hex string")
    status = result.get("status")
    verdict = "SUCCESS" if str(status).startswith("success") \
        else "REJECTED"
    lines = [
        f"# KineticLab result: {verdict} ({_v(status)})",
        "",
        "Human-auditable summary. Every number below is copied from",
        "result.json and diagnostics.json in this directory — nothing is",
        "recomputed or authored here. Null renders as `null` (unknown).",
        "",
        "## Status and measurement",
        "",
        f"- status: {_v(status)}",
        f"- measurement: {_v(result.get('measurement_name'))}",
        f"- value: {_v(result.get('value'))}",
        f"- unit: {_v(result.get('unit'))}",
        f"- interval: {_v(result.get('interval'))}",
        f"- interval_method: {_v(result.get('interval_method'))}",
        "",
        "## Identifiable quantity",
        "",
    ]
    quantity = result.get("identifiable_quantity")
    if isinstance(quantity, dict):
        lines.append(f"- name: {_v(quantity.get('name'))}")
        lines.append(f"- value: {_v(quantity.get('value'))}")
        lines.append(f"- unit: {_v(quantity.get('unit'))}")
    else:
        lines.append("- identifiable quantity: null (absent)")
    lines.extend(["", "## Fit", ""])
    fit = result.get("fit")
    m1 = diagnostics.get("m1")
    if not isinstance(fit, dict) and not isinstance(m1, dict):
        lines.append("- fit: none (no fit output; see status)")
    else:
        fit_dict = fit if isinstance(fit, dict) else {}
        m1_dict = m1 if isinstance(m1, dict) else {}
        lines.append(f"- model_id: {_v(fit_dict.get('model_id'))}")
        lines.append(f"- converged: {_v(fit_dict.get('converged'))}")
        lines.append(
            f"- termination_reason: {_v(m1_dict.get('termination_reason'))}")
        lines.append(f"- optimizer: {_v(fit_dict.get('optimizer'))}")
        lines.append(f"- solver: {_v(fit_dict.get('solver'))}")
        lines.append(
            f"- observation_count: {_v(fit_dict.get('observation_count'))}")
        lines.append(
            f"- rejected_count: {_v(fit_dict.get('rejected_count'))}")
        lines.append(
            f"- g_over_l_per_s2: {_v(fit_dict.get('g_over_l_per_s2'))}")
        lines.append(f"- gravity_m_s2: {_v(fit_dict.get('gravity_m_s2'))}")
        fitted = _rows(m1_dict.get("fitted"))
        if fitted:
            lines.append("- fitted (copied from diagnostics):")
            for key, value in fitted:
                lines.append(f"  - {key}: {_v(value)}")
        else:
            lines.append("- fitted: null (absent)")
        summary = _rows(fit_dict.get("residual_summary"))
        if summary:
            lines.append("- residual_summary (copied from fit.v1):")
            for key, value in summary:
                lines.append(f"  - {key}: {_v(value)}")
        else:
            lines.append("- residual_summary: null (absent)")
        objectives = m1_dict.get("objectives")
        final_ssr = objectives.get("final_ssr") \
            if isinstance(objectives, dict) else None
        lines.append(f"- final_ssr: {_v(final_ssr)}")
        lines.append(f"- bound_hits: {_v(m1_dict.get('bound_hits'))}")
        lines.append(f"- n_points: {_v(m1_dict.get('n_points'))}")
    # KL-10.11: rendered ONLY when the assembly ran the bootstrap
    # (diagnostics.fit_uncertainty present) — rejection and
    # insufficient-data summaries stay byte-identical, per the
    # KL-10.11 re-issue condition (d). Copied values only.
    fu = diagnostics.get("fit_uncertainty")
    if isinstance(fu, dict):
        lines.extend(["", "## Uncertainty", ""])
        lines.append(f"- method: {_v(fu.get('method'))}")
        lines.append(f"- seed: {_v(fu.get('seed'))}")
        lines.append(f"- n_boot: {_v(fu.get('n_boot'))}")
        lines.append(f"- block_frames: {_v(fu.get('block_frames'))}")
        lines.append("- extended_to_contain_point: "
                     f"{_v(fu.get('extended_to_contain_point'))}")
        for key, unit in (("omega_per_s", "1/s"),
                          ("g_over_l_eff_per_s2", "1/s^2")):
            part = fu.get(key)
            if isinstance(part, dict):
                lines.append(
                    f"- {key} ({unit}): low {_v(part.get('low'))}, "
                    f"point {_v(part.get('point'))}, "
                    f"high {_v(part.get('high'))}")
            else:
                lines.append(f"- {key} ({unit}): null (absent)")
    lines.extend(["", "## M2 diagnostic", ""])
    m2 = diagnostics.get("m2")
    if not isinstance(m2, dict):
        lines.append("- M2 diagnostic: not run (no M2 output)")
    else:
        lines.append(f"- included: {_v(m2.get('included'))}")
        lines.append(f"- justification: {_v(m2.get('justification'))}")
        lines.append(f"- converged: {_v(m2.get('converged'))}")
        lines.append(
            f"- termination_reason: {_v(m2.get('termination_reason'))}")
        for key, value in _rows(m2.get("fitted")):
            lines.append(f"- fitted.{key}: {_v(value)}")
        lines.append(
            f"- g_over_l_per_s2: {_v(m2.get('g_over_l_per_s2'))}")
        lines.append(f"- bound_hits: {_v(m2.get('bound_hits'))}")
        warnings = m2.get("warnings")
        if isinstance(warnings, list) and warnings:
            lines.append("- warnings:")
            for warning in warnings:
                if isinstance(warning, dict):
                    lines.append(f"  - `{warning.get('code')}`: "
                                 f"{_v(warning.get('detail'))}")
                else:
                    lines.append(f"  - {_v(warning)}")
        else:
            lines.append("- warnings: none")
    lines.extend(["", "## Quality metrics", ""])
    metrics = result.get("quality_metrics")
    metrics_dict = metrics if isinstance(metrics, dict) else {}
    for key in ("frames_total", "frames_usable", "observations_total",
                "observations_valid", "calibrated_frames"):
        lines.append(f"- {key}: {_v(metrics_dict.get(key))}")
    lines.extend(["", "## Assumptions", ""])
    assumptions = result.get("assumptions")
    if isinstance(assumptions, list) and assumptions:
        for assumption in assumptions:
            lines.append(f"- {_v(assumption)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    warnings = result.get("warnings")
    if isinstance(warnings, list) and warnings:
        for warning in warnings:
            if isinstance(warning, dict):
                lines.append(f"- `{warning.get('code')}`: "
                             f"{_v(warning.get('detail'))}")
            else:
                lines.append(f"- {_v(warning)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Reject reasons", ""])
    reasons = result.get("reject_reasons")
    if isinstance(reasons, list) and reasons:
        for reason in reasons:
            if isinstance(reason, dict):
                lines.append(f"- `{reason.get('code')}` "
                             f"({_v(reason.get('field'))}): "
                             f"{_v(reason.get('detail'))}")
            else:
                lines.append(f"- {_v(reason)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Provenance", ""])
    provenance = result.get("provenance")
    provenance_dict = provenance if isinstance(provenance, dict) else {}
    lines.append(f"- software_name: {_v(provenance_dict.get('software_name'))}")
    lines.append(
        f"- software_version: {_v(provenance_dict.get('software_version'))}")
    lines.append(
        f"- input_sha256: {_v(provenance_dict.get('input_sha256'))}")
    lines.append(f"- model_name: {_v(provenance_dict.get('model_name'))}")
    lines.append(
        f"- model_version: {_v(provenance_dict.get('model_version'))}")
    raw_refs = provenance_dict.get("raw_refs")
    if isinstance(raw_refs, list) and raw_refs:
        lines.append("- raw_refs:")
        for ref in raw_refs:
            lines.append(f"  - {_v(ref)}")
    else:
        lines.append("- raw_refs: none")
    # F6: input digests render verbatim, but only when they are
    # honestly shaped — malformed digests are a renderer TypeError
    # (no new taxonomy code), never silent prose.
    hashes = provenance_dict.get("artifact_hashes")
    if hashes is None:
        lines.append("- artifact_hashes: null (absent)")
    else:
        if not isinstance(hashes, dict) \
                or set(hashes) != set(ARTIFACT_HASH_KEYS):
            raise TypeError("provenance.artifact_hashes must be an "
                            "object with exactly the keys "
                            + ", ".join(ARTIFACT_HASH_KEYS))
        for key in ARTIFACT_HASH_KEYS:
            value = hashes[key]
            if value is not None and (
                    not isinstance(value, str) or len(value) != 64
                    or any(char not in _HEX_DIGITS for char in value)):
                raise TypeError(
                    f"provenance.artifact_hashes[{key!r}] must be "
                    "null or 64-char lowercase hex")
        lines.append("- artifact_hashes (input digests, copied):")
        for key in ARTIFACT_HASH_KEYS:
            lines.append(f"  - {key}: {_v(hashes[key])}")
    lines.extend(["", "## Export files", ""])
    lines.append("SHA-256 over the exact written bytes, in write order:")
    lines.append("")
    for name in HASHED_FILES:
        lines.append(f"- {name}: {file_hashes[name]}")
    lines.append(f"- {SUMMARY_FILENAME}: (this file — self-hash excluded "
                 "by construction; verify by regenerating)")
    lines.append("")
    return "\n".join(lines)
