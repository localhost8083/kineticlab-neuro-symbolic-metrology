"""Measurement-certificate tests (KL-10.24).

Renderer: byte-identity, unknown-null paths, rejection codes
verbatim (no explanations). Route: the server-harness pattern from
tests/test_ui.py (direct handler dispatch, no sockets).
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from kineticlab.ui.certificate import render_certificate
from tests.contract_samples import valid_artifact_hashes, valid_result
from tests.test_ui import REPO_ROOT, dispatch

RUN_ID = "live-20261028T120000Z-deadbeef"


def rejected_result():
    """A valid unsupported_input result.v1 with one fired E-code."""
    result = valid_result(status="unsupported_input")
    result["value"] = None
    result["unit"] = None
    result["interval"] = None
    result["interval_method"] = None
    result["identifiable_quantity"] = {"name": "g/L_eff", "value": None,
                                       "unit": "1/s^2"}
    result["reject_reasons"] = [{
        "code": "E_NOT_AN_OBJECT", "field": "payload",
        "detail": "raw model output is not a JSON object"}]
    return result


def diagnostics_with_uncertainty():
    """Diagnostics doc shaped like the assembly export, with a band."""
    asm = REPO_ROOT / "fixtures" / "assembly" / "diagnostics.json"
    doc = json.loads(asm.read_text(encoding="utf-8"))
    doc["fit_uncertainty"] = {
        "method": "block_bootstrap", "seed": 7, "n_boot": 400,
        "block_frames": 27, "extended_to_contain_point": False,
        "omega_per_s": {"low": 3.8, "point": 3.87, "high": 3.95},
        "g_over_l_eff_per_s2": {"low": 14.44, "point": 15.0,
                                "high": 15.6}}
    return doc


class CertificateRenderTest(unittest.TestCase):
    def test_byte_identity(self):
        result = valid_result()
        hashes = valid_artifact_hashes()
        first = render_certificate(result, diagnostics_with_uncertainty(),
                                   hashes)
        second = render_certificate(result, diagnostics_with_uncertainty(),
                                    hashes)
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("<!DOCTYPE html>"))

    def test_copies_values_from_result(self):
        page = render_certificate(valid_result(),
                                  diagnostics_with_uncertainty(),
                                  valid_artifact_hashes())
        self.assertIn("15.0", page)
        self.assertIn("success", page)
        self.assertIn("block_bootstrap", page)
        self.assertIn("b0" * 32, page)
        self.assertIn("1/s^2", page)

    def test_diagnostics_none_renders_unknown_never_numbers(self):
        with_diag = render_certificate(valid_result(),
                                       diagnostics_with_uncertainty(),
                                       None)
        without = render_certificate(valid_result(), None, None)
        self.assertEqual(without,
                         render_certificate(valid_result(), {}, None))
        self.assertIn("unknown", without)
        self.assertNotIn("block_bootstrap", without)
        self.assertNotIn("n_boot", without)
        self.assertNotIn("400", without)
        # The populated render differs only by carrying the real band.
        self.assertNotEqual(without, with_diag)

    def test_rejection_renders_codes_verbatim_without_explanations(self):
        page = render_certificate(rejected_result(), None, None)
        self.assertIn("E_NOT_AN_OBJECT", page)
        self.assertIn("REJECTED", page)
        # No explanations: the fired detail and the page glossary
        # wording must both stay out of the certificate.
        self.assertNotIn("raw model output is not a JSON object", page)


class CertificateRouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        self.previous_key = os.environ.get("MODEL_API_KEY")
        os.environ["MODEL_API_KEY"] = "test-key"
        run_dir = self.work / "live_out" / RUN_ID
        run_dir.mkdir(parents=True)
        result = rejected_result()
        (run_dir / "result.json").write_text(
            json.dumps(result), encoding="utf-8")
        (run_dir / "diagnostics.json").write_text(
            json.dumps(diagnostics_with_uncertainty()), encoding="utf-8")

    def tearDown(self):
        if self.previous_key is None:
            os.environ.pop("MODEL_API_KEY", None)
        else:
            os.environ["MODEL_API_KEY"] = self.previous_key
        self.tmp.cleanup()

    def test_route_serves_attachment_for_stored_run(self):
        status, headers, body = dispatch(
            REPO_ROOT, self.work, "GET",
            f"/api/runs/{RUN_ID}/certificate", {})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertEqual(headers["Content-Disposition"],
                         f'attachment; filename="certificate-{RUN_ID}.html"')
        page = body.decode("utf-8")
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn("E_NOT_AN_OBJECT", page)
        self.assertIn("block_bootstrap", page)

    def test_unknown_run_id_is_registered_not_found(self):
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "GET",
            "/api/runs/live-20261028T120000Z-00000000/certificate", {})
        self.assertEqual(status, 404)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")

    def test_bad_run_id_shape_is_registered_not_found(self):
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "GET", "/api/runs/bogus/certificate", {})
        self.assertEqual(status, 404)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")

    def test_certificate_download_is_key_free(self):
        # KL-10.25: the key gates live capture, not the certificate
        # of a run's already-stored exports. Every other live export
        # stays gated.
        os.environ.pop("MODEL_API_KEY", None)
        status, headers, _ = dispatch(
            REPO_ROOT, self.work, "GET",
            f"/api/runs/{RUN_ID}/certificate", {})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Disposition"].startswith(
            "attachment"))
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "GET",
            f"/api/runs/{RUN_ID}/result.json", {})
        self.assertEqual(status, 503)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["field"], "MODEL_API_KEY")


class DemoCertificateRouteTest(unittest.TestCase):
    """KL-10.25: the pinned success demo replay serves the same
    certificate from demo_out bytes — key-free, with digests computed
    from the on-disk export bytes."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        demo_dir = self.work / "demo_out" / "success"
        demo_dir.mkdir(parents=True)
        asm = REPO_ROOT / "fixtures" / "assembly"
        for name in ("result.json", "diagnostics.json", "angles.csv",
                     "summary.md"):
            shutil.copy(asm / name, demo_dir / name)
        # The demo's own diagnostics.json carries the band, so the
        # certificate's fit_uncertainty section must render numbers —
        # not "unknown" (which is only honest when diagnostics is
        # genuinely absent).
        (demo_dir / "diagnostics.json").write_text(
            json.dumps(diagnostics_with_uncertainty()),
            encoding="utf-8")
        result = json.loads(
            (asm / "result.json").read_text(encoding="utf-8"))
        self.g_over_l = repr(result["identifiable_quantity"]["value"])

    def test_route_serves_demo_certificate_key_free(self):
        os.environ.pop("MODEL_API_KEY", None)
        status, headers, body = dispatch(
            REPO_ROOT, self.work, "GET",
            "/api/exports/success/certificate", {})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertEqual(headers["Content-Disposition"],
                         'attachment; filename="certificate-success.html"')
        page = body.decode("utf-8")
        self.assertTrue(page.startswith("<!DOCTYPE html>"))
        self.assertIn(self.g_over_l, page)
        # Diagnostics exist -> the fit_uncertainty band renders as
        # values, never as the unknown row.
        self.assertIn("block_bootstrap", page)
        self.assertNotIn("<th>fit_uncertainty</th><td>unknown</td>",
                         page)
        # The digest table hashes the on-disk exports (hex digests),
        # so the files' rows are present and deterministic.
        for name in ("angles.csv", "diagnostics.json", "result.json",
                     "summary.md"):
            with self.subTest(export=name):
                self.assertIn(f"<th>{name}</th>", page)

    def test_rejection_chain_has_no_certificate_route(self):
        status, _, raw = dispatch(
            REPO_ROOT, self.work, "GET",
            "/api/exports/rejection/certificate", {})
        self.assertEqual(status, 404)
        payload = json.loads(raw.decode("utf-8"))
        self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")

    def test_missing_demo_exports_is_registered_not_found(self):
        # No demo run yet -> the not-written-yet 404, same as exports.
        empty = tempfile.TemporaryDirectory()
        try:
            status, _, raw = dispatch(
                REPO_ROOT, Path(empty.name), "GET",
                "/api/exports/success/certificate", {})
            self.assertEqual(status, 404)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["error"]["code"], "E_MISSING_FIELD")
        finally:
            empty.cleanup()


if __name__ == "__main__":
    unittest.main()
