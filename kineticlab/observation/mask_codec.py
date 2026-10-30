"""one_bit mask codec: range coder + context model + canonical gate (KL-3.2).

Decodes the range-coder stream bytes produced by
``mask_framing.decode_mask_data`` into box-relative binary rasters,
re-encodes them through the mirror encoder as a canonical gate, and
derives mask area/centroid. Pure Python, stdlib only.

Algorithm attribution: this module implements the published SAM 3
one_bit wire algorithm — the ``dev.meta.ai`` SAM grammar plus the
``meta-models/meta-sam`` ``protocol/sam3.md`` payload spec (5-char
base-85 length prefix, 32-bit range coder, 12-bit causal context
model, canonical round-trip gate), following Meta's ``meta_sam_parser``
reference decoder, which is published under the SAM License. The code
below is original project code written against that spec; see also
the task prompt's inline spec transcription (§1-§6).

Raster layout: row-major bytes holding only 0 or 1, exactly
``width * height`` entries, box-relative (pixel (col, row) sits at
frame (x1 + col, y1 + row) for the record's bbox corner).

Failure mapping (fail-fast with the caller's ``ref`` =
``<path>#L<line>`` on ``mask_reference``; the locked 32+9 taxonomy
holds — every codec failure is content contradicting its framing):

- stream shorter than 4 bytes, byte exhaustion mid-raster, or a zero
  range-coder step -> ``E_INCOHERENT_VALUE`` (stream contradicts
  the dims it claims to fill);
- re-encoded payload differing from the original text ->
  ``E_INCOHERENT_VALUE`` ("not canonical or invalid finalization");
- raster with zero set bits -> ``E_INCOHERENT_VALUE`` (centroid
  undefined; never fabricated).
"""

from __future__ import annotations

from kineticlab.contracts import ContractError, FieldError
from kineticlab.observation.mask_framing import MAGIC, pack_body

_TOP = 1 << 24
_BOTTOM = 1 << 16
_MASK32 = 0xFFFFFFFF
_COUNT_BUMP = 14
_COUNT_CAP = 4096
_CONTEXTS = 1 << 12
_PAD = 2


def _fail(ref: str, detail: str) -> None:
    raise ContractError([FieldError("E_INCOHERENT_VALUE", "mask_reference",
                                    f"{ref}: {detail}")])


# Hot-loop note: context counts carry no u16 masking. A single count can
# never approach 65536 (the pair is halved as soon as its sum reaches
# 4096, so one count peaks just above ~4110), making the mask dead
# weight per pixel. Range state (code/low/range) keeps exact u32
# masking per the spec — bigints must never leak into the coder.


def decode_raster(stream: bytes, width: int, height: int, *, ref: str) -> bytes:
    """Range-decode ``stream`` to a ``width * height`` binary raster.

    Per-pixel control flow follows spec §3 (32-bit range decoder
    with TOP/BOTTOM renorm) and §4 (12-bit causal context over the
    zero-padded bitmap, row-major). Raises fail-fast ``ContractError``.
    """
    if len(stream) < 4:
        _fail(ref, "mask stream is too short for range finalization")
    size = len(stream)
    pos = 4
    low = 0
    rng = _MASK32
    code = int.from_bytes(stream[0:4], "big")
    counts = [1] * (_CONTEXTS * 2)
    stride = width + 2 * _PAD
    padded = bytearray(stride * (height + _PAD))
    output = bytearray(width * height)
    out_index = 0
    bump = _COUNT_BUMP
    cap = _COUNT_CAP
    mask = _MASK32
    top = _TOP
    bottom = _BOTTOM
    # Exact-output hotspot note (KL-8.7): context bits 2-6 are a
    # contiguous 5-bit window of row y-1 and bits 7-11 of row y-2,
    # both rows fully decoded by causality, so each window slides
    # one bit per column instead of re-reading 5 cells. Bits 0-1
    # stay direct reads. The assembled integer is identical to the
    # 12-read form on every pixel (guarded by the corpus
    # round-trip test); only the arithmetic path changed.
    for row in range(height):
        base = (row + _PAD) * stride + _PAD
        row_above = base - stride
        row_above2 = row_above - stride
        win_a = (padded[row_above - 2] | (padded[row_above - 1] << 1)
                 | (padded[row_above] << 2)
                 | (padded[row_above + 1] << 3)
                 | (padded[row_above + 2] << 4))
        win_b = (padded[row_above2 - 2] | (padded[row_above2 - 1] << 1)
                 | (padded[row_above2] << 2)
                 | (padded[row_above2 + 1] << 3)
                 | (padded[row_above2 + 2] << 4))
        for col in range(width):
            at = base + col
            above = at - stride
            above2 = above - stride
            context = (padded[at - 1] | (padded[at - 2] << 1)
                       | (win_a << 2) | (win_b << 7))
            if col + 1 < width:
                win_a = (win_a >> 1) | (padded[above + 3] << 4)
                win_b = (win_b >> 1) | (padded[above2 + 3] << 4)
            slot = context << 1
            zero = counts[slot]
            one = counts[slot + 1]
            scaled = rng // (zero + one)
            if scaled == 0:
                _fail(ref, "mask stream has an invalid coding state")
            pick = ((code - low) & mask) // scaled
            if pick >= zero + one:
                pick = zero + one - 1
            if pick < zero:
                bit = 0
                rng = scaled * zero
            else:
                bit = 1
                low = (low + scaled * zero) & mask
                rng = scaled * one
            while True:
                if (low ^ ((low + rng) & mask)) & mask < top:
                    pass
                elif rng < bottom:
                    rng = (-low) & mask & (bottom - 1)
                else:
                    break
                if pos >= size:
                    _fail(ref, "mask stream ended early for "
                               f"{width}x{height} raster")
                code = ((code << 8) | stream[pos]) & mask
                pos += 1
                low = (low << 8) & mask
                rng = (rng << 8) & mask
            padded[at] = bit
            output[out_index] = bit
            out_index += 1
            counts[slot + bit] += bump
            if counts[slot] + counts[slot + 1] >= cap:
                counts[slot] = (counts[slot] >> 1) or 1
                counts[slot + 1] = (counts[slot + 1] >> 1) or 1
    return bytes(output)


