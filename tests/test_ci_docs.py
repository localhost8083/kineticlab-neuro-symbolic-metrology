"""README/CI drift-lock tests (KL-10.8).

Pins the public contract together with plain-text assertions
(stdlib only, no YAML parser): every README Quickstart command must appear
in .github/workflows/ci.yml, the workflow must keep its promised shape
(matrix OS pair, timeout floor, triggers), and the five suite-count tokens
across README + Docs must all name the same integer so one stale count
cannot ship again.

These files are tracked; a missing one is a loud failure, never a skip.
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
REPRODUCE = ROOT / "Docs" / "REPRODUCE.md"
RUNBOOK = ROOT / "Docs" / "Demo_Runbook.md"
OVERVIEW = ROOT / "Docs" / "OVERVIEW.md"

# Every command of the README Quickstart block, verbatim order.
QUICKSTART_COMMANDS = (
    "python --version",
    "python -m kineticlab --help",
    "python scripts/media_check.py",
    "python -m unittest",
    "python -m kineticlab serve",
)

# (file, regex with one integer group) for each suite-count token.
COUNT_TOKENS = (
    (README, r"tests-(\d+)%20passing"),   # README badge
    (README, r"# (\d+) tests"),           # README Quickstart comment
    (REPRODUCE, r"`(\d+) tests, OK`"),    # REPRODUCE.md expectation
    (RUNBOOK, r'"(\d+) tests pass'),      # Demo_Runbook.md say-line
    (OVERVIEW, r"(?:a|an) (\d+)-test suite"),  # OVERVIEW.md engineering shape
)


def _read(path):
    if not path.is_file():
        raise AssertionError(f"tracked file missing: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


class CiDocsLockTests(unittest.TestCase):
    def test_quickstart_commands_in_workflow(self):
        """Every README Quickstart command appears in ci.yml, in order."""
        ci = _read(WORKFLOW)
        code = "\n".join(ln for ln in ci.splitlines()
                         if not ln.strip().startswith("#"))
        positions = []
        for cmd in QUICKSTART_COMMANDS:
            pos = ci.find(cmd)
            self.assertNotEqual(
                pos, -1, f"Quickstart command missing from ci.yml: {cmd}")
            positions.append(code.find(cmd))
        self.assertEqual(
            positions, sorted(positions),
            "ci.yml must run the Quickstart commands in README order")

    def test_serve_replacement_block_present(self):
        """The blocking `serve` step is replaced by a documented
        background start + poll-200 + stop block, not dropped."""
        ci = _read(WORKFLOW)
        for marker in ("background", "127.0.0.1:8137", "30 s"):
            self.assertIn(
                marker, ci,
                f"serve-replacement marker missing from ci.yml: {marker}")

    def test_workflow_shape(self):
        """ci.yml keeps its promised shape: OS matrix, timeout floor,
        and push/PR/dispatch triggers."""
        ci = _read(WORKFLOW)
        for os_label in ("ubuntu-latest", "windows-latest"):
            self.assertIn(os_label, ci, f"matrix OS missing: {os_label}")
        match = re.search(r"timeout-minutes:\s*(\d+)", ci)
        self.assertIsNotNone(match, "timeout-minutes missing from ci.yml")
        self.assertGreaterEqual(
            int(match.group(1)), 40, "timeout-minutes floor is 40")
        for trigger in ("push:", "pull_request", "workflow_dispatch"):
            self.assertIn(trigger, ci, f"trigger missing: {trigger}")

    def test_suite_count_tokens_agree(self):
        """All five suite-count tokens name the same integer."""
        counts = []
        for path, pattern in COUNT_TOKENS:
            text = _read(path)
            matches = re.findall(pattern, text)
            label = f"{path.relative_to(ROOT)} /{pattern}/"
            self.assertEqual(
                len(matches), 1,
                f"expected exactly one count token in {label}, "
                f"found {len(matches)}")
            counts.append(int(matches[0]))
        self.assertEqual(
            len(set(counts)), 1,
            f"suite-count tokens disagree across docs: {counts}")

    def test_no_pep701_fstrings(self):
        """Python floor is 3.11: no multi-line expressions inside
        single-quoted f-string braces. On the 3.11 floor the
        parser rejects those at import time (SyntaxError), so the
        interpreter enforces natively there; this static walk
        matters on 3.12+ parsers, which accept the syntax. The
        walk must not run below 3.12: pre-3.12 AST nodes do not
        carry per-expression positions (a FormattedValue
        inherits the whole f-string's span), which would flag
        legal code."""
        import ast
        import sys
        if sys.version_info < (3, 12):
            self.skipTest(
                "3.11 parser enforces the PEP 701 floor natively; "
                "position-based static walk is 3.12+ only")
        offenders = []
        for path in sorted((ROOT / "kineticlab").rglob("*.py")):
            text = _read(path)
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.JoinedStr):
                    continue
                segment = ast.get_source_segment(text, node)
                if segment is None or segment.startswith(('f"""',
                                                          "f'''")):
                    continue
                for value in node.values:
                    if (isinstance(value, ast.FormattedValue)
                            and value.end_lineno > value.lineno):
                        offenders.append(
                            f"{path.relative_to(ROOT)}:"
                            f"{value.lineno}")
        self.assertEqual(
            offenders, [],
            "PEP 701 f-strings break the 3.11 CI floor: "
            + ", ".join(offenders))
