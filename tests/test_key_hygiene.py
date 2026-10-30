"""Key-hygiene scan tests (M-0).

Proves no key-like string appears in the working tree, fixtures,
logs, or exports, and (when git is available) in git history.
Findings report file + line only — matched text is NEVER printed,
so this suite cannot itself leak a secret into test output.

Secret material belongs in the process environment
(`MODEL_API_KEY`) only — never in files. `.env*` files are
therefore rejected by presence, not by content.
"""

import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = frozenset({
    ".git", ".hg", ".sl", ".eden", ".agents", ".claude", ".muse",
    ".venv", "venv", "ENV", "__pycache__", ".pytest_cache",
    ".mypy_cache", ".hypothesis", ".ruff_cache", "node_modules",
    "dist", "build",
})

SKIP_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".so", ".dll", ".dylib", ".mp4", ".mov", ".mkv",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".pdf", ".zip", ".gz",
    ".tar", ".mp3", ".wav", ".flac", ".ttf", ".otf", ".woff",
})

MAX_SCAN_BYTES = 2_000_000

# Placeholder values that are documentation, not secrets. Anything
# else matching an assignment pattern is flagged.
PLACEHOLDER_VALUES = frozenset({
    "...", "xxx", "your-key-here", "changeme", "placeholder",
    "test-key", "dummy", "none", "null", "false", "true", "env",
})

SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{16,}")
# \b anchor: real keys are delimited tokens; unanchored, the pattern
# matches random substrings inside base64 blobs (observed in a Docs
# audit file's embedded PNG data URI).
AWS_PATTERN = re.compile(r"\bAKIA[0-9A-Z]{16}")
ASSIGN_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|secret[_-]?key|client[_-]?secret|"
    r"access[_-]?token|auth[_-]?token)\b\s*[:=]\s*['\"]?"
    r"([A-Za-z0-9_\-\.=]{8,})"
)
ENV_VALUE_PATTERN = re.compile(
    r"MODEL_API_KEY\s*=\s*['\"]?([^\s'\"]{8,})"
)


def format_finding(relpath, lineno):
    """Render a finding without any matched content (anti-leak)."""
    return "possible secret material in %s:%d (content redacted)" % (
        relpath, lineno)


def value_is_placeholder(value):
    lowered = value.strip().lower().rstrip("'\",;")
    if lowered in PLACEHOLDER_VALUES:
        return True
    if lowered.startswith(("$", "<", "{")):
        return True
    for marker in ("...", "xxx", "your_", "example", "changeme",
                   "placeholder"):
        if marker in lowered:
            return True
    # Reading the key from the process environment is the approved
    # pattern (M-0 key hygiene), not a leak.
    for marker in ("os.environ", "os.getenv", "getenv", "environ[",
                   "env.get", "env["):
        if marker in lowered:
            return True
    return False


def scan_text(relpath, text):
    """Return finding strings for one decoded file (paths only)."""
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if SK_PATTERN.search(line) or BEARER_PATTERN.search(line) \
                or AWS_PATTERN.search(line):
            findings.append(format_finding(relpath, lineno))
            continue
        flagged = False
        for match in ASSIGN_PATTERN.finditer(line):
            if not value_is_placeholder(match.group(2)):
                flagged = True
                break
        if not flagged:
            for match in ENV_VALUE_PATTERN.finditer(line):
                if not value_is_placeholder(match.group(1)):
                    flagged = True
                    break
        if flagged:
            findings.append(format_finding(relpath, lineno))
    return findings


def iter_scannable_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name not in SKIP_DIRS)
        for name in sorted(filenames):
            if name.startswith(".env"):
                yield os.path.join(dirpath, name), True
                continue
            if os.path.splitext(name)[1].lower() in SKIP_SUFFIXES:
                continue
            full = os.path.join(dirpath, name)
            try:
                if os.path.getsize(full) > MAX_SCAN_BYTES:
                    continue
            except OSError:
                continue
            yield full, False


