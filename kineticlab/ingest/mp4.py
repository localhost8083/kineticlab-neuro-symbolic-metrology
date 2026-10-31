"""Shared stdlib MP4 structural parser (KL-2.1 box structure, KL-2.2 timing).

Single implementation of ISO BMFF box parsing used by both the
``kineticlab.ingest`` package and ``scripts/media_check.py``. Reports
container/codec/geometry/stream structure plus per-sample video timing;
unknown values are ``None``, never guessed. ``pix_fmt`` needs a decoder
and is always ``None`` here.

Timing (``extract_sample_timing``) expands the video track sample table
in decode order: ``stts`` decoding deltas, ``ctts`` composition offsets
(signed in version 1), ``stsz`` counts/sizes, ``stsc`` chunk runs, and
``stco``/``co64`` chunk offsets. PTS = DTS + composition offset, or DTS
when ``ctts`` is absent. Edit lists (``elst``) are deliberately NOT
applied: reported times are track-timeline values, never shifted,
clamped, or re-zeroed.

A structurally contradictory file (truncated boxes, disagreeing sample
counts, out-of-range chunk data) raises ``ProbeError`` — never a silent
best-effort report.
"""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path

CODEC_NAMES = {
    "avc1": "h264",
    "avc3": "h264",
    "hev1": "hevc",
    "hvc1": "hevc",
    "mp4v": "mpeg4",
    "av01": "av1",
}


class ProbeError(Exception):
    """The file is missing, unreadable, or not a parseable MP4 structure."""


def iter_boxes(data: bytes, start: int, end: int):
    """Yield (box_type, content_start, content_end) for each child box."""
    offset = start
    while offset < end:
        if end - offset < 8:
            raise ProbeError(f"truncated box header at offset {offset}")
        (size, box_type) = struct.unpack_from(">I4s", data, offset)
        header = 8
        if size == 1:
            if end - offset < 16:
                raise ProbeError(f"truncated large-size header at offset {offset}")
            (size,) = struct.unpack_from(">Q", data, offset + 8)
            header = 16
        elif size == 0:
            size = end - offset
        if size < header or offset + size > end:
            raise ProbeError(f"invalid box size {size} at offset {offset}")
        yield box_type.decode("ascii", errors="replace"), offset + header, offset + size
        offset += size


def find_child(data: bytes, start: int, end: int, want: str):
    """Return (content_start, content_end) of the first child box `want`."""
    for box_type, content_start, content_end in iter_boxes(data, start, end):
        if box_type == want:
            return content_start, content_end
    return None


def find_children(data: bytes, start: int, end: int, want: str):
    """Return every child box `want` as (content_start, content_end)."""
    return [
        (content_start, content_end)
        for box_type, content_start, content_end in iter_boxes(data, start, end)
        if box_type == want
    ]


def read_mvhd(data: bytes, start: int, end: int):
    """Return (timescale, duration) from an mvhd/mdhd box body."""
    if end - start < 4:
        raise ProbeError("truncated media header")
    version = data[start]
    if version == 1:
        if end - start < 28:
            raise ProbeError("truncated v1 media header")
        timescale, duration = struct.unpack_from(">IQ", data, start + 20)
    else:
        if end - start < 20:
            raise ProbeError("truncated v0 media header")
        timescale, duration = struct.unpack_from(">II", data, start + 12)
    return timescale, duration


def parse_trak(data: bytes, start: int, end: int) -> dict:
    """Extract handler, sample format, geometry, timing, and counts of a track."""
    track: dict = {"handler": None, "format": None, "width": None,
                   "height": None, "timescale": None, "stsz_frames": None,
                   "stts_frames": None, "timing_uniform": None}
    mdia = find_child(data, start, end, "mdia")
    if mdia is None:
        return track
    mdhd = find_child(data, *mdia, "mdhd")
    if mdhd is not None:
        try:
            track_timescale, _ = read_mvhd(data, *mdhd)
        except ProbeError:
            track_timescale = None
        track["timescale"] = track_timescale or None
    minf_box = find_child(data, *mdia, "minf")
    if minf_box is None:
        return track
    hdlr = find_child(data, *mdia, "hdlr")
    if hdlr is not None and hdlr[1] - hdlr[0] >= 12:
        track["handler"] = data[hdlr[0] + 8:hdlr[0] + 12].decode("ascii", errors="replace")
    stbl = find_child(data, *minf_box, "stbl")
    if stbl is None:
        return track
    stsd = find_child(data, *stbl, "stsd")
    if stsd is not None and stsd[1] - stsd[0] >= 16:
        entry_count = struct.unpack_from(">I", data, stsd[0] + 4)[0]
        entry_offset = stsd[0] + 8
        if entry_count >= 1 and stsd[1] - entry_offset >= 36:
            entry_size = struct.unpack_from(">I", data, entry_offset)[0]
            track["format"] = data[entry_offset + 4:entry_offset + 8].decode(
                "ascii", errors="replace")
            if track["handler"] == "vide" and entry_size >= 86:
                track["width"] = struct.unpack_from(">H", data, entry_offset + 32)[0]
                track["height"] = struct.unpack_from(">H", data, entry_offset + 34)[0]
    stsz = find_child(data, *stbl, "stsz")
    if stsz is not None and stsz[1] - stsz[0] >= 12:
        track["stsz_frames"] = struct.unpack_from(">I", data, stsz[0] + 8)[0]
    stts = find_child(data, *stbl, "stts")
    if stts is not None and stts[1] - stts[0] >= 8:
        entry_count = struct.unpack_from(">I", data, stts[0] + 4)[0]
        frames = 0
        deltas = set()
        cursor = stts[0] + 8
        for _ in range(entry_count):
            if cursor + 8 > stts[1]:
                raise ProbeError("truncated stts entry")
            count, delta = struct.unpack_from(">II", data, cursor)
            frames += count
            deltas.add(delta)
            cursor += 8
        track["stts_frames"] = frames
        track["timing_uniform"] = len(deltas) == 1
    return track


