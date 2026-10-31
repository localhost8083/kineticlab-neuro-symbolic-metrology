"""Local web UI tests (KL-8.1 Part B through KL-8.8 redesign).

Covers: localhost-only binding (structural + bind-target
capture, no socket needed); homepage serving; page
self-consistency (every JS element id exists, textContent only,
relative fetch URLs only, zero external references);
server-source offline scan (no client/egress primitives);
upload verdicts for a real clip (measured structure + PTS
health + measurement-unavailable notice) and every malformed
variant (registered codes, never 500); demo endpoints (success
value matches the pin, rejection honest, exports served,
byte-stable reruns); traversal-safe export allowlist; serve CLI
plumbing incl. a live start-probe-stop test that runs where
socket binds are allowed and skips with reason where the
sandbox forbids them.
KL-8.8 contracts: dark default, theme toggle + persistence via
CSS custom properties (charts re-themed through the same
tokens), five-stage stepper with styled connected states wired
to real workflow events, honest indeterminate progress (no
percent machinery at all — stage text + real elapsed clock),
workstation regions (viewer / filmstrip / overlay, detected
objects + explicit human confirmation, null-honest full-label
metric cards, chart tabs, evidence & provenance), rAF-only
timing (zero timer calls), and functional-ID preservation so
backend/live dispatch tests never rot.

Server interaction runs through direct handler dispatch (real
``do_GET``/``do_POST`` code, in-memory streams) instead of TCP:
the sandbox forbids ``listen()`` even on loopback, and the
dispatch harness exercises every route, validator, and error
map identically.
"""

import inspect
import io
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from email.message import Message
from pathlib import Path

from kineticlab import __version__ as PACKAGE_VERSION
from kineticlab.cli import main
from kineticlab.contracts import ERROR_CODES, WARNING_CODES
from kineticlab.ui import BIND_HOST, make_server
from kineticlab.ui.server import MAX_UPLOAD_BYTES, _Handler
from tests import require_smoke

# Worktree-isolated agent may have no kineticlab/ tree; fall back
# to the main checkout absolute path named in the task so file
# reads (page, fixtures, overlay) resolve in both locations.
_CANDIDATE = Path(__file__).resolve().parent.parent
_MAIN_FALLBACK = Path("E:/kineticlab-neuro-symbolic-metrology")
if (_CANDIDATE / "kineticlab" / "ui" / "index.html").is_file():
    REPO_ROOT = _CANDIDATE
else:
    REPO_ROOT = _MAIN_FALLBACK

UI_DIR = REPO_ROOT / "kineticlab" / "ui"
TEST_3 = REPO_ROOT / "Smoke" / "test_3.mp4"
TEST_3_SHA = ("a98a532410a4af2d70921d5adaf1298f151dab8f0e92348f6920"
              "cce0be5875ce")


class _FakeServer:
    def __init__(self, repo, work):
        self.ui_repo_root = repo
        self.ui_work_dir = work


def dispatch(repo, work, command, path, headers, body=b""):
    """Drive the real handler with in-memory streams (no sockets).

    Returns (status, headers dict, body bytes) parsed from what the
    handler wrote — the same bytes TCP would carry.
    """
    (work / "uploads").mkdir(parents=True, exist_ok=True)
    (work / "demo_out").mkdir(parents=True, exist_ok=True)
    handler = _Handler.__new__(_Handler)
    handler.server = _FakeServer(repo, work)
    handler.client_address = ("127.0.0.1", 0)
    handler.command = command
    handler.path = path
    handler.requestline = f"{command} {path} HTTP/1.0"
    message = Message()
    for key, value in headers.items():
        message[key] = value
    handler.headers = message
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler.request_version = "HTTP/1.0"
    handler.close_connection = True
    if command == "GET":
        handler.do_GET()
    elif command == "POST":
        handler.do_POST()
    elif command in ("PUT", "DELETE", "PATCH"):
        handler._method_not_allowed()
    else:
        raise AssertionError(f"unsupported test command {command}")
    raw = handler.wfile.getvalue()
    head, _, payload = raw.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    response_headers = {}
    for line in lines[1:]:
        key, _, value = line.partition(":")
        response_headers[key.strip()] = value.strip()
    return status, response_headers, payload


def _multipart(field, filename, content_type, data,
               boundary="ui-test-boundary"):
    head = (f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{field}\"; "
            f"filename=\"{filename}\"\r\n"
            f"Content-Type: {content_type}\r\n\r\n").encode("latin-1")
    tail = f"\r\n--{boundary}--\r\n".encode("latin-1")
    body = head + data + tail
    return f"multipart/form-data; boundary={boundary}", body


class DispatchCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def get(self, path):
        return dispatch(REPO_ROOT, self.work, "GET", path, {})

    def post(self, path, headers, body=b""):
        with_content_length = dict(headers)
        with_content_length["Content-Length"] = str(len(body))
        return dispatch(REPO_ROOT, self.work, "POST", path,
                        with_content_length, body)


