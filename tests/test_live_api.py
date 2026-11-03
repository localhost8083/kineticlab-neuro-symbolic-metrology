"""Live-route + live-panel tests (KL-8.4).

`POST /api/live` (detect/measure stages) and `GET /api/runs/<id>/<name>`
run through direct handler dispatch with a mock transport serving the
pinned live raw bytes — no network, no sockets. Covered: key gating
(503 without it), the full misuse map (400/404 with the chain's own
codes), happy detect/measure per mode, the runs allowlist (traversal
impossible), key hygiene over every response, and the live panel's
structural contract (confirm gate, prompt defaults, mm never defaulted,
MediaRecorder honesty).
"""

import io
import json
import os
import re
import tempfile
import unittest
from email.message import Message
from pathlib import Path

from kineticlab.capture import BASE_URL
from kineticlab.ui.server import _Handler
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_DIR = REPO_ROOT / "kineticlab" / "ui"
DEMO_TEST = REPO_ROOT / "Smoke" / "demo_test.mp4"
PIN_BOB = (REPO_ROOT / "fixtures" / "live"
           / "raw_bob_one_bit.txt").read_text(encoding="utf-8")
PIN_CARD = (REPO_ROOT / "fixtures" / "live"
            / "raw_card_one_bit.txt").read_text(encoding="utf-8")
SECRET = "test-key-live-api-probe-7c1d"


def pin_transport(texts):
    """Mock transport serving {prompt-substring: output_text}."""

    def send(request):
        url = request["url"]
        if url == f"{BASE_URL}/files":
            return {"status": 200, "body": b'{"id": "file-pin"}'}
        if request["method"] == "DELETE":
            return {"status": 200, "body": b"{}"}
        prompt = json.loads(request["body"].decode("utf-8"))
        text = prompt["input"][0]["content"][0]["text"]
        for key, value in texts.items():
            if key in text:
                chosen = value
                break
        else:
            chosen = ""
        payload = {"output": [{"type": "message", "content": [
            {"type": "output_text", "text": chosen}]}]}
        return {"status": 200, "body": json.dumps(payload).encode()}
    return send


FULL_TEXTS = {"ball": PIN_BOB, "card": PIN_CARD}


class _FakeServer:
    def __init__(self, repo, work, transport=None):
        self.ui_repo_root = repo
        self.ui_work_dir = work
        self.ui_transport = transport


def dispatch(repo, work, command, path, headers, body=b"",
             transport=None):
    """Drive the real handler with in-memory streams (no sockets)."""
    (work / "uploads").mkdir(parents=True, exist_ok=True)
    (work / "demo_out").mkdir(parents=True, exist_ok=True)
    (work / "live_out").mkdir(parents=True, exist_ok=True)
    handler = _Handler.__new__(_Handler)
    handler.server = _FakeServer(repo, work, transport)
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


def multipart(fields, file_data=None, filename="swing.mp4",
              content_type="video/mp4",
              boundary="live-test-boundary"):
    """Build a mixed text-field + optional file multipart body."""
    chunks = []
    for name, value in fields.items():
        chunks.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; "
             f'name="{name}"\r\n\r\n').encode("latin-1")
            + value.encode("utf-8") + b"\r\n")
    if file_data is not None:
        head = (f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="clip"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
                ).encode("latin-1")
        chunks.append(head + file_data + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("latin-1"))
    return (f"multipart/form-data; boundary={boundary}",
            b"".join(chunks))


class LiveCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        # staticmethod: a bare closure stored on the class would bind
        # `self` on instance access and break the transport signature.
        cls.transport = staticmethod(pin_transport(FULL_TEXTS))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def set_key(self, value):
        previous = os.environ.get("MODEL_API_KEY")
        if value is None:
            os.environ.pop("MODEL_API_KEY", None)
        else:
            os.environ["MODEL_API_KEY"] = value

        def restore():
            if previous is None:
                os.environ.pop("MODEL_API_KEY", None)
            else:
                os.environ["MODEL_API_KEY"] = previous

        self.addCleanup(restore)

    def get(self, path):
        return dispatch(REPO_ROOT, self.work, "GET", path, {},
                        transport=self.transport)

    def post_live(self, fields, file_data=None, **kwargs):
        content_type, body = multipart(fields, file_data, **kwargs)
        headers = {"Content-Type": content_type,
                   "Content-Length": str(len(body))}
        return dispatch(REPO_ROOT, self.work, "POST", "/api/live",
                        headers, body, transport=self.transport)

    def detect(self, mode="full", prompts=None, file_data=None):
        fields = {"stage": "detect", "mode": mode}
        fields.update(prompts or {})
        if file_data is None:
            # KL-9.6 B1: the default clip is the Smoke/ file; every
            # caller inherits this guard.
            require_smoke(DEMO_TEST)
            file_data = DEMO_TEST.read_bytes()
        return self.post_live(fields, file_data)