def probe_bytes(data: bytes, display: str) -> dict:
    """Parse MP4 structure from bytes. Raises ProbeError when unparseable.

    Header-only: box extents are trusted from headers, so a truncated
    mdat can pass here; extract_sample_timing catches it via its chunk
    offset range check. Consumers using this probe alone must not treat
    frame_count as decoded truth."""
    report: dict = {"path": display, "sha256": hashlib.sha256(data).hexdigest(),
                    "warnings": []}
    try:
        top_start, top_end = 0, len(data)
        ftyp = find_child(data, top_start, top_end, "ftyp")
        if ftyp is None:
            raise ProbeError("no ftyp box: not an MP4 file")
        report["major_brand"] = data[ftyp[0]:ftyp[0] + 4].decode("ascii", errors="replace")
        report["compatible_brands"] = [
            data[i:i + 4].decode("ascii", errors="replace")
            for i in range(ftyp[0] + 8, ftyp[1], 4)
        ]
        moov = find_child(data, top_start, top_end, "moov")
        if moov is None:
            raise ProbeError("no moov box: no media metadata")
        mvhd = find_child(data, *moov, "mvhd")
        if mvhd is None:
            raise ProbeError("no mvhd box: no presentation timing")
        timescale, duration = read_mvhd(data, *mvhd)
        report["duration_s"] = duration / timescale if timescale else None
        if not timescale:
            report["warnings"].append("mvhd timescale is zero; duration unknown")
        tracks = [parse_trak(data, *trak) for trak in find_children(data, *moov, "trak")]
        report["track_count"] = len(tracks)
        report["video_track_count"] = sum(1 for track in tracks
                                          if track["handler"] == "vide")
        report["audio_track_count"] = sum(1 for track in tracks
                                          if track["handler"] == "soun")
        videos = [track for track in tracks if track["handler"] == "vide"]
        if not videos:
            raise ProbeError("no video track found")
        video = videos[0]
        report["codec_tag"] = video["format"]
        report["codec"] = CODEC_NAMES.get(video["format"] or "")
        if report["codec"] is None:
            report["warnings"].append(
                f"unmapped sample format {video['format']!r}; codec unknown")
        report["width"] = video["width"]
        report["height"] = video["height"]
        report["timescale"] = video["timescale"]
        report["frames"] = video["stsz_frames"]
        report["stts_frames"] = video["stts_frames"]
        report["timing_uniform"] = video["timing_uniform"]
        if (video["stsz_frames"] is not None and video["stts_frames"] is not None
                and video["stsz_frames"] != video["stts_frames"]):
            raise ProbeError(
                f"stsz frames ({video['stsz_frames']}) disagree with stts frames "
                f"({video['stts_frames']}); structure contradictory")
        if report["frames"] and report["duration_s"]:
            report["fps_measured"] = report["frames"] / report["duration_s"]
        else:
            report["fps_measured"] = None
        report["has_audio"] = any(track["handler"] == "soun" for track in tracks)
        # Pixel format requires a decoder; this structural probe must not guess it.
        report["pix_fmt"] = None
        report["pix_fmt_reason"] = "requires decode; not present in box structure"
    except struct.error as error:
        raise ProbeError(f"malformed box structure: {error}") from error
    return report


def probe_mp4(path: Path) -> dict:
    """Parse MP4 structure from a file. Raises ProbeError on missing/unparseable input."""
    if not path.is_file():
        raise ProbeError(f"video not found: {path}")
    return probe_bytes(path.read_bytes(), str(path))


