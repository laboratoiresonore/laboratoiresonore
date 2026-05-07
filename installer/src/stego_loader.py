"""Optional configuration loader.

If a `key.png` is dropped next to the installer, this module pulls
extra manifest entries from its embedded payload (Ed25519-signed
JSON, LSB-encoded into the pixel data). When no key.png is present,
or the signature doesn't verify, returns None and the installer
falls back to the public manifest only.
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


# Embedded public key. The matching private key is held by the
# maintainer; nobody else can produce a payload that verifies here.
_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAQ2SAT5tndurVZ8WN3j3bVO+6EGRKBRQNQ5RLrrCfJew=
-----END PUBLIC KEY-----
"""

# Wire format constants (must match the producer side).
_MAGIC = b"L0SK"
_VERSION = 1
_SIG_BYTES = 64


def _public_key() -> Ed25519PublicKey:
    return load_pem_public_key(_PUBLIC_KEY_PEM)


def _key_png_path(installer_root: Optional[Path] = None) -> Path:
    if installer_root is not None:
        return installer_root / "key.png"
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "key.png"
    return Path(__file__).resolve().parents[2] / "key.png"


def _lsb_decode(png_path: Path, max_bytes: int = 4096) -> Optional[bytes]:
    """Pull payload bytes from the bottom bit of each pixel channel.
    Returns None if PIL isn't installed or the file isn't a parseable
    image."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(png_path)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        pixels = img.tobytes()
    except (OSError, ValueError):
        return None

    out = bytearray()
    cap = min(max_bytes, len(pixels) // 8)
    bit_idx = 0
    for _ in range(cap):
        byte = 0
        for shift in range(8):
            byte |= (pixels[bit_idx] & 1) << shift
            bit_idx += 1
        out.append(byte)
    return bytes(out)


def _parse_payload(blob: bytes) -> Optional[dict]:
    """Verify + parse the framed payload. Returns None on any failure
    (wrong magic / wrong version / bad signature / malformed JSON)."""
    if len(blob) < 4 + 1 + 4 + _SIG_BYTES:
        return None
    if blob[:4] != _MAGIC:
        return None
    if blob[4] != _VERSION:
        return None
    length = struct.unpack("<I", blob[5:9])[0]
    if length <= 0 or length > 1_000_000:
        return None
    if len(blob) < 9 + length + _SIG_BYTES:
        return None
    body = blob[9:9 + length]
    sig = blob[9 + length:9 + length + _SIG_BYTES]
    header = blob[:9]
    try:
        _public_key().verify(sig, header + body)
    except Exception:  # noqa: BLE001
        return None
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def read(*, installer_root: Optional[Path] = None) -> Optional[dict]:
    """Try to read the optional key.png next to the installer. Returns
    the verified payload dict on success, None on any failure
    (missing file, PIL missing, bad signature, malformed payload).
    Never raises -- caller treats None as 'no extra config'."""
    path = _key_png_path(installer_root)
    if not path.exists():
        return None
    blob = _lsb_decode(path)
    if blob is None:
        return None
    return _parse_payload(blob)
