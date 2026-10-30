"""one_bit mask decode tests (KL-3.2).

The production decode path (`decode_mask_data` -> `decode_raster` ->
`check_canonical` -> `raster_geometry`) must decode all 959 real
`Smoke/results/*_raw.txt` payloads to binary box-relative rasters
with canonical round-trip, derive mask-only area/centroid, and fail
malformed input with exact registered codes naming file+line.

Pins below were measured from the decode on 2026-10-27 (first ball
frame: mask 123x93, area 9566, frame centroid =
bbox corner + local means). They act as regression pins: identical
bytes must yield identical geometry. No value here is authored —
every number comes out of the decoder.
"""

import tempfile
import unittest
from pathlib import Path

from kineticlab.contracts import ContractError
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture
from kineticlab.observation.mask_codec import (
    check_canonical,
    decode_raster,
    encode_raster_stream,
    raster_geometry,
)
from kineticlab.observation.mask_framing import decode_mask_data, pack_body
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_FILES = (
    "test_3_yellow_ball_raw.txt",
    "test_3_white_card_raw.txt",
    "card_raw.txt",
    "red_sphere_raw.txt",
    "real_white_paper_raw.txt",
)
BALL_RAW = REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt"

FIRST_BALL_AREA = 9566
FIRST_BALL_LOCAL = (60.76740539410412, 45.682103282458705)
FIRST_BALL_FRAME = (565.7674053941041, 366.6821032824587)


def iter_corpus():
    require_smoke(*(REPO_ROOT / "Smoke/results" / name
                    for name in RAW_FILES))
    for name in RAW_FILES:
        path = REPO_ROOT / "Smoke/results" / name
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            yield path, line_no, line.split(";data=", 1)[1][:-2]


class CorpusDecodeTest(unittest.TestCase):
    def test_all_payloads_decode_with_canonical_round_trip(self):
        count = 0
        for path, line_no, data in iter_corpus():
            ref = f"{path}#L{line_no}"
            framing = decode_mask_data(data, ref=ref)
            raster = decode_raster(framing.opaque, framing.width,
                                   framing.height, ref=ref)
            self.assertEqual(len(raster), framing.width * framing.height)
            self.assertLessEqual(set(raster), {0, 1})
            check_canonical(framing.payload, raster, framing.width,
                            framing.height, ref=ref)
            area, _, _ = raster_geometry(raster, framing.width, framing.height,
                                         x1=0.0, y1=0.0, ref=ref)
            self.assertGreater(area, 0)
            count += 1
        self.assertEqual(count, 959)

    def test_first_ball_frame_pins(self):
        require_smoke(BALL_RAW)
        line = BALL_RAW.read_text(encoding="utf-8").splitlines()[0]
        framing = decode_mask_data(line.split(";data=", 1)[1][:-2], ref="pin")
        self.assertEqual((framing.width, framing.height), (123, 93))
        raster = decode_raster(framing.opaque, framing.width, framing.height,
                               ref="pin")
        area, local_x, local_y = raster_geometry(
            raster, framing.width, framing.height, x1=0.0, y1=0.0, ref="pin")
        self.assertEqual(area, FIRST_BALL_AREA)
        self.assertEqual((local_x, local_y), FIRST_BALL_LOCAL)
        _, frame_x, frame_y = raster_geometry(
            raster, framing.width, framing.height,
            x1=505.0, y1=321.0, ref="pin")
        self.assertEqual((frame_x, frame_y), FIRST_BALL_FRAME)


class CodecFailureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(BALL_RAW)
        cls.line = BALL_RAW.read_text(encoding="utf-8").splitlines()[0]
        cls.data = cls.line.split(";data=", 1)[1][:-2]
        _, _, cls.payload = cls.data.split(",", 2)
        framing = decode_mask_data(cls.data, ref="setup")
        cls.width = framing.width
        cls.height = framing.height
        cls.raster = decode_raster(framing.opaque, framing.width,
                                   framing.height, ref="setup")

    def test_truncated_body_rejected(self):
        short = self.payload[:-5]
        with self.assertRaises(ContractError) as raised:
            decode_mask_data(f"93,123,{short}", ref="some/path#L7")
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertIn("some/path#L7", raised.exception.errors[0].message)

    def test_wrong_declared_length_rejected(self):
        bad = self.payload[:4] + "#" + self.payload[5:]
        with self.assertRaises(ContractError) as raised:
            decode_mask_data(f"93,123,{bad}", ref="some/path#L7")
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertIn("some/path#L7", raised.exception.errors[0].message)

    def test_non_canonical_raster_rejected(self):
        flipped = bytearray(self.raster)
        flipped[1000] ^= 1
        with self.assertRaises(ContractError) as raised:
            check_canonical(self.payload, bytes(flipped), self.width,
                            self.height, ref="some/path#L7")
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        for error in raised.exception.errors:
            self.assertEqual(error.field, "mask_reference")
            self.assertIn("some/path#L7", error.message)
            self.assertIn("not canonical", error.message)

    def test_invalid_character_rejected(self):
        bad = self.payload[:20] + "|" + self.payload[21:]
        with self.assertRaises(ContractError) as raised:
            decode_mask_data(f"93,123,{bad}", ref="some/path#L7")
        self.assertEqual(raised.exception.codes, ["E_BAD_ENUM"])
        self.assertIn("some/path#L7", raised.exception.errors[0].message)

    def test_lossless_marker_rejected(self):
        with self.assertRaises(ContractError) as raised:
            decode_mask_data(f"93,123,~" + self.payload[1:], ref="some/path#L7")
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        self.assertIn("some/path#L7", raised.exception.errors[0].message)

    def test_zero_mask_rejected(self):
        with self.assertRaises(ContractError) as raised:
            raster_geometry(bytes(self.width * self.height), self.width,
                            self.height, x1=0.0, y1=0.0, ref="some/path#L7")
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertIn("some/path#L7", raised.exception.errors[0].message)

    def test_exhausted_stream_rejected(self):
        framing = decode_mask_data(self.data, ref="setup")
        with self.assertRaises(ContractError) as raised:
            decode_raster(framing.opaque[:10], framing.width, framing.height,
                          ref="some/path#L7")
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertIn("some/path#L7", raised.exception.errors[0].message)

class CodecSyntheticTest(unittest.TestCase):
    # KL-9.6 B1: pure-synthetic mirror-encoder check, moved out of
    # CodecFailureTest so it still runs on clones without Smoke/.
    def test_synthetic_raster_round_trip(self):
        # The mirror encoder must invert the decoder on non-corpus bits.
        bits = bytes((index * 7 + 3) % 2 for index in range(10 * 10))
        stream = encode_raster_stream(bits, 10, 10)
        self.assertEqual(decode_raster(stream, 10, 10, ref="synthetic"), bits)
        self.assertEqual(
            encode_raster_stream(
                decode_raster(stream, 10, 10, ref="synthetic"), 10, 10), stream)


class AdapterDecodeFailureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(REPO_ROOT / "Smoke/test_3.mp4", BALL_RAW)
        cls.table = extract_frame_records(REPO_ROOT / "Smoke/test_3.mp4")
        cls.line = BALL_RAW.read_text(encoding="utf-8").splitlines()[0]

    def parse_text(self, payload_text):
        head, data = self.line.split(";data=", 1)
        height, width, _ = data[:-2].split(",", 2)
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                             mode="w", encoding="utf-8")
        handle.write(f"{head};data={height},{width},{payload_text}|>\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def assert_file_fails(self, payload_text, codes):
        path = self.parse_text(payload_text)
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(path, object_role="bob", object_id="bob-1",
                              frame_table=self.table)
        self.assertEqual(raised.exception.codes, codes)
        for error in raised.exception.errors:
            self.assertIn(f"{path}#L1", error.message)

    def test_corrupt_payload_fails_file_with_line(self):
        _, _, payload = self.line.split(";data=", 1)[1][:-2].split(",", 2)
        bad = payload[:4] + "#" + payload[5:]
        self.assert_file_fails(bad, ["E_INCOHERENT_VALUE"])

    def test_zero_mask_fails_file_with_line(self):
        stream = encode_raster_stream(bytes(123 * 93), 123, 93)
        self.assert_file_fails("!" + pack_body(stream), ["E_INCOHERENT_VALUE"])

    def test_lossless_payload_fails_file_with_line(self):
        _, _, payload = self.line.split(";data=", 1)[1][:-2].split(",", 2)
        self.assert_file_fails("~" + payload[1:], ["E_NOT_AN_OBJECT"])


if __name__ == "__main__":
    unittest.main()