def _read_full_header(data: bytes, start: int, end: int, what: str):
    """Return (version, entry_count, entries_start) of a full box body."""
    if end - start < 8:
        raise ProbeError(f"truncated {what} header")
    version = data[start]
    (entry_count,) = struct.unpack_from(">I", data, start + 4)
    return version, entry_count, start + 8


def _expand_runs(entries: list[tuple[int, int]], sample_count: int, what: str) -> list[int]:
    """Expand (count, value) runs to one value per sample, in decode order."""
    total = sum(count for count, _ in entries)
    if total != sample_count:
        raise ProbeError(f"{what} covers {total} samples, sample table has {sample_count}")
    expanded: list[int] = []
    for count, value in entries:
        expanded.extend([value] * count)
    return expanded


def _read_stts(data: bytes, start: int, end: int, sample_count: int) -> list[int]:
    """Return per-sample decoding deltas in timescale units."""
    _, entry_count, cursor = _read_full_header(data, start, end, "stts")
    entries = []
    for _ in range(entry_count):
        if cursor + 8 > end:
            raise ProbeError("truncated stts entry")
        count, delta = struct.unpack_from(">II", data, cursor)
        entries.append((count, delta))
        cursor += 8
    return _expand_runs(entries, sample_count, "stts")


def _read_ctts(data: bytes, start: int, end: int, sample_count: int) -> list[int]:
    """Return per-sample composition offsets (signed in version 1)."""
    version, entry_count, cursor = _read_full_header(data, start, end, "ctts")
    offset_format = ">i" if version == 1 else ">I"
    entries = []
    for _ in range(entry_count):
        if cursor + 8 > end:
            raise ProbeError("truncated ctts entry")
        (count,) = struct.unpack_from(">I", data, cursor)
        (offset,) = struct.unpack_from(offset_format, data, cursor + 4)
        entries.append((count, offset))
        cursor += 8
    return _expand_runs(entries, sample_count, "ctts")


def _read_stsz(data: bytes, start: int, end: int) -> tuple[int, list[int]]:
    """Return (sample_count, per-sample sizes in bytes)."""
    if end - start < 12:
        raise ProbeError("truncated stsz header")
    sample_size, sample_count = struct.unpack_from(">II", data, start + 4)
    # KL-9.6 M8: bound BEFORE any allocation. The uniform path below
    # used to multiply first, so a 4-billion count demanded a
    # 4-billion-element list before the caller's post-hoc check could
    # run. Same ProbeError style as the per-sample path.
    if sample_count > len(data):
        raise ProbeError(
            f"sample count {sample_count} exceeds file size {len(data)}")
    if sample_size != 0:
        return sample_count, [sample_size] * sample_count
    cursor = start + 12
    sizes = []
    for _ in range(sample_count):
        if cursor + 4 > end:
            raise ProbeError("truncated stsz size table")
        (size,) = struct.unpack_from(">I", data, cursor)
        sizes.append(size)
        cursor += 4
    return sample_count, sizes


def _read_chunk_offsets(data: bytes, stbl_start: int, stbl_end: int) -> list[int]:
    """Return chunk byte offsets from exactly one of stco/co64."""
    stco = find_child(data, stbl_start, stbl_end, "stco")
    co64 = find_child(data, stbl_start, stbl_end, "co64")
    if stco is not None and co64 is not None:
        raise ProbeError("both stco and co64 present; chunk offsets contradictory")
    if stco is None and co64 is None:
        raise ProbeError("neither stco nor co64 present; chunk offsets unknown")
    box_start, box_end = co64 if co64 is not None else stco
    assert box_start is not None and box_end is not None
    _, entry_count, cursor = _read_full_header(data, box_start, box_end, "stco/co64")
    width = 8 if co64 is not None else 4
    offsets = []
    for _ in range(entry_count):
        if cursor + width > box_end:
            raise ProbeError("truncated stco/co64 entry")
        (offset,) = struct.unpack_from(">Q" if width == 8 else ">I", data, cursor)
        offsets.append(offset)
        cursor += width
    for offset in offsets:
        if not 0 < offset < len(data):
            raise ProbeError(f"chunk offset {offset} out of range for {len(data)} bytes")
    return offsets