class LiveHomeTests(LiveCase):
    def test_page_stamps_true_with_key(self):
        self.set_key(SECRET)
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("const LIVE_AVAILABLE = true;", text)
        self.assertNotIn(SECRET, text)

    def test_page_stamps_false_without_key(self):
        self.set_key(None)
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("const LIVE_AVAILABLE = false;", text)
        self.assertIn('<section class="panel hidden" id="livePanel"',
                      text)


class LiveDetectTests(LiveCase):
    def test_no_key_is_503(self):
        self.set_key(None)
        status, _, body = self.detect()
        self.assertEqual(status, 503)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")
        self.assertEqual(payload["error"]["field"], "MODEL_API_KEY")

    def test_stage_misuse(self):
        self.set_key(SECRET)
        require_smoke(DEMO_TEST)
        status, _, body = self.post_live({"mode": "full"},
                                         DEMO_TEST.read_bytes())
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")
        self.assertEqual(payload["error"]["field"], "part:stage")
        status, _, body = self.post_live(
            {"stage": "poke", "mode": "full"}, DEMO_TEST.read_bytes())
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_BAD_ENUM")
        self.assertEqual(payload["error"]["field"], "part:stage")

    def test_mode_misuse(self):
        self.set_key(SECRET)
        require_smoke(DEMO_TEST)
        status, _, body = self.post_live({"stage": "detect"},
                                         DEMO_TEST.read_bytes())
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["field"], "part:mode")
        status, _, body = self.post_live(
            {"stage": "detect", "mode": "sideways"},
            DEMO_TEST.read_bytes())
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_BAD_ENUM")

    def test_clip_misuse(self):
        self.set_key(SECRET)
        status, _, body = self.post_live({"stage": "detect",
                                          "mode": "full"})
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["field"], "part:clip")
        status, _, body = self.post_live(
            {"stage": "detect", "mode": "full"}, b"junk-bytes"
            * 100)
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_NOT_AN_OBJECT")
        status, _, body = self.post_live(
            {"stage": "detect", "mode": "full"}, b"")
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_EMPTY_STRING")

    def test_blank_prompt_is_400(self):
        self.set_key(SECRET)
        require_smoke(DEMO_TEST)
        status, _, body = self.post_live(
            {"stage": "detect", "mode": "motion", "prompt_bob": "  "},
            DEMO_TEST.read_bytes())
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_EMPTY_STRING")

    def test_detect_full_happy(self):
        self.set_key(SECRET)
        status, _, body = self.detect(
            prompts={"prompt_bob": "red ball",
                     "prompt_card": "white paper card"})
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertRegex(payload["run_id"],
                         r"^live-\d{8}T\d{6}Z-[0-9a-f]{8}$")
        self.assertEqual(payload["filename"], "swing.mp4")
        summary = payload["summary"]
        self.assertEqual(summary["mode"], "full")
        self.assertEqual(summary["video"]["frames"], 591)
        for role in ("bob", "card"):
            self.assertGreater(summary["roles"][role]["valid"], 0)
            self.assertEqual(
                len(summary["roles"][role]["first_box"]), 4)
        self.assertNotIn(SECRET, body.decode("utf-8"))

    def test_detect_motion_happy(self):
        self.set_key(SECRET)
        status, _, body = self.detect(
            mode="motion", prompts={"prompt_bob": "red ball"})
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(sorted(payload["summary"]["roles"]), ["bob"])

    def test_detect_empty_output_is_502(self):
        self.set_key(SECRET)
        require_smoke(DEMO_TEST)
        empty = pin_transport({})
        content_type, body = multipart(
            {"stage": "detect", "mode": "motion",
             "prompt_bob": "nothing matches this"},
            DEMO_TEST.read_bytes())
        headers = {"Content-Type": content_type,
                   "Content-Length": str(len(body))}
        status, _, answered = dispatch(
            REPO_ROOT, self.work, "POST", "/api/live", headers,
            body, transport=empty)
        self.assertEqual(status, 502)
        payload = json.loads(answered.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_EMPTY_STRING")

    def test_detect_auth_failure_is_502_naming_key(self):
        self.set_key(SECRET)
        require_smoke(DEMO_TEST)

        def denied(request):
            return {"status": 401, "body": b'{"error": "bad key"}'}

        content_type, body = multipart(
            {"stage": "detect", "mode": "motion",
             "prompt_bob": "red ball"},
            DEMO_TEST.read_bytes())
        headers = {"Content-Type": content_type,
                   "Content-Length": str(len(body))}
        status, _, answered = dispatch(
            REPO_ROOT, self.work, "POST", "/api/live", headers,
            body, transport=denied)
        self.assertEqual(status, 502)
        payload = json.loads(answered.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")
        self.assertEqual(payload["error"]["field"], "MODEL_API_KEY")
        self.assertNotIn(SECRET, answered.decode("utf-8"))


class LiveMeasureTests(LiveCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.full_id = cls._run_detect(mode="full")
        cls.motion_id = cls._run_detect(mode="motion")

    @classmethod
    def _run_detect(cls, mode):
        require_smoke(DEMO_TEST)
        previous = os.environ.get("MODEL_API_KEY")
        os.environ["MODEL_API_KEY"] = SECRET
        try:
            fields = {"stage": "detect", "mode": mode,
                      "prompt_bob": "red ball"}
            if mode == "full":
                fields["prompt_card"] = "white paper card"
            content_type, body = multipart(fields,
                                           DEMO_TEST.read_bytes())
            headers = {"Content-Type": content_type,
                       "Content-Length": str(len(body))}
            status, _, answered = dispatch(
                REPO_ROOT, cls.work, "POST", "/api/live", headers,
                body, transport=cls.transport)
            assert status == 200, answered.decode("utf-8")[:500]
            return json.loads(answered.decode("utf-8"))["run_id"]
        finally:
            if previous is None:
                os.environ.pop("MODEL_API_KEY", None)
            else:
                os.environ["MODEL_API_KEY"] = previous

    def measure(self, run_id, card_width_mm=None, mode=None,
                pivot_length_mm=None, card_height_mm=None):
        fields = {"stage": "measure", "run_id": run_id}
        if card_width_mm is not None:
            fields["card_width_mm"] = card_width_mm
        if card_height_mm is not None:
            fields["card_height_mm"] = card_height_mm
        if mode is not None:
            fields["mode"] = mode
        if pivot_length_mm is not None:
            fields["pivot_length_mm"] = pivot_length_mm
        return self.post_live(fields)

    def test_no_key_is_503(self):
        self.set_key(None)
        status, _, body = self.measure(self.full_id, "85.0")
        self.assertEqual(status, 503)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["field"], "MODEL_API_KEY")

    def test_run_id_misuse(self):
        self.set_key(SECRET)
        status, _, body = self.post_live({"stage": "measure"})
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["field"], "part:run_id")
        status, _, body = self.measure("live-nope")
        self.assertEqual(status, 404)
        status, _, body = self.measure(
            "live-20200101T000000Z-00000000")
        self.assertEqual(status, 404)

    def test_mode_mismatch_is_400(self):
        self.set_key(SECRET)
        status, _, body = self.measure(self.full_id, "85.0",
                                       mode="motion")
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"],
                         "E_INCOHERENT_VALUE")

    def test_mm_misuse_is_400(self):
        self.set_key(SECRET)
        status, _, body = self.measure(self.full_id)
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")
        status, _, body = self.measure(self.full_id, "abc")
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_WRONG_TYPE")
        status, _, body = self.measure(self.motion_id, "85.0")
        self.assertEqual(status, 400)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["error"]["code"],
                         "E_INCOHERENT_VALUE")

    def test_measure_full_happy(self):
        self.set_key(SECRET)
        status, _, body = self.measure(self.full_id, "85.0",
                                       card_height_mm="54.0")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["mode"], "full")
        # KL-10.11: the bootstrap ran on the live full run.
        self.assertEqual(payload["result"]["status"], "success")
        self.assertEqual(payload["result"]["interval_method"],
                         "block_bootstrap")
        self.assertEqual(
            sorted(payload["files"]),
            ["angles.csv", "diagnostics.json", "result.json",
             "summary.md"])
        for name, href in payload["files"].items():
            with self.subTest(export=name):
                self.assertEqual(
                    href, f"/api/runs/{self.full_id}/{name}")
                get_status, headers, content = self.get(href)
                self.assertEqual(get_status, 200)
                self.assertGreater(len(content), 0)
        self.assertNotIn(SECRET, body.decode("utf-8"))

    def test_measure_motion_happy(self):
        self.set_key(SECRET)
        status, _, body = self.measure(self.motion_id)
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        self.assertEqual(payload["mode"], "motion")
        report = payload["report"]
        self.assertEqual(report["status"], "complete")
        self.assertIsNone(report["scale_mm_per_px"])
        self.assertEqual(report["reason"],
                         "no reference card: no scale")
        self.assertEqual(sorted(payload["files"]),
                         ["motion_angles.csv", "motion_report.json"])
        for name, href in payload["files"].items():
            with self.subTest(export=name):
                get_status, _, content = self.get(href)
                self.assertEqual(get_status, 200)
                self.assertGreater(len(content), 0)

    def test_measure_full_with_pivot_computes_gravity(self):
        # KL-10.17 item 2: the measure form field reaches assemble.
        self.set_key(SECRET)
        status, _, body = self.measure(self.full_id, "85.0",
                                       pivot_length_mm="500",
                                       card_height_mm="54.0")
        self.assertEqual(status, 200)
        payload = json.loads(body.decode("utf-8"))
        fit = payload["result"]["fit"]
        self.assertEqual(fit["pivot_length_mm"], 500.0)
        self.assertEqual(fit["pivot_length_source"],
                         "independent_measurement")
        self.assertAlmostEqual(fit["gravity_m_s2"],
                               fit["g_over_l_per_s2"] * 0.5)
        self.assertNotIn(SECRET, body.decode("utf-8"))

    def test_measure_invalid_pivot_fail_closed_byte_identical(self):
        # KL-10.17 item 2: an unusable pivot field is treated as
        # absent — the null-gravity path, never an error page.
        self.set_key(SECRET)
        _, _, plain_body = self.measure(self.full_id, "85.0",
                                        card_height_mm="54.0")
        plain = json.loads(plain_body.decode("utf-8"))
        self.assertIsNone(plain["result"]["fit"]["gravity_m_s2"])
        for bad in ("junk", "5", "9999"):
            with self.subTest(pivot=bad):
                status, _, body = self.measure(
                    self.full_id, "85.0", pivot_length_mm=bad,
                    card_height_mm="54.0")
                self.assertEqual(status, 200)
                payload = json.loads(body.decode("utf-8"))
                self.assertEqual(payload["result"], plain["result"])
                self.assertEqual(payload["diagnostics"],
                                 plain["diagnostics"])

    def test_measure_without_summary_is_404(self):
        self.set_key(SECRET)
        from kineticlab.capture.chain import new_run_id

        run_id = new_run_id()
        (self.work / "live_out" / run_id).mkdir(parents=True)
        status, _, body = self.measure(run_id, "85.0")
        self.assertEqual(status, 404)


