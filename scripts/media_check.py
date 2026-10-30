#!/usr/bin/env python3
"""Offline structural media check (KL-0.3 smoke command).

Reports container/codec/geometry/frame structure and compares it against
pinned per-fixture expectations in `fixtures/*.json`. The MP4 box parser
is shared with the package (`kineticlab.ingest.mp4`, KL-2.1); this script
keeps only fixture comparison and CLI behavior.

This is executable support for the smoke command, not decoded media
validation. Unknown values are reported as null, never guessed:
`pix_fmt` needs a decoder, so the probe always reports it as null.

Usage (run from the repo root):
    python scripts/media_check.py                     # check every fixture
    python scripts/media_check.py --fixture fixtures/test_3.json
    python scripts/media_check.py --probe Smoke/test_3.mp4 [--json]

Exit codes: 0 pass, 1 mismatch or parse failure, 2 usage or missing file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kineticlab.ingest.mp4 import ProbeError, probe_mp4  # noqa: E402


KNOWN_EXPECT_KEYS = frozenset({
    "sha256", "major_brand", "codec", "codec_tag", "width", "height",
    "frames", "duration_s", "duration_tol_s", "fps", "fps_tol", "has_audio",
    "pix_fmt",
})


def check_fixture(fixture_path: Path) -> tuple[bool, dict, list[str]]:
    """Probe the fixture video and compare against pinned expectations."""
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    expect = fixture.get("expect", {})
    unknown = sorted(set(expect) - KNOWN_EXPECT_KEYS)
    if unknown:
        raise ProbeError(f"{fixture_path}: unknown expectation keys: {unknown}")
    root = fixture_path.parent.parent
    video = root / fixture["video"]
    report = probe_mp4(video)
    report["video_ref"] = fixture["video"]
    failures: list[str] = []
    for key in ("sha256", "major_brand", "codec", "codec_tag", "width",
                "height", "frames", "has_audio"):
        if key in expect and report.get(key) != expect[key]:
            failures.append(f"{key}: expected {expect[key]!r}, measured {report.get(key)!r}")
    if "duration_s" in expect and expect["duration_s"] is not None:
        tol = expect.get("duration_tol_s", 0.05)
        measured = report.get("duration_s")
        if measured is None or abs(measured - expect["duration_s"]) > tol:
            failures.append(
                f"duration_s: expected {expect['duration_s']} +/- {tol}, "
                f"measured {measured}")
    if "fps" in expect and expect["fps"] is not None:
        tol = expect.get("fps_tol", 0.5)
        measured = report.get("fps_measured")
        if measured is None or abs(measured - expect["fps"]) > tol:
            failures.append(
                f"fps: expected {expect['fps']} +/- {tol}, measured {measured}")
    # A null pix_fmt expectation is never compared: this probe cannot measure it.
    return not failures, report, failures


def format_human(name: str, report: dict, failures: list[str]) -> str:
    status = "PASS" if not failures else "FAIL"
    summary = (
        f"{report.get('codec')}/{report.get('codec_tag')} "
        f"{report.get('width')}x{report.get('height')} "
        f"{report.get('frames')}f {report.get('duration_s'):.3f}s "
        f"audio={'yes' if report.get('has_audio') else 'no'}"
    )
    lines = [f"{status} {name}: {report.get('video_ref', report['path'])} {summary}"]
    lines.extend(f"  {failure}" for failure in failures)
    lines.extend(f"  warning: {warning}" for warning in report.get("warnings", []))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="media_check.py", description="Offline structural MP4 check (KL-0.3).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fixture", action="append", type=Path,
                       help="fixture JSON to check (repeatable; default: fixtures/*.json)")
    group.add_argument("--probe", type=Path, metavar="VIDEO",
                       help="report structure of one video without comparing")
    parser.add_argument("--json", action="store_true", help="print full JSON report(s)")
    args = parser.parse_args(argv)

    if args.probe is not None:
        try:
            report = probe_mp4(args.probe)
        except ProbeError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1 if args.probe.is_file() else 2
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_human("probe", report, []))
        return 0

    fixture_paths = args.fixture
    if not fixture_paths:
        repo_root = Path(__file__).resolve().parent.parent
        fixture_paths = sorted((repo_root / "fixtures").glob("*.json"))
    if not fixture_paths:
        print("error: no fixture files found", file=sys.stderr)
        return 2

    overall_ok = True
    for fixture_path in fixture_paths:
        try:
            fixture_display = os.path.relpath(fixture_path, Path.cwd())
        except ValueError:
            fixture_display = str(fixture_path)
        try:
            ok, report, failures = check_fixture(fixture_path)
        except (ProbeError, KeyError, json.JSONDecodeError) as error:
            print(f"FAIL {fixture_display}: error: {error}", file=sys.stderr)
            return 1 if fixture_path.is_file() else 2
        if args.json:
            print(json.dumps({"fixture": fixture_display, "ok": ok,
                              "report": report, "failures": failures}, indent=2))
        else:
            print(format_human(fixture_display, report, failures))
        overall_ok = overall_ok and ok
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
