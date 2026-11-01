"""Measurement-certificate tests (KL-10.24).

Renderer: byte-identity, unknown-null paths, rejection codes
verbatim (no explanations). Route: the server-harness pattern from
tests/test_ui.py (direct handler dispatch, no sockets).
"""

import json
import os
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


if __name__ == "__main__":
    unittest.main()
