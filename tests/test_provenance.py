"""Provenance artifact-hash tests (KL-7.5 F6).

Covers: the additive ``artifact_hashes`` object (strict 64-char
lowercase hex per digest, null when an artifact was unreadable);
required at the result boundary (missing/null rejected);
optional elsewhere with legacy fixtures round-tripping
byte-identically (key omitted when None); and the live
run-metadata digest/byte-count pin test.
"""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from tests import require_smoke
from tests.contract_samples import (
    valid_artifact_hashes,
    valid_media,
    valid_result,
)
from kineticlab.contracts import (
    ContractError,
    MediaMetadata,
    ResultContract,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_DIR = REPO_ROOT / "fixtures" / "live"


class ArtifactHashesParserTests(unittest.TestCase):
    def test_valid_hashes_parse_at_result(self):
        record = ResultContract.from_dict(valid_result())
        hashes = record.provenance.artifact_hashes
        self.assertIsNotNone(hashes)
        assert hashes is not None
        self.assertEqual(hashes.raw_bob_sha256, "b0" * 32)
        self.assertEqual(hashes.geometry_report_sha256, "e0" * 32)

    def test_missing_at_result_rejected(self):
        data = valid_result()
        del data["provenance"]["artifact_hashes"]
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_MISSING_FIELD", raised.exception.codes)

    def test_null_at_result_rejected(self):
        data = valid_result()
        data["provenance"]["artifact_hashes"] = None
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_NULL_NOT_ALLOWED", raised.exception.codes)

    def test_optional_elsewhere(self):
        record = MediaMetadata.from_dict(valid_media())
        self.assertIsNone(record.provenance.artifact_hashes)
        self.assertNotIn("artifact_hashes", record.to_dict()["provenance"])

    def test_present_null_elsewhere_accepted(self):
        data = valid_media()
        data["provenance"]["artifact_hashes"] = None
        record = MediaMetadata.from_dict(data)
        self.assertIsNone(record.provenance.artifact_hashes)

    def test_null_digests_allowed(self):
        # Unknown stays null: unreadable artifacts hash to nothing.
        data = valid_result()
        data["provenance"]["artifact_hashes"] = {
            key: None for key in valid_artifact_hashes()}
        record = ResultContract.from_dict(data)
        hashes = record.provenance.artifact_hashes
        self.assertIsNotNone(hashes)
        assert hashes is not None
        self.assertIsNone(hashes.raw_bob_sha256)

    def test_malformed_digests_rejected(self):
        for key in valid_artifact_hashes():
            for bad in ("abc", "B0" * 32, "zz" * 32, "b0" * 31 + "b1x"):
                with self.subTest(key=key, bad=bad[:8]):
                    data = valid_result()
                    data["provenance"]["artifact_hashes"][key] = bad
                    with self.assertRaises(ContractError) as raised:
                        ResultContract.from_dict(data)
                    self.assertIn("E_BAD_SHA256",
                                  raised.exception.codes)

    def test_wrong_type_rejected(self):
        data = valid_result()
        data["provenance"]["artifact_hashes"] = "b0" * 32
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_WRONG_TYPE", raised.exception.codes)

    def test_extra_key_rejected(self):
        data = valid_result()
        data["provenance"]["artifact_hashes"]["extra_sha256"] = "a0" * 32
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_UNEXPECTED_FIELD", raised.exception.codes)

    def test_missing_subkey_rejected(self):
        data = valid_result()
        del data["provenance"]["artifact_hashes"]["raw_card_sha256"]
        with self.assertRaises(ContractError) as raised:
            ResultContract.from_dict(data)
        self.assertIn("E_MISSING_FIELD", raised.exception.codes)

    def test_to_dict_round_trip(self):
        record = ResultContract.from_dict(valid_result())
        text = json.dumps(record.to_dict())
        self.assertEqual(ResultContract.from_dict(json.loads(text)),
                         record)
        self.assertEqual(
            record.to_dict()["provenance"]["artifact_hashes"],
            valid_artifact_hashes())


class LiveMetadataTests(unittest.TestCase):
    def load_metadata(self):
        return json.loads(
            (LIVE_DIR / "run_metadata.json").read_text(encoding="utf-8"))

    def test_artifact_digests_and_bytes_match(self):
        metadata = self.load_metadata()
        self.assertIn("artifacts", metadata)
        for name, artifact in metadata["artifacts"].items():
            with self.subTest(artifact=name):
                path = LIVE_DIR / name
                data = path.read_bytes()
                self.assertEqual(
                    hashlib.sha256(data).hexdigest(), artifact["sha256"])
                self.assertEqual(path.stat().st_size, artifact["bytes"])

    # KL-9.6 B1: split out of the digest test above — the input clip
    # lives under gitignored Smoke/, so fresh clones skip this half
    # while the committed-artifact half above still runs.
    def test_input_clip_digest_matches_pin(self):
        metadata = self.load_metadata()
        clip = metadata["input_clip"]
        clip_path = REPO_ROOT / clip["path"]
        require_smoke(clip_path)
        clip_bytes = clip_path.read_bytes()
        self.assertEqual(hashlib.sha256(clip_bytes).hexdigest(),
                         clip["sha256"])


if __name__ == "__main__":
    unittest.main()