def _read_sample_chunks(data: bytes, start: int, end: int, chunk_count: int,
                        sample_count: int) -> list[int]:
    """Return the 1-based chunk number of each sample in decode order."""
    _, entry_count, cursor = _read_full_header(data, start, end, "stsc")
    runs = []
    for _ in range(entry_count):
        if cursor + 12 > end:
            raise ProbeError("truncated stsc entry")
        first_chunk, per_chunk, _ = struct.unpack_from(">III", data, cursor)
        runs.append((first_chunk, per_chunk))
        cursor += 12
    if not runs or runs[0][0] != 1:
        raise ProbeError("stsc first run must start at chunk 1")
    for (previous, _), (current, _) in zip(runs, runs[1:]):
        if current <= previous:
            raise ProbeError("stsc first_chunk entries must strictly increase")
    if runs[-1][0] > chunk_count:
        raise ProbeError("stsc run starts beyond the last chunk")
    per_chunk_of = [0] * chunk_count
    for index, (first_chunk, per_chunk) in enumerate(runs):
        last_chunk = runs[index + 1][0] - 1 if index + 1 < len(runs) else chunk_count
        for chunk in range(first_chunk - 1, last_chunk):
            per_chunk_of[chunk] = per_chunk
    if sum(per_chunk_of) != sample_count:
        raise ProbeError(f"stsc maps {sum(per_chunk_of)} samples, "
                         f"sample table has {sample_count}")
    chunks: list[int] = []
    for chunk_number, per_chunk in enumerate(per_chunk_of, start=1):
        chunks.extend([chunk_number] * per_chunk)
    return chunks


def extract_sample_timing(data: bytes) -> dict:
    """Extract per-sample video timing in decode order (KL-2.2).

    Returns ``{"timescale": int, "samples": [{"dts", "pts", "delta",
    "size", "chunk"}]}`` with times in track-timescale units (exact
    integers; callers convert to seconds). Requires exactly one video
    track; raises ``ProbeError`` on any missing table, count
    contradiction, or out-of-range chunk data.
    """
    try:
        moov = find_child(data, 0, len(data), "moov")
        if moov is None:
            raise ProbeError("no moov box: no media metadata")
        video_stbl = None
        video_timescale = None
        video_tracks = 0
        for trak_start, trak_end in find_children(data, *moov, "trak"):
            mdia = find_child(data, trak_start, trak_end, "mdia")
            if mdia is None:
                continue
            hdlr = find_child(data, *mdia, "hdlr")
            handler = None
            if hdlr is not None and hdlr[1] - hdlr[0] >= 12:
                handler = data[hdlr[0] + 8:hdlr[0] + 12].decode("ascii", errors="replace")
            if handler != "vide":
                continue
            video_tracks += 1
            if video_tracks > 1:
                raise ProbeError("more than one video track; timing ambiguous")
            mdhd = find_child(data, *mdia, "mdhd")
            if mdhd is not None:
                track_timescale, _ = read_mvhd(data, *mdhd)
                video_timescale = track_timescale or None
            minf = find_child(data, *mdia, "minf")
            if minf is not None:
                video_stbl = find_child(data, *minf, "stbl")
        if video_tracks == 0:
            raise ProbeError("no video track found")
        if video_timescale is None:
            raise ProbeError("video track has no mdhd timescale")
        if video_stbl is None:
            raise ProbeError("video track has no sample table (stbl)")
        stbl_start, stbl_end = video_stbl
        stsz = find_child(data, stbl_start, stbl_end, "stsz")
        if stsz is None:
            raise ProbeError("no stsz box: sample count unknown")
        sample_count, sizes = _read_stsz(data, *stsz)
        if sample_count > len(data):
            raise ProbeError(f"sample count {sample_count} exceeds file size {len(data)}")
        stts = find_child(data, stbl_start, stbl_end, "stts")
        if stts is None:
            raise ProbeError("no stts box: decoding times unknown")
        deltas = _read_stts(data, *stts, sample_count)
        ctts = find_child(data, stbl_start, stbl_end, "ctts")
        offsets = _read_ctts(data, *ctts, sample_count) if ctts is not None else [0] * sample_count
        chunk_offsets = _read_chunk_offsets(data, stbl_start, stbl_end)
        stsc = find_child(data, stbl_start, stbl_end, "stsc")
        if stsc is None:
            raise ProbeError("no stsc box: sample-to-chunk mapping unknown")
        chunks = _read_sample_chunks(data, *stsc, len(chunk_offsets), sample_count)
        for chunk_number, offset in enumerate(chunk_offsets, start=1):
            extent = offset + sum(size for size, chunk in zip(sizes, chunks)
                                  if chunk == chunk_number)
            if extent > len(data):
                raise ProbeError(f"chunk {chunk_number} extends beyond end of file")
        samples = []
        decoding_time = 0
        for delta, offset, size, chunk in zip(deltas, offsets, sizes, chunks):
            samples.append({"dts": decoding_time, "pts": decoding_time + offset,
                            "delta": delta, "size": size, "chunk": chunk})
            decoding_time += delta
    except struct.error as error:
        raise ProbeError(f"malformed box structure: {error}") from error
    return {"timescale": video_timescale, "samples": samples}