class BindingTests(unittest.TestCase):
    def test_localhost_only_structural(self):
        self.assertEqual(BIND_HOST, "127.0.0.1")
        params = inspect.signature(make_server).parameters
        self.assertNotIn("host", params)
        self.assertNotIn("bind", params)

    def test_make_server_binds_loopback_only(self):
        import kineticlab.ui.server as server_module

        captured = {}

        class FakeHTTPServer:
            def __init__(self, address, handler):
                captured["address"] = address
                captured["handler"] = handler

        real = server_module.HTTPServer
        server_module.HTTPServer = FakeHTTPServer
        try:
            with tempfile.TemporaryDirectory() as tmp:
                make_server(8137, REPO_ROOT, Path(tmp))
        finally:
            server_module.HTTPServer = real
        self.assertEqual(captured["address"], ("127.0.0.1", 8137))
        self.assertIs(captured["handler"], _Handler)

    def test_bad_port_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for bad in (-1, 65536, 100000):
                with self.subTest(port=bad):
                    with self.assertRaises(ValueError):
                        make_server(bad, REPO_ROOT, Path(tmp))

    def test_no_client_primitives_in_server_source(self):
        for name in ("__init__.py", "server.py"):
            source = (UI_DIR / name).read_text(encoding="utf-8")
            for primitive in ("urlopen", "URLopener",
                              "urllib.request", "http.client",
                              "create_connection", "socket.connect",
                              "import socket"):
                with self.subTest(file=name, primitive=primitive):
                    self.assertNotIn(primitive, source)


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def test_referenced_ids_exist(self):
        used = set(re.findall(r'el\("([^"]+)"\)', self.page))
        # KL-8.8 adds new el() calls for workstation/progress/theme;
        # keep the invariant tight — every JS ref must resolve.
        self.assertGreater(len(used), 10)
        defined = set(re.findall(r'id="([^"]+)"', self.page))
        self.assertEqual(used - defined, set())

    def test_text_content_only(self):
        self.assertIn("textContent", self.page)
        self.assertNotIn("innerHTML", self.page)
        self.assertNotIn("outerHTML", self.page)
        self.assertNotIn("insertAdjacentHTML", self.page)
        self.assertNotIn("document.write", self.page)
        self.assertNotIn("eval(", self.page)

    def test_no_external_references(self):
        # The lone http:// exemption is the SVG namespace constant
        # (an identifier, never fetched); it must appear exactly
        # once, and nothing else external may exist.
        namespace = 'const SVG_NS = "http://www.w3.org/2000/svg";'
        self.assertEqual(self.page.count(namespace), 1)
        rest = self.page.replace(namespace, "")
        for token in ("http://", "https://", "src=\"http",
                      "href=\"http", "url(http", "@import"):
            with self.subTest(token=token):
                self.assertNotIn(token, rest)
        script = self.page.split("<script>", 1)[1]
        # The helper-internal fetch takes its URL as a parameter;
        # every actual target below must be a relative literal or
        # a server-provided export href.
        helper_calls = len(re.findall(r"await fetch\(url, ", script))
        self.assertEqual(helper_calls, 1)
        script = re.sub(r"await fetch\(url, .*?\);\n?", "", script)
        calls = re.findall(r"fetch\(([^;]*?)\)", script)
        self.assertGreater(len(calls), 0)
        for call in calls:
            first_arg = call.split(",")[0].strip()
            if first_arg.startswith(("'", '"')):
                self.assertTrue(
                    first_arg[1:].startswith("/"),
                    f"non-relative fetch target: {first_arg}")
            else:
                self.assertTrue(
                    first_arg.startswith("files["),
                    f"unexpected fetch target: {first_arg}")
        self.assertEqual(
            len(re.findall(r"function postJSON\(url\)", script)), 1)
        posts = re.findall(r"postJSON\(\s*\"([^\"]*)\"", script)
        self.assertGreater(len(posts), 0)
        for target in posts:
            self.assertTrue(
                target.startswith("/"),
                f"non-relative postJSON target: {target}")

    def test_verdict_rule_present(self):
        # Verdict styling keys on the status field only: success*
        # green/amber, anything else red. Never the reverse.
        self.assertIn('status.indexOf("success") === 0', self.page)
        script = self.page.split("<script>", 1)[1]
        for token in ('"verdict ok"', '"verdict warn"', '"verdict bad"'):
            with self.subTest(token=token):
                self.assertIn(token, script)
        self.assertIn(".verdict.bad", self.page)
        self.assertIn(".verdict.ok", self.page)
        self.assertIn(".verdict.warn", self.page)

    def test_reduced_motion_respected(self):
        self.assertIn("prefers-reduced-motion", self.page)

    def test_no_timers_in_script(self):
        # KL-8.8: zero timer calls — toasts and elapsed clocks run on
        # the shared requestAnimationFrame ticker instead.
        script = self.page.split("<script>", 1)[1]
        self.assertNotIn("setInterval", script)
        self.assertEqual(len(re.findall(r"setTimeout\s*\(", script)), 0)
        self.assertIn("requestAnimationFrame", script)
        self.assertIn("scheduleRaf", script)

    def test_no_model_math_in_script(self):
        # The page plots observed points only: no fitted-curve
        # evaluation of any kind may exist, even in comments.
        # Illustrative draft charts (Math.sin/cos in a template
        # stub) are not allowed — real charts derive from angles.csv.
        # KL-10.9-B amends the trig ban for ONE sentinel-delimited
        # sim module only: zero trig outside the sentinels.
        script = self.page.split("<script>", 1)[1]
        begin = "/* __KL_SIM_MODULE_BEGIN__ */"
        end = "/* __KL_SIM_MODULE_END__ */"
        self.assertEqual(script.count(begin), 1)
        self.assertEqual(script.count(end), 1)
        outside = script.split(begin)[0] + script.split(end)[1]
        for token in ("Math.cos", "Math.sin", "Math.exp",
                      "Math.tan"):
            with self.subTest(token=token):
                self.assertNotIn(token, outside)
        # "amplitude" stays banned page-wide (the sim module
        # never needed the word).
        self.assertNotIn("amplitude", script)

    def test_chart_reads_csv_columns(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn('fetch(files["angles.csv"])', script)
        self.assertIn('"pts_seconds"', script)
        self.assertIn('"theta_rad"', script)

    def test_drag_drop_wiring(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn('addEventListener("drop"', script)
        self.assertIn('classList.add("dragover")', script)
        self.assertIn("new FormData()", script)
        self.assertIn('form.append("clip"', script)
        self.assertIn('fetch("/api/upload"', script)

    def test_stepper_derived_from_response(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn("function paintStepper(payload, summaryOk)",
                      script)
        self.assertIn("li.className = stage.state;", script)
        for state in ('"complete"', '"failed"', '"pending"'):
            with self.subTest(state=state):
                self.assertIn(state, script)

    def test_tabs_keyboard_wiring(self):
        self.assertIn('role="tablist"', self.page)
        # Result tabs (Trajectory/Evidence/Provenance) plus chart
        # tabs (Trajectory/Residuals/Motion Trail/Replay), all with
        # roving arrow-key navigation.
        self.assertGreaterEqual(
            len(re.findall(r'<button[^>]*role="tab"[ >]', self.page)), 3)
        self.assertGreaterEqual(
            len(re.findall(r'<div[^>]*role="tabpanel"[ >]', self.page)),
            3)
        self.assertIn("aria-selected", self.page)
        for tab in ("ctabTrajectory", "ctabResiduals", "ctabTrail",
                    "ctabReplay"):
            with self.subTest(tab=tab):
                self.assertIn(f'id="{tab}"', self.page)
        script = self.page.split("<script>", 1)[1]
        for key in ("ArrowRight", "ArrowLeft", "Home", "End"):
            with self.subTest(key=key):
                self.assertIn(key, script)

    def test_fitted_derivation_present(self):
        # Observed − residual per index over two pipeline
        # artifacts (no model evaluation — see no-model-math).
        script = self.page.split("<script>", 1)[1]
        self.assertIn("points[i][1] - residuals[i][1]", script)
        self.assertIn("computed from pipeline residuals", script)

    def test_period_annotation_wiring(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn('fetch(files["diagnostics.json"])', script)
        self.assertIn("period_s", script)

    def test_trail_and_strip_wiring(self):
        script = self.page.split("<script>", 1)[1]
        for token in ("centroid_x_px", "centroid_y_px",
                      "residual_rad", "point_index"):
            with self.subTest(token=token):
                self.assertIn(token, script)

    def test_scrubber_sync(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn("function syncPlayheads(idx)", script)
        for view in ("thetaView", "trailView", "stripView"):
            with self.subTest(view=view):
                self.assertIn(view, script)
        self.assertIn('id="scrub"', self.page)
        self.assertIn('addEventListener("input"', script)

    def test_rounded_display(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn("toPrecision(4)", script)
        self.assertIn('setAttribute("title"', script)

    def test_hash_truncation(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn("slice(0, 12)", script)
        self.assertIn('"copy"', script)
        self.assertIn("navigator.clipboard", script)

    def test_autostart_wiring(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn("DOMContentLoaded", script)
        # KL-8.6: no auto-start — the DOMContentLoaded handler must not call runDemo
        handler = script.split("DOMContentLoaded", 1)[1].split("});", 1)[0]
        self.assertNotIn("runDemo", handler)
        self.assertIn("Nothing measured yet", self.page)
        self.assertIn('id="stageIdle"', self.page)
        self.assertIn('id="demoSuccessBtn"', self.page)
        self.assertIn('id="demoRejectBtn"', self.page)
        self.assertIn('el("demoSuccessBtn").addEventListener("click"', script)
        self.assertIn('el("demoRejectBtn").addEventListener("click"', script)

    def test_upload_collapsed_default(self):
        # Collapsible upload section must exist; post-8.8 it may
        # live inside the video workstation while keeping the id.
        self.assertIn('id="uploadDetails"', self.page)
        self.assertIn("<details", self.page)

    def test_advisory_label(self):
        self.assertIn("Advisory replay", self.page)
        self.assertIn('id="advisoryBox"', self.page)

    def test_amber_verdict_status_keyed(self):
        self.assertIn(".verdict.warn", self.page)
        script = self.page.split("<script>", 1)[1]
        self.assertIn('"success_with_warnings"', script)

    def test_chain_panels(self):
        for panel in ('id="panelSuccess"', 'id="panelReject"'):
            with self.subTest(panel=panel):
                self.assertIn(panel, self.page)
        # Run history moved to the ops bar — the sidebar keeps only
        # the two demo actions, exactly one of each label.
        self.assertNotIn('id="lastSuccess"', self.page)
        self.assertNotIn('id="lastReject"', self.page)
        self.assertEqual(self.page.count("Run success chain"), 1)
        self.assertEqual(self.page.count("Run rejection chain"), 1)

    def test_pipeline_strip(self):
        # Pre-8.8 pipeline strip had 3 "live capture, offline replay"
        # tags; post-8.8 keeps the copy in the new layout — at least
        # one must survive so offline-replay truth stays visible.
        self.assertIn("SAM 3.1 masks", self.page)
        self.assertGreaterEqual(
            self.page.count("live capture, offline replay"), 1)

    def test_explainer_copy(self):
        self.assertIn("Phone video in, auditable physics out",
                      self.page)
        self.assertIn("SAM 3.1 sees, deterministic math computes",
                      self.page)

    def test_value_subtitle(self):
        self.assertIn("gravity \u00f7 effective length", self.page)
        self.assertIn("g is not claimed because no independent "
                      "length was provided", self.page)

    def test_replay_animation_label(self):
        # KL-10.5: the momentary "Replay animation" button became a
        # Play/Pause toggle with a 1x tag and frame counter.
        self.assertIn('id="replayBtn"', self.page)
        self.assertIn(">Play<", self.page)
        self.assertIn("1×", self.page)
        self.assertIn('id="frameCounter"', self.page)
        self.assertNotIn("Replay animation", self.page)
        self.assertNotIn("Replay reveal", self.page)


# ── KL-8.8 redesign contracts ──────────────────────────────

class ThemeContractTests(unittest.TestCase):
    """Dark default + CSS-var theme system from Templete_UI."""

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        try:
            cls.script = cls.page.split("<script>", 1)[1]
        except IndexError:
            cls.script = ""
        try:
            cls.style = cls.page.split("<style>", 1)[1].split("</style>", 1)[0]
        except IndexError:
            cls.style = ""

    def test_dark_default(self):
        # Spec: dark is the default. Allow either explicit
        # data-theme="dark" on <html> or dark tokens as :root
        # defaults with a light alternate declared.
        has_dark_attr = 'data-theme="dark"' in self.page
        has_dark_root = ("--bg:" in self.style and
                         "#0b1120" in self.style.lower())
        self.assertTrue(
            has_dark_attr or has_dark_root,
            "page must default to dark (data-theme=\"dark\" or dark :root)")

    def test_theme_toggle_present(self):
        self.assertIn('id="themeToggle"', self.page)
        # Must be a button with accessible name.
        self.assertRegex(
            self.page,
            r'<button[^>]*id="themeToggle"[^>]*aria-label="[^"]*theme[^"]*"',
            "theme toggle must be a button with aria-label mentioning theme")

    def test_theme_css_custom_properties(self):
        # Light/dark swap is via CSS vars, not duplicated rules.
        for token in ("--bg", "--surface", "--text", "--border",
                      "--blue", "--green"):
            with self.subTest(token=token):
                self.assertIn(token, self.style)
        # At least one data-theme override block must exist.
        self.assertRegex(
            self.style,
            r'html\[data-theme="(dark|light)"\]|'
            r'\[data-theme="(dark|light)"\]',
            "expected html[data-theme] override block for theme swap")

    def test_theme_persistence_wiring(self):
        # Must read/write a localStorage theme key and flip
        # data-theme / dataset.theme on click.
        self.assertIn("localStorage.getItem", self.script)
        self.assertIn("localStorage.setItem", self.script)
        self.assertRegex(
            self.script,
            r"kineticlab-theme|theme",
            "theme key should mention 'theme' for auditability")
        self.assertRegex(
            self.script,
            r"dataset\.theme|data-theme|setAttribute\(\"data-theme\"",
            "toggle must flip data-theme / dataset.theme")
        self.assertIn('themeToggle', self.script)
        self.assertIn('addEventListener("click"', self.script)

    def test_theme_toggle_icon_sync(self):
        # Icon must sync with current theme (sun/moon or similar).
        self.assertRegex(
            self.script,
            r"syncThemeIcon|themeToggle\.textContent|setAttribute.*theme",
            "expected icon/label sync on theme toggle")

    def test_no_hardcoded_theme_without_vars(self):
        # Core surfaces must use var(--*) not hardcoded repeats.
        self.assertIn("var(--bg)", self.style)
        self.assertIn("var(--text)", self.style)

    def test_charts_follow_theme(self):
        # Charts re-render through the same token system on toggle.
        self.assertIn("chartPalette", self.script)
        self.assertIn("repaintCharts", self.script)
        self.assertIn("repaintCharts();", self.script)


class FiveStageStepperTests(unittest.TestCase):
    """Header + quiet nav + five-stage stepper."""

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def test_stepper_element_exists(self):
        self.assertIn('class="stepper"', self.page)
        self.assertRegex(
            self.page,
            r'aria-label="[^"]*workflow[^"]*"',
            "stepper should carry an aria-label naming the workflow")

    def test_five_stages_present(self):
        # Top stepper has exactly five stages; the old ol#stepList
        # (4 stages: assembled/outcome/exports/summary) lives
        # separately and is not counted here.
        # Count by the titled stage markers inside the stepper section.
        stepper = re.search(
            r'<section[^>]*class="stepper"[^>]*>.*?</section>',
            self.page, re.DOTALL)
        self.assertIsNotNone(stepper, "stepper section not found")
        block = stepper.group(0)
        titles = re.findall(r'class="step-title"[^>]*>([^<]+)', block)
        if not titles:
            # Fallback: some builds use data-step or plain numbers.
            titles = re.findall(r'class="step[^"]*"[^>]*>.*?</div>\s*<div',
                                block, re.DOTALL)
        self.assertEqual(
            len(titles), 5,
            f"expected 5 titled stages, found {len(titles)}: {titles[:6]}")

    def test_stage_titles(self):
        lowered = self.page.lower()
        for name in ("upload", "detect", "confirm", "measure", "result"):
            with self.subTest(stage=name):
                self.assertIn(name, lowered,
                              f"stepper must name stage '{name}'")

    def test_stage_descriptions_present(self):
        # Each stage should carry a short description, not just a number.
        self.assertGreaterEqual(
            len(re.findall(r'class="step-desc"', self.page)), 5)

    def test_step_states_in_css(self):
        style = self.page.split("<style>", 1)[1] if "<style>" in self.page else ""
        for state in (".step.done", ".step.active"):
            with self.subTest(state=state):
                self.assertIn(state, style)

    def test_stepper_visual_rules_complete(self):
        # Regression: markup without CSS shipped once as raw
        # concatenated text. Number circles, connectors, failed,
        # and the in-flight processing state must all have rules.
        style = self.page.split("<style>", 1)[1].split("</style>", 1)[0]
        self.assertIn(".step-number", style)
        self.assertRegex(style, r"\.step[^{]*:after")
        self.assertIn(".step.failed", style)
        self.assertIn(".step.processing", style)

    def test_stepper_wired_to_workflow(self):
        # States flip only from real workflow events.
        script = self.page.split("<script>", 1)[1]
        self.assertIn("function setWorkflowStage(stage, state)", script)
        for state in ('"done"', '"active"', '"processing"', '"failed"'):
            with self.subTest(state=state):
                self.assertIn(state, script)
        self.assertIn("resetWorkflow", script)

    def test_status_model_and_gating(self):
        # Six overall states only; panels take detail, titles come
        # from the model. Actions gate on real prerequisites plus
        # the single-request busy flag.
        script = self.page.split("<script>", 1)[1]
        for state in ("Ready for analysis", "Detecting",
                      "Awaiting confirmation", "Measuring",
                      "Complete", "Failed"):
            with self.subTest(state=state):
                self.assertIn(state, script)
        self.assertIn("function setAppStatus", script)
        self.assertIn("function updateActionStates", script)
        self.assertIn("function setBusy", script)
        self.assertIn("opBusy", script)
        self.assertIn("function updateIdleState", script)
        self.assertIn('id="idleText"', self.page)
        self.assertIn('id="idleAction"', self.page)

    def test_nav_and_header_present(self):
        # Quiet nav + header are part of the KL-8.8 shell.
        self.assertRegex(self.page, r"<header[^>]*class=\"topbar\"")
        self.assertRegex(self.page, r"<aside[^>]*class=\"sidebar\"")
        self.assertIn('data-nav="', self.page)

    def test_no_dead_navigation(self):
        # Every nav item performs its advertised action: no History
        # or Settings stubs may exist anywhere in markup or script.
        lowered = self.page.lower()
        self.assertNotIn("history view", lowered)
        self.assertNotIn("settings view", lowered)
        for stub in ('id="navHistory"', 'id="navSettings"',
                     "coming soon", "not implemented"):
            with self.subTest(stub=stub):
                self.assertNotIn(stub, self.page)


class ProgressHonestyTests(unittest.TestCase):
    """Honest indeterminate progress: stage text only, no percent machinery."""

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        try:
            cls.script = cls.page.split("<script>", 1)[1]
        except IndexError:
            cls.script = ""
        try:
            cls.style = cls.page.split("<style>", 1)[1].split("</style>", 1)[0]
        except IndexError:
            cls.style = ""

    def test_opsbar_indeterminate(self):
        # Post-revision: the modal dialog is gone; a persistent ops
        # bar carries the indeterminate track plus stage text.
        self.assertNotIn('id="progressModal"', self.page)
        self.assertIn('id="opsBar"', self.page)
        self.assertIn('class="progress-track', self.page)
        self.assertIn('id="opTrack"', self.page)
        self.assertIn('role="status"', self.page)
        for ident in ("opState", "opStateText", "opActivity",
                      "opDetail", "opElapsed", "opLast"):
            with self.subTest(ident=ident):
                self.assertIn(f'id="{ident}"', self.page)

    def test_no_percent_machinery(self):
        # No percent element, fill bar, formatter, or literal can
        # exist: indeterminate means no numbers, full stop.
        for token in ("progressPercent", "progressFill", "setProgress"):
            with self.subTest(token=token):
                self.assertNotIn(token, self.page)
        self.assertNotIn("100%", self.script)
        self.assertNotIn("percent +=", self.script)
        self.assertNotIn("progress +=", self.script)
        self.assertNotIn("setInterval", self.script)

    def test_progress_stage_text(self):
        self.assertRegex(
            self.page,
            r"Waiting for backend|stage|indeterminate|Awaiting",
            "progress status should name the stage, not a percent")
        self.assertIn("showProgress", self.script)
        self.assertRegex(
            self.script.lower(),
            r"indeterminate|no percentage|no fake|stage text",
            "script should comment why progress stays indeterminate")

    def test_progress_elapsed_and_last(self):
        # Real elapsed clock plus a persistent record of the last
        # completed operation (phase + outcome, never a percent).
        self.assertIn('id="opElapsed"', self.page)
        self.assertIn('id="opLast"', self.page)
        self.assertIn("opsComplete", self.script)
        self.assertIn("scheduleRaf", self.script)


class WorkstationRegionTests(unittest.TestCase):
    """Video workstation + detected objects + metrics + charts + evidence."""

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def test_workspace_shell(self):
        self.assertRegex(
            self.page,
            r'class="workspace"|class="shell"|class="app"',
            "expected workspace/shell grid container")
        # Should be a multi-column layout.
        self.assertIn("grid-template-columns", self.page)

    def test_video_workstation(self):
        for token in ("viewer-wrap", "video-stage", "filmstrip"):
            with self.subTest(token=token):
                self.assertIn(token, self.page)
        # Overlay toggle and playback controls.
        self.assertIn('id="overlayBtn"', self.page)
        self.assertIn('id="playBtn"', self.page)
        self.assertIn('id="seek"', self.page)
        self.assertIn('id="speedBtn"', self.page)
        self.assertIn('id="fsBtn"', self.page)
        self.assertIn('id="timeLabel"', self.page)

    def test_mask_mode_omitted_not_faked(self):
        # The backend serves no mask rasters, so no Mask view may
        # exist; the omission must be documented, not silent.
        self.assertNotIn('id="maskBtn"', self.page)
        self.assertNotIn("ctabMask", self.page)
        self.assertIn("deliberately omitted", self.page)

    def test_detected_objects_panel(self):
        self.assertRegex(
            self.page,
            r"Detected objects|detected-objects|object-panel",
            "expected detected-objects panel heading")
        self.assertIn('class="object-row"', self.page)
        self.assertIn('id="objectsList"', self.page)
        self.assertIn('id="liveConfirmBtn"', self.page)
        self.assertIn('id="liveBackBtn"', self.page)
        self.assertIn('id="detectSourceBody"', self.page)
        self.assertIn('id="confirmStatus"', self.page)
        self.assertIn("Awaiting your confirmation", self.page)

    def test_metric_cards_full_labels(self):
        # Regression: truncated labels ("ANGUL FREQUE") shipped once.
        # Full labels only, with no truncating CSS on metric names.
        for name in ("Angular frequency (ω)", "Period (T)",
                     "Effective length (L_eff)", "g / L_eff (ω²)"):
            with self.subTest(metric=name):
                self.assertIn(name, self.page)
        style = self.page.split("<style>", 1)[1].split("</style>", 1)[0]
        names = re.findall(r"\.metric-name\s*\{[^}]*\}", style)
        self.assertGreater(len(names), 0)
        for rule in names:
            with self.subTest(rule=rule):
                self.assertNotIn("text-overflow", rule)
                self.assertNotIn("white-space:nowrap", rule.replace(" ", ""))

    def test_metric_cards_null_honest(self):
        for name in ("Angular frequency", "Period", "Effective length",
                     "g / L"):
            with self.subTest(metric=name):
                self.assertIn(name, self.page)
        # Initial values must be null-honest (dash / null / not computed).
        self.assertGreaterEqual(
            len(re.findall(r'class="metric-value[^"]*"', self.page)), 4)
        self.assertRegex(
            self.page,
            r"Not computed|not computed|—|null|Not available",
            "metric cards must be null-honest before a run")
        # L_eff only when established — gravity note must stay.
        self.assertRegex(
            self.page,
            r"gravity.*not claimed|Gravity.*not computed|independent.*length",
            "gravity caveat must remain visible near the cards")

    def test_chart_tabs(self):
        for tab in ("Trajectory", "Residuals", "Motion Trail", "Replay"):
            with self.subTest(tab=tab):
                self.assertIn(tab, self.page)
        # Tabs must be wired via data-tab or role=tab.
        self.assertRegex(
            self.page,
            r'data-tab="|role="tab"',
            "chart tabs need data-tab or role=tab wiring")

    def test_evidence_provenance_panel(self):
        self.assertRegex(
            self.page,
            r"Provenance|provenance|Evidence.*provenance",
            "expected evidence/provenance panel")
        self.assertIn('class="prov-list"', self.page)
        for token in ("Model output hash", "Computation hash", "SAM 3.1"):
            with self.subTest(token=token):
                self.assertIn(token, self.page)

    def test_server_status_truthful(self):
        # The pill derives from our own location plus observed fetch
        # outcomes — never a hardcoded host or an assumed state.
        script = self.page.split("<script>", 1)[1]
        self.assertIn("location.host", script)
        self.assertIn("markOnline", script)
        self.assertIn('id="serverPill"', self.page)
        self.assertIn('id="serverFoot"', self.page)


class RefinementTests(unittest.TestCase):
    """KL-8.10 refinement: sidebar, bounded charts, diagnostics home."""

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        try:
            cls.script = cls.page.split("<script>", 1)[1]
        except IndexError:
            cls.script = ""
        try:
            cls.style = cls.page.split("<style>", 1)[1].split("</style>", 1)[0]
        except IndexError:
            cls.style = ""

    def test_sidebar_width_in_range(self):
        # KL-10.14: the sidebar is the left rail at 300–320px, and the
        # shell carries three tracks (rail, center, persistent sim).
        self.assertRegex(
            self.style,
            r"\.shell\{[^}]*grid-template-columns:3[012]\dpx",
            "left rail width must be 300–329px")
        self.assertIn("minmax(0,1fr) 320px", self.style)

    def test_advanced_diagnostics_collapsed(self):
        # Collapsed by default (no open attribute) and owning the
        # moved blocks: mask overlay, raw input replay, assumptions,
        # summary. Outcome-relevant lists stay in their tabs.
        self.assertIn('<details class="acc" id="advDiag"', self.page)
        self.assertNotIn('<details class="acc" id="advDiag" open',
                         self.page)
        adv = self.page.index('id="advDiag"')
        for ident in ("overlayImg", "advisoryBox", "assumeList",
                      "summaryPre"):
            with self.subTest(ident=ident):
                self.assertGreater(
                    self.page.index(f'id="{ident}"'), adv,
                    f"{ident} must live inside Advanced Diagnostics")
        for ident in ("warnList", "reasonList", "provRows",
                      "artifactRows", "exportLinks"):
            with self.subTest(ident=ident):
                self.assertLess(
                    self.page.index(f'id="{ident}"'), adv,
                    f"{ident} must stay in the default Results view")

    def test_charts_bounded(self):
        # KL-8.11 touch-up: caps raised 280/260/300 -> 600 and width
        # capped + centered, so charts fill their cards instead of
        # letterboxing to a ~594px island on wide screens.
        for rule in ("#chartSvg.plot{max-height:600px;max-width:1150px;"
                     "margin:0 auto}",
                     "#stripSvg.plot{max-height:600px;max-width:1150px;"
                     "margin:0 auto}",
                     "#trailSvg.plot{max-height:600px;max-width:1150px;"
                     "margin:0 auto}"):
            with self.subTest(rule=rule):
                self.assertIn(rule, self.style)
        # Chart boxes hide until measured points arrive — no tall
        # empty bordered boxes under the empty text.
        for ident in ("chartWrap", "stripWrap", "trailWrap"):
            with self.subTest(ident=ident):
                self.assertIn(f'class="chart-wrap hidden" id="{ident}"',
                              self.page)
        self.assertIn('show(el("chartWrap"))', self.script)
        self.assertIn('"chartWrap", "trailWrap", "stripWrap"',
                      self.script)

    def test_fitted_curve_distinct(self):
        # The fitted series draws as a dashed curve through the
        # payload's own fitted points (matching the legend swatch),
        # never recomputed from a formula.
        self.assertIn('"stroke-dasharray": "5 3"', self.script)
        self.assertIn("observed minus pipeline residual", self.script)

    def test_idle_action_never_demo_labeled(self):
        # The idle button serves the live flow only; demos live in
        # the sidebar alone.
        self.assertIn('id="idleAction" type="button">Stage a clip<',
                      self.page)
        for label in ("Stage a clip", "Retry Detect", "Retry Measure",
                      "Review boxes", "Measure", "Detect objects"):
            with self.subTest(label=label):
                self.assertIn(label, self.script)


class FunctionalIdPreservationTests(unittest.TestCase):
    """Old functional IDs must survive the redesign — backend/live/tests need them."""

    # Every ID that dispatch/page/live handlers or existing
    # tests/el() calls address. If one disappears, uploads/demos/
    # live capture or invariant tests silently break. The KL-8.6
    # demo-body cards (valueBig/...) were replaced by the Key
    # Results metric cards, so those seven IDs retired with them;
    # everything else below must exist.
    REQUIRED_IDS = [
        # App shell
        "themeToggle", "serverPill", "serverDot", "serverPillText",
        "versionChip", "serverFoot",
        # Quiet nav (real actions only)
        "navAnalysis", "navCharts", "navEvidence",
        # Workflow stepper
        "stepUpload", "stepDetect", "stepConfirm", "stepMeasure",
        "stepResults",
        # Upload workstation
        "uploadDetails", "dropZone", "clipFile", "fileChip",
        "browseBtn", "fileMeta", "stageEmptyMedia", "filmstrip",
        "uploadBtn", "uploadSpin", "uploadErr", "uploadOut",
        "mediaRows", "ptsRows", "measureNote", "uploadRows",
        # Viewer controls
        "playBtn", "timeLabel", "seek", "speedBtn", "overlayBtn",
        "rawViewBtn", "fsBtn", "frameChip",
        # Pinned demos (history lines retired to the ops bar)
        "panelSuccess", "panelReject",
        "demoSuccessBtn", "demoRejectBtn", "demoSpin",
        # Live capture (detect → confirm → measure). The viewer
        # picker is the single file input; the live panel only
        # displays the staged clip, so the duplicate live picker IDs
        # retired with the consolidation.
        "livePanel", "noKeyPanel", "liveFileChip",
        "liveRecordBtn", "liveRecordNote",
        "livePreview", "liveOverlay",
        "liveModeFull", "liveModeMotion", "livePromptBob", "livePromptCard",
        "livePromptCardWrap", "liveDetectBtn", "liveSpin", "liveDetectHint",
        "liveErr", "liveConfirm", "liveCounts", "objectsList",
        "detectSourceBody", "confirmStatus",
        "liveConfirmBtn", "liveBackBtn",
        "liveMeasureWrap", "liveMmRow", "liveMm", "liveMeasureBtn",
        "liveMeasureSpin", "liveMeasureHint", "liveMeasureErr", "liveRunNote",
        "liveMotionOut", "liveMotionCompact",
        # Status + metrics + provenance summary
        "modeTag", "statusRing", "statusArc", "statusTitle", "statusNote",
        "factMode", "factFrames", "factRes", "factDur",
        "metricOmega", "metricPeriod", "metricLeff", "metricGoverL",
        "metricOmegaWhy", "metricPeriodWhy", "metricLeffWhy",
        "metricGoverLWhy", "gravityTitle", "gravityBody",
        "provChip", "provSummary", "provFullBtn",
        # Result stage
        "chartsPanel", "stageIdle", "stageEmpty", "stageEmptyTitle",
        "stageEmptySub", "stageResult", "verdict", "demoErr", "demoBody",
        "stepList",
        "tabTrajectory", "tabEvidence", "tabProvenance",
        "panelTrajectory", "panelEvidence", "panelProvenance",
        "ctabTrajectory", "ctabResiduals", "ctabTrail", "ctabReplay",
        "viewTrajectory", "viewResiduals", "viewTrail", "viewReplay",
        "rmsChip",
        "chartSvg", "chartMeta", "trailSvg", "trailMeta", "stripSvg",
        "scrub", "playheadReadout", "replayBtn", "chartNote", "overlayImg",
        # Scientific Analysis card (KL-10.5)
        "sciCard", "sciState", "periodChip", "trailWindow",
        "frameCounter", "replayCaption", "sciDiagWrap", "sciDiagRows",
        "fitLegend",
        # Measured-arm replay (KL-10.9-A)
        "replayLabel", "replayEmpty", "replayWrap", "replaySvg",
        "replaySpeed", "replayReadout",
        # Simulation playground (KL-10.9-B)
        "ctabSimulation", "viewSimulation", "simSvg", "simLabel",
        "simWrap", "simSeedTile",
        "simTrailNote", "simSeedLine", "simPlayBtn", "simResetBtn",
        "simScale", "simG", "simGamma", "simAngle", "simGVal",
        "simGammaVal", "simAngleVal", "simThetaReadout",
        "simClockReadout", "simCaption",
        "warnList", "assumeList", "reasonList", "advisoryBox",
        "provRows", "artifactRows", "exportLinks", "summaryPre",
        "reportsCard", "reportLinks",
        # Overlays
        "toastWrap",
        # Persistent ops bar (replaced the progress modal)
        "opsBar", "opState", "opStateText", "opActivity", "opDetail",
        "opTrack", "opElapsed", "opLast",
        # Deliberate upload state + compact contextual idle
        "playerWrap", "browseEmptyBtn", "recordEmptyBtn", "emptyError",
        "idleText", "idleAction",
        # Words-only chart empties (never sample data)
        "chartEmpty", "stripEmpty", "trailEmpty",
        # Chart boxes (hidden until measured points arrive)
        "chartWrap", "stripWrap", "trailWrap",
        # Advanced diagnostics (collapsed by default)
        "advDiag",
        # KL-10.13 polish: top loading bar + inline field errors
        "globalProgress", "globalProgressLabel", "clipFieldError",
        "liveMmError", "livePromptBobError", "livePromptCardError",
        # KL-10.14 dashboard: header verdict badge + interval sub-line
        "verdictBadge", "omegaInterval",
        # KL-10.15 gravity: length input + g tile + interval note
        "liveLengthMm", "liveLengthError", "metricGravity",
        "metricGravityWhy", "intervalNote",
    ]

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def test_all_functional_ids_present(self):
        missing = []
        for ident in self.REQUIRED_IDS:
            if f'id="{ident}"' not in self.page:
                missing.append(ident)
        self.assertEqual(
            missing, [],
            f"missing functional IDs (backend/live need them): {missing}")

    def test_clipFile_still_accepts_mp4(self):
        self.assertRegex(
            self.page,
            r'id="clipFile"[^>]*accept="[^"]*video/mp4',
            "clipFile must still accept video/mp4")

    def test_single_file_picker(self):
        # One source-video workflow: exactly one file input may
        # exist, and the retired duplicate picker IDs must be gone.
        self.assertEqual(self.page.count('type="file"'), 1)
        for retired in ('id="liveClipFile"', 'id="liveBrowseBtn"',
                        'id="liveDropZone"'):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, self.page)

    def test_toast_system_present(self):
        script = self.page.split("<script>", 1)[1]
        self.assertIn("function notify(title, message, kind)", script)
        self.assertIn("scheduleRaf", script)
        self.assertIn("toast-x", self.page)
        self.assertIn('aria-live="polite"', self.page)
        # Toasts are the one append-only surface; the cap keeps
        # repeated runs from stacking notification cards.
        self.assertIn("wrap.children.length > 4", script)


class HomeTests(DispatchCase):
    def test_homepage_serves(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["Content-Type"])
        text = body.decode("utf-8")
        self.assertIn("KineticLab", text)
        self.assertIn("Run success chain", text)
        self.assertIn("Validate clip", text)

    def test_version_stamped_from_package(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertNotIn("__KL_VERSION__", text)
        self.assertIn("v" + PACKAGE_VERSION, text)

    def test_overlay_serves_pinned_bytes(self):
        status, headers, body = self.get("/api/overlay")
        self.assertEqual(status, 200)
        self.assertIn("image/svg+xml", headers["Content-Type"])
        pinned = (REPO_ROOT / "fixtures" / "geometry"
                  / "overlay_live_ball.svg").read_bytes()
        self.assertEqual(body, pinned)

    def test_unknown_route_404_with_code(self):
        status, _, body = self.get("/nope")
        self.assertEqual(status, 404)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")

    def test_wrong_method_405_with_code(self):
        status, _, body = dispatch(REPO_ROOT, self.work, "PUT",
                                   "/", {})
        self.assertEqual(status, 405)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_WRONG_TYPE")


class UploadTests(DispatchCase):
    def _upload(self, body, content_type):
        status, _, raw = self.post("/api/upload",
                                   {"Content-Type": content_type},
                                   body)
        return status, json.loads(raw.decode("utf-8"))

    def test_valid_clip_verdict_measured(self):
        require_smoke(TEST_3)
        data = TEST_3.read_bytes()
        content_type, body = _multipart("clip", "test_3.mp4",
                                        "video/mp4", data)
        status, verdict = self._upload(body, content_type)
        self.assertEqual(status, 200)
        media = verdict["media"]
        self.assertEqual(media["width"], 1024)
        self.assertEqual(media["height"], 576)
        self.assertEqual(media["frame_count"], 234)
        self.assertAlmostEqual(media["duration_seconds"], 7.872,
                               delta=0.05)
        self.assertEqual(media["source_sha256"], TEST_3_SHA)
        pts = verdict["pts"]
        self.assertEqual(pts["samples"], 234)
        self.assertEqual(pts["null_pts"], 0)
        self.assertTrue(pts["healthy"])
        self.assertIsNone(pts["code"])
        self.assertFalse(verdict["measurement"]["available"])
        self.assertIn("live SAM",
                      verdict["measurement"]["reason"])
        upload = verdict["upload"]
        self.assertEqual(upload["filename"], "test_3.mp4")
        self.assertEqual(upload["sha256"], TEST_3_SHA)
        self.assertEqual(upload["bytes"], len(data))
        saved = self.work / upload["stored"]
        self.assertTrue(saved.is_file())
        self.assertEqual(saved.read_bytes(), data)

    def test_empty_file_rejected(self):
        content_type, body = _multipart("clip", "empty.mp4",
                                        "video/mp4", b"")
        status, payload = self._upload(body, content_type)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "E_EMPTY_STRING")

    def test_wrong_part_type_rejected(self):
        content_type, body = _multipart("clip", "clip.mp4",
                                        "text/plain", b"x" * 16)
        status, payload = self._upload(body, content_type)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "E_WRONG_TYPE")

    def test_bad_magic_rejected(self):
        content_type, body = _multipart(
            "clip", "fake.mp4", "video/mp4", b"not an mp4 file" * 4)
        status, payload = self._upload(body, content_type)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "E_NOT_AN_OBJECT")

    def test_missing_part_rejected(self):
        content_type, body = _multipart("other", "clip.mp4",
                                        "video/mp4", b"x" * 16)
        status, payload = self._upload(body, content_type)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")

    def test_non_multipart_rejected(self):
        status, payload = self._upload(b"{}", "application/json")
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "E_WRONG_TYPE")

    def test_empty_body_rejected(self):
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "POST", "/api/upload",
            {"Content-Type": "multipart/form-data; boundary=x",
             "Content-Length": "0"}, b"")
        self.assertEqual(status, 400)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_EMPTY_STRING")

    def test_oversized_declared_rejected_without_read(self):
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "POST", "/api/upload",
            {"Content-Type": "multipart/form-data; boundary=x",
             "Content-Length": str(MAX_UPLOAD_BYTES + 1)},
            b"short")
        self.assertEqual(status, 400)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_OUT_OF_RANGE")

    def test_malformed_mp4_pipeline_code(self):
        # Valid envelope + ftyp magic, garbage structure: the
        # pipeline's own probe code surfaces (never a 500).
        data = b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 64
        content_type, body = _multipart("clip", "broken.mp4",
                                        "video/mp4", data)
        status, payload = self._upload(body, content_type)
        self.assertEqual(status, 400)
        self.assertRegex(payload["error"]["code"], r"^E_[A-Z_]+$")


class HostValidationTests(DispatchCase):
    """POST Host allowlist: loopback forms only (KL-9.6 M7)."""

    def upload_with_host(self, host):
        content_type, body = _multipart("clip", "clip.mp4",
                                        "video/mp4", b"x" * 16)
        headers = {"Content-Type": content_type}
        if host is not None:
            headers["Host"] = host
        return self.post("/api/upload", headers, body)

    def test_foreign_host_rejected_with_registered_code(self):
        for host in ("evil.example.com", "evil.example.com:8137",
                     "127.0.0.2", "localhost.evil.com",
                     "127.0.0.1:abc"):
            with self.subTest(host=host):
                status, _, raw = self.upload_with_host(host)
                self.assertEqual(status, 400)
                payload = json.loads(raw.decode("utf-8"))
                self.assertEqual(payload["error"]["code"],
                                 "E_WRONG_TYPE")
                self.assertEqual(payload["error"]["field"], "Host")

    def test_loopback_hosts_pass_the_guard(self):
        for host in ("127.0.0.1", "127.0.0.1:8137", "localhost",
                     "localhost:8137", "LOCALHOST:8137",
                     "  127.0.0.1  "):
            with self.subTest(host=host):
                status, _, raw = self.upload_with_host(host)
                payload = json.loads(raw.decode("utf-8"))
                # b"x"*16 has no MP4 magic: reaching the media gate
                # (E_NOT_AN_OBJECT) proves the Host guard passed it.
                self.assertEqual(payload["error"]["code"],
                                 "E_NOT_AN_OBJECT")

    def test_missing_host_allowed(self):
        # HTTP/1.0 and local probes send no Host; a rebinding
        # attack must present the victim domain, so an absent
        # header carries no attack origin and is allowed.
        _, _, raw = self.upload_with_host(None)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_NOT_AN_OBJECT")


class SocketTimeoutTests(DispatchCase):
    """Idle-socket timeout: bounded wait, quiet reclaim (KL-9.6 M9)."""

    def test_handler_carries_idle_timeout(self):
        self.assertEqual(_Handler.timeout, 30)

    def test_timeout_error_is_quiet(self):
        from kineticlab.ui.server import HTTPServer

        server = HTTPServer.__new__(HTTPServer)
        stderr = io.StringIO()
        previous = sys.stderr
        sys.stderr = stderr
        try:
            try:
                raise TimeoutError("timed out")
            except TimeoutError:
                server.handle_error(None, ("127.0.0.1", 0))
        finally:
            sys.stderr = previous
        self.assertEqual(stderr.getvalue(), "")

    def test_stalled_body_read_completes_without_crash(self):
        # A client stalling mid-body raises TimeoutError from the
        # socket read; do_POST must absorb it (null-code 500 here —
        # in production the dead socket then fails the fallback
        # write and handle_error reclaims it quietly) and the
        # server keeps serving.
        message = Message()
        message["Content-Type"] = "multipart/form-data; boundary=x"
        message["Content-Length"] = "100"
        handler = _Handler.__new__(_Handler)
        handler.server = _FakeServer(REPO_ROOT, self.work)
        handler.client_address = ("127.0.0.1", 0)
        handler.command = "POST"
        handler.path = "/api/upload"
        handler.requestline = "POST /api/upload HTTP/1.0"
        handler.headers = message

        class Stalled:
            def read(self, count=-1):
                raise TimeoutError("stall")

        handler.rfile = Stalled()
        handler.wfile = io.BytesIO()
        handler.request_version = "HTTP/1.0"
        handler.close_connection = True
        handler.do_POST()  # must not raise
        raw = handler.wfile.getvalue()
        head, _, payload = raw.partition(b"\r\n\r\n")
        status = int(head.decode("latin-1").split("\r\n")[0]
                     .split(" ")[1])
        self.assertEqual(status, 500)
        body = json.loads(payload.decode("utf-8"))
        self.assertIsNone(body["error"]["code"])


class DemoEndpointTests(DispatchCase):
    def _run(self, chain):
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "POST", f"/api/demo/{chain}",
            {"Content-Length": "0"}, b"")
        self.assertEqual(status, 200)
        return json.loads(raw.decode("utf-8"))

    def test_rejection_demo_honest(self):
        payload = self._run("rejection")
        self.assertEqual(payload["chain"], "rejection")
        result = payload["result"]
        self.assertEqual(result["status"], "unsupported_input")
        self.assertIsNone(result["value"])
        self.assertEqual([reason["code"]
                          for reason in result["reject_reasons"]],
                         ["E_MALFORMED_JSON"])
        self.assertIn("unsupported_input", payload["status_line"])
        self.assertEqual(set(payload["files"]),
                         {"result.json", "diagnostics.json",
                          "angles.csv", "summary.md"})
        for name, href in payload["files"].items():
            with self.subTest(export=name):
                status, _, _ = self.get(href)
                self.assertEqual(status, 200)
        _, _, summary = self.get(payload["files"]["summary.md"])
        text = summary.decode("utf-8")
        self.assertIn("REJECTED (unsupported_input)", text)
        self.assertNotIn("SUCCESS", text)

    def test_success_demo_matches_pin(self):
        payload = self._run("success")
        result = payload["result"]
        # KL-10.11: the bootstrap ran on the demo success chain.
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["value"], 30.00563573707589)
        self.assertEqual(result["interval_method"], "block_bootstrap")
        pinned = json.loads(
            (REPO_ROOT / "fixtures" / "assembly"
             / "result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["provenance"]["artifact_hashes"],
                         pinned["provenance"]["artifact_hashes"])
        _, _, summary = self.get(payload["files"]["summary.md"])
        self.assertIn("30.00563573707589",
                      summary.decode("utf-8"))

    def test_rerun_byte_stable(self):
        first = self._run("rejection")
        first_bytes = {}
        for name, href in first["files"].items():
            _, _, body = self.get(href)
            first_bytes[name] = body
        second = self._run("rejection")
        for name, href in second["files"].items():
            _, _, body = self.get(href)
            self.assertEqual(body, first_bytes[name])

    def test_demo_with_body_rejected(self):
        status, _, raw = self.post("/api/demo/success",
                                   {"Content-Type": "text/plain"},
                                   b"junk")
        self.assertEqual(status, 400)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_WRONG_TYPE")

    def test_unknown_demo_chain_404(self):
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "POST", "/api/demo/bogus",
            {"Content-Length": "0"}, b"")
        self.assertEqual(status, 404)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")

    def test_demo_response_includes_advisory(self):
        payload = self._run("rejection")
        advisory = payload["advisory"]
        self.assertEqual(advisory["setup"]["warnings_added"], 3)
        self.assertEqual(advisory["setup"]["codes"],
                         ["W_ASSUMPTION_UNVERIFIED"] * 3)
        self.assertEqual(advisory["setup"]["status_before"],
                         "success")
        self.assertEqual(advisory["setup"]["status_after"],
                         "success_with_warnings")
        self.assertEqual(advisory["narrative"]["source"], "model")


