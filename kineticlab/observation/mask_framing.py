"""Mask payload transport framing (KL-3.2, spec-aligned).

Validates and unpacks the ``data=d0,d1,payload`` mask fields in
``Smoke/results/*_raw.txt`` (959 payloads, 5 files). Pure Python,
stdlib only.

Wire format (per the published SAM 3 protocol: dev.meta.ai SAM docs
for the ``data=<H>,<W>,<enc>payload`` grammar and the meta-models
``meta-sam`` ``protocol/sam3.md`` payload spec; the unpack/pack laws
below mirror Meta's ``meta_sam_parser`` reference decoder, published
under the SAM License):

- ``data`` splits as ``d0,d1,payload`` (the payload alphabet excludes
  ``,``, so the first two commas are the split points), with ``d0``
  = box row count (height) and ``d1`` = box column count (width).
  NOTE: the KL-3.1 docstring labeled this field ``W,H``; the bytes
  show ``H,W`` order, and the bytes win: this module returns
  ``height=d0, width=d1``.
- ``payload`` = ``!`` one_bit marker + base-85 text (``~`` lossless
  payloads are out of scope and rejected on the documented path
  below). Digits are ranks 0..84 in the locked 85-char alphabet
  (ASCII 0x21..0x7E minus the seven wire delimiters
  ``" \\ , ; < > |``, first 85 in ASCII order); any other
  character is invalid.
- The first 5 text chars after the marker are the declared decoded
  length as a base-85 big-endian number. The expected text length
  follows exactly: ``5 + (length // 4) * 5 + (0 if length % 4 == 0
  else length % 4 + 1)``. Mismatch is an error.
- Body groups: 5 chars -> u32 -> 4 bytes big-endian. A group value
  above u32 is an error (this is exactly why corpus group digit 0
  never exceeds rank 82, and why no payload is ever 2 (mod 5): a
  1-char tail group is illegal).
- Tail (``length % 4`` bytes): read ``rem + 1`` chars, pad the
  missing digit positions with digit value 84, take the top ``rem``
  bytes of the u32.
- Canonical check: re-packing the decoded bytes must reproduce the
  payload text EXACTLY (the reference enforces this on every
  decode; so do we — pack cost is linear in ~200 bytes).

Failure mapping (fail-fast, consistent with the KL-3.1 adapter: a
malformed payload fails the whole file, since corruption voids the
file's trust; missing data stays null and never reaches this path):

- ``data`` without ``d0,d1,`` -> ``E_NOT_AN_OBJECT``;
- non-integer dims -> ``E_WRONG_TYPE``; dims <= 0 ->
  ``E_OUT_OF_RANGE``;
- empty payload where H*W > 0 -> ``E_EMPTY_STRING``;
- bad marker char (including out-of-scope ``~``) ->
  ``E_NOT_AN_OBJECT``;
- char outside the 85-char alphabet -> ``E_BAD_ENUM``;
- ``len(payload) % 5 == 2`` (illegal 1-char tail) ->
  ``E_NOT_AN_OBJECT``;
- declared length contradicting the text length, group/tail above
  u32, or re-pack mismatch -> ``E_INCOHERENT_VALUE`` (individually
  valid pieces contradict each other).

Every detail names the caller's ``ref`` (``<path>#L<line>``). No new
codes: the locked 32+9 taxonomy covers all cases.
"""

from __future__ import annotations

from dataclasses import dataclass

from kineticlab.contracts import ContractError, FieldError

MAGIC = "!"
LOSSLESS_MARKER = "~"
_WIRE_DELIMITERS = frozenset(['"', '\\', ',', ';', '<', '>', '|'])
_WIRE_ALPHABET = "".join(
    chr(code) for code in range(0x21, 0x7F) if chr(code) not in _WIRE_DELIMITERS
)
assert len(_WIRE_ALPHABET) == 87
MASK_ALPHABET = frozenset(_WIRE_ALPHABET[:85])
"""The 85 digit chars: ASCII 0x21..0x7E minus wire delimiters, first 85.

The remaining two wire chars (``}``/``~``, ranks 85/86) are not valid
digits: any rank >= 85 is rejected, so ``~`` can never hide mid-payload.
"""
assert len(MASK_ALPHABET) == 85

_DIGITS = sorted(MASK_ALPHABET)
_CHAR_VALUE = {char: rank for rank, char in enumerate(_DIGITS)}
_TOP_CHAR = _DIGITS[-1]
assert _TOP_CHAR == "{" and _CHAR_VALUE[_TOP_CHAR] == 84
assert MAGIC in MASK_ALPHABET

_RADIX = 85
_PREFIX_LENGTH = 5
_U32_LIMIT = 2 ** 32


@dataclass(frozen=True)
class DecodedMaskFraming:
    """Validated framing: dims + stream bytes + source text for ``mask_codec``."""

    width: int
    height: int
    opaque: bytes
    payload: str


def _fail(code: str, ref: str, detail: str) -> None:
    raise ContractError([FieldError(code, "mask_reference",
                                    f"{ref}: {detail}")])


