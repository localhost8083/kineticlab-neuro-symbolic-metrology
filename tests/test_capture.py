"""Live SAM capture transport tests (KL-8.4).

`run_capture` speaks the proven wire shape (Files upload -> file id,
non-streaming `/responses`, delete-after) over stdlib urllib with an
injectable transport; every test below runs a mock. Covered: exact
request shapes, verbatim saves, metadata facts, the full registered-code
error map, key hygiene (the secret never lands in outputs), and a
stdlib-only import scan over the capture package.
"""

import ast
import hashlib
import json
import sys
import tempfile
import unittest
import urllib.error
import warnings
from pathlib import Path

from kineticlab.capture import (
    BASE_URL,
    MODEL_ID,
    ROLE_FILENAMES,
    TIMEOUT_SECONDS,
    build_responses_body,
    build_upload_body,
    extract_output_text,
    run_capture,
    urllib_transport,
)
from kineticlab.contracts import ContractError
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent


def _responses_body(text):
    payload = {"output": [{"type": "message", "content": [
        {"type": "output_text", "text": text}]}]}
    return json.dumps(payload).encode("utf-8")


class MockTransport:
    """Canned wire peer: records requests, serves scripted outputs."""

    def __init__(self, texts=None, status=200, upload_id="file-test",
                 delete_status=200, raw_bodies=None):
        self.texts = texts or {}
        self.status = status
        self.upload_id = upload_id
        self.delete_status = delete_status
        self.raw_bodies = raw_bodies or {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        url = request["url"]
        if url == f"{BASE_URL}/files":
            body = self.raw_bodies.get(
                "upload", json.dumps({"id": self.upload_id}).encode())
            return {"status": self.status, "body": body}
        if request["method"] == "DELETE":
            return {"status": self.delete_status, "body": b"{}"}
        body = self.raw_bodies.get("responses")
        if body is None:
            prompt = json.loads(request["body"].decode("utf-8"))
            text = prompt["input"][0]["content"][0]["text"]
            body = _responses_body(self.texts.get(text, ""))
        return {"status": self.status, "body": body}


class CaptureTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clip = self.root / "swing.mp4"
        self.clip.write_bytes(b"\x00\x00\x00\x08ftyp" + b"v" * 256)
        self.out = self.root / "cap"

    def test_timeout_documented_value(self):
        self.assertEqual(TIMEOUT_SECONDS, 300)

    def test_multisegment_fails_fast_with_hint(self):
        # KL-9.2 item 2: a second model segment for one prompt fails
        # at detect with E_NOT_AN_OBJECT plus an actionable hint —
        # before the next role's API calls burn (roles capture in
        # sorted order, so a bad bob saves card's upload/responses/
        # delete). The offending bytes stay on disk verbatim.
        require_smoke(
            REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt")
        line = (REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt"
                ).read_text(encoding="utf-8").splitlines()[0]
        bad = line + "|><|box;x1=936;y1=503;x2=995;y2=719;c=0.75"
        transport = MockTransport(
            texts={"red ball": bad + "\n",
                   "white paper card": "<0f>box"})
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball",
                                    "card": "white paper card"},
                        self.out, "KEY", transport=transport)
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        error = raised.exception.errors[0]
        self.assertEqual(error.field, "line 1")
        self.assertIn("multiple objects for this prompt", error.message)
        self.assertIn("more specific bob prompt", error.message)
        self.assertIn("Motion mode", error.message)
        saved = (self.out / ROLE_FILENAMES["bob"]).read_bytes()
        self.assertEqual(saved, (bad + "\n").encode("utf-8"))
        self.assertEqual(len(transport.requests), 3)
        bodies = [item.get("body") or b""
                  for item in transport.requests]
        self.assertFalse(any(b"white paper card" in body
                             for body in bodies))

    def test_request_shape(self):
        transport = MockTransport(texts={"red ball": "<0f>box",
                                         "white paper card": "<0f>box"})
        run_capture(self.clip, {"bob": "red ball",
                                "card": "white paper card"},
                    self.out, "KEY", transport=transport)
        self.assertEqual(len(transport.requests), 6)
        uploads = [item for item in transport.requests
                   if item["url"] == f"{BASE_URL}/files"]
        answers = [item for item in transport.requests
                   if item["url"] == f"{BASE_URL}/responses"]
        deletes = [item for item in transport.requests
                   if item["method"] == "DELETE"]
        self.assertEqual((len(uploads), len(answers), len(deletes)),
                         (2, 2, 2))
        for item in transport.requests:
            self.assertEqual(item["headers"]["Authorization"],
                             "Bearer KEY")
        upload = uploads[0]
        self.assertEqual(upload["method"], "POST")
        self.assertIn("multipart/form-data; boundary=",
                      upload["headers"]["Content-Type"])
        self.assertIn(b'name="purpose"', upload["body"])
        self.assertIn(b"user_data", upload["body"])
        self.assertIn(self.clip.read_bytes(), upload["body"])
        answered = answers[0]
        self.assertEqual(answered["method"], "POST")
        self.assertEqual(answered["headers"]["Content-Type"],
                         "application/json")
        payload = json.loads(answered["body"].decode("utf-8"))
        self.assertEqual(payload["model"], MODEL_ID)
        self.assertEqual(payload["stream"], False)
        self.assertEqual(
            payload["metadata"],
            {"include_confidence": "true", "mask_encoding": "one_bit"})
        content = payload["input"][0]["content"]
        self.assertEqual(payload["input"][0]["role"], "user")
        self.assertEqual(content[0],
                         {"type": "input_text", "text": "red ball"})
        self.assertEqual(content[1],
                         {"type": "input_video", "file_id": "file-test"})
        self.assertEqual(deletes[0]["url"],
                         f"{BASE_URL}/files/file-test")
        self.assertIsNone(deletes[0]["body"])

    def test_roles_capture_in_sorted_order(self):
        transport = MockTransport(texts={"b": "t1", "c": "t2"})
        run_capture(self.clip, {"card": "c", "bob": "b"}, self.out,
                    "KEY", transport=transport)
        prompts = [json.loads(item["body"].decode("utf-8"))
                   ["input"][0]["content"][0]["text"]
                   for item in transport.requests
                   if item["url"] == f"{BASE_URL}/responses"]
        self.assertEqual(prompts, ["b", "c"])

    def test_verbatim_save_and_metadata(self):
        text = "<0f>box;mask|x;y;c;data=3,2,!!!!!../../|<"
        transport = MockTransport(texts={"red ball": text})
        out = run_capture(self.clip, {"bob": "red ball"}, self.out,
                          "KEY", transport=transport, mode="motion")
        raw = Path(out["raw_paths"]["bob"])
        self.assertEqual(raw.name, ROLE_FILENAMES["bob"])
        self.assertEqual(raw.read_bytes(), text.encode("utf-8"))
        self.assertEqual(out["clip_sha256"],
                         hashlib.sha256(self.clip.read_bytes())
                         .hexdigest())
        metadata = json.loads(
            Path(out["metadata_path"]).read_text(encoding="utf-8"))
        self.assertEqual(metadata["model"], MODEL_ID)
        self.assertEqual(metadata["endpoint"], BASE_URL)
        self.assertEqual(metadata["mask_encoding"], "one_bit")
        self.assertTrue(metadata["include_confidence"])
        self.assertFalse(metadata["stream"])
        self.assertEqual(metadata["mode"], "motion")
        self.assertEqual(metadata["prompts"], {"bob": "red ball"})
        self.assertEqual(metadata["input_clip"]["filename"],
                         "swing.mp4")
        self.assertEqual(metadata["input_clip"]["sha256"],
                         out["clip_sha256"])
        self.assertEqual(metadata["input_clip"]["bytes"], 264)
        artifact = metadata["artifacts"][ROLE_FILENAMES["bob"]]
        self.assertEqual(artifact["bytes"], len(text.encode("utf-8")))
        self.assertEqual(artifact["sha256"],
                         hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(artifact["upload_id"], "file-test")
        self.assertTrue(artifact["upload_deleted_after"])
        self.assertTrue(metadata["uploads_deleted_after"])
        self.assertIsNone(metadata["usage"])
        self.assertEqual(out["metadata"], metadata)

    def test_key_never_in_outputs(self):
        secret = "test-key-live-capture-probe-4b2a"
        transport = MockTransport(texts={"red ball": "<0f>t"})
        out = run_capture(self.clip, {"bob": "red ball"}, self.out,
                          secret, transport=transport, mode="motion")
        blob = json.dumps(out, sort_keys=True)
        self.assertNotIn(secret, blob)
        for path in self.out.iterdir():
            self.assertNotIn(secret, path.read_text(encoding="utf-8"))

    def test_empty_output_is_registered_rejection(self):
        transport = MockTransport(texts={"red ball": "   "})
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out,
                        "KEY", transport=transport)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_EMPTY_STRING")
        self.assertEqual(error.field, "output_text:bob")

    def test_auth_rejection_names_key(self):
        cases = [("upload", 401), ("responses", 403)]
        for endpoint, status in cases:
            with self.subTest(endpoint=endpoint, status=status):
                def selective(request, endpoint=endpoint,
                              status=status):
                    if endpoint == "upload" and request["url"].endswith(
                            "/files"):
                        return {"status": status,
                                "body": b'{"error": "bad key"}'}
                    if endpoint == "responses" and request["url"].endswith(
                            "/responses"):
                        return {"status": status,
                                "body": b'{"error": "bad key"}'}
                    if request["method"] == "DELETE":
                        return {"status": 200, "body": b"{}"}
                    if request["url"].endswith("/files"):
                        return {"status": 200,
                                "body": b'{"id": "file-test"}'}
                    return {"status": 200,
                            "body": _responses_body("<0f>t")}

                with self.assertRaises(ContractError) as raised:
                    run_capture(self.clip, {"bob": "red ball"},
                                self.out, "KEY",
                                transport=selective)
                error = raised.exception.errors[0]
                self.assertEqual(error.code, "E_MISSING_FIELD")
                self.assertEqual(error.field, "MODEL_API_KEY")
                self.assertIn(str(status), error.message)

    def test_server_error_names_absent_text(self):
        transport = MockTransport(
            texts={"red ball": "<0f>t"},
            raw_bodies={"responses": b'{"error": {"message": "down"}}'})
        transport.status = 200

        def failing(request):
            if request["url"].endswith("/responses"):
                return {"status": 500,
                        "body": b'{"error": {"message": "down"}}'}
            return transport(request)

        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out,
                        "KEY", transport=failing)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "output_text")
        self.assertIn("500", error.message)
        self.assertIn("down", error.message)

    def test_malformed_response_bytes(self):
        transport = MockTransport(
            raw_bodies={"responses": b"not json {{{"})
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out,
                        "KEY", transport=transport)
        self.assertEqual(raised.exception.errors[0].code,
                         "E_MALFORMED_JSON")

    def test_response_wrong_shape(self):
        transport = MockTransport(raw_bodies={"responses": b"[1, 2]"})
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out,
                        "KEY", transport=transport)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_WRONG_TYPE")
        self.assertEqual(error.field, "response")

    def test_response_without_output_text(self):
        transport = MockTransport(
            raw_bodies={"responses": b'{"output": []}'})
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out,
                        "KEY", transport=transport)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "output_text")

    def test_missing_upload_id(self):
        transport = MockTransport(raw_bodies={"upload": b"{}"})
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out,
                        "KEY", transport=transport)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "upload_id")

    def test_delete_failure_recorded_not_raised(self):
        transport = MockTransport(texts={"red ball": "<0f>t"},
                                  delete_status=500)
        out = run_capture(self.clip, {"bob": "red ball"}, self.out,
                          "KEY", transport=transport)
        artifact = out["metadata"]["artifacts"][ROLE_FILENAMES["bob"]]
        self.assertFalse(artifact["upload_deleted_after"])
        self.assertEqual(artifact["delete_status"], 500)
        self.assertFalse(out["metadata"]["uploads_deleted_after"])
        self.assertTrue(Path(out["raw_paths"]["bob"]).is_file())

    def test_output_text_segments_concatenate(self):
        payload = {"output": [
            {"type": "message", "content": [
                {"type": "output_text", "text": "<0f>a"},
                {"type": "output_text", "text": "<1f>b"}]},
            {"type": "reasoning", "content": [
                {"type": "output_text", "text": "<2f>c"}]}]}
        self.assertEqual(extract_output_text(payload, "bob"),
                         "<0f>a<1f>b<2f>c")
        self.assertEqual(
            extract_output_text({"output_text": "<0f>z"}, "bob"),
            "<0f>z")

    def test_blank_inputs_rejected(self):
        transport = MockTransport(texts={"red ball": "<0f>t"})
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out, "")
        self.assertEqual(raised.exception.errors[0].code,
                         "E_MISSING_FIELD")
        self.assertEqual(raised.exception.errors[0].field,
                         "MODEL_API_KEY")
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "  "}, self.out, "KEY",
                        transport=transport)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_EMPTY_STRING")
        self.assertEqual(error.field, "prompt:bob")
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"ball": "red ball"}, self.out,
                        "KEY", transport=transport)
        self.assertEqual(raised.exception.errors[0].code, "E_BAD_ENUM")
        with self.assertRaises(ContractError) as raised:
            run_capture(self.clip, {"bob": "red ball"}, self.out,
                        "KEY", transport=transport, mode="sideways")
        self.assertEqual(raised.exception.errors[0].code, "E_BAD_ENUM")
        with self.assertRaises(ContractError) as raised:
            run_capture(self.root / "absent.mp4", {"bob": "red ball"},
                        self.out, "KEY", transport=transport)
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "clip_path")
        empty = self.root / "empty.mp4"
        empty.write_bytes(b"")
        with self.assertRaises(ContractError) as raised:
            run_capture(empty, {"bob": "red ball"}, self.out, "KEY",
                        transport=transport)
        self.assertEqual(raised.exception.errors[0].code,
                         "E_EMPTY_STRING")
        with self.assertRaises(ContractError) as raised:
            run_capture(self.root, {"bob": "red ball"}, self.out,
                        "KEY", transport=transport)
        self.assertEqual(raised.exception.errors[0].code,
                         "E_WRONG_TYPE")

    def test_network_failure_maps_to_missing_response(self):
        import urllib.request

        real = urllib.request.urlopen

        def failing(*args, **kwargs):
            raise urllib.error.URLError("connection refused")

        urllib.request.urlopen = failing
        self.addCleanup(setattr, urllib.request, "urlopen", real)
        with self.assertRaises(ContractError) as raised:
            urllib_transport({"method": "POST", "url": BASE_URL,
                              "headers": {}, "body": b"{}"})
        error = raised.exception.errors[0]
        self.assertEqual(error.code, "E_MISSING_FIELD")
        self.assertEqual(error.field, "api_response")

    def test_http_error_status_passthrough(self):
        import urllib.request

        real = urllib.request.urlopen

        class FakeError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__(BASE_URL, 429, "slow", {}, None)
                self._payload = b'{"error": "slow"}'

            def read(self, *args, **kwargs):
                return self._payload

        def raising(*args, **kwargs):
            raise FakeError()

        urllib.request.urlopen = raising
        self.addCleanup(setattr, urllib.request, "urlopen", real)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            answered = urllib_transport(
                {"method": "POST", "url": BASE_URL,
                 "headers": {}, "body": b"{}"})
        self.assertEqual(answered["status"], 429)
        self.assertEqual(answered["body"], b'{"error": "slow"}')

    def test_upload_body_builder(self):
        content_type, body = build_upload_body(b"BYTES", "clip.mp4")
        self.assertTrue(content_type.startswith(
            "multipart/form-data; boundary="))
        self.assertIn(b'name="purpose"', body)
        self.assertIn(b"user_data", body)
        self.assertIn(b"BYTES", body)
        self.assertIn(b'filename="clip.mp4"', body)

    def test_responses_body_builder(self):
        payload = json.loads(
            build_responses_body("red ball", "file-9").decode("utf-8"))
        self.assertEqual(payload["model"], MODEL_ID)
        self.assertFalse(payload["stream"])
        content = payload["input"][0]["content"]
        self.assertEqual(content[0]["text"], "red ball")
        self.assertEqual(content[1]["file_id"], "file-9")

    def test_capture_package_is_stdlib_only(self):
        allowed = set(sys.stdlib_module_names) | {"kineticlab"}
        package = REPO_ROOT / "kineticlab" / "capture"
        for path in sorted(package.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name.split(".")[0]
                             for item in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 \
                        and node.module:
                    names = [node.module.split(".")[0]]
                else:
                    continue
                for name in names:
                    with self.subTest(file=path.name, module=name):
                        self.assertIn(name, allowed)


if __name__ == "__main__":
    unittest.main()