def encode_raster_stream(raster: bytes, width: int, height: int) -> bytes:
    """Mirror range-encode a binary raster to stream bytes (canonical gate)."""
    if len(raster) != width * height:
        raise ValueError("raster size contradicts width*height")
    low = 0
    rng = _MASK32
    out = bytearray()
    counts = [1] * (_CONTEXTS * 2)
    stride = width + 2 * _PAD
    padded = bytearray(stride * (height + _PAD))
    bump = _COUNT_BUMP
    cap = _COUNT_CAP
    mask = _MASK32
    top = _TOP
    bottom = _BOTTOM
    # Same sliding-window context as decode_raster (see note there):
    # identical integers, fewer reads per pixel.
    for row in range(height):
        base = (row + _PAD) * stride + _PAD
        row_above = base - stride
        row_above2 = row_above - stride
        win_a = (padded[row_above - 2] | (padded[row_above - 1] << 1)
                 | (padded[row_above] << 2)
                 | (padded[row_above + 1] << 3)
                 | (padded[row_above + 2] << 4))
        win_b = (padded[row_above2 - 2] | (padded[row_above2 - 1] << 1)
                 | (padded[row_above2] << 2)
                 | (padded[row_above2 + 1] << 3)
                 | (padded[row_above2 + 2] << 4))
        row_start = row * width
        for col in range(width):
            bit = raster[row_start + col]
            if bit != 0 and bit != 1:
                raise ValueError("raster is not binary")
            at = base + col
            above = at - stride
            above2 = above - stride
            context = (padded[at - 1] | (padded[at - 2] << 1)
                       | (win_a << 2) | (win_b << 7))
            if col + 1 < width:
                win_a = (win_a >> 1) | (padded[above + 3] << 4)
                win_b = (win_b >> 1) | (padded[above2 + 3] << 4)
            slot = context << 1
            zero = counts[slot]
            one = counts[slot + 1]
            scaled = rng // (zero + one)
            if bit == 0:
                rng = scaled * zero
            else:
                low = (low + scaled * zero) & _MASK32
                rng = scaled * one
            while True:
                if (low ^ ((low + rng) & mask)) & mask < top:
                    pass
                elif rng < bottom:
                    rng = (-low) & mask & (bottom - 1)
                else:
                    break
                out.append((low >> 24) & 0xFF)
                low = (low << 8) & _MASK32
                rng = (rng << 8) & _MASK32
            padded[at] = bit
            counts[slot + bit] += bump
            if counts[slot] + counts[slot + 1] >= cap:
                counts[slot] = (counts[slot] >> 1) or 1
                counts[slot + 1] = (counts[slot + 1] >> 1) or 1
    for _ in range(4):
        out.append((low >> 24) & 0xFF)
        low = (low << 8) & _MASK32
    return bytes(out)


def check_canonical(payload: str, raster: bytes, width: int, height: int,
                    *, ref: str) -> None:
    """Raise unless re-encoding ``raster`` reproduces ``payload`` exactly."""
    if MAGIC + pack_body(encode_raster_stream(raster, width, height)) != payload:
        _fail(ref, "mask payload is not canonical or invalid finalization")


def raster_geometry(raster: bytes, width: int, height: int, *,
                    x1: float, y1: float, ref: str) -> tuple[int, float, float]:
    """Derive (area_px, centroid_x_px, centroid_y_px) from decoded bits.

    Mask-local means plus the bbox corner (top-left origin, +x right,
    +y down). A zero mask fails explicitly: its centroid is undefined.
    """
    if len(raster) != width * height:
        raise ValueError("raster size contradicts width*height")
    total_x = 0
    total_y = 0
    area = 0
    index = 0
    for row in range(height):
        for col in range(width):
            if raster[index]:
                total_x += col
                total_y += row
                area += 1
            index += 1
    if area == 0:
        _fail(ref, "mask decodes to zero set bits; centroid undefined")
    return area, x1 + total_x / area, y1 + total_y / area