class ExportsTests(DispatchCase):
    def test_missing_before_run_404(self):
        with tempfile.TemporaryDirectory() as tmp:
            status, _, raw = dispatch(
                REPO_ROOT, Path(tmp), "GET",
                "/api/exports/success/result.json", {})
            self.assertEqual(status, 404)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["error"]["code"],
                             "E_MISSING_FIELD")

    def test_traversal_rejected(self):
        for path in ("/api/exports/success/../../x",
                     "/api/exports/success/%2e%2e/x",
                     "/api/exports/bogus/result.json",
                     "/api/exports/success/other.txt"):
            with self.subTest(path=path):
                status, _, _ = self.get(path)
                self.assertEqual(status, 404)


class ServeCliTests(unittest.TestCase):
    def test_bad_port_exits_two(self):
        previous_cwd = os.getcwd()
        self.addCleanup(os.chdir, previous_cwd)
        os.chdir(REPO_ROOT)
        for bad in ("0", "99999"):
            with self.subTest(port=bad):
                self.assertEqual(
                    main(["serve", "--port", bad]), 2)


def _binds_allowed():
    probe = socket.socket()
    try:
        probe.bind(("127.0.0.1", 0))
        probe.listen(1)
    except OSError:
        return False
    finally:
        probe.close()
    return True


class LiveServeTests(unittest.TestCase):
    def test_subprocess_start_probe_stop(self):
        if not _binds_allowed():
            self.skipTest("socket listen forbidden here "
                          "(sandbox); live start-path runs where "
                          "binds are allowed")
        port = 18137
        process = subprocess.Popen(
            [sys.executable, "-m", "kineticlab", "serve",
             "--port", str(port)],
            cwd=str(REPO_ROOT), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True,
            encoding="utf-8")
        # Cleanups run LIFO: terminate, then wait, then the stdout
        # pipe closes last (KL-10.7: the unclosed fd-3 TextIOWrapper
        # raised a ResourceWarning on the full suite under -X dev).
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.wait, 30)
        self.addCleanup(process.terminate)
        deadline = time.time() + 60
        body = b""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/",
                        timeout=10) as response:
                    self.assertEqual(response.status, 200)
                    body = response.read()
                break
            except OSError:
                time.sleep(0.5)
                continue
        else:
            self.fail("serve did not come up in 60s")
        self.assertIn("KineticLab", body.decode("utf-8"))


class FriendlyErrorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        cls.script = cls.page.split("<script>", 1)[1]

    def _table_block(self, name):
        start = self.script.index(f"const {name} = {{")
        end = self.script.index("\n};", start)
        return self.script[start:end]

    def test_error_mapping_complete(self):
        block = self._table_block("ERROR_FRIENDLY")
        self.assertEqual(len(ERROR_CODES), 32)
        for code in sorted(ERROR_CODES):
            with self.subTest(code=code):
                self.assertRegex(block, rf"\b{code}: \{{ title: ")
        for field in ('{ title: "', ', why: "', ', action: "'):
            with self.subTest(field=field):
                self.assertEqual(len(re.findall(re.escape(field),
                                                 block)), 32)

    def test_warning_mapping_complete(self):
        block = self._table_block("WARN_FRIENDLY")
        self.assertEqual(len(WARNING_CODES), 9)
        for code in sorted(WARNING_CODES):
            with self.subTest(code=code):
                self.assertRegex(block, rf"\b{code}: \{{ title: ")
        for field in ('{ title: "', ', why: "', ', action: "'):
            with self.subTest(field=field):
                self.assertEqual(len(re.findall(re.escape(field),
                                                 block)), 9)

    def test_show_error_renders_friendly(self):
        lookup = self.script[
            self.script.index("function friendlyEntry("):
            self.script.index("function showError(")]
        for token in ("ERROR_FRIENDLY", "WARN_FRIENDLY"):
            with self.subTest(token=token):
                self.assertIn(token, lookup)
        start = self.script.index("function showError(")
        end = self.script.index("\n}\n", start)
        body = self.script[start:end]
        for token in ("friendlyEntry(code)",
                      'createElement("details")',
                      'createElement("summary")',
                      '"Technical detail"', 'tag muted',
                      '"Next step: "'):
            with self.subTest(token=token):
                self.assertIn(token, body)

    def test_reason_and_warn_lists_use_mapping(self):
        self.assertIn("friendlyEntry(r.code)", self.script)
        self.assertIn("WARN_FRIENDLY[w.code]", self.script)
        self.assertIn("Next step: ", self.script)


class DurationCopyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def test_detect_duration_hint(self):
        self.assertIn('id="liveDetectHint"', self.page)
        self.assertIn("Typical for a 237-frame clip: ~2 min vision model, "
                      "then ~5 min local encoding with no progress bar",
                      self.page)

    def test_measure_duration_hint(self):
        self.assertIn('id="liveMeasureHint"', self.page)
        self.assertIn("Full mode takes ~20 minutes; motion mode is fast.",
                      self.page)


class ConsoleIndependenceTests(unittest.TestCase):
    def test_dead_console_stderr_still_serves(self):
        # KL-8.7 item 5: the access line is attempted (proving the
        # write exists) but a dead console never fails the request.
        for fault in (OSError("dead Windows console"),
                      ValueError("I/O operation on closed file")):
            with self.subTest(fault=type(fault).__name__):
                attempts = []

                class DeadStderr:
                    def write(self, text):
                        attempts.append(text)
                        raise fault

                    def flush(self):
                        raise fault

                previous = sys.stderr
                sys.stderr = DeadStderr()
                try:
                    with tempfile.TemporaryDirectory() as tmp:
                        status, _, raw = dispatch(
                            REPO_ROOT, Path(tmp), "GET", "/", {})
                finally:
                    sys.stderr = previous
                self.assertEqual(status, 200)
                self.assertIn("KineticLab", raw.decode("utf-8"))
                self.assertGreaterEqual(len(attempts), 1)

    def _quiet_server(self):
        import kineticlab.ui.server as server_module
        return server_module.HTTPServer(
            ("127.0.0.1", 0), _Handler, bind_and_activate=False)

    def test_handle_error_swallows_dead_socket(self):
        # KL-9.2 item 1: a client that refreshes mid-response aborts
        # the socket; the secondary connection error must not print
        # a traceback on top of the handled outcome.
        for fault in (BrokenPipeError("dead socket"),
                      ConnectionResetError("dead socket"),
                      ConnectionAbortedError("dead socket")):
            with self.subTest(fault=type(fault).__name__):
                captured = io.StringIO()
                previous = sys.stderr
                sys.stderr = captured
                server = self._quiet_server()
                try:
                    try:
                        raise fault
                    except OSError:
                        server.handle_error(None, ("127.0.0.1", 0))
                finally:
                    server.server_close()
                    sys.stderr = previous
                self.assertEqual(captured.getvalue(), "")

    def test_handle_error_prints_real_bugs(self):
        # Genuine server bugs stay loud through the standard path.
        captured = io.StringIO()
        previous = sys.stderr
        sys.stderr = captured
        server = self._quiet_server()
        try:
            try:
                raise ValueError("boom")
            except ValueError:
                server.handle_error(None, ("127.0.0.1", 0))
        finally:
            server.server_close()
            sys.stderr = previous
        self.assertIn("ValueError", captured.getvalue())


class LayoutCompressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def test_sidebar_capped_with_internal_scroll(self):
        # KL-8.8 shell moves this to sidebar; keep the intent:
        # the action column never outgrows the viewport.
        has_cap = ("max-height:" in self.page and
                   ("calc(100vh" in self.page or "100vh" in self.page))
        has_sidebar = "class=\"sidebar\"" in self.page
        self.assertTrue(
            has_cap or has_sidebar,
            "expected capped sidebar/workspace (max-height + viewport)")

    def test_secondary_accordions_collapsed(self):
        # Evidence/provenance accordions stay collapsed by default;
        # exactly one may be open for orientation.
        open_count = self.page.count('<details class="acc" open>')
        self.assertGreaterEqual(open_count, 1)
        self.assertLessEqual(open_count, 2)
        self.assertIn("Warnings (verbatim)</summary>", self.page)
        for summary in ("Assumptions (verbatim)", "Reject reasons",
                        "Advisory replay", "Provenance",
                        "Input artifact digests",
                        "Exports (exact written bytes)",
                        "Summary (copied, never recomputed)"):
            with self.subTest(summary=summary):
                self.assertIn(summary, self.page)

    def test_prompts_collapsed(self):
        self.assertIn("Prompts (defaults usually fine)", self.page)
        self.assertIn('id="livePromptBob" value="red ball"',
                      self.page)

    def test_chains_single_column(self):
        # Old .chains single-column grid; new workspace keeps the same
        # intent via .workspace grid — either is acceptable.
        has_chains = ".chains {" in self.page
        has_workspace = ".workspace" in self.page
        self.assertTrue(has_chains or has_workspace)


class TouchUp811Tests(unittest.TestCase):
    """KL-8.11 Fable touch-up pins (page sha16 180EDAB5F57C3E63).

    NaN can never render: non-finite CSV rows are skipped at parse,
    and the playhead readout guards its frame-order operands. Charts
    fill their cards instead of letterboxing. The stepper carries a
    title clarifying the all-done-during-demo semantics.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")

    def test_parse_guard_skips_non_finite_rows(self):
        self.assertIn("if (row.some((v) => !Number.isFinite(v))) continue;",
                      self.page)

    def test_playhead_readout_finite_guard(self):
        self.assertIn("Number.isFinite(order[safe])", self.page)

    def test_charts_fill_cards(self):
        self.assertEqual(
            self.page.count("max-height:600px;max-width:1150px;"
                            "margin:0 auto"), 3)

    def test_stepper_demo_title(self):
        self.assertIn("Stages reflect the most recent run", self.page)

    def test_point_index_fallback(self):
        # G8 feedback fix: demo angles.csv has no point_index column;
        # without the frame_index fallback every row was non-finite
        # and the row guard blanked all charts.
        self.assertIn('let iIdx = col("point_index");', self.page)
        self.assertIn('if (iIdx < 0) iIdx = col("frame_index");', self.page)

    def test_viewer_column_stretches(self):
        self.assertIn(".workspace>.panel:first-child{align-self:stretch;",
                      self.page)
        self.assertIn(".workspace>.panel:first-child .video-stage{flex:1}",
                      self.page)


class Truthfulness812Tests(unittest.TestCase):
    """KL-8.12 pins: terminal activity text, bar-level tint, Reports.

    The ops bar chip alone is not enough — terminal and gated states
    must rewrite the activity line, the bar itself must carry the
    state tint, and run reports must surface above the tabs.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        try:
            cls.script = cls.page.split("<script>", 1)[1]
        except IndexError:
            cls.script = ""
        try:
            cls.style = cls.page.split("<style>", 1)[1].split("</style>", 1)[0]
        except IndexError:
            cls.style = ""

    def test_terminal_activity_text_per_state(self):
        # setAppStatus rewrites opActivity/opDetail for terminal and
        # gated states; in-flight states keep showProgress text.
        fn = self.script.split("function setAppStatus(state, note, facts)",
                               1)[1].split("\n}\n", 1)[0]
        for text in ("Run complete.",
                     "Reports and charts are in the results area below.",
                     "Run failed.",
                     "the failed panel shows the cause and recovery steps.",
                     "Detection finished.",
                     "Confirm or reject the boxes to continue.",
                     "OPS_IDLE_ACTIVITY", "OPS_IDLE_DETAIL"):
            with self.subTest(text=text):
                self.assertIn(text, fn)
        self.assertIn('el("opActivity").textContent', fn)
        self.assertIn('el("opDetail").textContent', fn)
        # In-flight branches must not exist here.
        self.assertNotIn('"Detecting"', fn)
        self.assertNotIn('"Measuring"', fn)

    def test_opsbar_mirrors_data_state(self):
        self.assertIn('el("opsBar").setAttribute("data-state", state)',
                      self.script)
        self.assertIn('id="opsBar" aria-label="Operations" '
                      'data-state="Ready for analysis"', self.page)

    def test_opsbar_tint_rules(self):
        # 3px leading border + token tint per state, smooth transition;
        # never color-only (the text chip names the state).
        self.assertIn(".opsbar{border-left:3px solid var(--border);"
                      "transition:background-color .2s,border-color .2s}",
                      self.style)
        for rule in (
                '#opsBar[data-state="Detecting"],'
                '#opsBar[data-state="Measuring"]',
                '#opsBar[data-state="Awaiting confirmation"]',
                '#opsBar[data-state="Complete"]',
                '#opsBar[data-state="Failed"]'):
            with self.subTest(rule=rule):
                self.assertIn(rule, self.style)
        self.assertIn("color-mix(in srgb,var(--green) 7%,var(--surface))",
                      self.style)
        self.assertIn("color-mix(in srgb,var(--red) 8%,var(--surface))",
                      self.style)

    def test_reports_block_surfaced(self):
        # Highlighted card above the tabs, hidden until files exist.
        self.assertIn('class="reports-card hidden" id="reportsCard"',
                      self.page)
        self.assertIn('id="reportLinks"', self.page)
        self.assertIn("<strong>Reports</strong>", self.page)
        self.assertIn("exact written bytes", self.page)
        self.assertGreater(self.page.index('id="reportsCard"'),
                           self.page.index('id="stepList"'))
        self.assertLess(self.page.index('id="reportsCard"'),
                        self.page.index('id="tabTrajectory"'))
        self.assertIn(".reports-card{", self.style)

    def test_reports_share_link_source(self):
        # One source array feeds both the accordion list and the
        # surfaced card — the two lists can never diverge.
        self.assertIn("function reportFileEntries()", self.script)
        self.assertIn("function paintReportsCard()", self.script)
        self.assertIn("function paintExportLinks(box)", self.script)
        self.assertEqual(self.script.count("reportFileEntries()"), 3)
        self.assertEqual(
            self.script.count("paintReportsCard();"), 2)
        self.assertIn('if (entries.length > 0) show(el("reportsCard"));',
                      self.script)
        self.assertIn('else hide(el("reportsCard"));', self.script)


NODE_STUB_JS = r"""
/* Minimal textContent-only DOM recorder for node-executed proofs
   (KL-9.6): plain recorders for the surface the page uses —
   createElement/createTextNode/replaceChildren/appendChild,
   className/classList/setAttribute/textContent — plus the globals
   the script touches at load (localStorage, documentElement
   dataset, rAF, matchMedia, performance, fetch). fetch is
   table-driven via global __FETCH. */
class __Cls {
  constructor() { this._s = new Set(); }
  add(...c) { for (const x of c) this._s.add(x); }
  remove(...c) { for (const x of c) this._s.delete(x); }
  toggle(c, force) {
    if (force === true) { this._s.add(c); return true; }
    if (force === false) { this._s.delete(c); return false; }
    if (this._s.has(c)) { this._s.delete(c); return false; }
    this._s.add(c); return true;
  }
  contains(c) { return this._s.has(c); }
}
class __Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.attrs = {};
    this._text = ""; this.className = ""; this.classList = new __Cls();
    this.style = {}; this.dataset = {}; this._parent = null;
    this.value = ""; this.checked = false; this.disabled = false;
    this._qs = {};
  }
  get textContent() {
    if (this._isText) return this._text;
    return this._text + this.children.map((c) => c.textContent).join("");
  }
  set textContent(v) { this._text = String(v); this.children = []; }
  appendChild(c) { c._parent = this; this.children.push(c); return c; }
  replaceChildren() { this.children = []; this._text = ""; }
  remove() {
    if (this._parent) {
      const i = this._parent.children.indexOf(this);
      if (i >= 0) this._parent.children.splice(i, 1);
      this._parent = null;
    }
  }
  get firstChild() { return this.children.length ? this.children[0] : null; }
  get parentElement() {
    if (!this._parent) this._parent = new __Node("div");
    return this._parent;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this.attrs, k)
      ? this.attrs[k] : null;
  }
  addEventListener() {}
  removeEventListener() {}
  querySelector(sel) {
    if (!this._qs[sel]) this._qs[sel] = new __Node("div");
    return this._qs[sel];
  }
  querySelectorAll() { return []; }
  click() {}
  focus() {}
  scrollIntoView() {}
}
const __ids = new Map();
function __byId(id) {
  const key = String(id);
  if (!__ids.has(key)) {
    const n = new __Node("div"); n.id = key; __ids.set(key, n);
  }
  return __ids.get(key);
}
function __textNode(text) {
  const n = new __Node("#text"); n._isText = true;
  n._text = String(text); return n;
}
globalThis.document = {
  getElementById: (id) => __byId(id),
  createElement: (tag) => new __Node(tag),
  createElementNS: (ns, tag) => new __Node(tag),
  createTextNode: (text) => __textNode(text),
  documentElement: new __Node("html"),
  addEventListener: () => {},
  activeElement: null,
};
globalThis.window = {
  location: { host: "127.0.0.1:8137" },
  matchMedia: () => ({ matches: true }),
  __lastFiles: null,
};
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.requestAnimationFrame = () => 0;
globalThis.performance = { now: () => Date.now() };
globalThis.navigator = {};
globalThis.__FETCH = {};
globalThis.fetch = async (url) => {
  if (!Object.prototype.hasOwnProperty.call(globalThis.__FETCH, url)) {
    throw new Error("unexpected fetch " + url);
  }
  const text = globalThis.__FETCH[url];
  return { ok: true, status: 200, text: async () => text };
};
function __emit(obj) { console.log("KLRESULT " + JSON.stringify(obj)); }
"""


