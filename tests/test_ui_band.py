"""KL-10.24 page-execution proofs: the drawn omega CI band and the
certificate download link.

Same pattern as tests/test_ui.py's node-executed classes (real page
script, DOM stub, real fixture payloads); kept in a separate module
only because tests/test_ui.py is already very large. The trig inside
the band envelope is scoped by the __KL_BAND_MODULE_* sentinels the
page-invariants test in tests/test_ui.py now owns.
"""

import json
import shutil
import unittest
from pathlib import Path

from tests.test_ui import REPO_ROOT, UI_DIR, run_page_driver

ASM = REPO_ROOT / "fixtures" / "assembly"

BAND = {
    "method": "block_bootstrap", "seed": 7, "n_boot": 400,
    "block_frames": 27, "extended_to_contain_point": False,
    "omega_per_s": {"low": 3.8, "point": 3.87, "high": 3.95},
    "g_over_l_eff_per_s2": {"low": 14.44, "point": 15.0, "high": 15.6},
}


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class BandChartTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")
        cls.result_text = (ASM / "result.json").read_text(
            encoding="utf-8")
        cls.diagnostics = json.loads(
            (ASM / "diagnostics.json").read_text(encoding="utf-8"))
        cls.angles_text = (ASM / "angles.csv").read_text(
            encoding="utf-8")

    def paint_check(self, diag_text, post):
        return (
            "(async () => {\n"
            "  const doc = await paintChart({ \"angles.csv\": \"u_csv\",\n"
            "    \"diagnostics.json\": \"u_diag\" }, "
            + self.result_text + ", null, \"demo success\");\n"
            + post +
            "})().catch((e) => {\n"
            "  console.error(\"KLFAIL \" + (e && e.stack || e));\n"
            "  process.exit(1);\n"
            "});\n")

    def band_state_js(self):
        return (
            "  const kids =\n"
            "    document.getElementById(\"chartSvg\").children;\n"
            "  let bandD = \"\", fittedD = \"\";\n"
            "  for (const k of kids) {\n"
            "    if (k.tag === \"path\" && k.attrs.opacity === \"0.15\")\n"
            "      bandD = k.attrs.d || \"\";\n"
            "    if (k.tag === \"path\" && k.attrs.fill === \"none\")\n"
            "      fittedD = k.attrs.d || \"\";\n"
            "  }\n"
            "  const order = bandD.length && fittedD.length\n"
            "    ? kids.findIndex((k) => k.tag === \"path\"\n"
            "      && k.attrs.opacity === \"0.15\")\n"
            "      - kids.findIndex((k) => k.tag === \"path\"\n"
            "      && k.attrs.fill === \"none\") : 0;\n")

    def test_band_draws_and_tracks_omega_bounds(self):
        diag = dict(self.diagnostics)
        diag["fit_uncertainty"] = BAND
        diag_text = json.dumps(diag)
        post = self.band_state_js() + (
            "  const aria = document.getElementById(\"chartSvg\")\n"
            "    .getAttribute(\"aria-label\");\n"
            "  const legend =\n"
            "    document.getElementById(\"bandLegendWrap\");\n"
            "  __emit({ bandLen: bandD.length,\n"
            "    bandNaN: bandD.includes(\"NaN\"),\n"
            "    order, aria,\n"
            "    legendShown: !legend.classList.contains(\"hidden\"),\n"
            "    legendText:\n"
            "      document.getElementById(\"bandLegend\")\n"
            "        .textContent });\n")
        out = run_page_driver(
            self.script, self.paint_check(diag_text, post),
            {"u_csv": self.angles_text, "u_diag": diag_text})
        self.assertGreater(out["bandLen"], 0)
        self.assertFalse(out["bandNaN"])
        # Band child index sits BEFORE the fitted-line child index.
        self.assertTrue(out["order"] < 0)
        self.assertIn("uncertainty band", out["aria"])
        self.assertTrue(out["legendShown"])
        self.assertIn("block bootstrap", out["legendText"])

    def test_band_geometry_changes_with_omega_bounds(self):
        diag = dict(self.diagnostics)
        diag["fit_uncertainty"] = BAND
        first_text = json.dumps(diag)
        wide = dict(BAND)
        wide["omega_per_s"] = {"low": 3.2, "point": 3.87, "high": 4.6}
        diag["fit_uncertainty"] = wide
        second_text = json.dumps(diag)
        post = self.band_state_js() + "  __emit({ bandD });\n"
        first = run_page_driver(
            self.script, self.paint_check(first_text, post),
            {"u_csv": self.angles_text, "u_diag": first_text})
        second = run_page_driver(
            self.script, self.paint_check(second_text, post),
            {"u_csv": self.angles_text, "u_diag": second_text})
        self.assertNotEqual(first["bandD"], second["bandD"])

    def test_no_fit_uncertainty_no_band_element(self):
        post = self.band_state_js() + (
            "  const aria = document.getElementById(\"chartSvg\")\n"
            "    .getAttribute(\"aria-label\");\n"
            "  const legend =\n"
            "    document.getElementById(\"bandLegendWrap\");\n"
            "  __emit({ bandLen: bandD.length, fittedLen: fittedD.length,\n"
            "    aria,\n"
            "    legendHidden: legend.classList.contains(\"hidden\"),\n"
            "    legendText:\n"
            "      document.getElementById(\"bandLegend\")\n"
            "        .textContent });\n")
        diag_text = json.dumps(self.diagnostics)
        out = run_page_driver(
            self.script, self.paint_check(diag_text, post),
            {"u_csv": self.angles_text, "u_diag": diag_text})
        self.assertEqual(out["bandLen"], 0)
        self.assertGreater(out["fittedLen"], 0)
        self.assertNotIn("uncertainty band", out["aria"])
        self.assertTrue(out["legendHidden"])
        self.assertEqual(out["legendText"], "")


@unittest.skipUnless(shutil.which("node"),
                     "node is required for page-execution proofs")
class CertificateLinkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        page = (UI_DIR / "index.html").read_text(encoding="utf-8")
        script = page.split("<script>", 1)[1].split("</script>", 1)[0]
        assert "__KL_LIVE_AVAILABLE__" in script
        cls.script = script.replace("__KL_LIVE_AVAILABLE__", "true")

    def link_state(self, payload_json):
        check = (
            "paintCertificateLink(" + payload_json + ");\n"
            "  const link = document.getElementById(\"certificateLink\");\n"
            "  __emit({ hidden: link.classList.contains(\"hidden\"),\n"
            "    href: link.getAttribute(\"href\") });\n")
        return run_page_driver(self.script, check, {})

    def test_live_full_payload_shows_route_link(self):
        payload = {"run_id": "live-20261028T120000Z-deadbeef",
                   "files": {"result.json":
                             "/api/runs/x/result.json"}}
        out = self.link_state(json.dumps(payload))
        self.assertFalse(out["hidden"])
        self.assertEqual(out["href"],
                         "/api/runs/live-20261028T120000Z-deadbeef"
                         "/certificate")

    def test_demo_payload_hides_link(self):
        out = self.link_state(json.dumps(
            {"chain": "success", "files": {"result.json": "x"}}))
        self.assertTrue(out["hidden"])
        out = self.link_state("null")
        self.assertTrue(out["hidden"])


if __name__ == "__main__":
    unittest.main()
