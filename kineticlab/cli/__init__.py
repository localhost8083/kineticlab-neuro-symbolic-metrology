"""Local command surface for the proven pipeline (KL-0.3).

`config` prints effective non-secret configuration; `demo` (KL-8.1,
OG F8b) runs the pinned SAM -> advisory -> assemble replay through
the shared ``kineticlab.demo`` entry surface; `capture` (KL-8.4) runs
one live SAM capture + measure chain (bring-your-own-key via
``MODEL_API_KEY``); `serve` starts the local web UI on 127.0.0.1;
`doctor` reports environment/fixture health one line per check.
No scientific logic lives here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

from kineticlab import __version__

CONFIG_FILENAME = "kineticlab.toml"


def find_repo_root(start: Path) -> Path | None:
    """Walk up from `start` to the directory holding `kineticlab.toml`."""
    current = start.resolve()
    for candidate in (current, *current.parents):
        if (candidate / CONFIG_FILENAME).is_file():
            return candidate
    return None


def load_config(root: Path) -> dict:
    """Load `kineticlab.toml`; unknown values stay missing, never guessed."""
    with (root / CONFIG_FILENAME).open("rb") as handle:
        return tomllib.load(handle)


def cmd_config(args: argparse.Namespace) -> int:
    root = find_repo_root(Path.cwd())
    if root is None:
        print(f"error: {CONFIG_FILENAME} not found above {Path.cwd()}", file=sys.stderr)
        return 2
    config = load_config(root)
    paths = config.get("paths", {})
    effective = {
        "root": str(root),
        "paths": {name: str((root / value).resolve()) for name, value in paths.items()},
        "api_enabled": bool(config.get("api", {}).get("enabled", False)),
    }
    print(json.dumps(effective, indent=2))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from kineticlab.contracts import ContractError
    from kineticlab.demo import (
        replay_advisory_pins,
        replay_sam_pins,
        run_demo_chain,
    )

    root = find_repo_root(Path.cwd())
    if root is None:
        print(f"error: {CONFIG_FILENAME} not found above {Path.cwd()}", file=sys.stderr)
        return 2
    out_base = Path(args.out_dir) if args.out_dir else root / "demo_out"
    try:
        sam = replay_sam_pins(root)
        print(f"SAM replay: {sam['clip']} ({sam['frames']} frames) -> "
              f"bob {sam['bob']['valid']}/{sam['bob']['records']} valid, "
              f"card {sam['card']['valid']}/{sam['card']['records']} valid")
        advisory = replay_advisory_pins(root)
        setup = advisory["setup"]
        unique_codes = ",".join(dict.fromkeys(setup["codes"]))
        print(f"advisory replay [{setup['label']}]: setup-review "
              f"+{setup['warnings_added']} {unique_codes} "
              f"({setup['status_before']} -> {setup['status_after']}); "
              f"narrative source={advisory['narrative']['source']} "
              f"({advisory['narrative']['chars']} chars, recorded "
              f"M-2 input)")
        out = run_demo_chain(root, chain=args.chain,
                             out_dir=out_base / args.chain)
    except ContractError as error:
        print(f"demo failed: {','.join(error.codes)}: "
              f"{error.errors[0].message if error.errors else ''}",
              file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"demo failed: {error}", file=sys.stderr)
        return 1
    print(out["status_line"])
    for path in out["written"]:
        print(f"wrote: {path}")
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    from kineticlab.capture.chain import new_run_id, run_live_chain
    from kineticlab.contracts import ContractError

    root = find_repo_root(Path.cwd())
    if root is None:
        print(f"error: {CONFIG_FILENAME} not found above {Path.cwd()}", file=sys.stderr)
        return 2
    api_key = os.environ.get("MODEL_API_KEY")
    if not api_key:
        print("error: live capture needs MODEL_API_KEY in the environment "
              "(E_MISSING_FIELD)", file=sys.stderr)
        return 2
    clip = Path(args.clip)
    if not clip.is_file():
        print(f"error: clip not found: {args.clip} (E_MISSING_FIELD)",
              file=sys.stderr)
        return 2
    if args.mode == "motion" and args.prompt_card is not None:
        print("error: motion mode captures no card; drop --prompt-card "
              "(E_INCOHERENT_VALUE)", file=sys.stderr)
        return 2
    if args.mode == "motion" and args.card_width_mm is not None:
        print("error: motion mode uses no card width; drop --card-width-mm "
              "(E_INCOHERENT_VALUE)", file=sys.stderr)
        return 2
    if args.mode == "full" and args.card_width_mm is None:
        print("error: full mode needs --card-width-mm, human-typed "
              "(E_MISSING_FIELD)", file=sys.stderr)
        return 2
    prompts = {"bob": args.prompt_bob
               if args.prompt_bob is not None else "red ball"}
    if args.prompt_card is not None:
        prompts["card"] = args.prompt_card
    elif args.mode == "full":
        prompts["card"] = "white paper card"
    out_base = Path(args.out_dir) if args.out_dir else root / "live_out"
    run_dir = out_base / new_run_id()
    try:
        out = run_live_chain(clip, args.mode, prompts,
                             args.card_width_mm, run_dir, api_key)
    except ContractError as error:
        print(f"capture failed: {','.join(error.codes)}: "
              f"{error.errors[0].message if error.errors else ''}",
              file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError) as error:
        print(f"capture failed: {error}", file=sys.stderr)
        return 1
    roles = out["summary"]["roles"]
    counts = ", ".join(f"{role} {info['valid']}/{info['records']} valid"
                       for role, info in sorted(roles.items()))
    print(f"captured: {counts}")
    print(out["status_line"])
    for path in out["written"]:
        print(f"wrote: {path}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    # Lazy import: the web UI is a serve-only dependency.
    from kineticlab.ui import serve

    root = find_repo_root(Path.cwd())
    if root is None:
        print(f"error: {CONFIG_FILENAME} not found above {Path.cwd()}", file=sys.stderr)
        return 2
    if not 1 <= args.port <= 65535:
        print(f"error: port must be 1..65535, got {args.port}",
              file=sys.stderr)
        return 2
    serve(port=args.port, repo_root=root)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Environment doctor (KL-10.24): one line per check, then a summary.

    Exit 0 when no check FAILs, 1 otherwise. The model API key is
    reported as present/absent only — the value is never printed.
    """
    import hashlib
    import shutil

    from kineticlab.contracts import ResultContract

    repo_root = find_repo_root(Path.cwd())
    package_only = repo_root is None
    root = repo_root or Path.cwd()
    passed = skipped = failed = 0
    if package_only:
        print("doctor: package-only mode; repository fixtures not checked; "
              "full repository health not claimed")

    def line(status: str, detail: str) -> None:
        nonlocal passed, skipped, failed
        if status == "PASS":
            passed += 1
        elif status == "SKIP":
            skipped += 1
        else:
            failed += 1
        print(f"[{status}] {detail}")

    # 1. Python version.
    if sys.version_info >= (3, 11):
        line("PASS", f"Python {sys.version_info.major}."
             f"{sys.version_info.minor} >= 3.11")
    else:
        line("FAIL", f"Python {sys.version_info.major}."
             f"{sys.version_info.minor} < 3.11 (required)")

    # 2. Package import + contract self-check (a valid result.v1
    # fixture must parse). Test-only builders are not package imports.
    try:
        import kineticlab  # noqa: F401 — the import itself is the check
    except Exception as error:  # noqa: BLE001 — doctor reports, never crashes
        line("FAIL", f"package import: {type(error).__name__}: {error}")
    else:
        if package_only:
            line("PASS", "kineticlab imports; package self-check complete; "
                 "repository contract fixture skipped in package-only mode")
        else:
            contract_fixture = root / "fixtures" / "contracts" / "valid_result.json"
            if not contract_fixture.is_file():
                line("FAIL", f"kineticlab imports; {contract_fixture} absent; "
                     "repository contract self-check unavailable")
            else:
                try:
                    ResultContract.from_dict(json.loads(
                        contract_fixture.read_text(encoding="utf-8")))
                    line("PASS", "kineticlab imports; contracts load; valid "
                         "result.v1 self-check parses")
                except Exception as error:  # noqa: BLE001 — doctor reports, never crashes
                    line("FAIL", f"contract self-check: {type(error).__name__}: {error}")

    # 3. Fixture integrity: pinned expectations + clip sha256.
    fixture_path = root / "fixtures" / "test_3.json"
    if package_only:
        line("SKIP", "repository fixture integrity skipped in package-only mode")
    elif not fixture_path.is_file():
        line("SKIP", f"fixtures/test_3.json absent under {root}; "
             "fixture integrity not checkable")
    else:
        try:
            fixture = json.loads(
                fixture_path.read_text(encoding="utf-8"))
            video = fixture["video"]
            pin = fixture["expect"]["sha256"]
            clip = root / video
            if not clip.is_file():
                line("FAIL", f"{video} absent but pinned in "
                     "fixtures/test_3.json")
            else:
                digest = hashlib.sha256(clip.read_bytes()).hexdigest()
                if digest == pin:
                    line("PASS", f"{video} sha256 matches the "
                         "fixtures/test_3.json pin")
                else:
                    line("FAIL", f"{video} sha256 {digest} != pinned "
                         f"{pin}")
        except (OSError, ValueError, KeyError) as error:
            line("FAIL", f"fixture integrity: {type(error).__name__}: "
                 f"{error}")

    # 4. Node (informational; tests.test_ui page proofs need it).
    if shutil.which("node") is not None:
        line("PASS", "node on PATH")
    else:
        line("SKIP", "node not on PATH; tests.test_ui page-execution "
             "proofs need it (informational, not a failure)")

    # 5. Key hygiene: presence only, never the value; .env* files
    # must not exist in the tree root (M-0).
    key_present = bool(os.environ.get("MODEL_API_KEY"))
    env_files = sorted(item.name for item in root.glob(".env*"))
    detail = ("MODEL_API_KEY " + ("present" if key_present else "absent")
              + " in environment (value never printed); "
              + (".env* in tree root: " + ", ".join(env_files)
                 if env_files else "no .env* file in tree root"))
    if env_files:
        line("FAIL", detail + " — keys live in the environment only")
    else:
        line("PASS", detail)

    # 6. Config parse (when present).
    if package_only:
        line("SKIP", "repository config check skipped in package-only mode")
    elif (root / CONFIG_FILENAME).is_file():
        try:
            load_config(root)
            line("PASS", f"{CONFIG_FILENAME} parses")
        except (OSError, tomllib.TOMLDecodeError) as error:
            line("FAIL", f"{CONFIG_FILENAME} parse: "
                 f"{type(error).__name__}: {error}")
    else:
        line("SKIP", f"{CONFIG_FILENAME} absent; nothing to parse")

    print(f"doctor: {passed} pass, {skipped} skip, {failed} fail")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kineticlab",
        description="Offline-first, auditable video metrology "
                    "(pipeline complete and gated; demo + local web UI "
                    "included).",
    )
    parser.add_argument("--version", action="version", version=f"kineticlab {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    config_parser = subparsers.add_parser(
        "config", help="print effective non-secret configuration and exit"
    )
    config_parser.set_defaults(func=cmd_config)
    demo_parser = subparsers.add_parser(
        "demo",
        help="replay pinned SAM + advisory artifacts, assemble one "
             "chain, print written exports (OG F8b front door)",
    )
    demo_parser.add_argument(
        "--chain", choices=("success", "rejection"), default="success",
        help="which pinned chain to assemble (default: success)",
    )
    demo_parser.add_argument(
        "--out-dir", default=None,
        help="export base directory (default: <repo>/demo_out)",
    )
    demo_parser.set_defaults(func=cmd_demo)
    capture_parser = subparsers.add_parser(
        "capture",
        help="run one live SAM capture + measure chain (needs "
             "MODEL_API_KEY in the environment)",
    )
    capture_parser.add_argument(
        "--clip", required=True,
        help="clip file to capture (MP4)",
    )
    capture_parser.add_argument(
        "--mode", required=True, choices=("full", "motion"),
        help="full (bob + card, needs --card-width-mm) or motion "
             "(bob only, scale-free)",
    )
    capture_parser.add_argument(
        "--card-width-mm", type=float, default=None,
        help="human-typed card width in mm (full mode only; never "
             "defaulted, never guessed)",
    )
    capture_parser.add_argument(
        "--prompt-bob", default=None,
        help='bob noun phrase (default: "red ball")',
    )
    capture_parser.add_argument(
        "--prompt-card", default=None,
        help='card noun phrase (default: "white paper card"; full '
             "mode only)",
    )
    capture_parser.add_argument(
        "--out-dir", default=None,
        help="live-run base directory (default: <repo>/live_out)",
    )
    capture_parser.set_defaults(func=cmd_capture)
    serve_parser = subparsers.add_parser(
        "serve", help="start the local web UI on 127.0.0.1 (blocking)"
    )
    serve_parser.add_argument(
        "--port", type=int, default=8137,
        help="localhost port to bind (default: 8137)",
    )
    serve_parser.set_defaults(func=cmd_serve)
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="check environment, contracts, fixtures, key hygiene, "
             "and config (one line per check); exits 0 when no check "
             "fails, 1 otherwise",
    )
    doctor_parser.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 2
    return int(func(args))
