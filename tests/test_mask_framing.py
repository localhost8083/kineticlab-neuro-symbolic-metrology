"""Mask payload framing tests (KL-3.2, transport layer only).

`decode_mask_data` must validate the proven outer framing of every
``data=d0,d1,payload`` mask field in the real `Smoke/results/*_raw.txt`
fixtures (959 payloads, 5 files) and reject malformed payloads with
exact registered codes naming file+line.

Scope boundary (deliberate): the inner byte-codec of the opaque run
is UNKNOWN (~75 exact-match oracle variants over the decoded bytes
found no RLE-sum, compression, XOR, polygon, or bit-field structure),
so these tests assert framing + failure behavior only. No test here
derives centroid/area (that would be guessing), and adapter records
stay valid=false + `W_PARTIAL_OBSERVATION` (covered by
`tests/test_observation.py`, which must stay green unchanged).

Structural pins were measured from the Smoke/ bytes on 2026-10-27
(959/959 exact for every framing law). They act as regression pins:
identical bytes must yield identical framing.
"""

import tempfile
import unittest
from pathlib import Path

from kineticlab.contracts import ContractError
from kineticlab.ingest import extract_frame_records
from kineticlab.observation import parse_raw_fixture
from kineticlab.observation.mask_framing import MASK_ALPHABET, decode_mask_data
from tests import require_smoke

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_FILES = (
    "test_3_yellow_ball_raw.txt",
    "test_3_white_card_raw.txt",
    "card_raw.txt",
    "red_sphere_raw.txt",
    "real_white_paper_raw.txt",
)

ALPHABET_LITERAL = ("!#$%&'()*+-./0123456789:=?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[]^_"
                    "`abcdefghijklmnopqrstuvwxyz{")
"""The exact 85 payload chars observed (ASCII 33..123 minus `" , ; < > \\`)."""

EXCLUDED_LITERAL = '",;<>\\'

FIRST_BALL_OPAQUE_HEX = (
    "5c5a42d2d0ae1f1c608146fb5887c7d3dbda722fe10356778807a3104106711b1bc336c"
    "0f7200b7062e01c923c3beb3e7d776c5e6a97f6eef78da712c74b2fafa20b820b2ece83d"
    "3c12e00"
)
"""First ball line (`<0f>`, 93x123) opaque bytes: decode-arithmetic pin."""


def iter_corpus():
    """Yield (path, line_no, x1, y1, x2, y2, data_value) for all 959 lines."""
    require_smoke(*(REPO_ROOT / "Smoke/results" / name
                    for name in RAW_FILES))
    for name in RAW_FILES:
        path = REPO_ROOT / "Smoke/results" / name
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            box, mask = line.split("|><|")
            fields = dict(token.split("=", 1) for token in box.split("<|", 1)[1].split(";")[1:])
            yield (path, line_no, int(fields["x1"]), int(fields["y1"]),
                   int(fields["x2"]), int(fields["y2"]),
                   mask.split(";data=", 1)[1][:-2])


class FramingLawTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = list(iter_corpus())

    def test_grouping_proof_offset_1_only(self):
        # Independent re-derivation (inline base-85, not the module's):
        # grouping at absolute offset 1 fits u32 on all 959 payloads,
        # while offsets 0/2/3/4 overflow on hundreds. This discriminator
        # is a property of the bytes, and it selects the grouping.
        values = {char: rank for rank, char in enumerate(sorted(ALPHABET_LITERAL))}

        def overflows(payload, offset):
            text = payload[offset:]
            for start in range(0, len(text) - 4, 5):
                total = 0
                for char in text[start:start + 5]:
                    total = total * 85 + values[char]
                if total >= 2 ** 32:
                    return True
            return False

        payloads = [data.split(",", 2)[2] for *_, data in self.rows]
        self.assertEqual(len(payloads), 959)
        self.assertEqual(sum(1 for payload in payloads if overflows(payload, 1)), 0)
        for offset in (0, 2, 3, 4):
            # Observed 484/430/444/465; assert well above zero.
            self.assertGreater(
                sum(1 for payload in payloads if overflows(payload, offset)), 400)

    def test_corpus_validates_with_bbox_dims(self):
        count = 0
        for path, line_no, x1, y1, x2, y2, data in self.rows:
            framing = decode_mask_data(data, ref=f"{path}#L{line_no}")
            # Evidence order is d0=rows(height), d1=cols(width).
            self.assertEqual(framing.height, y2 - y1 + 1)
            self.assertEqual(framing.width, x2 - x1 + 1)
            # Corpus-observed opaque lengths (content-dependent, 49..199).
            self.assertGreaterEqual(len(framing.opaque), 49)
            self.assertLessEqual(len(framing.opaque), 199)
            count += 1
        self.assertEqual(count, 959)

    def test_first_ball_blob_pin(self):
        path = REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt"
        line = path.read_text(encoding="utf-8").splitlines()[0]
        framing = decode_mask_data(line.split(";data=", 1)[1][:-2], ref="pin")
        self.assertEqual((framing.height, framing.width), (93, 123))
        self.assertEqual(framing.opaque.hex(), FIRST_BALL_OPAQUE_HEX)

    def test_x_and_length_laws_corpus(self):
        values = {char: rank for rank, char in enumerate(sorted(ALPHABET_LITERAL))}
        for path, line_no, *_rest, data in self.rows:
            payload = data.split(",", 2)[2]
            self.assertNotEqual(len(payload) % 5, 2)
            self.assertEqual(values[payload[4]], (len(payload) - 5) // 107)


class _FramingAsserts:
    # KL-9.6 B1: shared failure-assertion mixin (no TestCase base,
    # so discovery never collects it) for the Smoke-backed failure
    # class and the Smoke-free synthetic class below.

    def assert_fails(self, data_value, codes, ref="some/path#L1"):
        with self.assertRaises(ContractError) as raised:
            decode_mask_data(data_value, ref=ref)
        self.assertEqual(raised.exception.codes, codes)
        for error in raised.exception.errors:
            self.assertEqual(error.field, "mask_reference")
            self.assertIn(ref, error.message)


class FramingFailureTest(_FramingAsserts, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(
            REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt")
        path = REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt"
        line = path.read_text(encoding="utf-8").splitlines()[0]
        cls.data = line.split(";data=", 1)[1][:-2]
        _, _, cls.payload = cls.data.split(",", 2)

    def test_missing_dims_rejected(self):
        self.assert_fails(self.payload, ["E_NOT_AN_OBJECT"])
        self.assert_fails("93", ["E_NOT_AN_OBJECT"])

    def test_non_integer_dims_rejected(self):
        self.assert_fails(f"H,123,{self.payload}", ["E_WRONG_TYPE"])
        self.assert_fails(f"93,W,{self.payload}", ["E_WRONG_TYPE"])

    def test_non_positive_dims_rejected(self):
        self.assert_fails(f"0,123,{self.payload}", ["E_OUT_OF_RANGE"])
        self.assert_fails(f"93,-1,{self.payload}", ["E_OUT_OF_RANGE"])

    def test_bad_magic_rejected(self):
        self.assert_fails(f"93,123,#" + self.payload[1:], ["E_NOT_AN_OBJECT"])

    def test_non_alphabet_chars_rejected(self):
        for char in (",", ";", "<", ">", '"', "\\"):
            with self.subTest(char=char):
                bad = self.payload[:20] + char + self.payload[21:]
                self.assert_fails(f"93,123,{bad}", ["E_BAD_ENUM"])

    def test_illegal_tail_length_rejected(self):
        trimmed = self.payload[:len(self.payload) - (len(self.payload) - 2) % 5]
        self.assertEqual(len(trimmed) % 5, 2)
        self.assert_fails(f"93,123,{trimmed}", ["E_NOT_AN_OBJECT"])

    def test_declared_length_mismatch_rejected(self):
        # 'ABC' header digits are valid alphabet chars, but the declared
        # length they encode contradicts the actual body length.
        bad = self.payload[0] + "ABC" + self.payload[4:]
        self.assert_fails(f"93,123,{bad}", ["E_INCOHERENT_VALUE"])

    def test_block_count_mismatch_rejected(self):
        # First ball payload has X='!' with (len-5)//107 == 0; '#' (=1) breaks it.
        self.assertEqual(self.payload[4], "!")
        self.assertEqual((len(self.payload) - 5) // 107, 0)
        bad = self.payload[:4] + "#" + self.payload[5:]
        self.assert_fails(f"93,123,{bad}", ["E_INCOHERENT_VALUE"])

    def test_lossless_marker_rejected(self):
        bad = "~" + self.payload[1:]
        with self.assertRaises(ContractError) as raised:
            decode_mask_data(f"93,123,{bad}", ref="some/path#L1")
        self.assertEqual(raised.exception.codes, ["E_NOT_AN_OBJECT"])
        self.assertIn("out of scope", raised.exception.errors[0].message)

    def test_length_prefix_mismatch_rejected(self):
        # Flipping body[0] changes K while the decoded length stays fixed.
        bad = self.payload[:5] + "A" + self.payload[6:]
        self.assertNotEqual(self.payload[5], "A")
        self.assert_fails(f"93,123,{bad}", ["E_INCOHERENT_VALUE"])


class FramingSyntheticTest(_FramingAsserts, unittest.TestCase):
    # KL-9.6 B1: pure-synthetic framing checks (hand-built payloads,
    # no corpus bytes), moved out of the Smoke-backed classes so
    # they still run on clones without Smoke/.

    def test_alphabet_is_locked_85(self):
        self.assertEqual(MASK_ALPHABET, frozenset(ALPHABET_LITERAL))
        self.assertEqual(len(ALPHABET_LITERAL), 85)
        self.assertEqual(len(set(ALPHABET_LITERAL)), 85)
        for char in EXCLUDED_LITERAL:
            self.assertNotIn(char, MASK_ALPHABET)

    def test_empty_payload_rejected(self):
        self.assert_fails("93,123,", ["E_EMPTY_STRING"])

    def test_too_short_payload_rejected(self):
        self.assert_fails("93,123,!!!!", ["E_NOT_AN_OBJECT"])

    def test_overflowing_group_rejected(self):
        # Declared length 4 ('$' is rank 4): body length matches, but the
        # '{{{{{' group (85**5 - 1) exceeds u32.
        payload = "!" + "!!!!$" + "{{{{{"
        self.assert_fails(f"93,123,{payload}", ["E_INCOHERENT_VALUE"])

    def test_tail_overflow_rejected(self):
        # Declared length 1 ('#' is rank 1): body length matches, but the
        # '{{' tail (padded with 84s) exceeds u32.
        payload = "!" + "!!!!#" + "{{"
        self.assert_fails(f"93,123,{payload}", ["E_INCOHERENT_VALUE"])

    def test_non_canonical_tail_rejected(self):
        # A re-pack mismatch must fail even when every other gate passes.
        # Search digit pairs for a 1-byte tail whose re-pack differs.
        found = None
        for d0 in range(85):
            for d1 in range(85):
                value = d0 * 85 ** 4 + d1 * 85 ** 3 + 84 * (85 ** 2 + 85 + 1)
                if value >= 2 ** 32:
                    continue  # overflow gate, not the re-pack gate
                byte0 = value >> 24
                packed = byte0 << 24
                e0 = packed // 85 ** 4
                e1 = (packed - e0 * 85 ** 4) // 85 ** 3
                if (e0, e1) != (d0, d1):
                    found = (d0, d1)
                    break
            if found is not None:
                break
        self.assertIsNotNone(found)
        digits = sorted(MASK_ALPHABET)
        tail = digits[found[0]] + digits[found[1]]
        self.assert_fails(f"93,123,!" + "!!!!#" + tail, ["E_INCOHERENT_VALUE"])


class AdapterFramingIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        require_smoke(REPO_ROOT / "Smoke/test_3.mp4",
                      REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt")
        cls.table = extract_frame_records(REPO_ROOT / "Smoke/test_3.mp4")
        cls.line = (REPO_ROOT / "Smoke/results/test_3_yellow_ball_raw.txt"
                    ).read_text(encoding="utf-8").splitlines()[0]

    def test_corrupt_payload_fails_fast_with_file_and_line(self):
        head, payload = self.line.split(";data=", 1)
        height, width, body = payload[:-2].split(",", 2)
        bad = (f"{head};data={height},{width}," + body[:4] + "#" + body[5:]
               + "|>")
        handle = tempfile.NamedTemporaryFile(suffix=".txt", delete=False,
                                             mode="w", encoding="utf-8")
        handle.write(bad + "\n")
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        with self.assertRaises(ContractError) as raised:
            parse_raw_fixture(handle.name, object_role="bob", object_id="bob-1",
                              frame_table=self.table)
        self.assertEqual(raised.exception.codes, ["E_INCOHERENT_VALUE"])
        self.assertEqual(raised.exception.errors[0].field, "mask_reference")
        self.assertIn(f"{handle.name}#L1", raised.exception.errors[0].message)


if __name__ == "__main__":
    unittest.main()