def pack_body(data: bytes) -> str:
    """Encode bytes to the canonical base-85 body (length prefix + groups)."""
    length = len(data)
    prefix: list[str] = [""] * _PREFIX_LENGTH
    remaining = length
    for index in range(_PREFIX_LENGTH - 1, -1, -1):
        prefix[index] = _DIGITS[remaining % _RADIX]
        remaining //= _RADIX
    if remaining != 0:
        raise ValueError("mask body too large to pack")
    out = list(prefix)
    full = length - length % 4
    for offset in range(0, full, 4):
        value = int.from_bytes(data[offset:offset + 4], "big")
        group = [""] * 5
        for index in range(4, -1, -1):
            group[index] = _DIGITS[value % _RADIX]
            value //= _RADIX
        out.extend(group)
    rem = length - full
    if rem:
        value = int.from_bytes(data[full:] + b"\x00" * (4 - rem), "big")
        group = [""] * 5
        for index in range(4, -1, -1):
            group[index] = _DIGITS[value % _RADIX]
            value //= _RADIX
        out.extend(group[:rem + 1])
    return "".join(out)


def unpack_body(body: str, *, ref: str) -> bytes:
    """Decode a base-85 body (after the marker) to bytes, spec checks first."""
    if len(body) < _PREFIX_LENGTH:
        _fail("E_NOT_AN_OBJECT", ref,
              "mask payload is too short to hold the length prefix")
    declared = 0
    for char in body[:_PREFIX_LENGTH]:
        declared = declared * _RADIX + _CHAR_VALUE[char]
    rem = declared % 4
    expected = (_PREFIX_LENGTH + (declared // 4) * 5
                + (0 if rem == 0 else rem + 1))
    if len(body) != expected:
        _fail("E_INCOHERENT_VALUE", ref,
              f"mask declared length {declared} contradicts "
              f"payload body length {len(body)}")
    raw = bytearray(declared)
    full = declared - rem
    for dst in range(0, full, 4):
        src = _PREFIX_LENGTH + dst // 4 * 5
        value = 0
        for char in body[src:src + 5]:
            value = value * _RADIX + _CHAR_VALUE[char]
        if value >= _U32_LIMIT:
            _fail("E_INCOHERENT_VALUE", ref,
                  f"mask group {body[src:src + 5]!r} exceeds u32")
        raw[dst:dst + 4] = value.to_bytes(4, "big")
    if rem:
        src = len(body) - (rem + 1)
        value = 0
        for char in body[src:]:
            value = value * _RADIX + _CHAR_VALUE[char]
        for _ in range(5 - (rem + 1)):
            value = value * _RADIX + (_RADIX - 1)
        if value >= _U32_LIMIT:
            _fail("E_INCOHERENT_VALUE", ref,
                  f"mask tail {body[src:]!r} exceeds u32")
        raw[full:] = value.to_bytes(4, "big")[:rem]
    if pack_body(bytes(raw)) != body:
        _fail("E_INCOHERENT_VALUE", ref,
              "mask payload is not canonical: re-pack mismatch")
    return bytes(raw)


def decode_mask_data(data_value: str, *, ref: str) -> DecodedMaskFraming:
    """Validate ``d0,d1,payload`` framing; return height/width + stream bytes.

    ``d0`` is the row count (height), ``d1`` the column count (width).
    ``ref`` names the payload (``<path>#L<line>``) for failure details.
    Raises fail-fast ``ContractError`` with registered codes.
    """
    parts = data_value.split(",", 2)
    if len(parts) != 3:
        _fail("E_NOT_AN_OBJECT", ref,
              f"mask data is not `d0,d1,payload`: {data_value[:40]!r}")
    height_text, width_text, payload = parts
    try:
        height = int(height_text)
    except ValueError:
        _fail("E_WRONG_TYPE", ref,
              f"mask height is not an integer: {height_text!r}")
        raise AssertionError("unreachable")
    try:
        width = int(width_text)
    except ValueError:
        _fail("E_WRONG_TYPE", ref,
              f"mask width is not an integer: {width_text!r}")
        raise AssertionError("unreachable")
    if width <= 0 or height <= 0:
        _fail("E_OUT_OF_RANGE", ref,
              f"mask dims must be positive integers: {height}x{width}")
    if not payload:
        _fail("E_EMPTY_STRING", ref,
              "mask payload is empty where "
              f"H*W = {height * width} > 0")
    if payload[0] != MAGIC:
        note = ("`~` lossless payloads are out of scope (one_bit only)"
                if payload[0] == LOSSLESS_MARKER
                else f"mask payload lacks the `{MAGIC}` marker")
        _fail("E_NOT_AN_OBJECT", ref, f"{note}: {payload[:8]!r}")
    for index, char in enumerate(payload):
        if char not in MASK_ALPHABET:
            _fail("E_BAD_ENUM", ref,
                  f"mask payload char {char!r} at index {index} is "
                  f"outside the locked 85-char alphabet")
    if len(payload) % 5 == 2:
        _fail("E_NOT_AN_OBJECT", ref,
              f"mask payload length {len(payload)} is 2 (mod 5): "
              f"a 1-char tail group is illegal")
    stream = unpack_body(payload[1:], ref=ref)
    return DecodedMaskFraming(width=width, height=height, opaque=stream,
                              payload=payload)