class KeyHygieneTests(unittest.TestCase):
    def test_no_dotenv_files(self):
        hits = []
        for full, is_env in iter_scannable_files(ROOT):
            if is_env:
                hits.append(os.path.relpath(full, ROOT))
        self.assertEqual(
            hits, [],
            "secret files must not exist (key lives in process "
            "environment only): %s" % hits)

    def test_no_key_like_strings_in_tree(self):
        findings = []
        for full, is_env in iter_scannable_files(ROOT):
            if is_env:
                continue
            try:
                with open(full, "r", encoding="utf-8") as handle:
                    text = handle.read()
            except (OSError, UnicodeDecodeError):
                continue
            relpath = os.path.relpath(full, ROOT)
            findings.extend(scan_text(relpath, text))
        self.assertEqual(
            findings, [],
            "key-like strings found (paths only, content redacted): "
            "%s" % findings[:10])

    def test_scanner_flags_synthetic_samples(self):
        # Samples are assembled at runtime so no key-like literal
        # appears in this file (which the tree scan also covers).
        samples = [
            "key = " + "'sk-" + "x" * 24 + "'",
            "Authorization: Bearer " + "y" * 32,
            "AKIA" + "Z" * 16,
            "api_key=" + "q" * 20,
            "export MODEL_API_KEY=" + "w" * 24,
        ]
        for sample in samples:
            with self.subTest(sample=sample[:12]):
                self.assertEqual(len(scan_text("synthetic", sample)), 1)
        # Placeholders and env-name references must not flag.
        benign = [
            "export MODEL_API_KEY='...'",
            'api_key = os.environ.get("MODEL_API_KEY")',
            "keep `MODEL_API_KEY` in the environment only",
            "api_key: null  # unknown until configured",
            # AKIA substring embedded mid-token in base64 soup (as
            # observed in a Docs data URI) is not a delimited key.
            "data:image/png;base64,iVBORw0KAKIA" + "Z" * 16
            + "restofblob",
        ]
        for sample in benign:
            with self.subTest(sample=sample[:24]):
                self.assertEqual(scan_text("synthetic", sample), [])

    def test_findings_never_carry_content(self):
        rendered = format_finding("some/file.txt", 7)
        self.assertIn("some/file.txt", rendered)
        self.assertIn("7", rendered)
        self.assertIn("redacted", rendered)

    def test_no_secrets_in_git_history(self):
        # safe.directory=* : the sandbox maps ownership to a
        # different user than the checkout owner, so the path form
        # is still rejected; the wildcard is read-only-safe here.
        safe = ["git", "-c", "safe.directory=*"]
        try:
            revs = subprocess.run(
                safe + ["rev-list", "--all"],
                capture_output=True, text=True, timeout=60, cwd=ROOT,
                check=False)
        except (OSError, subprocess.SubprocessError) as error:
            self.skipTest("git unavailable: %s" % error)
            return
        if revs.returncode != 0 or not revs.stdout.strip():
            self.skipTest("git history unavailable in this environment")
            return
        pattern = ("sk-[A-Za-z0-9]{20,}|bearer [A-Za-z0-9_\\-\\.]{16,}|"
                   "\\bAKIA[0-9A-Z]{16}|"
                   "api[_-]?key.{0,5}[:=].{0,3}[A-Za-z0-9_\\-]{16,}")
        try:
            found = subprocess.run(
                safe + ["grep", "-l", "-i", "-E", pattern]
                + revs.stdout.split(),
                capture_output=True, text=True, timeout=120, cwd=ROOT,
                check=False)
        except (OSError, subprocess.SubprocessError) as error:
            self.skipTest("git grep unavailable: %s" % error)
            return
        # grep exit 1 with empty output = clean; list paths only.
        hits = [line for line in found.stdout.splitlines()
                if line and ":" in line]
        self.assertEqual(
            hits, [],
            "possible secret material in git history "
            "(rev:path only, content redacted): %s" % hits[:10])


if __name__ == "__main__":
    unittest.main()
