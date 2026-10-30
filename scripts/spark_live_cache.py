"""Live-cache helper for Spark advisories. Ran 2026-10-28 (key-holding session): 2 live entries cached.

The user (or a key-holding session) runs this AFTER the offline build
is verified, supplying the user-verified contract as arguments:

  python scripts/spark_live_cache.py --endpoint <url> --model <id> \\
      --kind setup-review --input features.json --out fixtures/advisory/

Reads the key from ``MODEL_API_KEY`` env only. The key is never
printed, never logged, and never written: it travels only in the
Authorization header, and any response containing the key value is
refused (nothing is cached). Writes one ``live``-labeled cache entry
(raw response + request metadata + SHA-256) for offline replay.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from kineticlab.advisory.cache import build_entry, save_entry  # noqa: E402
from kineticlab.advisory.live import (  # noqa: E402
    build_chat_request,
    extract_content,
)

REQUEST_TIMEOUT_SECONDS = 300


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cache one live Spark advisory response (key from env).")
    parser.add_argument("--endpoint", required=True,
                        help="chat-completions URL (user-verified contract)")
    parser.add_argument("--model", required=True,
                        help="serving model id (user-verified contract)")
    parser.add_argument("--kind", required=True,
                        choices=("setup-review", "narrative"))
    parser.add_argument("--input", required=True, type=Path,
                        help="request input JSON file (features/result)")
    parser.add_argument("--out", required=True, type=Path,
                        help="cache directory receiving the live entry")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = os.environ.get("MODEL_API_KEY")
    if not api_key:
        print("MODEL_API_KEY is unset", file=sys.stderr)
        return 2
    try:
        input_text = args.input.read_text(encoding="utf-8")
    except OSError as error:
        print(f"cannot read input: {error}", file=sys.stderr)
        return 2
    try:
        body = build_chat_request(args.model, args.kind, input_text)
    except Exception as error:  # ContractError: bad kind/model/input
        print(f"bad request: {error}", file=sys.stderr)
        return 2
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        args.endpoint, data=data, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key})
    try:
        with urllib.request.urlopen(request,
                                    timeout=REQUEST_TIMEOUT_SECONDS) as reply:
            raw = reply.read().decode("utf-8")
    except Exception as error:
        # Status/reason only: never print a body that might echo input.
        print(f"live request failed: {type(error).__name__}: {error}",
              file=sys.stderr)
        return 1
    try:
        content = extract_content(raw)
    except Exception as error:
        print(f"live response unusable: {error}", file=sys.stderr)
        return 1
    if api_key in content:
        # The model must never see the key, but refuse loudly if it
        # somehow echoes: nothing is cached, nothing is printed.
        print("live response contains key material; refused to cache",
              file=sys.stderr)
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    entry = build_entry(
        label="live", kind=args.kind,
        request={
            "endpoint": args.endpoint,
            "model": args.model,
            "input_sha256": hashlib.sha256(
                input_text.encode("utf-8")).hexdigest(),
            "input_desc": args.input.name,
            "recorded_utc": stamp,
        },
        response_text=content)
    target = save_entry(args.out / f"{args.kind}_{stamp}.json", entry)
    print(json.dumps({"cached": target.name,
                      "sha256": entry["response_sha256"],
                      "label": "live"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