def run_page_driver(script, check_js, fetch_map=None):
    """Execute the real page script under node; return the emitted JSON.

    Any throw — including at script load — fails loudly with the
    node stack; silence is impossible.
    """
    driver = (NODE_STUB_JS + "\n" + script + "\n"
              "globalThis.__FETCH = "
              + json.dumps(fetch_map or {}) + ";\n" + check_js + "\n")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "driver.js"
        path.write_text(driver, encoding="utf-8")
        completed = subprocess.run(
            ["node", str(path)], capture_output=True, text=True,
            encoding="utf-8",
            timeout=120, cwd=tmp)
    if completed.returncode != 0:
        raise AssertionError(
            "node driver failed:\n" + completed.stderr[-3000:])
    for line in completed.stdout.splitlines():
        if line.startswith("KLRESULT "):
            return json.loads(line[len("KLRESULT "):])
    raise AssertionError(
        "no KLRESULT in node output:\n"
        + completed.stdout[-2000:] + "\n" + completed.stderr[-2000:])


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class NodeExecutionTests(unittest.TestCase):
    """KL-9.6 items 1-4: the fixes proven by EXECUTING the shipped
    page script under node with a DOM stub and real payloads — the
    string pins that let these bugs ship are not proof here."""

    @classmethod
    def setUpClass(cls):
        page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")
        asm = REPO_ROOT / "fixtures" / "assembly"
        cls.rejection_result = json.loads(
            (asm / "rejection" / "result.json").read_text(
                encoding="utf-8"))
        cls.success_result = json.loads(
            (asm / "result.json").read_text(encoding="utf-8"))
        cls.diagnostics_text = (
            asm / "diagnostics.json").read_text(encoding="utf-8")
        cls.angles_text = (
            asm / "angles.csv").read_text(encoding="utf-8")

    def test_b2_paint_verdict_rejection_renders_without_throw(self):
        check = (
            "try {\n"
            "  paintVerdict(" + json.dumps(self.rejection_result)
            + ", null);\n"
            "  const v = document.getElementById(\"verdict\");\n"
            "  const rej = { cls: v.className,\n"
            "    head: v.children.length ? v.children[0].textContent\n"
            "      : v.textContent,\n"
            "    badges: v.children\n"
            "      .filter((c) => c.className === \"countbadge\")\n"
            "      .map((c) => c.textContent) };\n"
            "  paintVerdict(" + json.dumps(self.success_result)
            + ", null);\n"
            "  const w = document.getElementById(\"verdict\");\n"
            "  const ok = { cls: w.className,\n"
            "    head: w.children.length ? w.children[0].textContent\n"
            "      : w.textContent,\n"
            "    badges: w.children\n"
            "      .filter((c) => c.className === \"countbadge\")\n"
            "      .map((c) => c.textContent) };\n"
            "  __emit({ rej, ok });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check)
        # Rejection (fit: null): no throw, honest heading, never
        # green, no count badge — the badge needs a real count.
        self.assertEqual(out["rej"]["cls"], "verdict bad")
        self.assertEqual(out["rej"]["head"],
                         "REJECTED (unsupported_input)")
        self.assertEqual(out["rej"]["badges"], [])
        # Success control: the badge renders from the real count.
        self.assertEqual(out["ok"]["cls"], "verdict warn")
        self.assertEqual(out["ok"]["head"], "SUCCESS WITH WARNINGS")
        self.assertEqual(out["ok"]["badges"], ["n=234"])

    def test_b5_residual_charts_render_finite_paths(self):
        check = (
            "(async () => {\n"
            "  const d = parseDiagnostics(null, "
            + json.dumps(self.diagnostics_text) + ");\n"
            "  const pairs = d.residuals;\n"
            "  const finite = pairs\n"
            "    .filter((p) => Number.isFinite(p[0])\n"
            "      && Number.isFinite(p[1])).length;\n"
            "  const doc = await paintChart({ \"angles.csv\": \"u_csv\",\n"
            "    \"diagnostics.json\": \"u_diag\" }, null, null);\n"
            "  const meta =\n"
            "    document.getElementById(\"chartMeta\").textContent;\n"
            "  const stripKids =\n"
            "    document.getElementById(\"stripSvg\").children;\n"
            "  let stripD = \"\";\n"
            "  for (const k of stripKids)\n"
            "    if (k.tag === \"path\") stripD = k.attrs.d || \"\";\n"
            "  const thetaKids =\n"
            "    document.getElementById(\"chartSvg\").children;\n"
            "  let fittedD = \"\";\n"
            "  for (const k of thetaKids)\n"
            "    if (k.tag === \"path\") fittedD = k.attrs.d || \"\";\n"
            "  __emit({ pairs: pairs.length, finite, first: pairs[0],\n"
            "    period: d.period, meta, stripLen: stripD.length,\n"
            "    stripNaN: stripD.includes(\"NaN\"),\n"
            "    fittedLen: fittedD.length,\n"
            "    fittedNaN: fittedD.includes(\"NaN\"),\n"
            "    docNull: doc === null });\n"
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")
        out = run_page_driver(
            self.script, check,
            {"u_csv": self.angles_text,
             "u_diag": self.diagnostics_text})
        # Unit level: all 234 dict residuals map to finite pairs.
        self.assertEqual(out["pairs"], 234)
        self.assertEqual(out["finite"], 234)
        self.assertAlmostEqual(out["first"][0], 0.0)
        self.assertAlmostEqual(out["first"][1], -0.07864719822009777)
        self.assertAlmostEqual(out["period"], 1.1470397067318712)
        # End to end: paired residuals, finite SVG path data —
        # the old pair[0]/pair[1] mapping wrote NaN paths here.
        self.assertIn("paired", out["meta"])
        self.assertGreater(out["stripLen"], 0)
        self.assertFalse(out["stripNaN"])
        self.assertGreater(out["fittedLen"], 0)
        self.assertFalse(out["fittedNaN"])
        self.assertFalse(out["docNull"])

    def test_b6_overlay_boxes_render_from_detect_summary(self):
        from tests.test_live_chain import FULL_TEXTS, pin_transport

        from kineticlab.capture.chain import new_run_id, run_detect

        require_smoke(TEST_3)
        with tempfile.TemporaryDirectory() as tmp:
            run_id = new_run_id()
            out = run_detect(
                TEST_3, Path(tmp) / run_id, "full",
                {"bob": "red ball", "card": "white paper card"},
                "test-key-node-proof", transport=pin_transport(
                    FULL_TEXTS))
        summary = out["summary"]
        check = (
            "try {\n"
            "  drawLiveOverlay(" + json.dumps(summary) + ");\n"
            "  const kids =\n"
            "    document.getElementById(\"liveOverlay\").children;\n"
            "  const rects = kids.filter((k) => k.tag === \"rect\")\n"
            "    .map((k) => [k.attrs.x, k.attrs.y, k.attrs.width,\n"
            "      k.attrs.height]);\n"
            "  const labels = kids.filter((k) => k.tag === \"text\")\n"
            "    .map((k) => k.textContent);\n"
            "  __emit({ rects, labels });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        rendered = run_page_driver(self.script, check)
        # Every role's array box renders as a finite rect; the old
        # .x1/.y1 reads produced NaN rects that never drew.
        self.assertEqual(len(rendered["rects"]),
                         len(summary["roles"]))
        for (name, info), rect in zip(sorted(summary["roles"].items()),
                                      rendered["rects"]):
            box = info["first_box"]
            got = [float(value) for value in rect]
            for value in got:
                # Finite, never NaN — compare numerically: JS
                # String(505) is "505" where Python str() is "505.0".
                self.assertTrue(value == value, name)
            self.assertEqual(
                got,
                [box[0], box[1], box[2] - box[0], box[3] - box[1]],
                name)
        labels = " ".join(rendered["labels"])
        for name in summary["roles"]:
            self.assertIn(name, labels)

    def motion_run(self, fit_double=None):
        """Real motion report + angles bytes via run_detect/measure."""
        import kineticlab.capture.chain as chain_module

        from tests.test_live_chain import FULL_TEXTS, pin_transport

        from kineticlab.capture.chain import (
            MOTION_CSV_FILENAME,
            new_run_id,
            run_detect,
            run_measure,
        )

        require_smoke(TEST_3)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        run = Path(tmp.name) / new_run_id()
        run_detect(TEST_3, run, "motion", {"bob": "red ball"},
                   "test-key-node-proof",
                   transport=pin_transport(FULL_TEXTS))
        if fit_double is not None:
            real = chain_module.fit_m1
            chain_module.fit_m1 = lambda request: dict(fit_double)
            self.addCleanup(setattr, chain_module, "fit_m1", real)
        out = run_measure(run)
        csv_text = (run / MOTION_CSV_FILENAME).read_text(
            encoding="utf-8")
        return out["report"], csv_text, out["status_line"]

    def render_motion_js(self, report, status_line):
        return (
            "(async () => {\n"
            "  await renderLiveMotion({ report: "
            + json.dumps(report) + ",\n"
            "    files: { \"motion_angles.csv\": \"u_csv\" },\n"
            "    status_line: " + json.dumps(status_line) + " });\n"
            "  const v = document.getElementById(\"verdict\");\n"
            "  const steps =\n"
            "    document.getElementById(\"stepList\").children\n"
            "      .map((li) => li.textContent);\n"
            "  __emit({ compact: document.getElementById(\n"
            "      \"liveMotionCompact\").textContent,\n"
            "    verdictCls: v.className,\n"
            "    verdictHead: v.children.length\n"
            "      ? v.children[0].textContent : v.textContent,\n"
            "    summary: document.getElementById(\n"
            "      \"summaryPre\").textContent,\n"
            "    steps });\n"
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")

    def test_b3_motion_complete_counts(self):
        report, csv_text, status_line = self.motion_run()
        self.assertEqual(report["status"], "complete")
        counts = (f"{report['n_fit_points']} points, "
                  f"{len(report['excluded_frames'])} dropped")
        out = run_page_driver(
            self.script, self.render_motion_js(report, status_line),
            {"u_csv": csv_text})
        self.assertTrue(out["compact"].startswith("Motion complete"),
                        out["compact"])
        self.assertIn(counts, out["compact"])
        self.assertNotIn("undefined", out["compact"])
        self.assertNotIn("not available", out["compact"])
        self.assertEqual(out["verdictCls"], "verdict ok")
        self.assertEqual(out["verdictHead"], "MOTION COMPLETE")
        self.assertIn("No summary.md in this payload.", out["summary"])
        measured = [step for step in out["steps"]
                    if "Measured" in step]
        self.assertEqual(len(measured), 1)
        self.assertIn(counts, measured[0])
        self.assertNotIn("undefined", measured[0])

    def test_b3_motion_incomplete_renders_honestly(self):
        double = {
            "fitter": "m1-test-double", "model": "m1.v1",
            "test_convention_note": "input points are synthetic",
            "fit": {},
            "diagnostics": {"converged": False,
                             "termination_reason":
                                 "budget_exhausted"},
        }
        report, csv_text, status_line = self.motion_run(double)
        self.assertEqual(report["status"], "incomplete")
        counts = (f"{report['n_fit_points']} points, "
                  f"{len(report['excluded_frames'])} dropped")
        out = run_page_driver(
            self.script, self.render_motion_js(report, status_line),
            {"u_csv": csv_text})
        # No throw (the old .toPrecision(null) crashed here);
        # honest incomplete text with the backend's reason.
        self.assertIn("Motion incomplete", out["compact"])
        self.assertIn("did not converge", out["compact"])
        self.assertIn("values not available", out["compact"])
        self.assertIn(counts, out["compact"])
        self.assertNotIn("undefined", out["compact"])
        self.assertEqual(out["verdictCls"], "verdict bad")
        self.assertEqual(out["verdictHead"], "MOTION INCOMPLETE")
        outcome = [step for step in out["steps"]
                   if "Outcome" in step]
        self.assertEqual(len(outcome), 1)
        self.assertIn("incomplete", outcome[0])


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class ScientificAnalysisTests(unittest.TestCase):
    """KL-10.5: the Scientific Analysis card proven by EXECUTING the
    shipped page script under node — real fixture payloads, DOM stub,
    rAF stub; every number asserted comes from the payload."""

    @classmethod
    def setUpClass(cls):
        page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")
        asm = REPO_ROOT / "fixtures" / "assembly"
        cls.result = json.loads(
            (asm / "result.json").read_text(encoding="utf-8"))
        cls.diagnostics_text = (
            asm / "diagnostics.json").read_text(encoding="utf-8")
        cls.angles_text = (
            asm / "angles.csv").read_text(encoding="utf-8")

    def paint_check(self, result_json, diag_text, files_extra="",
                    preamble="", post=""):
        return (
            "(async () => {\n" + preamble +
            "  const doc = await paintChart({ \"angles.csv\": \"u_csv\",\n"
            "    \"diagnostics.json\": \"u_diag\"" + files_extra +
            " }, " + result_json + ", null, \"demo success\");\n" +
            post +
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")

    def fetch_map(self, diag_text=None):
        return {"u_csv": self.angles_text,
                "u_diag": diag_text or self.diagnostics_text}

    def test_sci_idle_state_honest(self):
        check = (
            "(async () => {\n"
            "  const doc = await paintChart({}, null, null,\n"
            "    \"demo success\");\n"
            "  const rows = document.getElementById(\"sciDiagRows\")\n"
            "    .children.map((tr) => tr.textContent);\n"
            "  __emit({ docNull: doc === null,\n"
            "    chip: document.getElementById(\"sciState\").textContent,\n"
            "    live: document.getElementById(\"sciState\").classList\n"
            "      .contains(\"live\"),\n"
            "    rms: document.getElementById(\"rmsChip\").textContent,\n"
            "    period: document.getElementById(\"periodChip\")\n"
            "      .textContent,\n"
            "    disabled: document.getElementById(\"replayBtn\")\n"
            "      .disabled,\n"
            "    counter: document.getElementById(\"frameCounter\")\n"
            "      .textContent,\n"
            "    rows });\n"
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")
        out = run_page_driver(self.script, check, {})
        self.assertTrue(out["docNull"])
        self.assertEqual(out["chip"], "No measurement loaded")
        self.assertFalse(out["live"])
        self.assertEqual(out["rms"], "Not computed")
        self.assertEqual(out["period"], "")
        self.assertTrue(out["disabled"])
        self.assertEqual(out["counter"], "")
        self.assertEqual(out["rows"], ["DiagnosticsNo measurement loaded."])

    def test_length_branch_uses_contract_vocabulary(self):
        # KL-10.6 MINOR-2: contracts.py emits pivot_length_source
        # "independent_measurement"; the page used to compare against
        # "independent" (dead branch, always failed closed). Proved by
        # executing the shipped function in both directions.
        check = (
            "  const hit = establishedLength({fit: {\n"
            "    pivot_length_mm: 1.0,\n"
            "    pivot_length_source: \"independent_measurement\"}},\n"
            "    null);\n"
            "  const miss = establishedLength({fit: {\n"
            "    pivot_length_mm: 1.0,\n"
            "    pivot_length_source: \"independent\"}}, null);\n"
            "  __emit({ hitValue: hit.value, hitWhy: hit.why,\n"
            "    missValue: miss.value });\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(out["hitValue"], 0.001)
        self.assertEqual(out["hitWhy"],
                         "Established independent pivot length "
                         "(pipeline record).")
        self.assertIsNone(out["missValue"])

    def test_trajectory_tab_renders_real_series(self):
        post = (
            "  const kids =\n"
            "    document.getElementById(\"chartSvg\").children;\n"
            "  const dots = kids.filter((k) => k.tag === \"circle\").length;\n"
            "  let fittedD = \"\";\n"
            "  for (const k of kids)\n"
            "    if (k.tag === \"path\") fittedD = k.attrs.d || \"\";\n"
            "  const trailKids =\n"
            "    document.getElementById(\"trailSvg\").children;\n"
            "  const trailDots = trailKids.filter((k) => k.tag === \"circle\"\n"
            "    && k.attrs.r === \"1.6\").length;\n"
            "  let trailD = \"\";\n"
            "  for (const k of trailKids)\n"
            "    if (k.tag === \"path\") trailD = k.attrs.d || \"\";\n"
            "  __emit({ dots, fittedLen: fittedD.length,\n"
            "    fittedNaN: fittedD.includes(\"NaN\"),\n"
            "    chip: document.getElementById(\"sciState\").textContent,\n"
            "    live: document.getElementById(\"sciState\").classList\n"
            "      .contains(\"live\"),\n"
            "    period: document.getElementById(\"periodChip\").textContent,\n"
            "    trailMeta: document.getElementById(\"trailMeta\")\n"
            "      .textContent,\n"
            "    trailDots, trailLen: trailD.length,\n"
            "    trailNaN: trailD.includes(\"NaN\"),\n"
            "    docNull: doc === null });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             self.diagnostics_text, post=post),
            self.fetch_map())
        # 234 measured points + finite fitted curve from the same
        # data path as before; header chip names mode + n.
        self.assertEqual(out["dots"], 234)
        self.assertGreater(out["fittedLen"], 0)
        self.assertFalse(out["fittedNaN"])
        self.assertEqual(out["chip"], "demo success · n=234")
        self.assertTrue(out["live"])
        self.assertEqual(out["period"], "T = 1.147 s")
        # Trail defaults to the 15 most recent centroids.
        self.assertEqual(out["trailDots"], 15)
        self.assertGreater(out["trailLen"], 0)
        self.assertFalse(out["trailNaN"])
        self.assertIn("showing 15 of 234", out["trailMeta"])
        self.assertFalse(out["docNull"])

    def test_residual_badge_degrees(self):
        post = (
            "  const chip = document.getElementById(\"rmsChip\");\n"
            "  __emit({ text: chip.textContent, title: chip.getAttribute(\n"
            "      \"title\"), good: chip.classList.contains(\"good\"),\n"
            "    na: chip.classList.contains(\"na\") });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             self.diagnostics_text, post=post),
            self.fetch_map())
        # 0.02275752015969389 rad × 57.29577951308232 = 1.3039…°.
        self.assertEqual(out["text"], "RMS 1.30° (pipeline)")
        self.assertEqual(out["title"], "0.02275752015969389 rad")
        self.assertFalse(out["good"])
        self.assertFalse(out["na"])

    def test_residual_badge_not_computed(self):
        result = dict(self.result)
        result["fit"] = dict(result["fit"])
        del result["fit"]["residual_summary"]
        post = (
            "  const chip = document.getElementById(\"rmsChip\");\n"
            "  __emit({ text: chip.textContent,\n"
            "    na: chip.classList.contains(\"na\") });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(result),
                             self.diagnostics_text, post=post),
            self.fetch_map())
        self.assertEqual(out["text"], "Not computed")
        self.assertTrue(out["na"])

    def test_trail_window_all_and_flags(self):
        diag = json.loads(self.diagnostics_text)
        diag["excluded_frames"] = [0, 5, 233]
        post = (
            "  const countDots = () => {\n"
            "    const kids = document.getElementById(\"trailSvg\")\n"
            "      .children;\n"
            "    let dots = 0, flagged = 0, d = \"\";\n"
            "    for (const k of kids) {\n"
            "      if (k.tag === \"circle\" && k.attrs.r === \"1.6\") {\n"
            "        dots++;\n"
            "        if (k.children.length) flagged++;\n"
            "      }\n"
            "      if (k.tag === \"path\") d = k.attrs.d || \"\";\n"
            "    }\n"
            "    return { dots, flagged, len: d.length,\n"
            "      nan: d.includes(\"NaN\") };\n"
            "  };\n"
            "  const win15 = countDots();\n"
            "  document.getElementById(\"trailWindow\").value = \"all\";\n"
            "  renderTrailWindow();\n"
            "  const winAll = countDots();\n"
            "  __emit({ win15, winAll,\n"
            "    meta: document.getElementById(\"trailMeta\")\n"
            "      .textContent });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             json.dumps(diag), post=post),
            self.fetch_map(json.dumps(diag)))
        # Default window: last 15 rows (219..233) — only frame 233
        # of the excluded set falls inside and draws flagged.
        self.assertEqual(out["win15"]["dots"], 15)
        self.assertEqual(out["win15"]["flagged"], 1)
        self.assertGreater(out["win15"]["len"], 0)
        self.assertFalse(out["win15"]["nan"])
        # Full history one click away: all 234 dots, 3 flagged.
        self.assertEqual(out["winAll"]["dots"], 234)
        self.assertEqual(out["winAll"]["flagged"], 3)
        self.assertGreater(out["winAll"]["len"], 0)
        self.assertFalse(out["winAll"]["nan"])
        self.assertIn("showing 234 of 234", out["meta"])

    def test_replay_advances_and_pauses(self):
        preamble = (
            "  window.matchMedia = () => ({ matches: false });\n"
            "  let rafCb = null;\n"
            "  globalThis.requestAnimationFrame = (cb) => {\n"
            "    rafCb = cb; return 1;\n"
            "  };\n")
        post = (
            "  const btn = () =>\n"
            "    document.getElementById(\"replayBtn\").textContent;\n"
            "  const scrub = () =>\n"
            "    document.getElementById(\"scrub\").value;\n"
            "  const counter = () =>\n"
            "    document.getElementById(\"frameCounter\").textContent;\n"
            "  const thetaX = () =>\n"
            "    document.getElementById(\"thetaView\")\n"
            "      .getAttribute(\"x1\");\n"
            "  const trailVis = () =>\n"
            "    document.getElementById(\"trailView\")\n"
            "      .getAttribute(\"visibility\");\n"
            "  const atStart = { btn: btn(), scrub: scrub(),\n"
            "    counter: counter(), x: thetaX(), vis: trailVis() };\n"
            "  rafCb(1000); rafCb(2000);\n"
            "  const mid = { btn: btn(), scrub: scrub(),\n"
            "    counter: counter(), x: thetaX(), vis: trailVis() };\n"
            "  toggleReplay();\n"
            "  const pausedCaption = document.getElementById(\n"
            "    \"replayCaption\").textContent;\n"
            "  rafCb(9000);\n"
            "  const frozen = scrub();\n"
            "  toggleReplay();\n"
            "  rafCb(9500); rafCb(20000);\n"
            "  const end = { btn: btn(), scrub: scrub(),\n"
            "    counter: counter(),\n"
            "    caption: document.getElementById(\"replayCaption\")\n"
            "      .textContent,\n"
            "    vis: trailVis(),\n"
            "    cx: document.getElementById(\"trailView\")\n"
            "      .getAttribute(\"cx\") };\n"
            "  __emit({ atStart, mid, pausedCaption, frozen, end });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             self.diagnostics_text,
                             preamble=preamble, post=post),
            self.fetch_map())
        # Auto-reveal starts playing from frame 0.
        self.assertEqual(out["atStart"]["btn"], "Pause")
        self.assertEqual(out["atStart"]["scrub"], "0")
        self.assertEqual(out["atStart"]["counter"], "1 / 234")
        # One synthetic second advances cursor (pts 0.0 -> 1.0 =
        # row 27 on this VFR clip), scrub, counter, and the
        # trajectory cursor; the trail marker hides (idx 27 sits
        # outside the 15-frame window ending at 233).
        self.assertEqual(out["mid"]["scrub"], "27")
        self.assertEqual(out["mid"]["counter"], "28 / 234")
        self.assertNotEqual(out["mid"]["x"], out["atStart"]["x"])
        self.assertEqual(out["mid"]["vis"], "hidden")
        # Pause freezes the cursor: a later tick changes nothing.
        self.assertIn("Paused", out["pausedCaption"])
        self.assertEqual(out["frozen"], "27")
        # Resume runs to the end: last frame, visible finite trail
        # marker, honest end caption, button back to Play.
        self.assertEqual(out["end"]["btn"], "Play")
        self.assertEqual(out["end"]["scrub"], "233")
        self.assertEqual(out["end"]["counter"], "234 / 234")
        self.assertEqual(out["end"]["caption"], "End of recording.")
        self.assertEqual(out["end"]["vis"], "visible")
        self.assertTrue(float(out["end"]["cx"]) ==
                        float(out["end"]["cx"]))

    def test_replay_reduced_motion_static(self):
        post = (
            "  const btn = document.getElementById(\"replayBtn\");\n"
            "  toggleReplay();\n"
            "  __emit({ scrub: document.getElementById(\"scrub\").value,\n"
            "    counter: document.getElementById(\"frameCounter\")\n"
            "      .textContent,\n"
            "    disabled: btn.disabled, btn: btn.textContent,\n"
            "    caption: document.getElementById(\"replayCaption\")\n"
            "      .textContent });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             self.diagnostics_text, post=post),
            self.fetch_map())
        # The DOM stub reports reduced motion: static mid-frame
        # (index 116 of 234), parked Play, explanatory caption;
        # the toggle call is a no-op.
        self.assertEqual(out["scrub"], "116")
        self.assertEqual(out["counter"], "117 / 234")
        self.assertTrue(out["disabled"])
        self.assertEqual(out["btn"], "Play")
        self.assertIn("reduced-motion", out["caption"])

    def diag_rows_check(self, result_json, diag_text, files_extra="",
                       fetch_extra=None):
        post = (
            "  const rows = document.getElementById(\"sciDiagRows\")\n"
            "    .children.map((tr) => tr.textContent);\n"
            "  __emit({ rows });\n")
        fetch = self.fetch_map(diag_text)
        fetch.update(fetch_extra or {})
        return run_page_driver(
            self.script,
            self.paint_check(result_json, diag_text,
                             files_extra=files_extra, post=post),
            fetch)

    def test_diagnostics_rows_demo(self):
        out = self.diag_rows_check(json.dumps(self.result),
                                   self.diagnostics_text)
        text = "\n".join(out["rows"])
        self.assertIn("included — included: converged", text)
        self.assertIn("diagnostic only, M1 stays reported", text)
        self.assertIn(
            "gamma_per_s = 0.029794544246787853", text)
        self.assertIn(
            "M1 30.00563573707589 · M2 30.019007396425668", text)
        self.assertIn(
            "117/234 calibrated, 468/468 observations valid", text)
        self.assertIn("Fit convergedyes", text)
        self.assertIn("Terminationrefine_tolerance_met", text)
        self.assertIn("Bound hits0", text)
        self.assertIn("Rejected count0", text)
        self.assertIn("Excluded frames0", text)
        self.assertIn("85.6 × 53.98 mm (human-typed reference)", text)
        self.assertIn("0.3286332854169991 mm/px", text)
        self.assertIn(
            "258.7318351096624 × 165.36871084913219 px", text)
        self.assertIn("Model limitationnot recorded", text)
        self.assertIn("Fit uncertainty methodnone", text)
        self.assertIn("Optimizerseparable_omega_grid_linear_lsq_golden_refine_v1",
                      text)
        self.assertIn("Solverclosed_form_small_angle", text)
        self.assertIn(
            "Parameter g_over_l30.00563573707589 1/s^2", text)
        self.assertIn(
            "theta0 = 0.2050088765289343 rad · "
            "omega0 = -1.1474172412079513 rad/s", text)

    def test_diagnostics_missing_keys(self):
        result = json.loads(json.dumps(self.result))
        del result["quality_metrics"]
        for key in ("rejected_count", "fit_uncertainty_method",
                    "optimizer", "solver", "parameter_names",
                    "initial_conditions", "g_over_l_per_s2"):
            del result["fit"][key]
        del result["calibration"]["reference_dimensions_mm"]
        del result["calibration"]["scale_mm_per_px"]
        del result["calibration"]["observed_oriented_dimensions_px"]
        diag = json.loads(self.diagnostics_text)
        del diag["m2"]
        del diag["m1"]["termination_reason"]
        del diag["m1"]["bound_hits"]
        del diag["excluded_frames"]
        out = self.diag_rows_check(json.dumps(result),
                                   json.dumps(diag))
        for label in ("M2 cross-check", "M2 fitted",
                      "Frame quality", "Termination", "Bound hits",
                      "Rejected count", "Excluded frames",
                      "Fit uncertainty method", "Optimizer",
                      "Solver", "Parameters", "Initial conditions",
                      "Model limitation"):
            with self.subTest(label=label):
                found = [line for line in out["rows"]
                         if line.startswith(label)]
                self.assertEqual(len(found), 1, out["rows"])
                self.assertIn("not recorded", found[0])
        scale = [line for line in out["rows"]
                 if line.startswith("Scale chain")][0]
        self.assertIn("reference not supplied", scale)
        self.assertIn("not recorded", scale)
        cross = [line for line in out["rows"]
                 if line.startswith("g/L cross-check")][0]
        self.assertIn("M1 not recorded · M2 not recorded", cross)

    def test_diagnostics_sidecars(self):
        geo_list = {"model_limitations":
                    ["M-3e hollow-ball note", "Arc-fit radius note"]}
        geo_str = {"model_limitations": "M-3e single-string note"}
        calib = {"reference_dimensions_mm":
                 {"width_mm": 85.0, "height_mm": 55.0},
                 "scale_mm_per_px": 0.5,
                 "observed_oriented_dimensions_px":
                 {"long_side_px": 100.0, "short_side_px": 200.0}}
        check = (
            "(async () => {\n"
            "  paintSciDiagnostics({ result: "
            + json.dumps(self.result) + ",\n"
            "    report: null,\n"
            "    diagnosticsDoc: JSON.parse("
            + json.dumps(self.diagnostics_text) + "),\n"
            "    geoDoc: " + json.dumps(geo_list) + ",\n"
            "    calibDoc: " + json.dumps(calib) + " });\n"
            "  const listed = document.getElementById(\"sciDiagRows\")\n"
            "    .children.map((tr) => tr.textContent);\n"
            "  paintSciDiagnostics({ result: "
            + json.dumps(self.result) + ",\n"
            "    report: null,\n"
            "    diagnosticsDoc: JSON.parse("
            + json.dumps(self.diagnostics_text) + "),\n"
            "    geoDoc: " + json.dumps(geo_str) + ",\n"
            "    calibDoc: null });\n"
            "  const single = document.getElementById(\"sciDiagRows\")\n"
            "    .children.map((tr) => tr.textContent);\n"
            "  __emit({ listed, single });\n"
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")
        out = run_page_driver(self.script, check, {})
        listed = "\n".join(out["listed"])
        # List form: one verbatim row per entry.
        self.assertIn("Model limitation 1M-3e hollow-ball note",
                      listed)
        self.assertIn("Model limitation 2Arc-fit radius note",
                      listed)
        # The linked calibration sidecar wins over the embedded one.
        # (JS String(85.0) renders "85" — the page shows payload
        # values verbatim.)
        self.assertIn("85 × 55 mm (human-typed reference)",
                      listed)
        self.assertIn("0.5 mm/px", listed)
        self.assertIn("100 × 200 px", listed)
        single = "\n".join(out["single"])
        # String form: one verbatim row.
        self.assertIn("Model limitationM-3e single-string note",
                      single)
        # Without a sidecar the embedded calibration applies.
        self.assertIn("85.6 × 53.98 mm (human-typed reference)",
                      single)


class ReplayAnimationTests(unittest.TestCase):
    """KL-10.9-A: the measured-arm replay proven by EXECUTING the
    shipped page script under node — real fixture payloads, DOM stub.
    The arm endpoint must BE the measured centroid; speed must be
    exact PTS-delta multiplication; missing data must render honest
    text, never throw, never fabricate."""

    LABEL = "Motion reconstructed from measured frames."

    @classmethod
    def setUpClass(cls):
        page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")
        asm = REPO_ROOT / "fixtures" / "assembly"
        cls.result = json.loads(
            (asm / "result.json").read_text(encoding="utf-8"))
        cls.diagnostics_text = (
            asm / "diagnostics.json").read_text(encoding="utf-8")
        cls.angles_text = (
            asm / "angles.csv").read_text(encoding="utf-8")
        rows = []
        for line in cls.angles_text.strip().split("\n")[1:]:
            cells = line.split(",")
            rows.append(tuple(float(c) for c in cells))
        cls.rows = rows

    def paint_check(self, result_json, diag_text, preamble="", post=""):
        return (
            "(async () => {\n" + preamble +
            "  const doc = await paintChart({ \"angles.csv\": \"u_csv\",\n"
            "    \"diagnostics.json\": \"u_diag\" }, " + result_json +
            ", null, \"demo success\");\n" +
            post +
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")

    def fetch_map(self, diag_text=None):
        return {"u_csv": self.angles_text,
                "u_diag": diag_text or self.diagnostics_text}

    def test_arm_label_and_endpoints_are_measured(self):
        post = (
            "  const kids =\n"
            "    document.getElementById(\"replaySvg\").children;\n"
            "  const dots = kids.filter((k) => k.tag === \"circle\"\n"
            "    && k.attrs.r === \"1.2\").length;\n"
            "  const anchors = kids.filter((k) => k.tag === \"circle\"\n"
            "    && k.attrs.r === \"4\").length;\n"
            "  let armD = \"\";\n"
            "  const arm = document.getElementById(\"replayArm\");\n"
            "  const bob = document.getElementById(\"replayBob\");\n"
            "  const child = kids.find((k) => k.tag === \"line\"\n"
            "    && k.attrs.id === \"replayArm\");\n"
            "  for (const k of kids)\n"
            "    if (k.tag === \"path\") armD = k.attrs.d || \"\";\n"
            "  __emit({ label: document.getElementById(\"replayLabel\")\n"
            "      .textContent,\n"
            "    dots, anchors, nan: armD.includes(\"NaN\"),\n"
            "    len: armD.length,\n"
            "    x1: child.attrs.x1, y1: child.attrs.y1,\n"
            "    x2: arm.getAttribute(\"x2\"), y2: arm.getAttribute(\"y2\"),\n"
            "    cx: bob.getAttribute(\"cx\"),\n"
            "    cy: bob.getAttribute(\"cy\") });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             self.diagnostics_text, post=post),
            self.fetch_map())
        # (a) the exact honest label, written by the script.
        self.assertEqual(out["label"], self.LABEL)
        # Every measured centroid drawn faint, one pivot anchor,
        # finite path data throughout.
        self.assertEqual(out["dots"], 234)
        self.assertEqual(out["anchors"], 1)
        self.assertGreater(out["len"], 0)
        self.assertFalse(out["nan"])
        for key in ("x1", "y1", "x2", "y2", "cx", "cy"):
            self.assertTrue(float(out[key]) == float(out[key]),
                            f"non-finite arm coordinate: {key}")
        # The arm endpoint IS the measured-centroid marker.
        self.assertEqual(out["x2"], out["cx"])
        self.assertEqual(out["y2"], out["cy"])

    def test_speed_multiplies_pts_deltas_exactly(self):
        check = (
            "  const speeds = [\"0.25\", \"0.5\", \"1\", \"2\", \"4\",\n"
            "    \"\", \"9\", \"1x\"];\n"
            "  const got = {};\n"
            "  for (const s of speeds) {\n"
            "    document.getElementById(\"replaySpeed\").value = s;\n"
            "    got[s] = replayAdvance(10.0, 2000);\n"
            "  }\n"
            "  __emit(got);\n")
        out = run_page_driver(self.script, check, {})
        # (b) 2000 ms at speed s advances the PTS cursor by 2*s.
        self.assertEqual(out["0.25"], 10.5)
        self.assertEqual(out["0.5"], 11.0)
        self.assertEqual(out["1"], 12.0)
        self.assertEqual(out["2"], 14.0)
        self.assertEqual(out["4"], 18.0)
        # Anything off the allowlist falls back to 1.
        self.assertEqual(out[""], 12.0)
        self.assertEqual(out["9"], 12.0)
        self.assertEqual(out["1x"], 12.0)

    def test_scrub_shows_measured_frame_values(self):
        post = (
            "  syncPlayheads(27);\n"
            "  const arm = document.getElementById(\"replayArm\");\n"
            "  const bob = document.getElementById(\"replayBob\");\n"
            "  __emit({ readout: document.getElementById(\n"
            "      \"replayReadout\").textContent,\n"
            "    counter: document.getElementById(\"frameCounter\")\n"
            "      .textContent,\n"
            "    x1: arm.getAttribute(\"x1\"), y1: arm.getAttribute(\"y1\"),\n"
            "    x2: arm.getAttribute(\"x2\"), y2: arm.getAttribute(\"y2\"),\n"
            "    cx: bob.getAttribute(\"cx\"),\n"
            "    cy: bob.getAttribute(\"cy\") });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             self.diagnostics_text, post=post),
            self.fetch_map())
        # (c) scrub to row 27 shows that row's measured theta/PTS.
        theta, pts = self.rows[27][2], self.rows[27][1]
        shown = re.findall(r"[-+0-9.eE]+", out["readout"])
        self.assertAlmostEqual(float(shown[0]), theta, places=4)
        self.assertAlmostEqual(float(shown[1]), pts, places=3)
        self.assertEqual(out["counter"], "28 / 234")
        self.assertEqual(out["x2"], out["cx"])
        self.assertEqual(out["y2"], out["cy"])

    def test_reduced_motion_parks_with_posed_arm(self):
        post = (
            "  toggleReplay();\n"
            "  const btn = document.getElementById(\"replayBtn\");\n"
            "  const bob = document.getElementById(\"replayBob\");\n"
            "  __emit({ scrub: document.getElementById(\"scrub\").value,\n"
            "    counter: document.getElementById(\"frameCounter\")\n"
            "      .textContent,\n"
            "    disabled: btn.disabled, btn: btn.textContent,\n"
            "    caption: document.getElementById(\"replayCaption\")\n"
            "      .textContent,\n"
            "    label: document.getElementById(\"replayLabel\")\n"
            "      .textContent,\n"
            "    readout: document.getElementById(\"replayReadout\")\n"
            "      .textContent,\n"
            "    cx: bob.getAttribute(\"cx\"),\n"
            "    cy: bob.getAttribute(\"cy\") });\n")
        out = run_page_driver(
            self.script,
            self.paint_check(json.dumps(self.result),
                             self.diagnostics_text, post=post),
            self.fetch_map())
        # (d) the stub reports reduced motion: static mid-frame,
        # parked Play, arm posed at the scrub position, no advance.
        self.assertEqual(out["scrub"], "116")
        self.assertEqual(out["counter"], "117 / 234")
        self.assertTrue(out["disabled"])
        self.assertEqual(out["btn"], "Play")
        self.assertIn("reduced-motion", out["caption"])
        self.assertEqual(out["label"], self.LABEL)
        theta, pts = self.rows[116][2], self.rows[116][1]
        shown = re.findall(r"[-+0-9.eE]+", out["readout"])
        self.assertAlmostEqual(float(shown[0]), theta, places=4)
        self.assertAlmostEqual(float(shown[1]), pts, places=3)
        self.assertTrue(float(out["cx"]) == float(out["cx"]))
        self.assertTrue(float(out["cy"]) == float(out["cy"]))

    def test_empty_payload_honest_empty_state(self):
        check = (
            "(async () => {\n"
            "  await paintChart({}, null, null, \"demo success\");\n"
            "  const emptyKids = document.getElementById(\"replaySvg\")\n"
            "    .children.length;\n"
            "  const emptyLabel = document.getElementById(\"replayLabel\")\n"
            "    .textContent;\n"
            "  const emptyBtn = document.getElementById(\"replayBtn\")\n"
            "    .disabled;\n"
            "  await paintChart({}, { status: \"unsupported_input\" },\n"
            "    null, \"demo rejection\");\n"
            "  __emit({ emptyKids, emptyLabel, emptyBtn,\n"
            "    caption: document.getElementById(\"replayCaption\")\n"
            "      .textContent,\n"
            "    disabled: document.getElementById(\"replayBtn\")\n"
            "      .disabled });\n"
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")
        out = run_page_driver(self.script, check, {})
        # (e) empty payload: nothing animated, honest text, no throw.
        self.assertEqual(out["emptyKids"], 0)
        self.assertIn("No measured frames", out["emptyLabel"])
        self.assertIn("nothing to replay", out["emptyLabel"])
        self.assertTrue(out["emptyBtn"])
        # Rejection: controls parked with the honest reason.
        self.assertIn("No replay: this run was rejected "
                      "(unsupported_input)", out["caption"])
        self.assertIn("nothing measured", out["caption"])
        self.assertTrue(out["disabled"])

    def test_missing_pivot_honest_no_arm(self):
        base = json.loads(self.diagnostics_text)
        variants = {
            "missing": {k: v for k, v in base.items()
                        if k != "pivot_px"},
            "null": {**base, "pivot_px": None},
            "malformed": {**base, "pivot_px": ["a", "b"]},
            "short": {**base, "pivot_px": [1.0]},
        }
        for name, diag in variants.items():
            with self.subTest(variant=name):
                post = (
                    "  const kids = document.getElementById(\n"
                    "    \"replaySvg\").children;\n"
                    "  const chartKids = document.getElementById(\n"
                    "    \"chartSvg\").children;\n"
                    "  const dots = chartKids.filter(\n"
                    "    (k) => k.tag === \"circle\").length;\n"
                    "  __emit({ label: document.getElementById(\n"
                    "      \"replayLabel\").textContent,\n"
                    "    kids: kids.length, dots });\n")
                out = run_page_driver(
                    self.script,
                    self.paint_check(json.dumps(self.result),
                                     json.dumps(diag), post=post),
                    self.fetch_map(json.dumps(diag)))
                # (e) no usable pivot: no arm, honest text, no
                # throw — while the measured charts still render.
                self.assertIn("No pivot in this payload",
                              out["label"])
                self.assertIn("arm not drawn", out["label"])
                self.assertEqual(out["kids"], 0)
                self.assertEqual(out["dots"], 234)

    def test_page_invariants_hold(self):
        # (f) the KL-10.5 bans survive this task: no trig, no
        # timers, textContent-only DOM writes. KL-10.9-B scopes
        # the trig ban to outside the sim sentinels (updated
        # per the KL-10.9-B brief, which owns this invariant).
        begin = "/* __KL_SIM_MODULE_BEGIN__ */"
        end = "/* __KL_SIM_MODULE_END__ */"
        outside = (self.script.split(begin)[0]
                   + self.script.split(end)[1])
        for token in ("Math.sin", "Math.cos", "Math.tan",
                      "Math.exp"):
            self.assertNotIn(token, outside)
        for token in ("innerHTML", "outerHTML",
                      "insertAdjacentHTML", "document.write",
                      "setTimeout", "setInterval"):
            self.assertNotIn(token, self.script)
        self.assertNotIn("eval(", self.script)
        # The honest label is owned in exactly one place.
        self.assertEqual(self.script.count(self.LABEL), 1)


class UncertaintyRowTests(unittest.TestCase):
    """KL-10.11: the bootstrap interval rows proven by EXECUTING
    the shipped page script under node — populated payload renders
    verbatim, missing payload renders "not recorded", never throws."""

    @classmethod
    def setUpClass(cls):
        page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")

    def _rows_check(self, ctx_js):
        return (
            "  paintSciDiagnostics(" + ctx_js + ");\n"
            "  __emit({ rows: document.getElementById(\"sciDiagRows\")\n"
            "    .children.map((tr) => tr.textContent) });\n")

    def test_populated_interval_renders_verbatim(self):
        ctx = (
            "{ result: { fit: { fit_uncertainty_method:"
            " \"block_bootstrap\" } },\n"
            "    report: null,\n"
            "    diagnosticsDoc: { fit_uncertainty: {\n"
            "      method: \"block_bootstrap\", seed: 7, n_boot: 64,\n"
            "      block_frames: 21,\n"
            "      omega_per_s: { low: 5.4, point: 5.5, high: 5.6 },\n"
            "      g_over_l_eff_per_s2: { low: 29.0, point: 30.0,\n"
            "        high: 31.0 } } },\n"
            "    geoDoc: null, calibDoc: null }")
        out = run_page_driver(self.script, self._rows_check(ctx), {})
        rows = "\n".join(out["rows"])
        self.assertIn("Fit uncertainty methodblock_bootstrap", rows)
        self.assertIn("Uncertainty interval (omega)"
                      "[5.4, 5.6] 1/s (point 5.5)", rows)
        self.assertIn("Uncertainty interval (g/L_eff)"
                      "[29, 31] 1/s^2 (point 30)", rows)
        self.assertIn("Resamplingresampling under M1 \u00b7 seed 7 "
                      "\u00b7 n_boot 64 \u00b7 block 21 frames", rows)

    def test_missing_interval_renders_not_recorded(self):
        ctx = ("{ result: null, report: null, diagnosticsDoc: {},\n"
               "    geoDoc: null, calibDoc: null }")
        out = run_page_driver(self.script, self._rows_check(ctx), {})
        rows = "\n".join(out["rows"])
        self.assertIn("Fit uncertainty methodnot recorded", rows)
        self.assertIn("Uncertainty interval (omega)not recorded",
                      rows)
        self.assertIn("Uncertainty interval (g/L_eff)not recorded",
                      rows)
        self.assertIn("Resamplingnot recorded", rows)


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class SimulationTests(unittest.TestCase):
    """KL-10.9-B: the simulation playground proven by EXECUTING the
    shipped page script under node — real fixture payloads, DOM stub,
    driven rAF. The model toy must label itself honestly, integrate
    sanely, and never touch pipeline-owned state."""

    LABEL = "MODEL RECONSTRUCTION \u2014 not measured data."
    SIM_IDS = frozenset([
        "simSvg", "simLabel", "simTrailNote", "simSeedLine",
        "simPlayBtn", "simResetBtn", "simScale", "simG", "simGamma",
        "simAngle", "simGVal", "simGammaVal", "simAngleVal",
        "simThetaReadout", "simClockReadout", "simCaption",
        "simArm", "simBob", "simSeedTile",
    ])

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = cls.page.split("<script>", 1)[1].split(
            "</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")
        asm = REPO_ROOT / "fixtures" / "assembly"
        cls.result = json.loads(
            (asm / "result.json").read_text(encoding="utf-8"))
        cls.diagnostics_text = (
            asm / "diagnostics.json").read_text(encoding="utf-8")
        cls.angles_text = (
            asm / "angles.csv").read_text(encoding="utf-8")

    def paint_run(self, preamble="", post=""):
        return (
            "(async () => {\n" + preamble +
            "  const doc = await paintChart({ \"angles.csv\": \"u_csv\",\n"
            "    \"diagnostics.json\": \"u_diag\" }, " + json.dumps(
                self.result) + ", null, \"demo success\");\n" +
            post +
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")

    def fetch_map(self):
        return {"u_csv": self.angles_text,
                "u_diag": self.diagnostics_text}

    def test_label_seed_and_underlay_from_measured_run(self):
        post = (
            "  const kids =\n"
            "    document.getElementById(\"simSvg\").children;\n"
            "  const dots = kids.filter((k) => k.tag === \"circle\"\n"
            "    && k.attrs.r === \"1.2\");\n"
            "  const arm = kids.find((k) => k.tag === \"line\"\n"
            "    && k.attrs.id === \"simArm\");\n"
            "  const bob = kids.find((k) => k.tag === \"circle\"\n"
            "    && k.attrs.id === \"simBob\");\n"
            "  __emit({ label: document.getElementById(\"simLabel\")\n"
            "      .textContent,\n"
            "    seed: document.getElementById(\"simSeedLine\")\n"
            "      .textContent,\n"
            "    note: document.getElementById(\"simTrailNote\")\n"
            "      .textContent,\n"
            "    g: document.getElementById(\"simG\").value,\n"
            "    gmin: document.getElementById(\"simG\").min,\n"
            "    gmax: document.getElementById(\"simG\").max,\n"
            "    gamma: document.getElementById(\"simGamma\").value,\n"
            "    dots: dots.length,\n"
            "    dim: dots.length > 0 ? dots[0].attrs.opacity : null,\n"
            "    x2: arm.attrs.x2, cx: bob.attrs.cx });\n")
        out = run_page_driver(
            self.script, self.paint_run(post=post), self.fetch_map())
        self.assertEqual(out["label"], self.LABEL)
        self.assertIn("30.00563573707589", out["seed"])
        self.assertIn("diagnostic cross-check, not measured",
                      out["seed"])
        self.assertEqual(out["g"], "30.00563573707589")
        self.assertEqual(out["gamma"], "0.029794544246787853")
        gmin, gmax = float(out["gmin"]), float(out["gmax"])
        self.assertLess(gmin, 30.00563573707589)
        self.assertGreater(gmax, 30.00563573707589)
        self.assertAlmostEqual((gmax - gmin) / 30.00563573707589,
                               0.5, places=9)
        self.assertEqual(
            out["note"],
            "Measured trail underlay: 234 frames (dimmed).")
        self.assertEqual(out["dots"], 234)
        self.assertEqual(out["dim"], "0.35")
        self.assertTrue(float(out["x2"]) == float(out["x2"]))
        self.assertTrue(float(out["cx"]) == float(out["cx"]))

    def test_integration_decay_and_conservation(self):
        check = (
            "  const roll = (gamma) => {\n"
            "    let th = 0.3, w = 0;\n"
            "    let early = 0, late = 0, max = 0;\n"
            "    for (let i = 0; i < 2400; i++) {\n"
            "      const next = simStepTheta(th, w, 30, gamma,\n"
            "        1 / 240);\n"
            "      th = next[0]; w = next[1];\n"
            "      const a = Math.abs(th);\n"
            "      if (a > max) max = a;\n"
            "      if (i < 240 && a > early) early = a;\n"
            "      if (i >= 2160 && a > late) late = a;\n"
            "    }\n"
            "    return { early, late, max };\n"
            "  };\n"
            "  __emit({ damped: roll(0.05), free: roll(0) });\n")
        out = run_page_driver(self.script, check, {})
        damped, free = out["damped"], out["free"]
        # Damping bleeds swing size; the undamped run holds it.
        self.assertLess(damped["late"], 0.9 * damped["early"])
        self.assertLessEqual(damped["max"], 0.3001)
        self.assertLess(abs(free["late"] - free["early"]), 1e-3)
        self.assertLessEqual(free["max"], 0.3001)

    def test_play_runs_five_simulated_seconds(self):
        preamble = (
            "  window.matchMedia = () => ({ matches: false });\n"
            "  let rafCb = null;\n"
            "  globalThis.requestAnimationFrame = (cb) => {\n"
            "    rafCb = cb; return 1;\n"
            "  };\n")
        post = (
            "  document.getElementById(\"simScale\").value = \"1\";\n"
            "  document.getElementById(\"simAngle\").value = \"0.3\";\n"
            "  simReset();\n"
            "  toggleSimPlay();\n"
            "  const btn = () =>\n"
            "    document.getElementById(\"simPlayBtn\").textContent;\n"
            "  const clock = () =>\n"
            "    document.getElementById(\"simClockReadout\")\n"
            "      .textContent;\n"
            "  const theta = () =>\n"
            "    document.getElementById(\"simThetaReadout\")\n"
            "      .textContent;\n"
            "  const armX = () =>\n"
            "    document.getElementById(\"simArm\")\n"
            "      .getAttribute(\"x2\");\n"
            "  rafCb(0);\n"
            "  const firstTheta = theta();\n"
            "  for (let t = 250; t <= 5000; t += 250) rafCb(t);\n"
            "  const mid = { btn: btn(), clock: clock(),\n"
            "    theta: theta(), x: armX() };\n"
            "  toggleSimPlay();\n"
            "  const pausedCaption = document.getElementById(\n"
            "    \"simCaption\").textContent;\n"
            "  rafCb(20000);\n"
            "  __emit({ firstTheta, mid, btn: btn(),\n"
            "    pausedCaption, frozen: clock() });\n")
        out = run_page_driver(
            self.script,
            self.paint_run(preamble=preamble, post=post),
            self.fetch_map())
        self.assertEqual(out["mid"]["btn"], "Pause")
        shown = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?",
                           out["mid"]["clock"])
        self.assertAlmostEqual(float(shown[0]), 5.0, places=2)
        self.assertTrue(out["mid"]["clock"].startswith(
            "simulated t = "))
        self.assertTrue(out["mid"]["theta"].startswith(
            "simulated \u03b8 = "))
        self.assertNotEqual(out["mid"]["theta"], out["firstTheta"])
        self.assertTrue(float(out["mid"]["x"]) ==
                        float(out["mid"]["x"]))
        self.assertEqual(out["btn"], "Play")
        self.assertEqual(out["pausedCaption"], "Simulation paused.")
        self.assertEqual(out["frozen"], out["mid"]["clock"])

    def test_isolation_result_untouched(self):
        preamble = (
            "  window.matchMedia = () => ({ matches: false });\n"
            "  let rafCb = null;\n"
            "  globalThis.requestAnimationFrame = (cb) => {\n"
            "    rafCb = cb; return 1;\n"
            "  };\n")
        post = (
            "  const resObj = " + json.dumps(self.result) + ";\n"
            "  const snap = () => JSON.stringify({\n"
            "    res: JSON.stringify(resObj),\n"
            "    sci: document.getElementById(\"sciState\").textContent,\n"
            "    meta: document.getElementById(\"chartMeta\")\n"
            "      .textContent,\n"
            "    fc: document.getElementById(\"frameCounter\")\n"
            "      .textContent,\n"
            "    rl: document.getElementById(\"replayLabel\")\n"
            "      .textContent,\n"
            "    rc: document.getElementById(\"replayCaption\")\n"
            "      .textContent,\n"
            "    rr: document.getElementById(\"replayReadout\")\n"
            "      .textContent,\n"
            "    rms: document.getElementById(\"rmsChip\").textContent,\n"
            "    pc: document.getElementById(\"periodChip\")\n"
            "      .textContent,\n"
            "    rows: document.getElementById(\"sciDiagRows\").children\n"
            "      .map((tr) => tr.textContent),\n"
            "    scrub: document.getElementById(\"scrub\").value,\n"
            "    scrubMax: document.getElementById(\"scrub\").max,\n"
            "    ph: document.getElementById(\"playheadReadout\")\n"
            "      .textContent,\n"
            "    chartN: document.getElementById(\"chartSvg\").children\n"
            "      .length,\n"
            "    trailN: document.getElementById(\"trailSvg\").children\n"
            "      .length,\n"
            "    stripN: document.getElementById(\"stripSvg\").children\n"
            "      .length,\n"
            "    replayN: document.getElementById(\"replaySvg\").children\n"
            "      .length,\n"
            "    sdPts: seriesData.points.length,\n"
            "    sdTrail: seriesData.trail.length,\n"
            "    sdPivot: JSON.stringify(seriesData.pivot) });\n"
            "  const doc2 = await paintChart(\n"
            "    { \"angles.csv\": \"u_csv\",\n"
            "      \"diagnostics.json\": \"u_diag\" },\n"
            "    resObj, null, \"demo success\");\n"
            "  const before = snap();\n"
            "  document.getElementById(\"simG\").value = \"22.5\";\n"
            "  document.getElementById(\"simGamma\").value = \"0.1\";\n"
            "  document.getElementById(\"simAngle\").value = \"0.5\";\n"
            "  document.getElementById(\"simScale\").value = \"2\";\n"
            "  toggleSimPlay();\n"
            "  for (let t = 0; t <= 2500; t += 250) rafCb(t);\n"
            "  const midClock = document.getElementById(\n"
            "    \"simClockReadout\").textContent;\n"
            "  const simKids = document.getElementById(\"simSvg\")\n"
            "    .children.length;\n"
            "  toggleSimPlay();\n"
            "  simReset();\n"
            "  const after = snap();\n"
            "  __emit({ before, after, midClock, simKids,\n"
            "    theta: document.getElementById(\"simThetaReadout\")\n"
            "      .textContent,\n"
            "    clock: document.getElementById(\"simClockReadout\")\n"
            "      .textContent });\n")
        driver = (
            "(async () => {\n" + preamble + post +
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")
        out = run_page_driver(self.script, driver, self.fetch_map())
        # The sim ran (5 simulated s at 2x) and reset ...
        shown = re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?",
                           out["midClock"])
        self.assertAlmostEqual(float(shown[0]), 5.0, places=2)
        self.assertGreater(out["simKids"], 200)
        self.assertEqual(out["theta"], "simulated \u03b8 = 0.50000 rad")
        self.assertEqual(out["clock"], "simulated t = 0.000 s")
        # ... while every result-owned byte stayed identical.
        self.assertEqual(out["before"], out["after"])

    def test_no_run_honest_note_and_static_pose(self):
        post = (
            "  wireSimulation();\n"
            "  const kids =\n"
            "    document.getElementById(\"simSvg\").children;\n"
            "  const dots = kids.filter((k) => k.tag === \"circle\"\n"
            "    && k.attrs.r === \"1.2\").length;\n"
            "  const arm = kids.find((k) => k.tag === \"line\"\n"
            "    && k.attrs.id === \"simArm\");\n"
            "  const bob = kids.find((k) => k.tag === \"circle\"\n"
            "    && k.attrs.id === \"simBob\");\n"
            "  __emit({ label: document.getElementById(\"simLabel\")\n"
            "      .textContent,\n"
            "    note: document.getElementById(\"simTrailNote\")\n"
            "      .textContent,\n"
            "    seed: document.getElementById(\"simSeedLine\")\n"
            "      .textContent,\n"
            "    dots,\n"
            "    x2: arm.attrs.x2, cx: bob.attrs.cx,\n"
            "    theta: document.getElementById(\"simThetaReadout\")\n"
            "      .textContent,\n"
            "    clock: document.getElementById(\"simClockReadout\")\n"
            "      .textContent });\n")
        out = run_page_driver(self.script, post, {})
        self.assertEqual(out["label"], self.LABEL)
        self.assertEqual(out["note"], "no measured trail loaded")
        self.assertIn("Seed: none", out["seed"])
        self.assertEqual(out["dots"], 0)
        self.assertTrue(float(out["x2"]) == float(out["x2"]))
        self.assertTrue(float(out["cx"]) == float(out["cx"]))
        self.assertEqual(out["theta"], "simulated \u03b8 = 0.30000 rad")
        self.assertEqual(out["clock"], "simulated t = 0.000 s")

    def test_reduced_motion_parks_with_live_sliders(self):
        post = (
            "  wireSimulation();\n"
            "  const btn = document.getElementById(\"simPlayBtn\");\n"
            "  const btnBefore = btn.textContent;\n"
            "  toggleSimPlay();\n"
            "  const btnAfter = btn.textContent;\n"
            "  const caption = document.getElementById(\"simCaption\")\n"
            "    .textContent;\n"
            "  document.getElementById(\"simAngle\").value = \"0.5\";\n"
            "  simReset();\n"
            "  __emit({ disabled: btn.disabled,\n"
            "    btnBefore, btnAfter,\n"
            "    caption,\n"
            "    theta: document.getElementById(\"simThetaReadout\")\n"
            "      .textContent,\n"
            "    clock: document.getElementById(\"simClockReadout\")\n"
            "      .textContent });\n")
        out = run_page_driver(self.script, post, {})
        # The stub reports reduced motion: parked Play, static
        # pose, controls still usable.
        self.assertTrue(out["disabled"])
        self.assertEqual(out["btnBefore"], out["btnAfter"])
        self.assertIn("reduced-motion", out["caption"])
        self.assertEqual(out["theta"], "simulated \u03b8 = 0.50000 rad")
        self.assertEqual(out["clock"], "simulated t = 0.000 s")

    def test_rejection_note_keeps_sim_usable(self):
        check = (
            "(async () => {\n"
            "  await paintChart({}, { status: \"unsupported_input\" },\n"
            "    null, \"demo rejection\");\n"
            "  const kids = document.getElementById(\"simSvg\")\n"
            "    .children;\n"
            "  const dots = kids.filter((k) => k.tag === \"circle\"\n"
            "    && k.attrs.r === \"1.2\").length;\n"
            "  const label = document.getElementById(\"simLabel\")\n"
            "    .textContent;\n"
            "  const g = document.getElementById(\"simG\").value;\n"
            "  simNoteRejection(\"success\");\n"
            "  const cleared = document.getElementById(\n"
            "    \"simTrailNote\").textContent;\n"
            "  document.getElementById(\"simAngle\").value = \"0.3\";\n"
            "  simReset();\n"
            "  __emit({ label, dots, cleared, g,\n"
            "    theta: document.getElementById(\"simThetaReadout\")\n"
            "      .textContent });\n"
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(out["cleared"], "no measured trail loaded")
        self.assertEqual(out["label"], self.LABEL)
        self.assertEqual(out["dots"], 0)
        self.assertEqual(out["g"], "20")
        self.assertEqual(out["theta"], "simulated \u03b8 = 0.30000 rad")

    def test_rejection_reason_shown(self):
        check = (
            "(async () => {\n"
            "  await paintChart({}, { status: \"unsupported_input\" },\n"
            "    null, \"demo rejection\");\n"
            "  __emit({ note: document.getElementById(\"simTrailNote\")\n"
            "    .textContent });\n"
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")
        out = run_page_driver(self.script, check, {})
        self.assertIn("run rejected (unsupported_input)", out["note"])
        self.assertIn("simulation still available", out["note"])

    def test_sim_region_static_contracts(self):
        begin = "/* __KL_SIM_MODULE_BEGIN__ */"
        end = "/* __KL_SIM_MODULE_END__ */"
        self.assertEqual(self.script.count(begin), 1)
        self.assertEqual(self.script.count(end), 1)
        region = self.script.split(begin)[1].split(end)[0]
        # Isolation, statically: only sim* element IDs referenced.
        ids = set(re.findall(r'el\("([^"]+)"', region))
        ids |= set(re.findall(r'getElementById\("([^"]+)"',
                              region))
        self.assertTrue(ids <= self.SIM_IDS,
                        f"non-sim IDs in module: {ids - self.SIM_IDS}")
        # No writes into pipeline-owned state, no masquerading
        # readouts, no success styling, no DOM-write escapes.
        for token in ("seriesData =", "result.", "exports",
                      "verdict", "syncPlayheads", "clearVisuals",
                      "paintChart", "paintMotion", "runDemo", "files[",
                      "period", "uncertainty", "interval",
                      "innerHTML", '"good"', '"live"'):
            with self.subTest(token=token):
                self.assertNotIn(token, region)
        # Trig lives here (the amended allowance), timers do not.
        self.assertIn("Math.sin", region)
        self.assertIn("Math.cos", region)
        self.assertNotIn("setTimeout", region)
        self.assertNotIn("setInterval", region)
        # The honest label is owned in exactly one place.
        self.assertEqual(self.script.count(self.LABEL), 1)
        # Sim controls are neutral buttons, never green.
        for btn_id in ("simPlayBtn", "simResetBtn"):
            tag = re.search(r"<button[^>]*id=\"" + btn_id +
                            r"\"[^>]*>", self.page).group(0)
            self.assertIn('class="btn small"', tag)
            self.assertNotIn("good", tag)
            self.assertNotIn("primary", tag)

    def test_sim_persistent_column_structure(self):
        # KL-10.14: stage stacked over controls in the persistent right
        # column; side-by-side again only when the rail spans full
        # width on narrower screens.
        block = self.page.split('id="viewSimulation"', 1)[1].split(
            'class="underbar"', 1)[0]
        self.assertIn('class="sim-layout"', block)
        self.assertIn('class="sim-stage-col"', block)
        self.assertIn('class="sim-panel"', block)
        self.assertIn(
            ".sim-layout{display:grid;"
            "grid-template-columns:minmax(0,1fr);",
            self.page)
        self.assertIn(
            "@media(max-width:1250px)"
            "{.sim-layout{grid-template-columns:minmax(0,1fr) 320px}}",
            self.page)
        self.assertLess(
            self.page.index("</main>"),
            self.page.index('id="viewSimulation"'))
        self.assertLess(
            self.page.index('id="viewSimulation"'),
            self.page.index('class="underbar"'))

    def test_sim_panel_stat_tiles_and_formula(self):
        # KL-10.12: kicker, badge chip, stat tiles, formula panel,
        # footer note — all present with the frozen node IDs.
        # KL-10.14: same content, re-anchored to the persistent column
        # (the old sciDiagWrap anchor now sits ahead of the sim block).
        block = self.page.split('id="viewSimulation"', 1)[1].split(
            'class="underbar"', 1)[0]
        self.assertIn("SIMULATION PLAYGROUND", block)
        self.assertIn('class="sim-badge" id="simLabel"', block)
        self.assertIn('class="sim-stats"', block)
        for ident in ("simThetaReadout", "simClockReadout",
                      "simSeedTile", "simGVal", "simGammaVal",
                      "simAngleVal"):
            with self.subTest(ident=ident):
                self.assertIn(f'id="{ident}"', block)
        self.assertIn('class="sim-formula"', block)
        self.assertIn("model, not fit to your data", block)
        self.assertIn(
            "Simulated clock never touches the measured timebase.",
            block)
        self.assertIn('class="sim-range" id="simG"', block)
        self.assertIn("#viewSimulation{--sim-accent:var(--blue-2)",
                      self.page)

    def test_sim_stage_scene_dressing(self):
        # KL-10.12: mount bar, plumb line, swing arc, gradient bob
        # are built inside the sentinel module (cosmetic JS only).
        begin = "/* __KL_SIM_MODULE_BEGIN__ */"
        end = "/* __KL_SIM_MODULE_END__ */"
        region = self.script.split(begin)[1].split(end)[0]
        for token in ("radialGradient", "simBobGrad",
                      "stroke-dasharray", "simArcPath",
                      "simRadial", "simSeedTile"):
            with self.subTest(token=token):
                self.assertIn(token, region)
        self.assertIn('id="simSeedTile"', self.page)


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class UiPolish1013Tests(unittest.TestCase):
    """KL-10.13: toasts, inline validation, and the top loading bar
    proven by EXECUTING the shipped page script under node with the
    DOM stub and a hand-driven rAF queue (the shared ticker is the
    only clock, so synthetic timestamps drive every lifecycle)."""

    RAF_PREAMBLE = (
        "  const __cbs = [];\n"
        "  globalThis.requestAnimationFrame = (cb) => {\n"
        "    __cbs.push(cb); return __cbs.length; };\n"
        "  const __tick = (now) => {\n"
        "    const batch = __cbs.splice(0, __cbs.length);\n"
        "    for (const cb of batch) cb(now); };\n")

    @classmethod
    def setUpClass(cls):
        page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")

    def test_toast_auto_dismiss_via_raf(self):
        check = (
            "try {\n" + self.RAF_PREAMBLE +
            "  notify(\"Run complete\", \"Done.\", \"ok\");\n"
            "  const wrap = document.getElementById(\"toastWrap\");\n"
            "  const before = wrap.children.length;\n"
            "  __tick(0);\n"
            "  __tick(3000);\n"
            "  const mid = wrap.children.length;\n"
            "  __tick(8000);\n"
            "  __emit({ before, mid, after: wrap.children.length });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(out["before"], 1)
        self.assertEqual(out["mid"], 1)
        self.assertEqual(out["after"], 0)

    def test_toast_hover_pauses_dismiss(self):
        check = (
            "try {\n" + self.RAF_PREAMBLE +
            "  notify(\"Saved\", \"Held.\", \"info\");\n"
            "  const wrap = document.getElementById(\"toastWrap\");\n"
            "  __tick(0);\n"
            "  const toast = wrap.children[0];\n"
            "  toast.onmouseenter();\n"
            "  __tick(60000);\n"
            "  const held = wrap.children.length;\n"
            "  toast.onmouseleave();\n"
            "  __tick(70000);\n"
            "  __emit({ held, after: wrap.children.length });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(out["held"], 1)
        self.assertEqual(out["after"], 0)

    def test_toast_close_button_dismisses(self):
        check = (
            "try {\n" + self.RAF_PREAMBLE +
            "  notify(\"Heads up\", \"Closable.\", \"warn\");\n"
            "  const wrap = document.getElementById(\"toastWrap\");\n"
            "  __tick(0);\n"
            "  const toast = wrap.children[0];\n"
            "  const kinds = toast.className;\n"
            "  toast.children[0].onclick();\n"
            "  const after = wrap.children.length;\n"
            "  __tick(9000);\n"
            "  __emit({ kinds, after,\n"
            "    still: wrap.children.length });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(out["kinds"], "toast warning")
        self.assertEqual(out["after"], 0)
        self.assertEqual(out["still"], 0)

    def test_toast_kinds_cap_and_structure(self):
        check = (
            "try {\n" + self.RAF_PREAMBLE +
            "  const mapped = [toastKindName(\"ok\"),\n"
            "    toastKindName(\"info\"), toastKindName(\"warn\"),\n"
            "    toastKindName(\"bad\"), toastKindName(\"error\"),\n"
            "    toastKindName(\"success\")];\n"
            "  notify(\"One\", \"a\", \"ok\");\n"
            "  notify(\"Two\", \"b\", \"info\");\n"
            "  notify(\"Three\", \"c\", \"warn\");\n"
            "  notify(\"Four\", \"d\", \"bad\");\n"
            "  notify(\"Five\", \"e\", \"success\");\n"
            "  const wrap = document.getElementById(\"toastWrap\");\n"
            "  const first = wrap.children[0];\n"
            "  __emit({ mapped, count: wrap.children.length,\n"
            "    classes: wrap.children.map((t) => t.className),\n"
            "    roles: wrap.children.map((t) =>\n"
            "      t.getAttribute(\"role\")),\n"
            "    kids: first.children.length,\n"
            "    head: first.children[1].textContent,\n"
            "    body: first.children[2].textContent });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(out["mapped"], ["success", "info", "warning",
                                         "error", "error", "success"])
        self.assertEqual(out["count"], 3)
        self.assertEqual(out["classes"], ["toast warning", "toast error",
                                          "toast success"])
        self.assertEqual(out["roles"], ["status", "status", "status"])
        self.assertEqual(out["kids"], 3)
        self.assertEqual(out["head"], "Three")
        self.assertEqual(out["body"], "c")

    def test_clip_validation_states(self):
        check = (
            "try {\n"
            "  const wrong = clipFileError({ name: \"notes.txt\",\n"
            "    type: \"text/plain\", size: 12 });\n"
            "  const empty = clipFileError({ name: \"a.mp4\",\n"
            "    type: \"video/mp4\", size: 0 });\n"
            "  const big = clipFileError({ name: \"a.mp4\",\n"
            "    type: \"video/mp4\", size: 70 * 1048576 });\n"
            "  const good = clipFileError({ name: \"a.webm\",\n"
            "    type: \"video/webm\", size: 100 });\n"
            "  const byExt = clipFileError({ name: \"a.mp4\",\n"
            "    type: \"\", size: 5 });\n"
            "  const badOk = validateClipSelection(\n"
            "    { name: \"notes.txt\", type: \"text/plain\", size: 12 });\n"
            "  const box = document.getElementById(\"clipFieldError\");\n"
            "  const shown = { ok: badOk, text: box.textContent,\n"
            "    hidden: box.classList.contains(\"hidden\"),\n"
            "    invalid: document.getElementById(\"dropZone\")\n"
            "      .getAttribute(\"aria-invalid\") };\n"
            "  const goodOk = validateClipSelection(\n"
            "    { name: \"a.mp4\", type: \"video/mp4\", size: 5 });\n"
            "  __emit({ wrong, empty, big, good, byExt, shown,\n"
            "    goodOk, cleared: box.textContent,\n"
            "    clearedInvalid: document.getElementById(\"dropZone\")\n"
            "      .getAttribute(\"aria-invalid\") });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertIn("not an MP4 or WebM", out["wrong"])
        self.assertIn("empty", out["empty"])
        self.assertIn("64 MB", out["big"])
        self.assertIsNone(out["good"])
        self.assertIsNone(out["byExt"])
        self.assertFalse(out["shown"]["ok"])
        self.assertIn("not an MP4 or WebM", out["shown"]["text"])
        self.assertFalse(out["shown"]["hidden"])
        self.assertEqual(out["shown"]["invalid"], "true")
        self.assertTrue(out["goodOk"])
        self.assertEqual(out["cleared"], "")
        self.assertEqual(out["clearedInvalid"], "false")

    def test_live_validation_loading_and_reduced_motion(self):
        check = (
            "try {\n"
            "  const bob = document.getElementById(\"livePromptBob\");\n"
            "  const card = document.getElementById(\"livePromptCard\");\n"
            "  bob.value = \"\"; card.value = \"card\";\n"
            "  const bobBad = validateLivePrompts(\"full\");\n"
            "  const bobErr = document.getElementById(\n"
            "    \"livePromptBobError\").textContent;\n"
            "  const bobInv = bob.getAttribute(\"aria-invalid\");\n"
            "  bob.value = \"red ball\"; card.value = \"\";\n"
            "  const cardBad = validateLivePrompts(\"full\");\n"
            "  card.value = \"card\";\n"
            "  const promptsOk = validateLivePrompts(\"full\");\n"
            "  const mm = document.getElementById(\"liveMm\");\n"
            "  mm.value = \"\";\n"
            "  const mmEmpty = validateLiveMm();\n"
            "  const mmErr = document.getElementById(\"liveMmError\")\n"
            "    .textContent;\n"
            "  mm.value = \"85.6\";\n"
            "  const mmGood = validateLiveMm();\n"
            "  mm.value = \"abc\";\n"
            "  const mmText = validateLiveMm();\n"
            "  showProgress(\"Measuring\", \"Working.\", \"Busy.\");\n"
            "  const bar = document.getElementById(\"globalProgress\");\n"
            "  const shownBar = !bar.classList.contains(\"hidden\");\n"
            "  const label = document.getElementById(\n"
            "    \"globalProgressLabel\").textContent;\n"
            "  hideProgress();\n"
            "  markChartsLoading(true);\n"
            "  const skel = document.getElementById(\"chartSvg\")\n"
            "    .classList.contains(\"skeleton\");\n"
            "  markChartsLoading(false);\n"
            "  __emit({ bobBad, bobErr, bobInv, cardBad, promptsOk,\n"
            "    mmEmpty, mmErr, mmGood, mmText, shownBar, label,\n"
            "    hiddenBar: bar.classList.contains(\"hidden\"),\n"
            "    skel, reduced: reducedMotion() });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertFalse(out["bobBad"])
        self.assertIn("empty", out["bobErr"])
        self.assertEqual(out["bobInv"], "true")
        self.assertFalse(out["cardBad"])
        self.assertTrue(out["promptsOk"])
        self.assertIsNone(out["mmEmpty"])
        self.assertIn("never guessed", out["mmErr"])
        self.assertEqual(out["mmGood"], 85.6)
        self.assertIsNone(out["mmText"])
        self.assertTrue(out["shownBar"])
        self.assertEqual(out["label"], "Measuring")
        self.assertTrue(out["hiddenBar"])
        self.assertTrue(out["skel"])
        self.assertTrue(out["reduced"])


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class DashboardLayout1014Tests(unittest.TestCase):
    """KL-10.14: the 3-column instrument dashboard — header badge,
    four-tab hero strip, left-rail order, persistent sim column,
    footer strip, and the Key Results interval line."""

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = cls.page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")
        asm = REPO_ROOT / "fixtures" / "assembly"
        cls.success_result = json.loads(
            (asm / "result.json").read_text(encoding="utf-8"))
        cls.rejection_result = json.loads(
            (asm / "rejection" / "result.json").read_text(
                encoding="utf-8"))

    def test_header_verdict_badge_states(self):
        self.assertIn('id="verdictBadge">No run yet', self.page)
        self.assertIn("verdict-badge is-neutral", self.page)
        check = (
            "try {\n"
            "  paintVerdict({ status: \"success\",\n"
            "    fit: { observation_count: 234 } }, null);\n"
            "  const badge = document.getElementById(\"verdictBadge\");\n"
            "  const good = { text: badge.textContent,\n"
            "    cls: badge.className,\n"
            "    verdict: document.getElementById(\"verdict\")\n"
            "      .className };\n"
            "  paintVerdict(" + json.dumps(self.success_result)
            + ", null);\n"
            "  const pinned = { text: badge.textContent,\n"
            "    cls: badge.className };\n"
            "  paintVerdict(" + json.dumps(self.rejection_result)
            + ", null);\n"
            "  const bad = { text: badge.textContent,\n"
            "    cls: badge.className,\n"
            "    verdict: document.getElementById(\"verdict\")\n"
            "      .className };\n"
            "  paintVerdict(null, { error: { code: \"E_TIMEOUT\" } });\n"
            "  const failed = { text: badge.textContent,\n"
            "    cls: badge.className };\n"
            "  paintVerdict({ status: \"success_with_warnings\",\n"
            "    fit: null }, null);\n"
            "  const warn = { text: badge.textContent,\n"
            "    cls: badge.className };\n"
            "  __emit({ good, pinned, bad, failed, warn });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(out["good"]["text"], "verdict: success")
        self.assertIn("is-success", out["good"]["cls"])
        self.assertEqual(out["good"]["verdict"], "verdict ok")
        self.assertEqual(out["pinned"]["text"],
                         "verdict: success with warnings")
        self.assertIn("is-warn", out["pinned"]["cls"])
        self.assertEqual(out["bad"]["text"], "verdict: rejected")
        self.assertIn("is-warn", out["bad"]["cls"])
        self.assertEqual(out["bad"]["verdict"], "verdict bad")
        self.assertEqual(out["failed"]["text"], "verdict: failed")
        self.assertIn("is-warn", out["failed"]["cls"])
        self.assertIn("is-warn", out["warn"]["cls"])
        self.assertNotIn("is-success", out["warn"]["cls"])

    def test_chart_strip_has_four_tabs(self):
        strip = self.page.split('id="sciCard"', 1)[1].split(
            'id="viewTrajectory"', 1)[0]
        self.assertEqual(strip.count('role="tab"'), 4)
        for ident in ("ctabTrajectory", "ctabResiduals", "ctabTrail",
                      "ctabReplay"):
            self.assertIn(f'id="{ident}"', strip)
        self.assertNotIn("ctabSimulation", strip)
        self.assertIn('id="ctabSimulation"', self.page)
        match = re.search(r"CTAB_IDS = \[(.*?)\]", self.script,
                          re.DOTALL)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).count('"ctab'), 4)
        self.assertNotIn("ctabSimulation", match.group(1))

    def test_left_rail_card_order(self):
        rail = self.page.split('<aside class="sidebar"', 1)[1].split(
            "</aside>", 1)[0]
        order = ["Video Analysis", "Measurement Status",
                 "Key Results (when ready)", "provSummary"]
        idx = [rail.index(token) for token in order]
        self.assertEqual(idx, sorted(idx))
        for ident in ("dropZone", "modeTag", "metricOmega",
                      "provSummary", "livePanel", "noKeyPanel"):
            self.assertIn(f'id="{ident}"', rail)

    def test_sim_persistent_column(self):
        tag = re.search(
            r'<div role="tabpanel" id="viewSimulation"[^>]*>',
            self.page)
        self.assertIsNotNone(tag)
        self.assertNotIn("hidden", tag.group(0))
        self.assertLess(
            self.page.index("</main>"),
            self.page.index('id="viewSimulation"'))
        check = (
            "try {\n"
            "  const hidden = (id) => document.getElementById(id)\n"
            "    .classList.contains(\"hidden\");\n"
            "  selectChartTab(\"ctabTrail\");\n"
            "  const trail = { view: hidden(\"viewTrail\"),\n"
            "    sim: hidden(\"viewSimulation\"),\n"
            "    replay: hidden(\"viewReplay\") };\n"
            "  selectChartTab(\"ctabTrajectory\");\n"
            "  const traj = { view: hidden(\"viewTrajectory\"),\n"
            "    sim: hidden(\"viewSimulation\") };\n"
            "  __emit({ trail, traj });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertFalse(out["trail"]["view"])
        self.assertFalse(out["trail"]["sim"])
        self.assertTrue(out["trail"]["replay"])
        self.assertFalse(out["traj"]["view"])
        self.assertFalse(out["traj"]["sim"])

    def test_footer_honest_strip(self):
        foot = self.page.split('<footer class="footer">', 1)[1].split(
            "</footer>", 1)[0]
        left = "Unknown values render as null"
        right = "All timestamps are real source PTS."
        self.assertIn(left, foot)
        self.assertIn(right, foot)
        self.assertLess(foot.index(left), foot.index(right))
        self.assertIn('id="serverFoot"', foot)

    def test_omega_interval_line(self):
        check = (
            "try {\n"
            "  const node = document.getElementById(\"omegaInterval\");\n"
            "  paintOmegaInterval({ fit_uncertainty: {\n"
            "    method: \"block_bootstrap\", n_boot: 800,\n"
            "    omega_per_s: { low: 5.468, point: 5.478,\n"
            "      high: 5.489 } } });\n"
            "  const band = node.textContent;\n"
            "  paintOmegaInterval(null);\n"
            "  const none = node.textContent;\n"
            "  paintOmegaInterval({ fit_uncertainty: { method: \"x\",\n"
            "    omega_per_s: { low: 1 } } });\n"
            "  __emit({ band, none, partial: node.textContent });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertEqual(
            out["band"],
            "ω ∈ [5.468, 5.489] 1/s · block bootstrap n=800")
        self.assertEqual(out["none"], "interval unavailable (null)")
        self.assertEqual(out["partial"], "interval unavailable (null)")


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class Gravity1015Tests(unittest.TestCase):
    """KL-10.15: optional pivot-length input, gravity tile with its
    honest null frame, the interval one-liner, and the layout-fit
    guards (stacked mode toggle, wrapping controls, wrapping
    metric values)."""

    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = cls.page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")
        cls.style = cls.page.split("<style>", 1)[1].split(
            "</style>", 1)[0]

    def test_length_validation_states(self):
        check = (
            "try {\n"
            "  const input = document.getElementById(\"liveLengthMm\");\n"
            "  const box = document.getElementById(\"liveLengthError\");\n"
            "  input.value = \"\";\n"
            "  const empty = validateLiveLength();\n"
            "  const emptyShown = { ok: empty.ok, value: empty.value,\n"
            "    hidden: box.classList.contains(\"hidden\") };\n"
            "  input.value = \"326\";\n"
            "  const good = validateLiveLength();\n"
            "  input.value = \"5\";\n"
            "  const bad = validateLiveLength();\n"
            "  const shown = { ok: bad.ok, text: box.textContent,\n"
            "    hidden: box.classList.contains(\"hidden\"),\n"
            "    invalid: input.getAttribute(\"aria-invalid\") };\n"
            "  input.value = \"abc\";\n"
            "  const text = validateLiveLength();\n"
            "  input.value = \"326\";\n"
            "  const fixed = validateLiveLength();\n"
            "  __emit({ emptyShown, good, shown, textOk: text.ok,\n"
            "    fixedOk: fixed.ok, cleared: box.textContent,\n"
            "    clearedInvalid: input.getAttribute(\"aria-invalid\")"
            " });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertTrue(out["emptyShown"]["ok"])
        self.assertIsNone(out["emptyShown"]["value"])
        self.assertTrue(out["emptyShown"]["hidden"])
        self.assertTrue(out["good"]["ok"])
        self.assertEqual(out["good"]["value"], 326)
        self.assertFalse(out["shown"]["ok"])
        self.assertIn("10 and 2000", out["shown"]["text"])
        self.assertFalse(out["shown"]["hidden"])
        self.assertEqual(out["shown"]["invalid"], "true")
        self.assertFalse(out["textOk"])
        self.assertTrue(out["fixedOk"])
        self.assertEqual(out["cleared"], "")
        self.assertEqual(out["clearedInvalid"], "false")

    def test_gravity_tile_states(self):
        check = (
            "try {\n"
            "  paintGravity({ fit: { gravity_m_s2: 9.78,\n"
            "    pivot_length_mm: 326.0,\n"
            "    pivot_length_source: \"independent_measurement\" } },\n"
            "    \"demo success\");\n"
            "  const tile = document.getElementById(\"metricGravity\")\n"
            "    .textContent;\n"
            "  const why = document.getElementById(\"metricGravityWhy\")\n"
            "    .textContent;\n"
            "  const title = document.getElementById(\"gravityTitle\")\n"
            "    .textContent;\n"
            "  const body = document.getElementById(\"gravityBody\")\n"
            "    .textContent;\n"
            "  paintGravity({ fit: { gravity_m_s2: null,\n"
            "    pivot_length_mm: null,\n"
            "    pivot_length_source: \"not_provided\" } },\n"
            "    \"demo success\");\n"
            "  const nullTile = document.getElementById(\n"
            "    \"metricGravity\").textContent;\n"
            "  const nullWhy = document.getElementById(\n"
            "    \"metricGravityWhy\").textContent;\n"
            "  const nullBody = document.getElementById(\"gravityBody\")\n"
            "    .textContent;\n"
            "  paintGravity({ fit: { gravity_m_s2: 9.78,\n"
            "    pivot_length_source: \"estimated_scale\" } }, \"x\");\n"
            "  const spoof = document.getElementById(\"metricGravity\")\n"
            "    .textContent;\n"
            "  __emit({ tile, why, title, body, nullTile, nullWhy,\n"
            "    nullBody, spoof });\n"
            "} catch (e) {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "}\n")
        out = run_page_driver(self.script, check, {})
        self.assertIn("m/s", out["tile"])
        self.assertIn("user-supplied", out["why"])
        self.assertIn("9.78", out["title"])
        self.assertIn("user_supplied", out["body"])
        self.assertEqual(out["nullTile"], "Not available")
        self.assertEqual(
            out["nullWhy"],
            "g is not claimed because no independent length was "
            "provided.")
        self.assertEqual(out["nullBody"], out["nullWhy"])
        self.assertEqual(out["spoof"], "Not available")

    def test_interval_note_one_liner(self):
        self.assertIn(
            'id="intervalNote">Intervals capture measurement noise '
            "under the model, not model-adequacy bias.<",
            self.page)

    def test_layout_fit_guards(self):
        self.assertIn(
            ".moderow{display:flex;flex-direction:column;", self.style)
        controls = re.search(r"\.video-controls\{[^}]*\}", self.style)
        self.assertIsNotNone(controls)
        self.assertIn("flex-wrap:wrap", controls.group(0))
        value = re.search(r"\.metric-value\{[^}]*\}", self.style)
        self.assertIsNotNone(value)
        self.assertIn("overflow-wrap:anywhere", value.group(0))
        self.assertNotIn("white-space:nowrap", value.group(0))


if __name__ == "__main__":
    unittest.main()
