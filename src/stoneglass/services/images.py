# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded PNG verification and lossless local export, independent of Qt/inference."""
import hashlib
import os
import struct
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from stoneglass.inference.errors import ErrorCode, InferenceError
from stoneglass.inference.resources import strict_local


@dataclass(frozen=True)
class ImageInfo:
    path: Path
    width: int
    height: int
    sha256: str


def validate_png(path: Path, width: int, height: int) -> ImageInfo:
    try:
        path = strict_local(path)
        if path.stat().st_size > 32 * 1024 * 1024:
            raise ValueError()
        data = path.read_bytes()
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError()
        offset, compressed, channels, saw_end = 8, bytearray(), 0, False
        while offset < len(data):
            if offset + 12 > len(data): raise ValueError()
            size = struct.unpack_from(">I", data, offset)[0]
            kind = data[offset + 4:offset + 8]
            end = offset + 12 + size
            if end > len(data): raise ValueError()
            body = data[offset + 8:end - 4]
            if zlib.crc32(kind + body) & 0xffffffff != struct.unpack_from(">I", data, end - 4)[0]: raise ValueError()
            if offset == 8:
                if kind != b"IHDR" or size != 13: raise ValueError()
                w, h, depth, color, comp, filtering, interlace = struct.unpack(">IIBBBBB", body)
                if (w, h) != (width, height) or not 0 < w * h <= 1024 * 1024 or depth != 8 or color not in (2, 6) or (comp, filtering, interlace) != (0, 0, 0): raise ValueError()
                channels = 3 if color == 2 else 4
            elif kind == b"IHDR": raise ValueError()
            if kind == b"IDAT": compressed.extend(body)
            if kind == b"IEND":
                if size or end != len(data): raise ValueError()
                saw_end = True
            offset = end
        if not channels or not compressed or not saw_end: raise ValueError()
        expected = height * (1 + width * channels)
        decoder = zlib.decompressobj()
        decoded = decoder.decompress(compressed, expected + 1)
        if len(decoded) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail: raise ValueError()
        if any(decoded[row * (width * channels + 1)] > 4 for row in range(height)): raise ValueError()
        return ImageInfo(path, width, height, hashlib.sha256(data).hexdigest())
    except (OSError, ValueError, struct.error, zlib.error, InferenceError):
        raise InferenceError(ErrorCode.GENERATION_FAILED, "The PNG output is missing, corrupt or incomplete. The file was preserved for review.") from None


def export_png(image: ImageInfo, destination: Path, *, overwrite: bool = False) -> Path:
    """Copy the validated full-resolution bytes; never resample or alter metadata."""
    source = validate_png(image.path, image.width, image.height)
    if source.sha256 != image.sha256:
        raise InferenceError(ErrorCode.GENERATION_FAILED, "The original image changed. Export was stopped.")
    strict_local(destination.parent, directory=True)
    if destination.suffix.lower() != ".png":
        raise ValueError("Choose a PNG filename.")
    if destination == image.path: return destination
    if destination.exists():
        strict_local(destination)
        if not overwrite: raise FileExistsError("The destination exists; confirm overwrite in the Save dialog.")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix="stoneglass-export-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(image.path.read_bytes())
            stream.flush(); os.fsync(stream.fileno())
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != image.sha256:
            raise OSError("Image export integrity check failed.")
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)