class LiveRunsTests(LiveCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        require_smoke(DEMO_TEST)
        previous = os.environ.get("MODEL_API_KEY")
        os.environ["MODEL_API_KEY"] = SECRET
        try:
            from kineticlab.capture.chain import new_run_id, run_detect

            cls.run_id = new_run_id()
            run_detect(DEMO_TEST, cls.work / "live_out" / cls.run_id,
                       "motion", {"bob": "red ball"}, SECRET,
                       transport=cls.transport)
            from kineticlab.capture.chain import run_measure

            run_measure(cls.work / "live_out" / cls.run_id)
        finally:
            if previous is None:
                os.environ.pop("MODEL_API_KEY", None)
            else:
                os.environ["MODEL_API_KEY"] = previous

    def test_no_key_is_503(self):
        self.set_key(None)
        status, _, _ = self.get(
            f"/api/runs/{self.run_id}/motion_report.json")
        self.assertEqual(status, 503)

    def test_allowlist_and_traversal(self):
        self.set_key(SECRET)
        bad = [
            f"/api/runs/{self.run_id}/clip.mp4",
            f"/api/runs/{self.run_id}/raw_bob_one_bit.txt",
            f"/api/runs/{self.run_id}/../motion_report.json",
            f"/api/runs/../motion_report.json",
            f"/api/runs/{self.run_id}/",
            "/api/runs/live-nope/motion_report.json",
            f"/api/runs/{self.run_id}/result.json",
        ]
        for path in bad:
            with self.subTest(path=path):
                status, _, body = self.get(path)
                self.assertEqual(status, 404)
                payload = json.loads(body.decode("utf-8"))
                self.assertEqual(payload["error"]["code"],
                                 "E_MISSING_FIELD")

    def test_serves_bytes_with_types(self):
        self.set_key(SECRET)
        cases = [("motion_report.json", "application/json"),
                 ("motion_angles.csv", "text/csv"),
                 ("capture_metadata.json", "application/json"),
                 ("detect_summary.json", "application/json")]
        for name, content_type in cases:
            with self.subTest(export=name):
                status, headers, content = self.get(
                    f"/api/runs/{self.run_id}/{name}")
                self.assertEqual(status, 200)
                self.assertIn(content_type,
                              headers["Content-Type"])
                disk = (self.work / "live_out" / self.run_id
                        / name).read_bytes()
                self.assertEqual(content, disk)


class LivePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        cls.script = cls.page.split("<script>", 1)[1]

    def test_live_token_once(self):
        self.assertEqual(
            self.page.count("__KL_LIVE_AVAILABLE__"), 1)
        self.assertIn("const LIVE_AVAILABLE = __KL_LIVE_AVAILABLE__;",
                      self.script)

    def test_panel_hidden_without_key(self):
        self.assertIn('<section class="panel hidden" id="livePanel"',
                      self.page)
        self.assertIn("if (!LIVE_AVAILABLE) return;", self.script)
        self.assertIn('show(el("livePanel"));', self.script)

    def test_confirm_gate_present(self):
        self.assertIn(
            'if (liveState.step !== "confirmed" || !liveState.runId) '
            "return;",
            self.script)
        self.assertIn('liveState.step = "confirmed";', self.script)
        self.assertIn('if (liveState.step !== "detected"', self.script)

    def test_detect_request_fields(self):
        self.assertIn('form.append("stage", "detect");', self.script)
        self.assertIn('form.append("mode", mode);', self.script)
        self.assertIn('form.append("prompt_bob",', self.script)
        self.assertIn('form.append("prompt_card",', self.script)
        self.assertIn('form.append("clip", liveState.file,',
                      self.script)
        self.assertIn('fetch("/api/live", { method: "POST", body: form });',
                      self.script)

    def test_measure_request_fields(self):
        self.assertIn('form.append("stage", "measure");', self.script)
        self.assertIn('form.append("run_id", liveState.runId);',
                      self.script)
        self.assertIn('form.append("card_width_mm", mm);', self.script)

    def test_prompt_defaults_and_mm_never_defaulted(self):
        self.assertIn('id="livePromptBob" value="ball"',
                      self.page)
        self.assertIn('id="livePromptCard" value="card"',
                      self.page)
        match = re.search(r'<input[^>]*id="liveMm"[^>]*>', self.page)
        self.assertIsNotNone(match)
        self.assertNotIn("value=", match.group(0))
        self.assertIn("never guessed", self.page)

    def test_confirm_overlay_wiring(self):
        self.assertIn("first_box", self.script)
        self.assertIn('setAttribute("viewBox"', self.script)
        self.assertIn('addEventListener("loadeddata"', self.script)
        self.assertIn("drawLiveOverlay", self.script)

    def test_full_measure_reuses_stage(self):
        self.assertIn("paintVerdict(payload.result", self.script)
        self.assertIn("await renderDemo(payload);", self.script)
        self.assertIn("paintStepper(payload, summaryOk);", self.script)

    def test_motion_render_copies_fields(self):
        # KL-8.6: motion detail promotes to results column — chart + compact sidebar.
        # Fields now appear via renderLiveMotion() (g_over_l/period/omega via
        # report.*) and via Evidence/Provenance tabs; sidebar keeps compact line.
        for field in ("g_over_l_per_s2", "period_s", "omega_per_s"):
            with self.subTest(field=field):
                self.assertIn(field, self.script)
        self.assertIn('el("liveMotionCompact")', self.script)
        self.assertIn("renderLiveMotion", self.script)
        self.assertIn("motion_angles.csv", self.script)
        self.assertIn("parseDiagnostics(report", self.script)

    def test_recording_honesty(self):
        self.assertIn('{ mimeType: "video/mp4" }', self.script)
        self.assertIn("MediaRecorder", self.script)
        self.assertIn("getUserMedia", self.script)
        self.assertIn("cannot record MP4", self.script)
        self.assertIn("No upload attempted", self.script)
        self.assertIn("not yet sent", self.script)


if __name__ == "__main__":
    unittest.main()
